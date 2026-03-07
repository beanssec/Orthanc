"""Maritime intelligence service — dark ship detection, STS transfers, port monitoring."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from math import atan2, cos, radians, sin, sqrt
from typing import Optional

from sqlalchemy import select, text

from app.db import AsyncSessionLocal

logger = logging.getLogger("orthanc.services.maritime_intel")


# ---------------------------------------------------------------------------
# Spatial helpers
# ---------------------------------------------------------------------------

def haversine_nm(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine distance in nautical miles."""
    R_NM = 3440.065  # Earth radius in nautical miles
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return R_NM * 2 * atan2(sqrt(a), sqrt(1 - a))


# ---------------------------------------------------------------------------
# Monitored geographic bboxes for dark-ship detection
# ---------------------------------------------------------------------------

MONITORED_BBOXES = [
    # Black Sea
    {"name": "Black Sea", "lat_min": 40.9, "lat_max": 46.6, "lng_min": 27.5, "lng_max": 41.0},
    # Strait of Hormuz / Persian Gulf
    {"name": "Strait of Hormuz", "lat_min": 22.0, "lat_max": 27.0, "lng_min": 56.0, "lng_max": 60.0},
    # Red Sea
    {"name": "Red Sea", "lat_min": 12.0, "lat_max": 30.0, "lng_min": 32.0, "lng_max": 45.0},
    # Eastern Mediterranean
    {"name": "Eastern Mediterranean", "lat_min": 30.0, "lat_max": 42.0, "lng_min": 25.0, "lng_max": 37.0},
]


def _in_monitored_area(lat: float, lng: float) -> Optional[str]:
    """Return the name of the monitored bbox if the point is inside one, else None."""
    for bbox in MONITORED_BBOXES:
        if (
            bbox["lat_min"] <= lat <= bbox["lat_max"]
            and bbox["lng_min"] <= lng <= bbox["lng_max"]
        ):
            return bbox["name"]
    return None


