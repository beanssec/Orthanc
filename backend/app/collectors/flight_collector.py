"""OpenSky Network flight tracker — filters for intelligence-relevant aircraft."""
from __future__ import annotations

import asyncio
import logging
import math
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.event import Event
from app.models.post import Post
from app.models.source import Source
from app.routers.feed import broadcast_post

logger = logging.getLogger("orthanc.collectors.flight")

OPENSKY_URL = "https://opensky-network.org/api/states/all"
POLL_INTERVAL = 300  # 5 minutes (OpenSky anonymous rate limit: 10 req/min, 400/day)
VIP_POLL_INTERVAL = 3600  # 1 hour — one request per hour for all VIP aircraft

# VIP aircraft watchlist — ICAO24 hex codes for government/diplomatic aircraft
# Used to detect unusual diplomatic flight activity that may indicate negotiations
VIP_WATCHLIST = {
    # Qatar Amiri Flight
    "06a106": "Qatar Amiri Flight (A7-AAH)",
    "06a1a4": "Qatar Amiri Flight (A7-HHE)",
    "06a1a6": "Qatar Amiri Flight (A7-HHJ)",
    "06a1b2": "Qatar Amiri Flight (A7-HHK)",
    "06a1b3": "Qatar Amiri Flight (A7-HHM)",
    # Oman Royal Flight
    "704800": "Oman Royal Flight (A4O-HMS)",
    "704801": "Oman Royal Flight (A4O-OMN)",
    # Swiss Air Force VIP
    "4b1800": "Swiss Air Force (T-785)",
    "4b1801": "Swiss Air Force (T-786)",
    # UAE Government
    "896400": "UAE Government (A6-PFA)",
    "896401": "UAE Government (A6-PFB)",
    # Notable US Government (not Air Force One but diplomatic transport)
    "ae01c7": "USAF VIP Transport (C-32A)",
    "ae01c8": "USAF VIP Transport (C-32A)",
}
_RATE_LIMIT_BACKOFF_BASE = 60.0   # seconds — initial backoff on 429
_RATE_LIMIT_BACKOFF_MAX = 900.0   # seconds — cap at 15 minutes

# Conflict zone bounding boxes for flight monitoring
MONITOR_ZONES: dict[str, dict[str, float]] = {
    "ukraine": {"lamin": 44.0, "lamax": 52.5, "lomin": 22.0, "lomax": 40.5},
    "middle_east": {"lamin": 12.0, "lamax": 42.0, "lomin": 25.0, "lomax": 63.0},
    "black_sea": {"lamin": 40.9, "lamax": 46.6, "lomin": 27.5, "lomax": 41.0},
}

# Military/intelligence callsign patterns (regex)
MILITARY_CALLSIGN_PATTERNS = [
    r"^RCH\d+",       # USAF Air Mobility Command
    r"^FORTE\d*",     # USAF reconnaissance
    r"^JAKE\d+",      # USAF
    r"^NATO\d*",      # NATO aircraft
    r"^LAGR\d+",      # US Army
    r"^REACH\d+",     # USAF
    r"^SPAR\d+",      # USAF Special Air Mission (VIP)
    r"^CEFOT\d*",     # CENTAF
    r"^UAM\d+",
    r"^UAVGH\d*",     # Drone
    r"^DRAGON\d+",
    r"^PANTHER\d+",
    r"^WOLF\d+",
    r"^EAGLE\d+",
    r"^HOMER\d+",
    r"^TOPCAT\d*",
    r"^CNV\d+",       # US Navy
    r"^NAVY\d+",
    r"^USMC\d+",
    r"^ARMY\d+",
    r"^DUKE\d+",
    r"^KING\d+",
    r"^BARON\d+",
    r"^HERKY\d+",     # C-130 Hercules
    r"^ATLAS\d+",
    r"^ION\d+",
    r"^IRON\d+",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in MILITARY_CALLSIGN_PATTERNS]


