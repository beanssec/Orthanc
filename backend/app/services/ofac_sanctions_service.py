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
OFAC_SDN_URL = "https://sanctionslistservice.ofac.treas.gov/api/publicationpreview/exports/sdn_advanced.xml"
OFAC_CONSOLIDATED_URL = "https://sanctionslistservice.ofac.treas.gov/api/publicationpreview/exports/consolidated.xml"

# SDN XML namespace (new OFAC advanced XML schema)
SDN_NS = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/ADVANCED_XML"

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

    # PartySubTypeID → entity_type mapping for the new advanced XML schema.
    # 1 = Individual, 2 = Entity (generic), 3 = Entity (org), 4 = Individual,
    # 5 = Vessel, 6 = Aircraft.  We keep it simple and map to our internal types.
    _PARTY_SUBTYPE_MAP: dict[str, str] = {
        "1": "person",
        "2": "organization",
        "3": "organization",
        "4": "person",
        "5": "vessel",
        "6": "aircraft",
    }

    def _parse_xml(self, xml_bytes: bytes, list_name: str) -> list[dict]:
        """Parse OFAC advanced XML (new SLS schema) into entity dicts.

        The new schema looks like:
          <Sanctions xmlns="https://...ADVANCED_XML">
            <DistinctParty FixedRef="36">
              <Profile ID="36" PartySubTypeID="3">
                <Identity ...>
                  <Alias AliasTypeID="1403" Primary="true">
                    <NamePartValue ...>PRIMARY NAME</NamePartValue>
                  </Alias>
                  <Alias AliasTypeID="1400" Primary="false">
                    <NamePartValue ...>AKA NAME</NamePartValue>
                  </Alias>
                </Identity>
              </Profile>
            </DistinctParty>
          </Sanctions>
        """
        import xml.etree.ElementTree as ET

        entities: list[dict] = []

        try:
            root = ET.fromstring(xml_bytes)
        except Exception as exc:
            logger.error("OFAC XML root parse failed: %s", exc)
            return entities

        # Detect namespace from root tag or use the known constant
        ns = SDN_NS
        # Strip namespace prefix helper
        def _tag(local: str) -> str:
            return f"{{{ns}}}{local}"

        # Support both namespaced and namespace-stripped documents
        def _findall(elem, local: str):
            results = elem.findall(_tag(local))
            if not results:
                results = elem.findall(local)
            return results

        def _find(elem, local: str):
            result = elem.find(_tag(local))
            if result is None:
                result = elem.find(local)
            return result

        def _attr(elem, name: str, default: str = "") -> str:
            return (elem.get(name) or default).strip()

        # Iterate DistinctParty elements — use iter() since they're nested
        # under intermediate wrapper elements, not direct children of root
        distinct_parties = list(root.iter(_tag("DistinctParty")))
        if not distinct_parties:
            distinct_parties = list(root.iter("DistinctParty"))
        if not distinct_parties:
            distinct_parties = _findall(root, "DistinctParty")

        logger.info("OFAC %s: found %d DistinctParty elements", list_name, len(distinct_parties))

        parse_errors = 0
        parse_skipped = 0
        for party in distinct_parties:
            try:
                entity = self._parse_distinct_party(party, list_name, _find, _findall, _attr)
                if entity:
                    entities.append(entity)
                else:
                    parse_skipped += 1
            except Exception as exc:
                parse_errors += 1
                if parse_errors <= 3:
                    logger.warning("OFAC DistinctParty parse error (showing first 3): %s", exc)

        if parse_errors or parse_skipped:
            logger.warning("OFAC %s: %d parse errors, %d skipped (no name), %d successful", 
                          list_name, parse_errors, parse_skipped, len(entities))

        logger.info("OFAC %s: parsed %d entities", list_name, len(entities))
        return entities

    def _parse_distinct_party(self, party, list_name: str, _find, _findall, _attr) -> dict | None:
        """Parse one <DistinctParty> element from the new OFAC advanced XML schema."""
        fixed_ref = _attr(party, "FixedRef")

        profile = _find(party, "Profile")
        if profile is None:
            return None

        profile_id = _attr(profile, "ID") or fixed_ref
        subtype_id = _attr(profile, "PartySubTypeID", "2")
        entity_type = self._PARTY_SUBTYPE_MAP.get(subtype_id, "organization")

        # Collect all Identity/Alias elements
        primary_name: str = ""
        aliases: list[str] = []

        identities = _findall(profile, "Identity")
        for identity in identities:
            alias_elems = _findall(identity, "Alias")
            for alias_elem in alias_elems:
                alias_type_id = _attr(alias_elem, "AliasTypeID")
                is_primary = _attr(alias_elem, "Primary").lower() == "true"

                # Collect NamePartValues — nested under DocumentedName/DocumentedNamePart
                # Use iter() to find them regardless of nesting depth or namespace
                name_parts = [
                    e for e in alias_elem.iter()
                    if (e.tag.split('}')[-1] if '}' in e.tag else e.tag) == "NamePartValue"
                ]
                parts_text = " ".join(
                    (p.text or "").strip() for p in name_parts if (p.text or "").strip()
                ).strip()

                if not parts_text:
                    continue

                # AliasTypeID 1403 = primary name, 1400 = aka/alias
                if alias_type_id == "1403" and is_primary:
                    primary_name = parts_text
                elif alias_type_id == "1400":
                    if parts_text not in aliases:
                        aliases.append(parts_text)
                else:
                    # Any other alias type — add to aliases if not primary
                    if not is_primary and parts_text not in aliases:
                        aliases.append(parts_text)

        # If no primary name found (edge case), use first alias
        if not primary_name:
            if aliases:
                primary_name = aliases.pop(0)
            else:
                return None

        # Remove primary name from aliases list if it crept in
        aliases = [a for a in aliases if a != primary_name]

        entity_id = f"ofac-{list_name}-{profile_id}"

        source_key = f"ofac_{list_name}"

        return {
            "id": entity_id,
            "name": primary_name,
            "entity_type": entity_type,
            "aliases": aliases,
            "datasets": [source_key],
            "countries": [],
            "properties": {
                **SOURCE_META,
                "ofac_uid": profile_id,
                "fixed_ref": fixed_ref,
                "party_subtype_id": subtype_id,
                "list": list_name,
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
