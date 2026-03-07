"""UK OFSI sanctions list ingestion — parses UK consolidated sanctions CSV."""
import asyncio
import csv
import io
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("orthanc.sanctions.uk")

UK_SANCTIONS_URL = (
    "https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.csv"
)


class UKSanctionsService:
    """Download and parse UK OFSI consolidated sanctions list."""

    def __init__(self):
        self._entities: list[dict] = []
        self._last_updated: Optional[datetime] = None
        self._loading = False

    async def download_and_parse(self) -> int:
        """Download UK sanctions CSV and parse into entity records.

        Returns count of entities parsed.
        """
        if self._loading:
            return len(self._entities)

        self._loading = True
        try:
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                resp = await client.get(UK_SANCTIONS_URL)
                resp.raise_for_status()
                csv_text = resp.text

            loop = asyncio.get_event_loop()
            entities = await loop.run_in_executor(None, self._parse_csv, csv_text)

            self._entities = entities
            self._last_updated = datetime.now(timezone.utc)
            logger.info("UK OFSI sanctions list loaded: %d entities", len(entities))
            return len(entities)
        except Exception as e:
            logger.error("Failed to download UK sanctions: %s", e)
            return 0
        finally:
            self._loading = False

    def _parse_csv(self, csv_text: str) -> list[dict]:
        """Parse the UK OFSI CSV format.

        The UK OFSI CSV has one row per name/alias record, grouped by Group ID.
        We collect all rows for each Group ID and produce one entity per group.
        """
        # Group rows by Group ID so aliases are merged correctly
        groups: dict[str, dict] = {}

        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            group_id = row.get("Group ID", "").strip()
            if not group_id:
                continue

            if group_id not in groups:
                # First row for this group — establish the entity
                group_type = row.get("Group Type", "").lower()
                entity_type = "person" if "individual" in group_type else "organization"

                # "Name 6" is the full/combined name; fall back to constructing from parts
                name = row.get("Name 6", "").strip()
                if not name:
                    parts = [row.get(f"Name {i}", "").strip() for i in range(1, 6)]
                    name = " ".join(p for p in parts if p)

                if not name:
                    continue

                groups[group_id] = {
                    "name": name,
                    "type": entity_type,
                    "source": "uk_ofsi",
                    "country": row.get("Country", "").strip(),
                    "regime": row.get("Regime", "").strip(),
                    "listed_date": row.get("Listed On", "").strip(),
                    "aliases": [],
                    "details": {
                        "group_id": group_id,
                        "un_reference": row.get("UN Reference", "").strip(),
                    },
                }
            else:
                # Additional row for existing group — treat as alias
                alias = row.get("Name 6", "").strip()
                if not alias:
                    parts = [row.get(f"Name {i}", "").strip() for i in range(1, 6)]
                    alias = " ".join(p for p in parts if p)
                if alias and alias != groups[group_id]["name"] and alias not in groups[group_id]["aliases"]:
                    groups[group_id]["aliases"].append(alias)

            # Collect explicit Alias columns from the current row
            entity = groups.get(group_id)
            if entity:
                for col, val in row.items():
                    if col.startswith("Alias") and val.strip():
                        alias_val = val.strip()
                        if alias_val != entity["name"] and alias_val not in entity["aliases"]:
                            entity["aliases"].append(alias_val)

        return list(groups.values())

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


uk_sanctions_service = UKSanctionsService()