def _safe_float(val) -> float | None:
    """Return val as float, or None if it is None, NaN, or infinite."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _is_military_callsign(callsign: str | None) -> bool:
    if not callsign:
        return False
    cs = callsign.strip()
    return any(p.match(cs) for p in _COMPILED_PATTERNS)


def _is_interesting(state: list) -> bool:
    """
    OpenSky state vector format (index):
    0: icao24, 1: callsign, 2: origin_country, 3: time_position, 4: last_contact,
    5: longitude, 6: latitude, 7: baro_altitude, 8: on_ground, 9: velocity,
    10: true_track (heading), 11: vertical_rate, 12: sensors, 13: geo_altitude,
    14: squawk, 15: spi, 16: position_source
    """
    callsign = state[1]
    altitude = state[7]  # baro_altitude in meters
    squawk = state[14]
    on_ground = state[8]

    if on_ground:
        return False

    # Military callsign
    if _is_military_callsign(callsign):
        return True

    # Emergency squawk codes
    if squawk in ("7500", "7600", "7700"):
        return True

    # Very high altitude (ISR, potential reconnaissance)
    if altitude and altitude > 15000:
        return True

    # No transponder data (altitude None but airborne)
    if altitude is None and not on_ground:
        return True

    return False


class FlightCollector:
    """Polls OpenSky Network for flights over conflict zones and caches current positions."""

    def __init__(self, poll_interval: int = POLL_INTERVAL):
        self._poll_interval = poll_interval
        self._task: asyncio.Task | None = None
        # In-memory cache of current flights: icao24 -> state dict
        self._current_flights: dict[str, dict] = {}
        # Exponential backoff state for 429 responses
        self._rate_limit_failures: int = 0

    async def start(self) -> None:
        if self._task and not self._task.done():
            logger.info("Flight collector already running")
            return
        logger.info("Starting flight collector (interval=%ds)", self._poll_interval)
        self._task = asyncio.create_task(self._poll_loop(), name="flight_poll")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Flight collector stopped")

    def get_current_flights(self) -> list[dict]:
        """Return cached current flight positions (used by API layer)."""
        return list(self._current_flights.values())

    async def _poll_loop(self) -> None:
        vip_last_check: float = 0.0
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                logger.info("Flight poll loop cancelled")
                raise
            except Exception as exc:
                logger.exception("Flight poll error: %s", exc)

            # VIP watchlist check (hourly — one request covers all aircraft)
            now = time.time()
            if now - vip_last_check >= VIP_POLL_INTERVAL:
                try:
                    await self._poll_vip_watchlist()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("VIP watchlist poll error: %s", exc)
                vip_last_check = time.time()

            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                raise

    async def _poll_vip_watchlist(self) -> None:
        """Query OpenSky for all VIP/government aircraft in a single request and persist sightings."""
        logger.info("Polling VIP watchlist (%d aircraft)", len(VIP_WATCHLIST))
        params = [("icao24", code) for code in VIP_WATCHLIST]

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(OPENSKY_URL, params=params)
                if resp.status_code == 429:
                    logger.warning("OpenSky rate limited on VIP poll — skipping")
                    return
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("OpenSky VIP request failed: %s", exc)
            return

        states = data.get("states") or []
        if not states:
            logger.debug("VIP poll: no aircraft currently airborne")
            return

        now_dt = datetime.now(timezone.utc)
        dedup_cutoff = now_dt - timedelta(hours=4)

        for state in states:
            if len(state) < 17:
                continue

            icao24 = (state[0] or "").lower()
            on_ground = state[8]

            if on_ground:
                continue  # Only care about airborne VIP aircraft

            aircraft_name = VIP_WATCHLIST.get(icao24)
            if not aircraft_name:
                continue  # Shouldn't happen but be safe

            lat = state[6]
            lng = state[5]
            heading = _safe_float(state[10])
            altitude = _safe_float(state[7])

            if lat is None or lng is None:
                continue

            timestamp_epoch = int(now_dt.timestamp())
            source_id = f"vip_{icao24}_{timestamp_epoch}"

            content = (
                f"🛩 VIP FLIGHT DETECTED: {aircraft_name} airborne. "
                f"Position: {lat:.4f}, {lng:.4f}. "
                f"Heading: {int(heading or 0)}°. "
                f"Origin/destination unknown — monitor for diplomatic activity."
            )

            try:
                async with AsyncSessionLocal() as session:
                    # Dedup: check for any VIP post for this aircraft in the last 4 hours
                    existing = await session.execute(
                        select(Post).where(
                            Post.source_type == "flight",
                            Post.source_id.like(f"vip_{icao24}_%"),
                            Post.timestamp >= dedup_cutoff,
                        )
                    )
                    if existing.scalars().first():
                        logger.debug("VIP dedup: %s already reported within 4h", icao24)
                        continue

                    post = Post(
                        source_type="flight",
                        source_id=source_id,
                        author="VIP Flight Tracker",
                        content=content,
                        raw_json={
                            "icao24": icao24,
                            "aircraft_name": aircraft_name,
                            "lat": lat,
                            "lng": lng,
                            "heading": heading,
                            "altitude": altitude,
                            "on_ground": on_ground,
                            "vip": True,
                            "updated_at": now_dt.isoformat(),
                        },
                        timestamp=now_dt,
                    )
                    session.add(post)
                    await session.flush()

                    event = Event(
                        post_id=post.id,
                        lat=lat,
                        lng=lng,
                        place_name=f"VIP flight: {aircraft_name}",
                        confidence=0.90,
                    )
                    session.add(event)

                    post_dict = {
                        "id": str(post.id),
                        "source_type": post.source_type,
                        "source_id": post.source_id,
                        "author": post.author,
                        "content": post.content,
                        "timestamp": post.timestamp.isoformat() if post.timestamp else None,
                        "ingested_at": post.ingested_at.isoformat() if post.ingested_at else None,
                        "event": None,
                    }
                    await broadcast_post(post_dict)
                    await session.commit()
                    logger.info("VIP sighting recorded: %s (%s)", aircraft_name, icao24)

            except Exception as db_exc:
                logger.warning("DB error storing VIP sighting %s: %s", icao24, db_exc)

    async def _poll_once(self) -> None:
        logger.info("Polling OpenSky Network for flights")
        all_interesting: dict[str, dict] = {}

        for zone_name, bbox in MONITOR_ZONES.items():
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(
                        OPENSKY_URL,
                        params={
                            "lamin": bbox["lamin"],
                            "lamax": bbox["lamax"],
                            "lomin": bbox["lomin"],
                            "lomax": bbox["lomax"],
                        },
                    )
                    if resp.status_code == 429:
                        self._rate_limit_failures += 1
                        backoff = min(
                            _RATE_LIMIT_BACKOFF_BASE * (2 ** (self._rate_limit_failures - 1)),
                            _RATE_LIMIT_BACKOFF_MAX,
                        )
                        logger.warning(
                            "OpenSky rate limited (attempt #%d) — exponential backoff %.0fs",
                            self._rate_limit_failures, backoff,
                        )
                        await asyncio.sleep(backoff)
                        return
                    resp.raise_for_status()
                    data = resp.json()
                    self._rate_limit_failures = 0  # reset on success
            except httpx.HTTPError as exc:
                logger.warning("OpenSky request failed for zone %s: %s", zone_name, exc)
                continue

            states = data.get("states") or []
            zone_count = 0

            for state in states:
                if len(state) < 17:
                    continue

                icao24 = state[0] or ""
                callsign = (state[1] or "").strip()
                origin_country = state[2] or "Unknown"
                lng = state[5]
                lat = state[6]
                altitude = _safe_float(state[7])   # NaN-safe baro_altitude
                on_ground = state[8]
                velocity = _safe_float(state[9])   # NaN-safe velocity
                heading = _safe_float(state[10])   # NaN-safe true_track
                squawk = state[14]

                if lat is None or lng is None:
                    continue

                is_interesting = _is_interesting(state)

                flight_data = {
                    "icao24": icao24,
                    "callsign": callsign or "Unknown",
                    "origin_country": origin_country,
                    "lat": lat,
                    "lng": lng,
                    "altitude": altitude,
                    "velocity": velocity,
                    "heading": heading,
                    "on_ground": on_ground,
                    "squawk": squawk,
                    "zone": zone_name,
                    "is_military": _is_military_callsign(callsign),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }

                # Always cache in-memory for the map layer
                all_interesting[icao24] = flight_data

                # Only persist interesting flights to DB
                if not is_interesting:
                    continue

                zone_count += 1

                if altitude is not None and velocity is not None:
                    content = (
                        f"[Flight] {callsign or 'Unknown'} ({icao24}) — "
                        f"Alt: {int(altitude)}m, Speed: {int(velocity)}m/s, "
                        f"Heading: {int(heading or 0)}°, Origin: {origin_country}, "
                        f"Zone: {zone_name}"
                    )
                else:
                    content = (
                        f"[Flight] {callsign or 'Unknown'} ({icao24}) — "
                        f"Origin: {origin_country}, Zone: {zone_name}"
                    )

                try:
                    async with AsyncSessionLocal() as session:
                        existing = await session.execute(
                            select(Post).where(
                                Post.source_type == "flight",
                                Post.source_id == icao24,
                            )
                        )
                        existing_post = existing.scalars().first()

                        if existing_post:
                            # Update existing flight record
                            existing_post.content = content
                            existing_post.raw_json = flight_data
                            existing_post.timestamp = datetime.now(timezone.utc)
                            await session.commit()
                        else:
                            # New interesting flight
                            post = Post(
                                source_type="flight",
                                source_id=icao24,
                                author=callsign or "Unknown",
                                content=content,
                                raw_json=flight_data,
                                timestamp=datetime.now(timezone.utc),
                            )
                            session.add(post)
                            await session.flush()

                            # Auto-create event
                            event = Event(
                                post_id=post.id,
                                lat=lat,
                                lng=lng,
                                place_name=f"Flight {callsign or icao24} over {zone_name}",
                                confidence=0.85,
                            )
                            session.add(event)

                            post_dict = {
                                "id": str(post.id),
                                "source_type": post.source_type,
                                "source_id": post.source_id,
                                "author": post.author,
                                "content": post.content,
                                "timestamp": post.timestamp.isoformat() if post.timestamp else None,
                                "ingested_at": post.ingested_at.isoformat() if post.ingested_at else None,
                                "event": None,
                            }
                            await broadcast_post(post_dict)
                            await session.commit()

                except Exception as db_exc:
                    logger.warning("DB error storing flight %s: %s", icao24, db_exc)

            logger.debug("Zone %s: %d interesting flights", zone_name, zone_count)
            await asyncio.sleep(2)  # brief pause between zone queries

        self._current_flights = all_interesting
        logger.info(
            "Flight poll complete: %d aircraft in monitoring zones", len(all_interesting)
        )

        # Update last_polled for any configured flight sources
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(Source).where(Source.type == "flight"))
                for src in result.scalars().all():
                    src.last_polled = datetime.now(timezone.utc)
                await session.commit()
        except Exception as exc:
            logger.warning("Failed to update flight source last_polled: %s", exc)


# Module-level singleton accessed by the layers router
flight_collector = FlightCollector()
