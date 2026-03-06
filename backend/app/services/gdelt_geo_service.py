"""GDELT GEO API — media attention heatmap data."""
import asyncio
import logging
import time
from typing import Optional
import httpx

logger = logging.getLogger("orthanc.services.gdelt_geo")

_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 900  # 15 minutes
_last_request_time = 0.0
_rate_lock = asyncio.Lock()


class GDELTGeoService:
    """Query GDELT GEO API for geographic media attention data."""

    BASE_URL = "https://api.gdeltproject.org/api/v2/geo/geo"

    async def get_heatmap(
        self,
        query: str,
        timespan: str = "7d",
    ) -> dict:
        """
        Get GeoJSON heatmap of media attention for a keyword.

        Args:
            query: Search keyword or phrase
            timespan: "7d", "3d", "24h"

        Returns:
            GeoJSON FeatureCollection with point features for media attention hotspots.
        """
        cache_key = f"geo:{query}:{timespan}"
        cached = _cache.get(cache_key)
        if cached and cached[0] > time.time():
            return cached[1]

        await self._rate_limit()

        params = {
            "query": query,
            "format": "GeoJSON",
            "timespan": timespan,
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(self.BASE_URL, params=params)
                if resp.status_code == 429:
                    logger.warning("GDELT GEO rate limited, waiting 10s")
                    await asyncio.sleep(10)
                    resp = await client.get(self.BASE_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.error("GDELT GEO API error: %s", exc)
            return {"type": "FeatureCollection", "features": []}

        # GDELT GEO returns a FeatureCollection
        if data.get("type") != "FeatureCollection":
            return {"type": "FeatureCollection", "features": []}

        _cache[cache_key] = (time.time() + CACHE_TTL, data)
        return data

    async def _rate_limit(self):
        """Enforce 1 request per 5 seconds."""
        global _last_request_time
        async with _rate_lock:
            now = time.time()
            wait = max(0, 5.0 - (now - _last_request_time))
            if wait > 0:
                await asyncio.sleep(wait)
            _last_request_time = time.time()


gdelt_geo_service = GDELTGeoService()
