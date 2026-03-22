"""UK Sanctions List ingestion — FCDO XML and OFSI CSV formats.

Primary source (FCDO XML):
  https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml

Legacy fallback (OFSI CSV):
  https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.csv

Refresh cadence: daily.
Parsed entities are stored in-memory AND upserted into sanctions_entities.
"""
import asyncio
import csv
import io
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import AsyncSessionLocal
from app.models.sanctions import SanctionsEntity

logger = logging.getLogger("orthanc.sanctions.uk")

# Primary: FCDO XML
UK_SANCTIONS_XML_URL = "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml"

# Legacy fallback: OFSI CSV
UK_SANCTIONS_CSV_URL = (
    "https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.csv"
)

REFRESH_INTERVAL = 86_400  # 24 hours
BATCH_SIZE = 500

SOURCE_META = {
    "source_class": "official_data",
    "default_reliability_prior": "high",
    "ecosystem": "sanctions",
    "language": "English",
}


class UKSanctionsService:
    """Download and parse UK consolidated sanctions list (FCDO XML + OFSI CSV fallback)."""

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
        self._task = asyncio.create_task(self._refresh_loop(), name="uk_sanctions_refresh")
        logger.info("UK sanctions refresh loop started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("UK sanctions service stopped")

    async def _refresh_loop(self) -> None:
        while self._running:
            try:
                await self.download_and_parse()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                logger.error("UK sanctions refresh error: %s", exc)
            try:
                await asyncio.sleep(REFRESH_INTERVAL)
            except asyncio.CancelledError:
                raise

    # ── Download & parse ──────────────────────────────────────────────────────

    async def download_and_parse(self) -> int:
        """Download UK sanctions list and parse into entity records.

        Tries FCDO XML first; falls back to OFSI CSV.
        Returns count of entities parsed.
        """
        if self._loading:
            return len(self._entities)

        self._loading = True
        try:
            # Try primary FCDO XML source
            entities = await self._try_xml()
            if not entities:
                # Fall back to OFSI CSV
                logger.warning("FCDO XML empty or failed — falling back to OFSI CSV")
                entities = await self._try_csv()

            self._entities = entities
            self._last_updated = datetime.now(timezone.utc)
            self._last_error = None
            logger.info("UK sanctions list loaded: %d entities", len(entities))

            # Upsert into DB
            await self._upsert_to_db(entities)

            return len(entities)
        except Exception as e:
            self._last_error = str(e)
            logger.error("Failed to download UK sanctions: %s", e)
            return 0
        finally:
            self._loading = False

    async def _try_xml(self) -> list[dict]:
        """Try downloading and parsing the FCDO XML format."""
        try:
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                resp = await client.get(UK_SANCTIONS_XML_URL)
                resp.raise_for_status()
                xml_data = resp.content

            loop = asyncio.get_event_loop()
            entities = await loop.run_in_executor(None, self._parse_fcdo_xml, xml_data)
            return entities
        except Exception as exc:
            logger.warning("FCDO XML fetch/parse failed: %s", exc)
            return []

    async def _try_csv(self) -> list[dict]:
        """Try downloading and parsing the OFSI CSV format (legacy fallback)."""
        try:
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                resp = await client.get(UK_SANCTIONS_CSV_URL)
                resp.raise_for_status()
                csv_text = resp.text

            loop = asyncio.get_event_loop()
            entities = await loop.run_in_executor(None, self._parse_csv, csv_text)
            return entities
        except Exception as exc:
            logger.warning("OFSI CSV fetch/parse failed: %s", exc)
            return []

    # ── FCDO XML Parser ───────────────────────────────────────────────────────

    def _parse_fcdo_xml(self, xml_data: bytes) -> list[dict]:
        """Parse the UK FCDO XML sanctions list (Designations format).

        Expected structure:
          <Designations>
            <Designation>
              <UniqueID>AFG0001</UniqueID>
              <Names>
                <Name>
                  <Name6>FULL ENTITY NAME</Name6>
                  <NameType>Primary Name</NameType>
                </Name>
                <Name>
                  <Name6>AKA NAME</Name6>
                  <NameType>Alias</NameType>
                </Name>
              </Names>
              <IndividualEntityShip>Entity</IndividualEntityShip>
              <RegimeName>...</RegimeName>
              <SanctionsImposed>Asset freeze</SanctionsImposed>
            </Designation>
          </Designations>

        No XML namespace on this document.
        """
        import xml.etree.ElementTree as ET

        entities: list[dict] = []
        seen_ids: set[str] = set()

        try:
            root = ET.fromstring(xml_data)
        except Exception as exc:
            logger.error("UK FCDO XML parse error: %s", exc)
            return entities

        def _get_text(elem, tag: str) -> str:
            child = elem.find(tag)
            return (child.text or "").strip() if child is not None else ""

        def _name_from_name_elem(name_elem) -> str:
            """Extract a display name from a <Name> element.

            Prefers Name6 (full name field); falls back to joining Name1-Name5
            (title, first, middle, middle2, surname).
            """
            name6 = _get_text(name_elem, "Name6")
            if name6:
                return name6
            parts = []
            for i in range(1, 6):
                part = _get_text(name_elem, f"Name{i}")
                if part:
                    parts.append(part)
            return " ".join(parts).strip()

        # Find all <Designation> elements under root
        designations = root.findall("Designation")
        if not designations:
            # Root might itself be a <Designation> list at a different depth
            designations = list(root.iter("Designation"))

        logger.debug("UK FCDO: found %d Designation elements", len(designations))

        for desig in designations:
            try:
                unique_id = _get_text(desig, "UniqueID")
                if not unique_id:
                    continue

                db_id = f"uk-fcdo-{unique_id}"
                if db_id in seen_ids:
                    continue
                seen_ids.add(db_id)

                # Names block
                primary_name: str = ""
                aliases: list[str] = []

                names_elem = desig.find("Names")
                if names_elem is not None:
                    for name_elem in names_elem.findall("Name"):
                        name_type = _get_text(name_elem, "NameType")
                        display = _name_from_name_elem(name_elem)
                        if not display:
                            continue
                        if name_type == "Primary Name":
                            primary_name = display
                        else:
                            # "Alias", "Primary Name Alias", or anything else
                            if display not in aliases:
                                aliases.append(display)

                if not primary_name:
                    # Use first alias as primary if no Primary Name found
                    if aliases:
                        primary_name = aliases.pop(0)
                    else:
                        continue

                # Remove primary from aliases in case of duplicate
                aliases = [a for a in aliases if a != primary_name]

                # Entity type from <IndividualEntityShip>
                ies_text = _get_text(desig, "IndividualEntityShip").lower()
                if "individual" in ies_text:
                    entity_type = "person"
                elif "ship" in ies_text or "vessel" in ies_text:
                    entity_type = "vessel"
                else:
                    entity_type = "organization"

                regime = _get_text(desig, "RegimeName")
                sanctions_imposed = _get_text(desig, "SanctionsImposed")

                datasets = ["uk_fcdo"]

                entities.append({
                    "id": db_id,
                    "name": primary_name,
                    "entity_type": entity_type,
                    "aliases": aliases,
                    "datasets": datasets,
                    "countries": [],
                    "properties": {
                        **SOURCE_META,
                        "source_id": unique_id,
                        "regime": regime,
                        "sanctions_imposed": sanctions_imposed,
                        "individual_entity_ship": ies_text,
                    },
                })
            except Exception as exc:
                logger.debug("UK FCDO Designation parse error: %s", exc)
                continue

        logger.info("UK FCDO: parsed %d entities from XML", len(entities))
        return entities

    # ── CSV Parser (OFSI legacy) ──────────────────────────────────────────────

    def _parse_csv(self, csv_text: str) -> list[dict]:
        """Parse the legacy UK OFSI CSV format."""
        groups: dict[str, dict] = {}

        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            group_id = row.get("Group ID", "").strip()
            if not group_id:
                continue

            if group_id not in groups:
                group_type = row.get("Group Type", "").lower()
                entity_type = "person" if "individual" in group_type else "organization"

                name = row.get("Name 6", "").strip()
                if not name:
                    parts = [row.get(f"Name {i}", "").strip() for i in range(1, 6)]
                    name = " ".join(p for p in parts if p)

                if not name:
                    continue

                groups[group_id] = {
                    "id": f"uk-ofsi-{group_id}",
                    "name": name,
                    "entity_type": entity_type,
                    "aliases": [],
                    "datasets": ["uk_ofsi"],
                    "countries": [row.get("Country", "").strip()] if row.get("Country", "").strip() else [],
                    "properties": {
                        **SOURCE_META,
                        "group_id": group_id,
                        "regime": row.get("Regime", "").strip(),
                        "un_reference": row.get("UN Reference", "").strip(),
                    },
                }
            else:
                alias = row.get("Name 6", "").strip()
                if not alias:
                    parts = [row.get(f"Name {i}", "").strip() for i in range(1, 6)]
                    alias = " ".join(p for p in parts if p)
                if alias and alias != groups[group_id]["name"] and alias not in groups[group_id]["aliases"]:
                    groups[group_id]["aliases"].append(alias)

            entity = groups.get(group_id)
            if entity:
                for col, val in row.items():
                    if col.startswith("Alias") and val.strip():
                        alias_val = val.strip()
                        if alias_val != entity["name"] and alias_val not in entity["aliases"]:
                            entity["aliases"].append(alias_val)

        return list(groups.values())

    # ── DB Upsert ─────────────────────────────────────────────────────────────

    async def _upsert_to_db(self, entities: list[dict]) -> None:
        """Upsert parsed entities into sanctions_entities table."""
        if not entities:
            return

        total = 0
        for i in range(0, len(entities), BATCH_SIZE):
            batch = entities[i : i + BATCH_SIZE]
            try:
                async with AsyncSessionLocal() as db:
                    for rec in batch:
                        stmt = pg_insert(SanctionsEntity).values(
                            id=rec["id"],
                            name=rec["name"],
                            entity_type=rec["entity_type"],
                            aliases=rec["aliases"],
                            datasets=rec["datasets"],
                            countries=rec["countries"],
                            properties=rec["properties"],
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
                logger.error("UK sanctions DB upsert error: %s", exc)
            await asyncio.sleep(0)

        logger.info("UK sanctions: upserted %d entities to DB", total)

    # ── In-memory search (legacy API compatibility) ───────────────────────────

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Search UK sanctions list by name or alias (case-insensitive substring)."""
        query_lower = query.lower()
        results: list[dict] = []

        for ent in self._entities:
            if len(results) >= limit:
                break
            if query_lower in ent["name"].lower():
                results.append(ent)
                continue
            if any(query_lower in a.lower() for a in ent.get("aliases", [])):
                results.append(ent)

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
            "entity_count": self._entity_count if hasattr(self, "_entity_count") else len(self._entities),
            "last_updated": self._last_updated.isoformat() if self._last_updated else None,
            "last_error": self._last_error,
        }

    @property
    def _entity_count(self) -> int:
        return len(self._entities)


uk_sanctions_service = UKSanctionsService()
