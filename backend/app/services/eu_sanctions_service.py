"""EU sanctions list ingestion — parses EU Consolidated Financial Sanctions List."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("orthanc.sanctions.eu")

EU_SANCTIONS_URL = (
    "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content"
)


class EUSanctionsService:
    """Download and parse EU consolidated sanctions list."""

    def __init__(self):
        self._entities: list[dict] = []
        self._last_updated: Optional[datetime] = None
        self._loading = False

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
            logger.info("EU sanctions list loaded: %d entities", len(entities))
            return len(entities)
        except Exception as e:
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
            for elem in root.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag == "nameAlias":
                    name = elem.get("wholeName", "").strip()
                    if name and name not in seen:
                        seen.add(name)
                        entities.append(
                            {
                                "name": name,
                                "type": "unknown",
                                "source": "eu_sanctions",
                                "aliases": [],
                                "nationalities": [],
                                "details": {},
                            }
                        )

        return entities

    def _parse_entity(self, elem) -> dict | None:
        """Parse a single sanctioned entity element."""
        entity: dict = {
            "type": "unknown",
            "source": "eu_sanctions",
            "aliases": [],
            "nationalities": [],
            "details": {},
        }

        # Determine subject type (person / organisation)
        sub_type = elem.get("subjectType", "").lower()
        if "person" in sub_type:
            entity["type"] = "person"
        elif "enterprise" in sub_type or "entity" in sub_type or "organisation" in sub_type:
            entity["type"] = "organization"

        # Walk child elements for names, aliases, citizenships
        for child in elem.iter():
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

            if tag == "nameAlias":
                whole_name = child.get("wholeName", "").strip()
                if whole_name:
                    if "name" not in entity:
                        entity["name"] = whole_name
                    else:
                        entity["aliases"].append(whole_name)

            elif tag == "citizenship":
                country = child.get("countryDescription", "").strip()
                if country:
                    entity["nationalities"].append(country)

        if "name" not in entity:
            return None

        return entity

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


eu_sanctions_service = EUSanctionsService()
