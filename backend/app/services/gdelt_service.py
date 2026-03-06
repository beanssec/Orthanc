"""GDELT DOC API service — on-demand global media intelligence."""
import asyncio
import logging
import time
from typing import Optional
import httpx

logger = logging.getLogger("orthanc.services.gdelt")

# Rate limit: 1 request per 5 seconds
_last_request_time = 0.0
_rate_lock = asyncio.Lock()
_cache: dict[str, tuple[float, dict]] = {}  # key -> (expires_at, data)
CACHE_TTL = 900  # 15 minutes


class GDELTService:
    """Query GDELT DOC API for global media articles."""

    BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

    async def search_articles(
        self,
        query: str,
        max_records: int = 75,
        mode: str = "artlist",
        timespan: str = "7d",
    ) -> dict:
        """
        Search GDELT for articles matching a query.

        Args:
            query: Search terms (entity name, keyword, etc.)
            max_records: Max results (default 75, max 250)
            mode: "artlist" for article list, "timelinevol" for volume timeline
            timespan: Time window — "7d", "3d", "24h", etc.

        Returns:
            Dict with articles list or timeline data.
        """
        cache_key = f"doc:{query}:{mode}:{timespan}:{max_records}"
        cached = _cache.get(cache_key)
        if cached and cached[0] > time.time():
            return cached[1]

        await self._rate_limit()

        params = {
            "query": query,
            "mode": mode,
            "maxrecords": min(max_records, 250),
            "format": "json",
            "timespan": timespan,
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(self.BASE_URL, params=params)
                if resp.status_code == 429:
                    logger.warning("GDELT rate limited, waiting 10s")
                    await asyncio.sleep(10)
                    resp = await client.get(self.BASE_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.error("GDELT DOC API error: %s", exc)
            return {"articles": []}

        # Normalize response
        result = {"articles": []}
        articles = data.get("articles", [])
        for art in articles:
            result["articles"].append({
                "title": art.get("title", ""),
                "url": art.get("url", ""),
                "source": art.get("domain", art.get("source", "")),
                "language": art.get("language", ""),
                "seendate": art.get("seendate", ""),
                "tone": art.get("tone", 0),
                "image": art.get("socialimage", ""),
            })

        _cache[cache_key] = (time.time() + CACHE_TTL, result)
        return result

    async def _rate_limit(self):
        """Enforce 1 request per 5 seconds."""
        global _last_request_time
        async with _rate_lock:
            now = time.time()
            wait = max(0, 5.0 - (now - _last_request_time))
            if wait > 0:
                await asyncio.sleep(wait)
            _last_request_time = time.time()


gdelt_service = GDELTService()
