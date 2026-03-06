"""NASA FIRMS thermal anomaly collector — free public CSV endpoint."""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.event import Event
from app.models.post import Post
from app.routers.feed import broadcast_post
from app.services.entity_extractor import entity_extractor
from app.services.geo_extractor import geo_extractor

logger = logging.getLogger("orthanc.collectors.firms")

# NASA FIRMS VIIRS SNPP 24-hour global active fire data (free, no key needed)
FIRMS_URL = (
    "https://firms.modaps.eosdis.nasa.gov/data/active_fire/"
    "suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_Global_24h.csv"
)

POLL_INTERVAL = 3600  # hourly

CONFLICT_ZONES: dict[str, dict[str, float]] = {
    "ukraine": {"lat_min": 44.0, "lat_max": 52.5, "lng_min": 22.0, "lng_max": 40.5},
    "middle_east": {"lat_min": 12.0, "lat_max": 42.0, "lng_min": 25.0, "lng_max": 63.0},
    "sudan": {"lat_min": 3.0, "lat_max": 22.0, "lng_min": 21.0, "lng_max": 38.0},
    "myanmar": {"lat_min": 9.5, "lat_max": 28.5, "lng_min": 92.0, "lng_max": 101.5},
}

# VIIRS confidence levels: l=low, n=nominal, h=high
ACCEPTED_CONFIDENCE = {"n", "h"}


def _in_conflict_zone(lat: float, lng: float) -> str | None:
    """Return conflict zone name if the point falls within it, else None."""
    for zone, bbox in CONFLICT_ZONES.items():
        if (
            bbox["lat_min"] <= lat <= bbox["lat_max"]
            and bbox["lng_min"] <= lng <= bbox["lng_max"]
        ):
            return zone
    return None


class FIRMSCollector:
    """Polls NASA FIRMS for thermal anomaly data and stores relevant detections."""

    def __init__(self, poll_interval: int = POLL_INTERVAL):
        self._poll_interval = poll_interval
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            logger.info("FIRMS collector already running")
            return
        logger.info("Starting FIRMS thermal collector (interval=%ds)", self._poll_interval)
        self._task = asyncio.create_task(self._poll_loop(), name="firms_poll")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("FIRMS collector stopped")

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                logger.info("FIRMS poll loop cancelled")
                raise
            except Exception as exc:
                logger.exception("FIRMS poll error: %s", exc)
            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                raise

    async def _poll_once(self) -> None:
        logger.info("Polling NASA FIRMS thermal data")
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                resp = await client.get(FIRMS_URL)
                resp.raise_for_status()
                csv_text = resp.text
        except httpx.HTTPError as exc:
            logger.error("Failed to fetch FIRMS data: %s", exc)
            return

        new_count = 0
        reader = csv.DictReader(io.StringIO(csv_text))

        async with AsyncSessionLocal() as session:
            for row in reader:
                try:
                    lat_str = row.get("latitude", "").strip()
                    lng_str = row.get("longitude", "").strip()
                    if not lat_str or not lng_str:
                        continue

                    lat = float(lat_str)
                    lng = float(lng_str)

                    zone = _in_conflict_zone(lat, lng)
                    if not zone:
                        continue  # skip points outside conflict zones

                    confidence = row.get("confidence", "l").strip().lower()
                    if confidence not in ACCEPTED_CONFIDENCE:
                        continue  # skip low-confidence

                    acq_date = row.get("acq_date", "").strip()
                    acq_time = row.get("acq_time", "").strip()
                    brightness = row.get("bright_ti4", row.get("brightness", "")).strip()
                    frp = row.get("frp", "").strip()
                    satellite = row.get("satellite", "").strip()
                    daynight = row.get("daynight", "").strip()

                    source_id = f"{lat}_{lng}_{acq_date}_{acq_time}"

                    # Dedup check
                    existing = await session.execute(
                        select(Post).where(
                            Post.source_type == "firms",
                            Post.source_id == source_id,
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue

                    content = (
                        f"[FIRMS] Thermal anomaly detected at {lat}, {lng} — "
                        f"Brightness: {brightness}, FRP: {frp}, "
                        f"Confidence: {confidence.upper()}, Zone: {zone}"
                    )

                    # Parse timestamp
                    ts: datetime | None = None
                    try:
                        if acq_date and acq_time:
                            hour = int(acq_time) // 100
                            minute = int(acq_time) % 100
                            ts = datetime.strptime(acq_date, "%Y-%m-%d").replace(
                                hour=hour, minute=minute, tzinfo=timezone.utc
                            )
                    except Exception:
                        ts = datetime.now(timezone.utc)

                    post = Post(
                        source_type="firms",
                        source_id=source_id,
                        author=f"NASA FIRMS ({satellite})",
                        content=content,
                        raw_json={
                            "lat": lat,
                            "lng": lng,
                            "brightness": brightness,
                            "frp": frp,
                            "confidence": confidence,
                            "acq_date": acq_date,
                            "acq_time": acq_time,
                            "satellite": satellite,
                            "daynight": daynight,
                            "zone": zone,
                        },
                        timestamp=ts,
                    )
                    session.add(post)
                    await session.flush()

                    # Broadcast to live feed
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

                    # Auto-create event with lat/lng
                    try:
                        event = Event(
                            post_id=post.id,
                            lat=lat,
                            lng=lng,
                            place_name=zone.replace("_", " ").title(),
                            confidence=0.9,
                        )
                        session.add(event)
                    except Exception as geo_exc:
                        logger.warning("FIRMS event creation failed for %s: %s", source_id, geo_exc)

                    # Entity extraction (picks up zone/country names from content)
                    try:
                        extracted_ents = entity_extractor.extract_entities(content)
                        for ent in extracted_ents:
                            from app.models.entity import Entity, EntityMention
                            canonical = entity_extractor.canonical_name(ent["name"])
                            existing_ent = await session.execute(
                                select(Entity).where(
                                    Entity.canonical_name == canonical,
                                    Entity.type == ent["type"],
                                )
                            )
                            entity = existing_ent.scalar_one_or_none()
                            if entity:
                                entity.mention_count += 1
                                entity.last_seen = datetime.now(tz=timezone.utc)
                            else:
                                entity = Entity(
                                    name=ent["name"],
                                    type=ent["type"],
                                    canonical_name=canonical,
                                    mention_count=1,
                                )
                                session.add(entity)
                                await session.flush()
                            mention = EntityMention(
                                entity_id=entity.id,
                                post_id=post.id,
                                context_snippet=ent["context_snippet"],
                            )
                            session.add(mention)
                    except Exception as ent_exc:
                        logger.warning("Entity extraction failed for FIRMS post %s: %s", post.id, ent_exc)

                    new_count += 1

                except Exception as row_exc:
                    logger.warning("FIRMS row parse error: %s — row: %s", row_exc, row)
                    continue

            await session.commit()

        logger.info("FIRMS poll complete: %d new thermal detections stored", new_count)
