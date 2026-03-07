"""ACLED conflict event collector."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.event import Event
from app.models.post import Post

logger = logging.getLogger("orthanc.collectors.acled")

# ACLED event types with display colors
ACLED_EVENT_TYPES = {
    "Battles": {"color": "#ef4444", "icon": "⚔️"},
    "Explosions/Remote violence": {"color": "#f97316", "icon": "💥"},
    "Violence against civilians": {"color": "#991b1b", "icon": "🩸"},
    "Protests": {"color": "#eab308", "icon": "✊"},
    "Riots": {"color": "#a855f7", "icon": "🔥"},
    "Strategic developments": {"color": "#3b82f6", "icon": "📋"},
}

# Default regions to monitor
DEFAULT_REGIONS = ["Middle East", "Eastern Europe", "Northern Africa"]


class ACLEDCollector:
    """Polls ACLED API for conflict events."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self, api_key: str, email: str, regions: list[str] | None = None) -> None:
        """Start polling ACLED API."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(
            self._poll_loop(api_key, email, regions or DEFAULT_REGIONS),
            name="acled_poll",
        )
        logger.info("ACLED collector started, monitoring regions: %s", regions or DEFAULT_REGIONS)

    async def stop(self) -> None:
        """Stop the collector."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("ACLED collector stopped")

    async def _poll_loop(self, api_key: str, email: str, regions: list[str]) -> None:
        """Poll every 6 hours."""
        while self._running:
            try:
                await self._poll(api_key, email, regions)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("ACLED poll error: %s", exc)
            try:
                await asyncio.sleep(6 * 3600)
            except asyncio.CancelledError:
                raise

    async def _poll(self, api_key: str, email: str, regions: list[str]) -> None:
        """Fetch recent ACLED events for all regions."""
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        for region in regions:
            try:
                await self._fetch_region(api_key, email, region, since)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("ACLED fetch error for region %s: %s", region, exc)
            # Rate limiting between regions
            try:
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                raise

    async def _fetch_region(self, api_key: str, email: str, region: str, since: str) -> None:
        """Fetch events for a single region from ACLED API."""
        url = "https://api.acleddata.com/acled/read"
        params = {
            "key": api_key,
            "email": email,
            "event_date": f"{since}|",
            "event_date_where": "BETWEEN",
            "region": region,
            "limit": 500,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        events = data.get("data", [])
        logger.info("ACLED: fetched %d events for %s since %s", len(events), region, since)

        new_count = 0
        async with AsyncSessionLocal() as session:
            for event in events:
                try:
                    acled_id = str(event.get("data_id", "")).strip()
                    if not acled_id:
                        continue

                    external_id = f"acled:{acled_id}"

                    # Dedup check via external_id
                    existing = await session.execute(
                        select(Post).where(Post.external_id == external_id)
                    )
                    if existing.scalars().first():
                        continue

                    # Build post content
                    event_type = event.get("event_type", "Unknown")
                    sub_event = event.get("sub_event_type", "")
                    actor1 = event.get("actor1", "Unknown")
                    actor2 = event.get("actor2", "") or ""
                    location = event.get("location", "") or ""
                    country = event.get("country", "") or ""
                    notes = event.get("notes", "") or ""
                    fatalities = event.get("fatalities", 0)

                    title = f"[{event_type}] {actor1}"
                    if actor2:
                        title += f" vs {actor2}"
                    title += f" — {location}, {country}"

                    content = f"{title}\n\n{notes}".strip()
                    if fatalities and int(fatalities) > 0:
                        content += f"\n\nFatalities: {fatalities}"

                    # Parse date
                    event_date_str = event.get("event_date", "")
                    try:
                        event_date = datetime.strptime(event_date_str, "%Y-%m-%d").replace(
                            tzinfo=timezone.utc
                        )
                    except (ValueError, TypeError):
                        event_date = datetime.now(timezone.utc)

                    lat_raw = event.get("latitude", 0)
                    lng_raw = event.get("longitude", 0)
                    try:
                        lat = float(lat_raw) if lat_raw else 0.0
                        lng = float(lng_raw) if lng_raw else 0.0
                    except (ValueError, TypeError):
                        lat, lng = 0.0, 0.0

                    raw_meta = {
                        "event_type": event_type,
                        "sub_event_type": sub_event,
                        "actor1": actor1,
                        "actor2": actor2,
                        "fatalities": int(fatalities) if fatalities else 0,
                        "country": country,
                        "admin1": event.get("admin1", "") or "",
                        "admin2": event.get("admin2", "") or "",
                        "source": event.get("source", "") or "",
                        "source_scale": event.get("source_scale", "") or "",
                        "region": region,
                        "source_url": event.get("source_url", "") or "",
                    }

                    post = Post(
                        source_type="acled",
                        source_id=acled_id,
                        author=actor1[:255] if actor1 else "ACLED",
                        content=content,
                        raw_json=raw_meta,
                        timestamp=event_date,
                        external_id=external_id,
                    )
                    session.add(post)
                    await session.flush()

                    # Add geo event (ACLED provides precise lat/lng)
                    if lat and lng:
                        geo_event = Event(
                            post_id=post.id,
                            lat=lat,
                            lng=lng,
                            place_name=f"{location}, {country}".strip(", ") or country or location,
                            confidence=0.95,
                            precision="exact",
                        )
                        session.add(geo_event)

                    # Entity extraction (non-blocking)
                    try:
                        from app.services.entity_extractor import entity_extractor
                        from app.models.entity import Entity, EntityMention
                        text_for_ner = content
                        extracted_ents = await entity_extractor.extract_entities_async(text_for_ner)
                        for ent in extracted_ents:
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
                        logger.debug("Entity extraction failed for ACLED post %s: %s", acled_id, ent_exc)

                    new_count += 1

                except Exception as row_exc:
                    logger.warning("ACLED row error for event %s: %s", event.get("data_id"), row_exc)
                    continue

            await session.commit()

        if new_count:
            logger.info("ACLED: stored %d new events for %s", new_count, region)


acled_collector = ACLEDCollector()
