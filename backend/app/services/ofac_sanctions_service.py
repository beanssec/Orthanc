"""OFAC Sanctions List Service — ingests OFAC SDN and Consolidated lists.

Downloads OFAC SDN (Specially Designated Nationals) and Consolidated Sanctions
lists from the official OFAC servers, parses the XML, and upserts into the
sanctions_entities table for use by the entity matching pipeline.

Sources:
  SDN list (SLS portal):  https://sanctionslist.ofac.treas.gov/Home/SdnList
  SDN list (legacy):      https://ofac.treasury.gov/downloads/sdn_advanced.xml
  Consolidated:           https://ofac.treasury.gov/downloads/consolidated.xml

The new Sanctions List Service (SLS) portal URL is tried first for the SDN list.
If it returns XML-parseable content, it is used; otherwise the legacy URL is used
as a fallback to guarantee continuity.

Refresh cadence: daily (triggered at startup, then every 24 h).
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

logger = logging.getLogger("orthanc.sanctions.ofac")

# New OFAC Sanctions List Service (SLS) portal — primary endpoint for SDN
OFAC_SDN_SLS_URL = "https://sanctionslist.ofac.treas.gov/Home/SdnList"

# Legacy OFAC XML download endpoints (fallback / consolidated)
OFAC_SDN_URL = "https://ofac.treasury.gov/downloads/sdn_advanced.xml"
OFAC_CONSOLIDATED_URL = "https://ofac.treasury.gov/downloads/consolidated.xml"

# SDN XML namespace
SDN_NS = "http://tempuri.org/sdnList.xsd"

# Map OFAC sdnType → our entity_type
OFAC_TYPE_MAP = {
    "individual": "person",
    "entity": "organization",
    "vessel": "vessel",
    "aircraft": "aircraft",
}

REFRESH_INTERVAL = 86_400  # 24 hours
BATCH_SIZE = 500

SOURCE_META = {
    "source_class": "official_data",
    "default_reliability_prior": "high",
    "ecosystem": "sanctions",
    "language": "English",
}


class OFACSanctionsService:
    """Download and ingest OFAC sanctions lists into sanctions_entities."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_sdn_updated: Optional[datetime] = None
        self._last_consolidated_updated: Optional[datetime] = None
        self._last_error: Optional[str] = None

    async def start(self) -> None:
        """Start periodic refresh loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._refresh_loop(), name="ofac_sanctions_refresh")
        logger.info("OFAC sanctions refresh loop started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("OFAC sanctions service stopped")

    # ── Refresh loop ──────────────────────────────────────────────────────────

    async def _refresh_loop(self) -> None:
        """Initial fetch + repeat every 24 h."""
        while self._running:
            try:
                await self.refresh_all()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                logger.error("OFAC refresh error: %s", exc)
            try:
                await asyncio.sleep(REFRESH_INTERVAL)
            except asyncio.CancelledError:
                raise

    async def refresh_all(self) -> None:
        """Fetch and upsert both OFAC lists.

        For the SDN list, the newer Sanctions List Service (SLS) portal URL is
        tried first.  If it fails or returns non-XML content the legacy direct
        download URL is used as a fallback so collection is never skipped.
        """
        sdn_ingested = await self._ingest_list("sdn", OFAC_SDN_SLS_URL)
        if not sdn_ingested:
            logger.info("OFAC SLS portal yielded nothing — falling back to legacy SDN URL")
            await self._ingest_list("sdn", OFAC_SDN_URL)
        await asyncio.sleep(5)  # stagger requests
        await self._ingest_list("consolidated", OFAC_CONSOLIDATED_URL)

    # ── Ingest a single list ──────────────────────────────────────────────────

    async def _ingest_list(self, list_name: str, url: str) -> bool:
        """Download and upsert one OFAC XML list.

        Returns True if entities were successfully parsed and upserted, False
        on any error (including non-XML responses) so the caller can fall back.
        """
        logger.info("Downloading OFAC %s list from %s", list_name, url)
        try:
            async with httpx.AsyncClient(
                timeout=120.0,
                follow_redirects=True,
                headers={"Accept": "application/xml, text/xml, */*"},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                xml_bytes = resp.content
        except httpx.HTTPError as exc:
            logger.error("OFAC %s download failed: %s", list_name, exc)
            return False

        # Reject HTML responses (e.g. portal login page, redirect to web UI)
        content_type = resp.headers.get("content-type", "").lower()
        if "html" in content_type and "xml" not in content_type:
            # Peek at raw bytes to double-check — sometimes servers lie
            if not xml_bytes.lstrip()[:5] in (b"<?xml", b"<sdnL", b"<cons"):
                logger.warning(
                    "OFAC %s from %s returned HTML (content-type: %s) — skipping",
                    list_name, url, content_type,
                )
                return False

        logger.info("OFAC %s: downloaded %.1f KB", list_name, len(xml_bytes) / 1024)

        loop = asyncio.get_event_loop()
        try:
            entities = await loop.run_in_executor(
                None, self._parse_xml, xml_bytes, list_name
            )
        except Exception as exc:
            logger.error("OFAC %s XML parse error: %s", list_name, exc)
            return False

        if not entities:
            logger.warning("OFAC %s: parsed 0 entities from %s", list_name, url)
            return False

        logger.info("OFAC %s: parsed %d entities", list_name, len(entities))
        await self._upsert_entities(entities)

        if list_name == "sdn":
            self._last_sdn_updated = datetime.now(timezone.utc)
        else:
            self._last_consolidated_updated = datetime.now(timezone.utc)

        return True

    # ── XML Parser ────────────────────────────────────────────────────────────

    def _parse_xml(self, xml_bytes: bytes, list_name: str) -> list[dict]:
        """Parse OFAC advanced XML format into entity dicts."""
        try:
            from lxml import etree
        except ImportError:
            import xml.etree.ElementTree as etree  # type: ignore

        entities: list[dict] = []

        try:
            root = etree.fromstring(xml_bytes)
        except Exception as exc:
            logger.error("OFAC XML root parse failed: %s", exc)
            return entities

        # Try namespace-aware and namespace-free paths
        ns = {"sdn": SDN_NS}
        sdn_entries = (
            root.findall(".//sdnEntry")
            or root.findall(f".//{{{SDN_NS}}}sdnEntry")
        )

        for entry in sdn_entries:
            try:
                entity = self._parse_entry(entry, list_name)
                if entity:
                    entities.append(entity)
            except Exception as exc:
                logger.debug("OFAC entry parse error: %s", exc)

        return entities

    def _parse_entry(self, entry, list_name: str) -> dict | None:
        """Parse one <sdnEntry> element."""

        def _find_text(elem, tag: str) -> str:
            """Find text stripping namespaces."""
            # Try bare tag
            child = elem.find(tag)
            if child is None:
                # Try with namespace wildcard
                child = elem.find(f"{{*}}{tag}")
            return (child.text or "").strip() if child is not None else ""

        def _find_all(elem, tag: str):
            children = elem.findall(tag)
            if not children:
                children = elem.findall(f"{{*}}{tag}")
            return children

        uid = _find_text(entry, "uid")
        if not uid:
            return None

        last_name = _find_text(entry, "lastName")
        first_name = _find_text(entry, "firstName")
        sdn_type = _find_text(entry, "sdnType").lower()

        # Build primary name
        if first_name and last_name:
            name = f"{first_name} {last_name}".strip()
        else:
            name = last_name or first_name
        if not name:
            return None

        entity_type = OFAC_TYPE_MAP.get(sdn_type, "organization")

        # Collect aliases from akaList
        aliases: list[str] = []
        aka_list = entry.find("akaList") or entry.find("{*}akaList")
        if aka_list is not None:
            for aka in _find_all(aka_list, "aka"):
                aka_last = _find_text(aka, "lastName")
                aka_first = _find_text(aka, "firstName")
                if aka_first and aka_last:
                    alias = f"{aka_first} {aka_last}".strip()
                elif aka_last:
                    alias = aka_last
                elif aka_first:
                    alias = aka_first
                else:
                    continue
                if alias and alias != name and alias not in aliases:
                    aliases.append(alias)

        # Nationalities / countries
        countries: list[str] = []
        nat_list = entry.find("nationalityList") or entry.find("{*}nationalityList")
        if nat_list is not None:
            for nat in _find_all(nat_list, "nationality"):
                country = _find_text(nat, "country")
                if country and country not in countries:
                    countries.append(country)

        # Programs (sanction regimes)
        programs: list[str] = []
        prog_list = entry.find("programList") or entry.find("{*}programList")
        if prog_list is not None:
            for prog in _find_all(prog_list, "program"):
                prog_text = (prog.text or "").strip()
                if prog_text:
                    programs.append(prog_text)

        entity_id = f"ofac-{list_name}-{uid}"

        return {
            "id": entity_id,
            "name": name,
            "entity_type": entity_type,
            "aliases": aliases,
            "datasets": [f"ofac_{list_name}"] + programs,
            "countries": countries,
            "properties": {
                **SOURCE_META,
                "ofac_uid": uid,
                "sdn_type": sdn_type,
                "list": list_name,
                "programs": programs,
            },
        }

    # ── DB Upsert ─────────────────────────────────────────────────────────────

    async def _upsert_entities(self, entities: list[dict]) -> None:
        """Batch-upsert parsed entities into sanctions_entities."""
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
                logger.error("OFAC upsert batch failed: %s", exc)
            await asyncio.sleep(0)  # yield control

        logger.info("OFAC: upserted %d entities", total)

    # ── Status ────────────────────────────────────────────────────────────────

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "last_sdn_updated": self._last_sdn_updated.isoformat() if self._last_sdn_updated else None,
            "last_consolidated_updated": self._last_consolidated_updated.isoformat() if self._last_consolidated_updated else None,
            "last_error": self._last_error,
            "sdn_sources": [OFAC_SDN_SLS_URL, OFAC_SDN_URL],  # primary + fallback
        }


# Singleton
ofac_sanctions_service = OFACSanctionsService()
