"""Cross-source intelligence fusion engine.

Detects multi-source corroborated events via spatial-temporal clustering.
Runs as a background task, polling every 5 minutes.
"""
import asyncio
import logging
import math
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, text

from app.db import AsyncSessionLocal
from app.models.fused_event import FusedEvent

logger = logging.getLogger("orthanc.services.fusion")

# Configurable thresholds
SPATIAL_RADIUS_KM = 50       # Events within 50km are considered co-located
TEMPORAL_WINDOW_HOURS = 6    # Events within 6 hours are contemporaneous
MIN_SOURCES = 2              # Minimum different source types to create a fused event
POLL_INTERVAL = 300          # Check every 5 minutes


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return R * 2 * math.asin(min(1.0, math.sqrt(a)))


class FusionService:
    """Detects multi-source corroborated events via spatial-temporal clustering."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "Fusion service started (radius=%dkm, window=%dh, min_sources=%d)",
            SPATIAL_RADIUS_KM,
            TEMPORAL_WINDOW_HOURS,
            MIN_SOURCES,
        )

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self):
        while self._running:
            try:
                await self._scan()
            except Exception as exc:
                logger.error("Fusion scan error: %s", exc, exc_info=True)
            await asyncio.sleep(POLL_INTERVAL)

    async def _scan(self):
        """Scan recent geolocated posts for multi-source clusters."""
        # Look back far enough to catch overlapping time windows
        since = datetime.now(timezone.utc) - timedelta(hours=TEMPORAL_WINDOW_HOURS * 2)

        async with AsyncSessionLocal() as session:
            # Query posts joined with their geo events (table: events, columns: lat, lng, place_name)
            result = await session.execute(
                text("""
                    SELECT
                        p.id,
                        p.source_type,
                        p.content,
                        p.timestamp,
                        e.lat,
                        e.lng,
                        e.place_name
                    FROM posts p
                    JOIN events e ON e.post_id = p.id
                    WHERE p.timestamp >= :since
                      AND e.lat IS NOT NULL
                      AND e.lng IS NOT NULL
                    ORDER BY p.timestamp DESC
                    LIMIT 500
                """),
                {"since": since},
            )
            rows = result.fetchall()

        if len(rows) < MIN_SOURCES:
            return

        # Greedy spatial-temporal clustering
        used: set[int] = set()
        clusters: list[list] = []

        for i, row_i in enumerate(rows):
            if i in used:
                continue
            cluster = [row_i]
            used.add(i)

            for j, row_j in enumerate(rows):
                if j in used:
                    continue
                # Spatial proximity check
                dist = haversine_km(row_i.lat, row_i.lng, row_j.lat, row_j.lng)
                if dist > SPATIAL_RADIUS_KM:
                    continue
                # Temporal proximity check
                if row_i.timestamp and row_j.timestamp:
                    time_diff = abs(
                        (row_i.timestamp - row_j.timestamp).total_seconds()
                    )
                    if time_diff > TEMPORAL_WINDOW_HOURS * 3600:
                        continue
                cluster.append(row_j)
                used.add(j)

            # Only retain clusters with multiple different source types
            source_types = set(r.source_type for r in cluster)
            if len(source_types) >= MIN_SOURCES:
                clusters.append(cluster)

        if not clusters:
            return

        logger.info("Fusion: found %d multi-source clusters", len(clusters))

        async with AsyncSessionLocal() as session:
            for cluster in clusters:
                post_ids = [_uuid.UUID(str(r.id)) if not isinstance(r.id, _uuid.UUID) else r.id for r in cluster]
                source_types = list(set(r.source_type for r in cluster))

                # Check if any existing fused event shares posts with this cluster.
                from app.models.fused_event import FusedEvent
                existing_check = await session.execute(
                    select(FusedEvent.id).limit(1)
                )
                # Skip overlap check if table is empty (common case)
                has_existing = existing_check.scalars().first()
                skip = False
                if has_existing:
                    # Check overlap one post at a time
                    for pid in post_ids[:5]:
                        chk = await session.execute(
                            text("SELECT 1 FROM fused_events WHERE :pid = ANY(component_post_ids) LIMIT 1"),
                            {"pid": pid},
                        )
                        if chk.fetchone():
                            skip = True
                            break
                if skip:
                    continue  # Already fused

                # Calculate centroid
                lats = [r.lat for r in cluster]
                lngs = [r.lng for r in cluster]
                centroid_lat = sum(lats) / len(lats)
                centroid_lng = sum(lngs) / len(lngs)

                # Radius = max distance from centroid to any cluster member
                max_dist = max(
                    haversine_km(centroid_lat, centroid_lng, r.lat, r.lng)
                    for r in cluster
                )

                # Time window
                timestamps = [r.timestamp for r in cluster if r.timestamp]
                if timestamps:
                    # Ensure timezone-aware
                    aware = []
                    for t in timestamps:
                        if t.tzinfo is None:
                            t = t.replace(tzinfo=timezone.utc)
                        aware.append(t)
                    time_start = min(aware)
                    time_end = max(aware)
                else:
                    now = datetime.now(timezone.utc)
                    time_start = time_end = now

                # Severity
                severity = "routine"
                if len(source_types) >= 3:
                    severity = "urgent"
                if len(source_types) >= 4 or len(cluster) >= 10:
                    severity = "flash"

                # Build summary snippets
                snippets = []
                for r in cluster[:5]:
                    snippet = (r.content or "")[:150]
                    snippets.append(f"[{r.source_type.upper()}] {snippet}")
                raw_summary = "\n".join(snippets)

                # Place names
                place_names = list(set(r.place_name for r in cluster if r.place_name))
                elapsed_h = (time_end - time_start).total_seconds() / 3600

                ai_summary = (
                    f"Multi-source corroborated event near "
                    f"{', '.join(place_names[:3]) or 'unknown location'}. "
                    f"{len(cluster)} reports from {len(source_types)} sources "
                    f"({', '.join(sorted(source_types))}) "
                    f"within {max_dist:.0f}km over {elapsed_h:.1f}h.\n\n{raw_summary}"
                )

                fused = FusedEvent(
                    component_post_ids=post_ids,
                    component_source_types=source_types,
                    centroid_lat=centroid_lat,
                    centroid_lng=centroid_lng,
                    radius_km=max_dist,
                    time_window_start=time_start,
                    time_window_end=time_end,
                    event_types=source_types,
                    severity=severity,
                    ai_summary=ai_summary,
                    entity_names=place_names[:5],
                )
                session.add(fused)
                logger.info(
                    "Fusion: created %s event near %s (%d posts, %d sources)",
                    severity,
                    place_names[:1] or ["unknown"],
                    len(cluster),
                    len(source_types),
                )

            await session.commit()

    async def get_recent(self, hours: int = 24, limit: int = 50) -> list[dict]:
        """Get recent fused events as dicts."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(FusedEvent)
                .where(FusedEvent.created_at >= since)
                .order_by(FusedEvent.created_at.desc())
                .limit(limit)
            )
            events = result.scalars().all()

        return [
            {
                "id": str(e.id),
                "component_post_ids": [str(pid) for pid in (e.component_post_ids or [])],
                "component_source_types": e.component_source_types or [],
                "centroid_lat": e.centroid_lat,
                "centroid_lng": e.centroid_lng,
                "radius_km": e.radius_km,
                "time_window_start": (
                    e.time_window_start.isoformat() if e.time_window_start else None
                ),
                "time_window_end": (
                    e.time_window_end.isoformat() if e.time_window_end else None
                ),
                "severity": e.severity,
                "ai_summary": e.ai_summary,
                "entity_names": e.entity_names or [],
                "source_count": len(e.component_source_types or []),
                "post_count": len(e.component_post_ids or []),
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ]

    async def get_by_id(self, event_id: str) -> Optional[dict]:
        """Get a single fused event by ID."""
        import uuid as _uuid
        try:
            eid = _uuid.UUID(event_id)
        except ValueError:
            return None

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(FusedEvent).where(FusedEvent.id == eid)
            )
            e = result.scalar_one_or_none()

        if not e:
            return None

        return {
            "id": str(e.id),
            "component_post_ids": [str(pid) for pid in (e.component_post_ids or [])],
            "component_source_types": e.component_source_types or [],
            "centroid_lat": e.centroid_lat,
            "centroid_lng": e.centroid_lng,
            "radius_km": e.radius_km,
            "time_window_start": (
                e.time_window_start.isoformat() if e.time_window_start else None
            ),
            "time_window_end": (
                e.time_window_end.isoformat() if e.time_window_end else None
            ),
            "event_types": e.event_types or [],
            "severity": e.severity,
            "ai_summary": e.ai_summary,
            "entity_names": e.entity_names or [],
            "source_count": len(e.component_source_types or []),
            "post_count": len(e.component_post_ids or []),
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }


# Module-level singleton
fusion_service = FusionService()
