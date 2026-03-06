"""ICIJ Offshore Leaks Database — Panama/Pandora/Paradise Papers."""
import asyncio
import logging
import time
from typing import Optional
import httpx

logger = logging.getLogger("orthanc.services.icij")

_cache: dict[str, tuple[float, list]] = {}
CACHE_TTL = 86400  # 24 hours
_rate_lock = asyncio.Lock()
_last_request = 0.0


class ICIJService:
    """Query ICIJ Offshore Leaks Database."""

    BASE_URL = "https://offshoreleaks.icij.org/api/v1"

    async def search(self, name: str, limit: int = 20) -> list[dict]:
        """Search for entities in offshore leaks data.

        Returns list of matches with: name, jurisdiction, linked_to, source_dataset, node_id
        """
        cache_key = f"icij:{name.lower().strip()}"
        cached = _cache.get(cache_key)
        if cached and cached[0] > time.time():
            logger.debug("ICIJ cache hit for %r", name)
            return cached[1]

        await self._rate_limit()

        data = None
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/search",
                    params={"q": name, "limit": limit},
                    headers={"Accept": "application/json"},
                )
                logger.info("ICIJ API response status: %d for query %r", resp.status_code, name)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "ICIJ API error %s: %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
            return []
        except Exception as exc:
            logger.error("ICIJ API request failed: %s", exc)
            return []

        # Normalize response — ICIJ API returns different formats
        results = []
        # The response might be a list or have a "data" / "results" key
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("data", data.get("results", data.get("nodes", [])))
            if not isinstance(items, list):
                # Maybe the top-level dict IS a single result — unlikely, but handle
                items = []
        else:
            items = []

        logger.info("ICIJ search for %r returned %d raw items", name, len(items))

        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            node_id = item.get("node_id", item.get("id", ""))
            url = (
                f"https://offshoreleaks.icij.org/nodes/{node_id}"
                if node_id
                else ""
            )
            source = item.get("sourceID", item.get("source", ""))
            results.append(
                {
                    "name": item.get("name", item.get("entity", item.get("label", ""))),
                    "type": item.get("type", item.get("node_type", item.get("labels", ["Entity"]))),
                    "jurisdiction": item.get(
                        "jurisdiction",
                        item.get("jurisdiction_description", item.get("countries", "")),
                    ),
                    "source": source,
                    "linked_count": item.get(
                        "linked_count", item.get("edge_count", item.get("number_relationships", 0))
                    ),
                    "address": item.get(
                        "address",
                        item.get("registered_address", item.get("service_provider", "")),
                    ),
                    "incorporation_date": item.get(
                        "incorporation_date",
                        item.get("date_incorporated", ""),
                    ),
                    "inactivation_date": item.get(
                        "inactivation_date",
                        item.get("date_struck_off", ""),
                    ),
                    "status": item.get("status", item.get("company_type", "")),
                    "url": url,
                    "dataset": self._dataset_label(source),
                }
            )

        _cache[cache_key] = (time.time() + CACHE_TTL, results)
        return results

    def _dataset_label(self, source_id: str) -> str:
        """Convert ICIJ source ID to human-readable dataset name."""
        labels = {
            "panama-papers": "Panama Papers",
            "paradise-papers": "Paradise Papers",
            "pandora-papers": "Pandora Papers",
            "bahamas-leaks": "Bahamas Leaks",
            "offshore-leaks": "Offshore Leaks",
        }
        return labels.get(str(source_id).lower(), str(source_id))

    async def _rate_limit(self):
        global _last_request
        async with _rate_lock:
            wait = max(0, 2.0 - (time.time() - _last_request))
            if wait > 0:
                await asyncio.sleep(wait)
            _last_request = time.time()


icij_service = ICIJService()
