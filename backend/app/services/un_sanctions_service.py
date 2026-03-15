"""UN Security Council Consolidated Sanctions List ingestion.

Downloads and parses the UN SC XML list, upserts into sanctions_entities.

Source:  https://scsanctions.un.org/resources/xml/en/consolidated.xml
Cadence: every 12 hours (refreshed twice daily — UN updates the list ad-hoc)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import AsyncSessionLocal
from app.models.sanctions import SanctionsEntity

logger = logging.getLogger("orthanc.sanctions.un")

UN_SC_XML_URL = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"
REFRESH_INTERVAL = 43_200  # 12 hours
BATCH_SIZE = 500

SOURCE_META = {
    "source_class": "official_data",
    "default_reliability_prior": "high",
    "ecosystem": "sanctions",
    "language": "English",
}


class UNSanctionsService:
    """Download and ingest the UN SC consolidated sanctions list."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_updated: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._entity_count: int = 0

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._refresh_loop(), name="un_sanctions_refresh")
        logger.info("UN SC sanctions refresh loop started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("UN SC sanctions service stopped")

    async def _refresh_loop(self) -> None:
        while self._running:
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                logger.error("UN SC sanctions refresh error: %s", exc)
            try:
                await asyncio.sleep(REFRESH_INTERVAL)
            except asyncio.CancelledError:
                raise

    async def refresh(self) -> None:
        """Download and upsert the UN SC consolidated list."""
        logger.info("Downloading UN SC consolidated sanctions list")
        try:
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                resp = await client.get(UN_SC_XML_URL)
                resp.raise_for_status()
                xml_bytes = resp.content
        except httpx.HTTPError as exc:
            logger.error("UN SC download failed: %s", exc)
            self._last_error = str(exc)
            return

        logger.info("UN SC: downloaded %.1f KB", len(xml_bytes) / 1024)

        loop = asyncio.get_event_loop()
        try:
            entities = await loop.run_in_executor(None, self._parse_xml, xml_bytes)
        except Exception as exc:
            logger.error("UN SC XML parse error: %s", exc)
            self._last_error = str(exc)
            return

        logger.info("UN SC: parsed %d entities", len(entities))
        await self._upsert_entities(entities)
        self._entity_count = len(entities)
        self._last_updated = datetime.now(timezone.utc)
        self._last_error = None

    def _parse_xml(self, xml_bytes: bytes) -> list[dict]:
        """Parse the UN SC consolidated XML format."""
        try:
            from lxml import etree
        except ImportError:
            import xml.etree.ElementTree as etree  # type: ignore

        entities: list[dict] = []

        try:
            root = etree.fromstring(xml_bytes)
        except Exception as exc:
            logger.error("UN SC XML root parse failed: %s", exc)
            return entities

        # Parse individuals
        for individual in root.iter():
            tag = individual.tag.split("}")[-1] if "}" in str(individual.tag) else str(individual.tag)
            if tag == "INDIVIDUAL":
                entity = self._parse_individual(individual)
                if entity:
                    entities.append(entity)

        # Parse entities/organizations
        for org in root.iter():
            tag = org.tag.split("}")[-1] if "}" in str(org.tag) else str(org.tag)
            if tag == "ENTITY":
                entity = self._parse_org(org)
                if entity:
                    entities.append(entity)

        return entities

    def _get_text(self, elem, tag: str) -> str:
        """Get text from child element, namespace-safe."""
        child = elem.find(tag)
        if child is None:
            child = elem.find(f"{{*}}{tag}")
        return (child.text or "").strip() if child is not None else ""

    def _parse_individual(self, elem) -> dict | None:
        """Parse an <INDIVIDUAL> element."""
        data_id = self._get_text(elem, "DATAID")
        if not data_id:
            return None

        first = self._get_text(elem, "FIRST_NAME")
        second = self._get_text(elem, "SECOND_NAME")
        third = self._get_text(elem, "THIRD_NAME")
        fourth = self._get_text(elem, "FOURTH_NAME")

        name_parts = [p for p in [first, second, third, fourth] if p]
        name = " ".join(name_parts).strip()
        if not name:
            return None

        # Collect aliases
        aliases: list[str] = []
        for alias_elem in elem.iter():
            a_tag = alias_elem.tag.split("}")[-1] if "}" in str(alias_elem.tag) else str(alias_elem.tag)
            if a_tag == "ALIAS_NAME":
                quality = self._get_text(alias_elem.getparent() if hasattr(alias_elem, 'getparent') else elem, "QUALITY")
                alias_name = (alias_elem.text or "").strip()
                if alias_name and alias_name != name and alias_name not in aliases:
                    aliases.append(alias_name)

        # Nationality
        countries: list[str] = []
        nationality = self._get_text(elem, "NATIONALITY")
        if nationality:
            countries.append(nationality)

        # List type (Al-Qaida, Taliban, etc.)
        list_type = self._get_text(elem, "UN_LIST_TYPE")
        reference = self._get_text(elem, "REFERENCE_NUMBER")

        datasets = ["un_sc"]
        if list_type:
            datasets.append(f"un_sc_{list_type.lower().replace(' ', '_').replace('-', '_')}")

        return {
            "id": f"un-sc-ind-{data_id}",
            "name": name,
            "entity_type": "person",
            "aliases": aliases,
            "datasets": datasets,
            "countries": countries,
            "properties": {
                **SOURCE_META,
                "dataid": data_id,
                "un_list_type": list_type,
                "reference_number": reference,
            },
        }

    def _parse_org(self, elem) -> dict | None:
        """Parse an <ENTITY> element (organization)."""
        data_id = self._get_text(elem, "DATAID")
        if not data_id:
            return None

        first_name = self._get_text(elem, "FIRST_NAME")
        name = first_name.strip()
        if not name:
            return None

        aliases: list[str] = []
        for alias_elem in elem.iter():
            a_tag = alias_elem.tag.split("}")[-1] if "}" in str(alias_elem.tag) else str(alias_elem.tag)
            if a_tag == "ALIAS_NAME":
                alias_name = (alias_elem.text or "").strip()
                if alias_name and alias_name != name and alias_name not in aliases:
                    aliases.append(alias_name)

        list_type = self._get_text(elem, "UN_LIST_TYPE")
        reference = self._get_text(elem, "REFERENCE_NUMBER")

        datasets = ["un_sc"]
        if list_type:
            datasets.append(f"un_sc_{list_type.lower().replace(' ', '_').replace('-', '_')}")

        return {
            "id": f"un-sc-ent-{data_id}",
            "name": name,
            "entity_type": "organization",
            "aliases": aliases,
            "datasets": datasets,
            "countries": [],
            "properties": {
                **SOURCE_META,
                "dataid": data_id,
                "un_list_type": list_type,
                "reference_number": reference,
            },
        }

    async def _upsert_entities(self, entities: list[dict]) -> None:
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
                logger.error("UN SC upsert batch failed: %s", exc)
            await asyncio.sleep(0)

        logger.info("UN SC: upserted %d entities", total)

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "last_updated": self._last_updated.isoformat() if self._last_updated else None,
            "entity_count": self._entity_count,
            "last_error": self._last_error,
        }


# Singleton
un_sanctions_service = UNSanctionsService()
