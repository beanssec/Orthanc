"""EU sanctions list ingestion — parses EU Consolidated Financial Sanctions List.

Source: https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content
Cadence: daily refresh; entities are stored in-memory AND upserted to sanctions_entities.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import AsyncSessionLocal
from app.models.sanctions import SanctionsEntity

logger = logging.getLogger("orthanc.sanctions.eu")

EU_SANCTIONS_URL = (
    "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content"
)

REFRESH_INTERVAL = 86_400  # 24 hours
BATCH_SIZE = 500

SOURCE_META = {
    "source_class": "official_data",
    "default_reliability_prior": "high",
    "ecosystem": "sanctions",
    "language": "English",
}


class EUSanctionsService:
    """Download and parse EU consolidated sanctions list."""

    def __init__(self):
        self._entities: list[dict] = []
        self._last_updated: Optional[datetime] = None
        self._loading = False
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_error: Optional[str] = None

    # ── Scheduled refresh ─────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start periodic refresh loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._refresh_loop(), name="eu_sanctions_refresh")
        logger.info("EU FSF sanctions refresh loop started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("EU sanctions service stopped")

    async def _refresh_loop(self) -> None:
        while self._running:
            try:
                await self.download_and_parse()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                logger.error("EU sanctions refresh error: %s", exc)
            try:
                await asyncio.sleep(REFRESH_INTERVAL)
            except asyncio.CancelledError:
                raise

    async def download_and_parse(self) -> int:
        """Download EU sanctions XML and parse into entity records.

        Returns count of entities parsed.
        """
        if self._loading:
            return len(self._entities)

        self._loading = True
        try:
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                resp = await client.get(EU_SANCTIONS_URL)
                resp.raise_for_status()
                xml_data = resp.content

            # Parse XML in executor (CPU-bound)
            loop = asyncio.get_event_loop()
            entities = await loop.run_in_executor(None, self._parse_xml, xml_data)

            self._entities = entities
            self._last_updated = datetime.now(timezone.utc)
            self._last_error = None
            logger.info("EU sanctions list loaded: %d entities", len(entities))

            # Upsert into DB
            await self._upsert_to_db(entities)

            return len(entities)
        except Exception as e:
            self._last_error = str(e)
            logger.error("Failed to download EU sanctions: %s", e)
            return 0
        finally:
            self._loading = False

    def _parse_xml(self, xml_data: bytes) -> list[dict]:
        """Parse the EU sanctions XML format."""
        from lxml import etree  # noqa: PLC0415

        entities = []
        root = etree.fromstring(xml_data)

        # EU sanctions XML uses namespace
        ns = {"eu": "http://eu.europa.ec/fpi/fsd/export"}

        # Try without namespace first, then with namespace, then wildcard
        sanctions_entities = (
            root.findall(".//sanctionEntity")
            or root.findall(".//eu:sanctionEntity", ns)
            or root.findall(".//{*}sanctionEntity")
        )

        for entity_elem in sanctions_entities:
            entity = self._parse_entity(entity_elem)
            if entity:
                entities.append(entity)

        # Fallback: if structured parsing yielded nothing, collect nameAlias elements directly
        if not entities:
            seen: set[str] = set()
            idx = 0
            for elem in root.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag == "nameAlias":
                    name = elem.get("wholeName", "").strip()
                    if name and name not in seen:
                        seen.add(name)
                        idx += 1
                        entities.append(
                            {
                                "id": f"eu-fsf-alias-{idx}",
                                "name": name,
                                "type": "unknown",
                                "entity_type": "unknown",
                                "source": "eu_sanctions",
                                "aliases": [],
                                "nationalities": [],
                                "details": {},
                                "datasets": ["eu_fsf"],
                                "countries": [],
                                "properties": SOURCE_META,
                            }
                        )

        return entities

    def _parse_entity(self, elem) -> dict | None:
        """Parse a single sanctioned entity element."""
        # Assign a stable ID from element attributes
        entity_id = (
            elem.get("logicalId", "") or elem.get("id", "") or
            elem.get("euReferenceNumber", "")
        ).strip()

        entity: dict = {
            "type": "unknown",
            "entity_type": "unknown",
            "source": "eu_sanctions",
            "aliases": [],
            "nationalities": [],
            "details": {},
            "datasets": ["eu_fsf"],
            "countries": [],
            "properties": {**SOURCE_META},
        }

        if entity_id:
            entity["id"] = f"eu-fsf-{entity_id}"
            entity["properties"]["eu_id"] = entity_id

        # Determine subject type (person / organisation)
        sub_type = elem.get("subjectType", "").lower()
        if "person" in sub_type:
            entity["type"] = "person"
            entity["entity_type"] = "person"
        elif "enterprise" in sub_type or "entity" in sub_type or "organisation" in sub_type:
            entity["type"] = "organization"
            entity["entity_type"] = "organization"

        # Walk child elements for names, aliases, citizenships
        name_idx = 0
        for child in elem.iter():
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

            if tag == "nameAlias":
                whole_name = child.get("wholeName", "").strip()
                if whole_name:
                    if "name" not in entity:
                        entity["name"] = whole_name
                        if not entity.get("id"):
                            entity["id"] = f"eu-fsf-name-{whole_name[:80]}"
                    else:
                        if whole_name not in entity["aliases"]:
                            entity["aliases"].append(whole_name)
                name_idx += 1

            elif tag == "citizenship":
                country = child.get("countryDescription", "").strip()
                if country:
                    entity["nationalities"].append(country)
                    if country not in entity["countries"]:
                        entity["countries"].append(country)

        if "name" not in entity:
            return None

        return entity

    # ── DB Upsert ─────────────────────────────────────────────────────────────

    async def _upsert_to_db(self, entities: list[dict]) -> None:
        """Upsert parsed EU entities into sanctions_entities table."""
        if not entities:
            return

        total = 0
        for i in range(0, len(entities), BATCH_SIZE):
            batch = entities[i : i + BATCH_SIZE]
            try:
                async with AsyncSessionLocal() as db:
                    for rec in batch:
                        rec_id = rec.get("id")
                        if not rec_id:
                            continue
                        entity_type = rec.get("entity_type") or rec.get("type") or "unknown"
                        stmt = pg_insert(SanctionsEntity).values(
                            id=rec_id,
                            name=rec["name"],
                            entity_type=entity_type,
                            aliases=rec.get("aliases", []),
                            datasets=rec.get("datasets", ["eu_fsf"]),
                            countries=rec.get("countries", []),
                            properties=rec.get("properties", SOURCE_META),
                            updated_at=func.now(),
                        )
                        stmt = stmt.on_conflict_do_update(
                            index_elements=["id"],
                            set_={
                                "name": stmt.excluded.name,
                                "entity_type": stmt.excluded.entity_type,
                                "aliases": stmt.excluded.aliases,
                                "datasets": stmt.excluded.datasets,
                                "countries": stmt.excluded.countries,
                                "properties": stmt.excluded.properties,
                                "updated_at": func.now(),
                            },
                        )
                        await db.execute(stmt)
                    await db.commit()
                total += len(batch)
            except Exception as exc:
                logger.error("EU sanctions DB upsert error: %s", exc)
            await asyncio.sleep(0)

        logger.info("EU FSF sanctions: upserted %d entities to DB", total)

    # ── In-memory search ──────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Search EU sanctions list by name (case-insensitive substring match)."""
        query_lower = query.lower()
        results: list[dict] = []

        for ent in self._entities:
            if len(results) >= limit:
                break

            name = ent.get("name", "")
            if query_lower in name.lower():
                results.append(ent)
                continue

            for alias in ent.get("aliases", []):
                if query_lower in alias.lower():
                    results.append(ent)
                    break

        return results

    @property
    def count(self) -> int:
        return len(self._entities)

    @property
    def last_updated(self) -> Optional[datetime]:
        return self._last_updated

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "entity_count": len(self._entities),
            "last_updated": self._last_updated.isoformat() if self._last_updated else None,
            "last_error": self._last_error,
        }


eu_sanctions_service = EUSanctionsService()
