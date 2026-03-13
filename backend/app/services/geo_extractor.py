"""Geo extraction service: NER via spaCy + geocoding via Nominatim."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

log = logging.getLogger("orthanc.geo")

# Global geocode queue — single worker drains it at ≤1 req/sec
# Prevents hundreds of concurrent asyncio.sleep() calls from starving event loop
_geocode_queue: asyncio.Queue | None = None
_geocode_results: dict[str, asyncio.Future] = {}
_geocode_worker_task: asyncio.Task | None = None


def _ensure_geocode_worker():
    """Lazily start the geocode worker on first use."""
    global _geocode_queue, _geocode_worker_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _geocode_queue is None:
        _geocode_queue = asyncio.Queue(maxsize=200)
    if _geocode_worker_task is None or _geocode_worker_task.done():
        _geocode_worker_task = loop.create_task(_geocode_worker_loop())


async def _geocode_worker_loop():
    """Single async worker: drains queue at ≤1 request/second."""
    global _geocode_queue
    import httpx  # noqa: PLC0415
    last_req = 0.0
    while True:
        try:
            location_name, fut = await asyncio.wait_for(_geocode_queue.get(), timeout=60)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            break

        # Rate limit: 1.2s between requests
        now = time.monotonic()
        wait = 1.2 - (now - last_req)
        if wait > 0:
            await asyncio.sleep(wait)
        last_req = time.monotonic()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": location_name, "format": "json", "limit": 1},
                    headers={"User-Agent": "Orthanc-OSINT/1.0"},
                    timeout=10.0,
                )
                resp.raise_for_status()
                data = resp.json()
            if data:
                precision = _classify_precision_from_nominatim(data[0])
                result = (
                    float(data[0]["lat"]),
                    float(data[0]["lon"]),
                    data[0].get("display_name", location_name),
                    precision,
                )
                if not fut.done():
                    fut.set_result(result)
            else:
                if not fut.done():
                    fut.set_result(None)
        except Exception as exc:  # noqa: BLE001
            log.warning("Geocode failed for %r: %s", location_name, exc)
            if not fut.done():
                fut.set_result(None)
        finally:
            _geocode_queue.task_done()

# Well-known country names — geocoding to centroid is useless
COUNTRY_NAMES: frozenset[str] = frozenset({
    "Afghanistan", "Albania", "Algeria", "Angola", "Argentina", "Armenia",
    "Australia", "Austria", "Azerbaijan", "Bahrain", "Bangladesh", "Belarus",
    "Belgium", "Bolivia", "Bosnia", "Brazil", "Bulgaria", "Cambodia",
    "Cameroon", "Canada", "Chad", "Chile", "China", "Colombia", "Congo",
    "Croatia", "Cuba", "Cyprus", "Czechia", "Czech Republic", "Denmark",
    "Ecuador", "Egypt", "Ethiopia", "Finland", "France", "Georgia",
    "Germany", "Ghana", "Greece", "Guatemala", "Honduras", "Hungary",
    "India", "Indonesia", "Iran", "Iraq", "Ireland", "Israel", "Italy",
    "Japan", "Jordan", "Kazakhstan", "Kenya", "Kuwait", "Kyrgyzstan",
    "Lebanon", "Libya", "Lithuania", "Malaysia", "Mali", "Mexico",
    "Moldova", "Morocco", "Mozambique", "Myanmar", "Nepal", "Netherlands",
    "Nigeria", "North Korea", "Norway", "Oman", "Pakistan", "Palestine",
    "Panama", "Peru", "Philippines", "Poland", "Portugal", "Qatar",
    "Romania", "Russia", "Saudi Arabia", "Senegal", "Serbia", "Slovakia",
    "Somalia", "South Africa", "South Korea", "South Sudan", "Spain",
    "Sri Lanka", "Sudan", "Sweden", "Switzerland", "Syria", "Taiwan",
    "Tajikistan", "Tanzania", "Thailand", "Tunisia", "Turkey", "Turkmenistan",
    "Uganda", "Ukraine", "United Arab Emirates", "UAE", "United Kingdom",
    "United States", "United States of America", "USA", "US", "UK",
    "Uzbekistan", "Venezuela", "Vietnam", "Yemen", "Zimbabwe",
    # Abbreviations / common variations
    "North Korea", "South Korea", "DR Congo", "DRC",
})

# Nominatim addresstype/type → precision tier
_NOMINATIM_EXACT = frozenset({
    "house", "building", "amenity", "place_of_worship", "restaurant",
    "hotel", "hospital", "school", "shop", "office", "attraction",
    "tourism", "military", "aerodrome", "aeroway",
})
_NOMINATIM_CITY = frozenset({
    "city", "town", "village", "suburb", "neighbourhood", "quarter",
    "hamlet", "locality", "borough", "municipality",
})
_NOMINATIM_REGION = frozenset({
    "state", "province", "county", "region", "district", "department",
    "administrative", "state_district",
})
_NOMINATIM_COUNTRY = frozenset({"country"})
_NOMINATIM_CONTINENT = frozenset({"continent"})


def _classify_precision_from_nominatim(result: dict) -> str:
    """Classify precision tier from a Nominatim search result dict."""
    addresstype = result.get("addresstype", "")
    place_type = result.get("type", "")
    place_class = result.get("class", "")

    for field in (addresstype, place_type, place_class):
        if field in _NOMINATIM_EXACT:
            return "exact"
        if field in _NOMINATIM_CITY:
            return "city"
        if field in _NOMINATIM_REGION:
            return "region"
        if field in _NOMINATIM_COUNTRY:
            return "country"
        if field in _NOMINATIM_CONTINENT:
            return "continent"

    # Fallback: inspect display_name rank
    rank = result.get("place_rank", 0)
    if rank >= 25:
        return "city"
    if rank >= 10:
        return "region"
    if rank >= 4:
        return "country"
    return "unknown"


class GeoExtractor:
    """Extracts locations from text and geocodes them."""

    def __init__(self) -> None:
        self._nlp = None
        self._geocode_cache: dict[str, tuple[float, float, str, str] | None] = {}
        # Backward-compatible timestamp used by country centroid fallback path.
        self._last_geocode_time = 0.0

    def _load_model(self) -> None:
        """Lazy-load spaCy model on first use to avoid slowing startup."""
        if self._nlp is None:
            import spacy  # noqa: PLC0415
            log.info("Loading spaCy model en_core_web_sm …")
            self._nlp = spacy.load("en_core_web_sm")
            log.info("spaCy model loaded.")

    @staticmethod
    def _is_plausible_location(name: str) -> bool:
        """Filter out obvious non-locations (random words from non-English NER)."""
        import re
        # Must contain at least one Latin letter (skip pure Cyrillic/Arabic/CJK)
        if not re.search(r'[a-zA-Z]', name):
            return False
        # Skip very short tokens
        if len(name) < 3:
            return False
        # Skip common false-positive words spaCy tags as GPE
        _FALSE_POSITIVES = frozenset({
            "the", "The", "this", "that", "here", "there", "today", "yesterday",
            "tomorrow", "now", "just", "more", "most", "many", "some", "all",
            "first", "last", "next", "new", "old", "one", "two", "three",
        })
        if name in _FALSE_POSITIVES:
            return False
        return True

    def extract_locations(self, text: str) -> list[str]:
        """Extract GPE, LOC, FAC entities from text using spaCy NER."""
        self._load_model()
        doc = self._nlp(text)
        locations: list[str] = []
        for ent in doc.ents:
            if ent.label_ in ("GPE", "LOC", "FAC"):
                name = ent.text.strip()
                if len(name) > 1 and name not in locations and self._is_plausible_location(name):
                    locations.append(name)
        return locations

    async def geocode(self, location_name: str) -> tuple[float, float, str, str] | None:
        """Geocode a location name using Nominatim OSM via a global rate-limited queue.

        Returns (lat, lng, display_name, precision) or None.
        Uses a single worker to enforce ≤1 req/sec without blocking the event loop.
        """
        if location_name in COUNTRY_NAMES:
            return None

        if not self._is_plausible_location(location_name):
            return None

        if location_name in self._geocode_cache:
            return self._geocode_cache[location_name]

        if len(self._geocode_cache) > 5000:
            return None

        _ensure_geocode_worker()
        if _geocode_queue is None or _geocode_queue.full():
            # Queue full — skip rather than block
            return None

        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        await _geocode_queue.put((location_name, fut))

        try:
            result = await asyncio.wait_for(asyncio.shield(fut), timeout=30.0)
            self._geocode_cache[location_name] = result
            return result
        except asyncio.TimeoutError:
            self._geocode_cache[location_name] = None
            return None

    async def process_post(self, post_id: str, content: str) -> list[dict]:
        """Extract locations from content and geocode them.

        Returns a list of event dicts: [{lat, lng, place_name, confidence, precision, post_id}].
        Max 3 events per post.
        """
        if not content:
            return []

        locations = self.extract_locations(content)
        if not locations:
            return []

        events: list[dict] = []
        for loc_name in locations[:3]:
            # Check if it's just a country name
            if loc_name in COUNTRY_NAMES:
                # Still geocode to get centroid, but mark as country-level
                import asyncio, httpx, time as _time  # noqa: PLC0415
                # Quick geocode without the skip
                now = _time.monotonic()
                elapsed = now - self._last_geocode_time
                if elapsed < 1.1:
                    await asyncio.sleep(1.1 - elapsed)
                self._last_geocode_time = _time.monotonic()
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(
                            "https://nominatim.openstreetmap.org/search",
                            params={"q": loc_name, "format": "json", "limit": 1},
                            headers={"User-Agent": "Orthanc-OSINT/1.0"},
                            timeout=10.0,
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        if data:
                            events.append({
                                "lat": float(data[0]["lat"]),
                                "lng": float(data[0]["lon"]),
                                "place_name": data[0].get("display_name", loc_name),
                                "confidence": 0.4,
                                "precision": "country",
                                "post_id": post_id,
                            })
                except Exception as exc:
                    log.warning("Country geocode failed for %r: %s", loc_name, exc)
                continue

            result = await self.geocode(loc_name)
            if result:
                lat, lng, display_name, precision = result
                events.append(
                    {
                        "lat": lat,
                        "lng": lng,
                        "place_name": display_name,
                        "confidence": 0.7,
                        "precision": precision,
                        "post_id": post_id,
                    }
                )
        return events


# Module-level singleton
geo_extractor = GeoExtractor()