class MaritimeIntelService:
    """Analyze AIS data for maritime intelligence indicators."""

    # Key ports to monitor
    MONITORED_PORTS = [
        {"name": "Sevastopol", "lat": 44.62, "lng": 33.52, "radius_nm": 5},
        {"name": "Tartus", "lat": 34.89, "lng": 35.87, "radius_nm": 3},
        {"name": "Bandar Abbas", "lat": 27.18, "lng": 56.28, "radius_nm": 5},
        {"name": "Hodeidah", "lat": 14.80, "lng": 42.95, "radius_nm": 3},
        {"name": "Vladivostok", "lat": 43.11, "lng": 131.90, "radius_nm": 5},
        {"name": "Kaliningrad", "lat": 54.71, "lng": 20.50, "radius_nm": 5},
        {"name": "Suez Canal N", "lat": 31.27, "lng": 32.31, "radius_nm": 5},
        {"name": "Suez Canal S", "lat": 29.95, "lng": 32.56, "radius_nm": 5},
        {"name": "Bab el-Mandeb", "lat": 12.60, "lng": 43.30, "radius_nm": 5},
        {"name": "Strait of Hormuz", "lat": 26.60, "lng": 56.25, "radius_nm": 10},
    ]

    # Tracks seen per port across polls: port_name -> set of MMSIs
    _prev_port_vessels: dict[str, set[str]] = {}

    # In-progress STS candidates: frozenset({mmsi1, mmsi2}) -> first_seen timestamp
    _sts_candidates: dict[frozenset, datetime] = {}

    def _is_near_port(self, lat: float, lng: float) -> Optional[str]:
        """Return port name if position is within any monitored port radius."""
        for port in self.MONITORED_PORTS:
            d = haversine_nm(lat, lng, port["lat"], port["lng"])
            if d <= port["radius_nm"]:
                return port["name"]
        return None

    # ---------------------------------------------------------------------------
    # Track storage
    # ---------------------------------------------------------------------------

    async def store_track_point(
        self,
        mmsi: str,
        vessel_name: Optional[str],
        lat: float,
        lng: float,
        speed: Optional[float],
        heading: Optional[float],
        course: Optional[float],
        destination: Optional[str],
        vessel_type: Optional[str],
        flag: Optional[str],
        timestamp: datetime,
    ) -> None:
        """Store a vessel position in the track history."""
        from app.models.vessel import VesselTrack

        try:
            async with AsyncSessionLocal() as session:
                track = VesselTrack(
                    mmsi=mmsi,
                    vessel_name=vessel_name,
                    lat=lat,
                    lng=lng,
                    speed=speed,
                    heading=heading,
                    course=course,
                    destination=destination,
                    vessel_type=vessel_type,
                    flag=flag,
                    timestamp=timestamp,
                )
                session.add(track)
                await session.commit()
        except Exception as exc:
            logger.warning("Failed to store track point for MMSI %s: %s", mmsi, exc)

    # ---------------------------------------------------------------------------
    # Dark ship detection
    # ---------------------------------------------------------------------------

    async def detect_dark_ships(self) -> list[dict]:
        """Find vessels that stopped transmitting AIS in sensitive areas.

        Algorithm:
        1. Get vessels seen in last 24h but NOT in last 6h
        2. Check if last known position was in a monitored bbox
        3. If yes → flag as dark ship event
        4. Ignore vessels with speed=0 at port (likely just docked)
        """
        now = datetime.now(timezone.utc)
        cutoff_24h = now - timedelta(hours=24)
        cutoff_6h = now - timedelta(hours=6)

        events: list[dict] = []
        try:
            async with AsyncSessionLocal() as session:
                # Get vessels last seen between 6-24h ago
                result = await session.execute(text("""
                    SELECT DISTINCT ON (mmsi)
                        mmsi, vessel_name, lat, lng, speed, timestamp
                    FROM vessel_tracks
                    WHERE timestamp >= :cutoff_24h
                      AND timestamp < :cutoff_6h
                    ORDER BY mmsi, timestamp DESC
                """), {"cutoff_24h": cutoff_24h, "cutoff_6h": cutoff_6h})
                candidates = result.fetchall()

                # Check these MMSIs haven't been seen more recently
                for row in candidates:
                    mmsi, vessel_name, lat, lng, speed, ts = row

                    # Check if there's a more recent track (would disqualify as dark)
                    recent = await session.execute(text("""
                        SELECT COUNT(*) FROM vessel_tracks
                        WHERE mmsi = :mmsi AND timestamp >= :cutoff_6h
                    """), {"mmsi": mmsi, "cutoff_6h": cutoff_6h})
                    recent_count = recent.scalar()
                    if recent_count and recent_count > 0:
                        continue  # Still active, not dark

                    # Check if last known position is in a monitored area
                    area = _in_monitored_area(lat, lng)
                    if area is None:
                        continue

                    # Ignore vessels sitting stationary at port (likely docked)
                    port = self._is_near_port(lat, lng)
                    if port and (speed is None or speed < 1.0):
                        continue

                    hours_dark = (now - ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else now - ts).total_seconds() / 3600

                    events.append({
                        "event_type": "dark_ship",
                        "mmsi": mmsi,
                        "vessel_name": vessel_name,
                        "lat": lat,
                        "lng": lng,
                        "severity": "notable",
                        "details": {
                            "area": area,
                            "last_seen": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                            "hours_dark": round(hours_dark, 1),
                            "last_speed": speed,
                        },
                    })

        except Exception as exc:
            logger.error("Dark ship detection error: %s", exc)

        if events:
            logger.info("Dark ship detection: found %d dark vessels", len(events))
        return events

    # ---------------------------------------------------------------------------
    # STS transfer detection
    # ---------------------------------------------------------------------------

    async def detect_sts_transfers(self) -> list[dict]:
        """Detect potential ship-to-ship transfers.

        Algorithm:
        1. Find pairs of vessels within ~500m (0.27 NM) of each other
        2. Both must have speed < 2 knots
        3. Must persist for at least 2 consecutive polls (>10 min)
        4. Exclude vessels at known ports/anchorages
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        events: list[dict] = []
        STS_RADIUS_NM = 0.27  # ~500 metres
        STS_PERSIST_MINUTES = 10

        try:
            async with AsyncSessionLocal() as session:
                # Get most recent position for each vessel seen in last 30 min, speed < 2kt
                result = await session.execute(text("""
                    SELECT DISTINCT ON (mmsi)
                        mmsi, vessel_name, lat, lng, speed, timestamp
                    FROM vessel_tracks
                    WHERE timestamp >= :cutoff
                      AND (speed IS NULL OR speed < 2.0)
                    ORDER BY mmsi, timestamp DESC
                """), {"cutoff": cutoff})
                slow_vessels = result.fetchall()

            # Pairwise proximity check (O(n²) but n is small in practice)
            vessels = [
                {
                    "mmsi": r[0],
                    "vessel_name": r[1],
                    "lat": r[2],
                    "lng": r[3],
                    "speed": r[4],
                    "timestamp": r[5],
                }
                for r in slow_vessels
                if r[2] is not None and r[3] is not None
            ]

            now = datetime.now(timezone.utc)
            new_candidates: dict[frozenset, datetime] = {}

            for i in range(len(vessels)):
                for j in range(i + 1, len(vessels)):
                    v1, v2 = vessels[i], vessels[j]

                    dist_nm = haversine_nm(v1["lat"], v1["lng"], v2["lat"], v2["lng"])
                    if dist_nm > STS_RADIUS_NM:
                        continue

                    # Exclude if either vessel is at a known port
                    if self._is_near_port(v1["lat"], v1["lng"]) or self._is_near_port(v2["lat"], v2["lng"]):
                        continue

                    pair_key = frozenset({v1["mmsi"], v2["mmsi"]})

                    # Track when we first saw this pair close together
                    first_seen = self._sts_candidates.get(pair_key, now)
                    new_candidates[pair_key] = first_seen

                    # Only fire event if pair has persisted long enough
                    duration_min = (now - first_seen).total_seconds() / 60
                    if duration_min < STS_PERSIST_MINUTES:
                        continue

                    events.append({
                        "event_type": "sts_transfer",
                        "mmsi": v1["mmsi"],
                        "vessel_name": v1["vessel_name"],
                        "lat": (v1["lat"] + v2["lat"]) / 2,
                        "lng": (v1["lng"] + v2["lng"]) / 2,
                        "severity": "notable",
                        "details": {
                            "vessel1_mmsi": v1["mmsi"],
                            "vessel1_name": v1["vessel_name"],
                            "vessel2_mmsi": v2["mmsi"],
                            "vessel2_name": v2["vessel_name"],
                            "distance_nm": round(dist_nm, 3),
                            "duration_min": round(duration_min, 1),
                            "vessel1_speed": v1["speed"],
                            "vessel2_speed": v2["speed"],
                        },
                    })

            # Update STS candidate tracking
            self._sts_candidates = new_candidates

        except Exception as exc:
            logger.error("STS detection error: %s", exc)

        if events:
            logger.info("STS detection: found %d potential transfers", len(events))
        return events

    # ---------------------------------------------------------------------------
    # Port call detection
    # ---------------------------------------------------------------------------

    async def detect_port_calls(self) -> list[dict]:
        """Detect vessels entering/leaving monitored ports."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=20)
        events: list[dict] = []

        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(text("""
                    SELECT DISTINCT ON (mmsi)
                        mmsi, vessel_name, lat, lng, speed, timestamp
                    FROM vessel_tracks
                    WHERE timestamp >= :cutoff
                    ORDER BY mmsi, timestamp DESC
                """), {"cutoff": cutoff})
                current_vessels = result.fetchall()

            # Build current port occupancy
            current_port_vessels: dict[str, set[str]] = {p["name"]: set() for p in self.MONITORED_PORTS}
            vessel_map: dict[str, dict] = {}

            for row in current_vessels:
                mmsi, vessel_name, lat, lng, speed, ts = row
                if lat is None or lng is None:
                    continue
                vessel_map[mmsi] = {"vessel_name": vessel_name, "lat": lat, "lng": lng}
                for port in self.MONITORED_PORTS:
                    d = haversine_nm(lat, lng, port["lat"], port["lng"])
                    if d <= port["radius_nm"]:
                        current_port_vessels[port["name"]].add(mmsi)

            # Compare against previous snapshot
            for port_name, current_mmsis in current_port_vessels.items():
                prev_mmsis = self._prev_port_vessels.get(port_name, set())

                # New arrivals
                for mmsi in current_mmsis - prev_mmsis:
                    v = vessel_map.get(mmsi, {})
                    events.append({
                        "event_type": "port_call",
                        "mmsi": mmsi,
                        "vessel_name": v.get("vessel_name"),
                        "lat": v.get("lat"),
                        "lng": v.get("lng"),
                        "severity": "routine",
                        "details": {
                            "port": port_name,
                            "direction": "arrival",
                        },
                    })

                # Departures
                for mmsi in prev_mmsis - current_mmsis:
                    # Only flag if we still have some recent data for this vessel
                    v = vessel_map.get(mmsi, {})
                    events.append({
                        "event_type": "port_call",
                        "mmsi": mmsi,
                        "vessel_name": v.get("vessel_name"),
                        "lat": v.get("lat"),
                        "lng": v.get("lng"),
                        "severity": "routine",
                        "details": {
                            "port": port_name,
                            "direction": "departure",
                        },
                    })

            # Update snapshot
            self._prev_port_vessels = current_port_vessels

        except Exception as exc:
            logger.error("Port call detection error: %s", exc)

        return events

    # ---------------------------------------------------------------------------
    # Sanctions cross-reference
    # ---------------------------------------------------------------------------

    async def check_sanctions_vessels(self) -> list[dict]:
        """Cross-reference recently seen vessel names against sanctions lists."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
        hits: list[dict] = []

        try:
            from sqlalchemy import text as sql_text
            async with AsyncSessionLocal() as session:
                # Get distinct vessels seen recently
                result = await session.execute(sql_text("""
                    SELECT DISTINCT mmsi, vessel_name
                    FROM vessel_tracks
                    WHERE timestamp >= :cutoff
                      AND vessel_name IS NOT NULL
                      AND vessel_name != ''
                      AND vessel_name != 'Unknown'
                """), {"cutoff": cutoff})
                vessels = result.fetchall()

            for mmsi, vessel_name in vessels:
                try:
                    # Check vessel name against sanctions entities
                    async with AsyncSessionLocal() as session:
                        result = await session.execute(sql_text("""
                            SELECT id, name, datasets, countries
                            FROM sanctions_entities
                            WHERE LOWER(name) LIKE LOWER(:name_pattern)
                               OR EXISTS (
                                   SELECT 1 FROM unnest(aliases) AS alias
                                   WHERE LOWER(alias) LIKE LOWER(:name_pattern)
                               )
                            LIMIT 3
                        """), {"name_pattern": f"%{vessel_name}%"})
                        matches = result.fetchall()

                    for match in matches:
                        hits.append({
                            "mmsi": mmsi,
                            "vessel_name": vessel_name,
                            "sanctions_entity_id": match[0],
                            "sanctions_name": match[1],
                            "datasets": match[2],
                            "countries": match[3],
                        })
                except Exception:
                    pass  # Sanctions table may not be populated

        except Exception as exc:
            logger.debug("Sanctions vessel check: %s", exc)

        return hits

    # ---------------------------------------------------------------------------
    # Internal: store event record and optionally create Post
    # ---------------------------------------------------------------------------

    async def _store_event(self, event: dict) -> None:
        """Persist a maritime event to the DB, deduplicating within a 6h window."""
        from app.models.vessel import MaritimeEvent

        event_type = event.get("event_type", "unknown")
        mmsi = event.get("mmsi", "")
        severity = event.get("severity", "routine")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=6)

        try:
            async with AsyncSessionLocal() as session:
                # Dedup: check if same event type + mmsi already recorded recently
                existing = await session.execute(text("""
                    SELECT id FROM maritime_events
                    WHERE mmsi = :mmsi
                      AND event_type = :event_type
                      AND detected_at >= :cutoff
                      AND resolved_at IS NULL
                    LIMIT 1
                """), {"mmsi": mmsi, "event_type": event_type, "cutoff": cutoff})
                if existing.fetchone():
                    return  # Already recorded

                me = MaritimeEvent(
                    event_type=event_type,
                    mmsi=mmsi,
                    vessel_name=event.get("vessel_name"),
                    lat=event.get("lat"),
                    lng=event.get("lng"),
                    details=event.get("details"),
                    severity=severity,
                )
                session.add(me)
                await session.flush()

                # Create a Post record for significant events so they appear in the feed
                if severity in ("notable", "critical") and event_type in ("dark_ship", "sts_transfer"):
                    from app.models.post import Post
                    from app.models.event import Event
                    from app.routers.feed import broadcast_post

                    vessel_name = event.get("vessel_name") or mmsi
                    details = event.get("details", {})

                    if event_type == "dark_ship":
                        area = details.get("area", "monitored area")
                        hours_dark = details.get("hours_dark", "?")
                        content = (
                            f"[Maritime Intel] DARK SHIP: {vessel_name} (MMSI: {mmsi}) "
                            f"went dark in {area} — last seen {hours_dark}h ago"
                        )
                    else:
                        v1 = details.get("vessel1_name", "Unknown")
                        v2 = details.get("vessel2_name", "Unknown")
                        duration = details.get("duration_min", "?")
                        content = (
                            f"[Maritime Intel] POSSIBLE STS TRANSFER: {v1} + {v2} "
                            f"within 500m for {duration} min"
                        )

                    lat = event.get("lat")
                    lng = event.get("lng")

                    post = Post(
                        source_type="maritime_intel",
                        source_id=f"{event_type}_{mmsi}",
                        author="Maritime Intel",
                        content=content,
                        raw_json=event,
                        timestamp=datetime.now(timezone.utc),
                    )
                    session.add(post)
                    await session.flush()

                    if lat and lng:
                        geo_event = Event(
                            post_id=post.id,
                            lat=lat,
                            lng=lng,
                            place_name=f"Maritime: {vessel_name}",
                            confidence=0.75,
                        )
                        session.add(geo_event)

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
                    try:
                        await broadcast_post(post_dict)
                    except Exception:
                        pass

                await session.commit()

        except Exception as exc:
            logger.warning("Failed to store maritime event (%s/%s): %s", event_type, mmsi, exc)

    # ---------------------------------------------------------------------------
    # Main analysis runner
    # ---------------------------------------------------------------------------

    async def run_analysis(self) -> dict:
        """Run all maritime intelligence checks and store detected events."""
        dark_ships = await self.detect_dark_ships()
        sts_transfers = await self.detect_sts_transfers()
        port_calls = await self.detect_port_calls()

        # Store events (with dedup)
        for event in dark_ships + sts_transfers + port_calls:
            await self._store_event(event)

        result = {
            "dark_ships": len(dark_ships),
            "sts_transfers": len(sts_transfers),
            "port_calls": len(port_calls),
        }

        if dark_ships or sts_transfers:
            logger.warning(
                "Maritime intel: %d dark ships, %d STS transfers, %d port calls",
                result["dark_ships"], result["sts_transfers"], result["port_calls"],
            )
        else:
            logger.debug(
                "Maritime intel analysis complete: %s",
                result,
            )

        return result

    # ---------------------------------------------------------------------------
    # Background analysis loop (called from orchestrator)
    # ---------------------------------------------------------------------------

    async def run_loop(self) -> None:
        """Run analysis every 15 minutes indefinitely."""
        while True:
            try:
                await self.run_analysis()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Maritime intel loop error: %s", exc)
            await asyncio.sleep(900)  # 15 minutes


# Singleton
maritime_intel_service = MaritimeIntelService()
