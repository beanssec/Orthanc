"""OCCRP Aleph — organized crime & corruption research."""
import asyncio
import logging
import time
from typing import Optional
import httpx

logger = logging.getLogger("orthanc.services.occrp")

_cache: dict[str, tuple[float, list]] = {}
CACHE_TTL = 86400  # 24 hours
_rate_lock = asyncio.Lock()
_last_request = 0.0


class OCCRPService:
    """Query OCCRP Aleph for entity records."""

    BASE_URL = "https://aleph.occrp.org/api/2"

    async def search(
        self, name: str, api_key: str | None = None, limit: int = 20
    ) -> list[dict]:
        """Search Aleph for entity records."""
        cache_key = f"occrp:{name.lower().strip()}"
        cached = _cache.get(cache_key)
        if cached and cached[0] > time.time():
            logger.debug("OCCRP cache hit for %r", name)
            return cached[1]

        await self._rate_limit()

        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"ApiKey {api_key}"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/search",
                    params={"q": name, "limit": limit},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "OCCRP API error %s: %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
            return []
        except Exception as exc:
            logger.error("OCCRP API request failed: %s", exc)
            return []

        results = []
        for item in data.get("results", [])[:limit]:
            if not isinstance(item, dict):
                continue
            props = item.get("properties", {}) if isinstance(item.get("properties"), dict) else {}
            # name can be a string or a list
            raw_name = item.get("name", "")
            if not raw_name:
                name_prop = props.get("name", "")
                if isinstance(name_prop, list):
                    raw_name = name_prop[0] if name_prop else ""
                else:
                    raw_name = str(name_prop)

            results.append(
                {
                    "name": raw_name,
                    "schema": item.get("schema", ""),
                    "dataset": item.get("collection", {}).get("label", "")
                    if isinstance(item.get("collection"), dict)
                    else "",
                    "dataset_category": item.get("collection", {}).get("category", "")
                    if isinstance(item.get("collection"), dict)
                    else "",
                    "countries": props.get("country", [])
                    if isinstance(props.get("country"), list)
                    else [],
                    "summary": item.get("highlight", ""),
                    "url": item.get("links", {}).get("self", "")
                    if isinstance(item.get("links"), dict)
                    else "",
                    "aleph_url": f"https://aleph.occrp.org/entities/{item.get('id', '')}",
                    "score": item.get("score", 0),
                    "updated_at": item.get("updated_at", ""),
                }
            )

        _cache[cache_key] = (time.time() + CACHE_TTL, results)
        return results

    async def _rate_limit(self):
        global _last_request
        async with _rate_lock:
            wait = max(0, 2.0 - (time.time() - _last_request))
            if wait > 0:
                await asyncio.sleep(wait)
            _last_request = time.time()


occrp_service = OCCRPService()
