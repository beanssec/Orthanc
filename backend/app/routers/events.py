"""Events router — backfill and query geo-extracted events."""
from __future__ import annotations

import asyncio
import logging
import math
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import AsyncSessionLocal, get_db
from app.middleware.auth import get_current_user
from app.models.event import Event
from app.models.post import Post
from app.models.user import User
from app.schemas.events import BackfillResponse, EventWithPost, PostSummary
from app.services.geo_extractor import geo_extractor, COUNTRY_NAMES

logger = logging.getLogger("orthanc.routers.events")

router = APIRouter(prefix="/events", tags=["events"])

# Precision hierarchy for filtering
PRECISION_ORDER = ["exact", "city", "region", "country", "continent", "unknown"]
PRECISION_INCLUDE: dict[str, list[str]] = {
    "exact": ["exact"],
    "city": ["exact", "city"],
    "region": ["exact", "city", "region"],
    "country": ["exact", "city", "region", "country"],
    "continent": ["exact", "city", "region", "country", "continent"],
}


# ---------------------------------------------------------------------------
# Background backfill task (geo-extract posts without events)
# ---------------------------------------------------------------------------

async def _run_backfill() -> None:
    """Process all posts that have no events yet and create event records."""
    logger.info("Starting geo backfill…")
    processed = 0
    events_created = 0

    # Get posts with no associated events
    async with AsyncSessionLocal() as session:
        # Subquery: post IDs that already have events
        has_event_sq = select(Event.post_id).distinct().scalar_subquery()
        stmt = select(Post).where(Post.id.not_in(has_event_sq)).order_by(Post.ingested_at.asc())
        result = await session.execute(stmt)
        posts = result.scalars().all()

    logger.info("Backfill: %d posts without events to process", len(posts))

    for post in posts:
        try:
            geo_events = await geo_extractor.process_post(str(post.id), post.content or "")
            if geo_events:
                async with AsyncSessionLocal() as session:
                    for evt in geo_events:
                        event = Event(
                            post_id=post.id,
                            lat=evt["lat"],
                            lng=evt["lng"],
                            place_name=evt["place_name"],
                            confidence=evt["confidence"],
                            precision=evt.get("precision", "unknown"),
                        )
                        session.add(event)
                    await session.commit()
                events_created += len(geo_events)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Backfill geo extraction failed for post %s: %s", post.id, exc)
        processed += 1

        if processed % 10 == 0:
            logger.info("Backfill progress: %d / %d posts processed", processed, len(posts))

    logger.info(
        "Geo backfill complete: %d posts processed, %d events created",
        processed,
        events_created,
    )


# ---------------------------------------------------------------------------
# Background precision backfill (classify existing events)
# ---------------------------------------------------------------------------

def _is_round_coords(lat: float | None, lng: float | None) -> bool:
    """Check if coordinates look like a country centroid (very round numbers)."""
    if lat is None or lng is None:
        return False
    return (abs(lat - round(lat)) < 0.5) and (abs(lng - round(lng)) < 0.5)


async def _run_precision_backfill() -> None:
    """Classify precision for all events that have precision=NULL or 'unknown'."""
    logger.info("Starting precision backfill…")
    updated = 0

    async with AsyncSessionLocal() as session:
        stmt = select(Event).where(
            (Event.precision == None) | (Event.precision == "unknown")  # noqa: E711
        )
        result = await session.execute(stmt)
        events = result.scalars().all()

    logger.info("Precision backfill: %d events to classify", len(events))

    for event in events:
        # Determine precision
        place_name = event.place_name or ""

        # Check if place_name is just a country name
        is_country = False
        for country in COUNTRY_NAMES:
            if place_name.strip().lower() == country.lower():
                is_country = True
                break
            # Also check if place_name STARTS with a known country (Nominatim display_name style)
            if place_name.lower().startswith(country.lower() + ",") or place_name.lower() == country.lower():
                is_country = True
                break

        if is_country:
            precision = "country"
        elif _is_round_coords(event.lat, event.lng):
            precision = "country"
        elif place_name and "," in place_name:
            # Nominatim display_name with commas → likely city-level or better
            precision = "city"
        elif place_name:
            precision = "city"
        else:
            precision = "unknown"

        try:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(Event).where(Event.id == event.id).values(precision=precision)
                )
                await session.commit()
            updated += 1
        except Exception as exc:
            logger.warning("Failed to update precision for event %s: %s", event.id, exc)

    logger.info("Precision backfill complete: %d events updated", updated)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/backfill", status_code=202, response_model=BackfillResponse)
async def backfill_events(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
) -> BackfillResponse:
    """Trigger a background job to geocode all posts that don't have events yet.

    Returns 202 Accepted immediately; processing continues in the background.
    """
    background_tasks.add_task(_run_backfill)
    return BackfillResponse(
        processed=0,
        events_created=0,
        message="Backfill started in background",
    )


@router.post("/backfill-precision", status_code=202)
async def backfill_precision(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Trigger precision classification for all existing events.

    Classifies events without precision scores based on place_name and coordinates.
    Returns 202 Accepted immediately.
    """
    background_tasks.add_task(_run_precision_backfill)
    return {"message": "Precision backfill started in background"}


@router.get("/", response_model=List[EventWithPost])
async def list_events(
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    source_types: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    min_precision: Optional[str] = Query(
        default=None,
        description="Minimum precision level: exact, city, region, country, continent. "
                    "Omit to return all events.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[EventWithPost]:
    """Return geo events with nested post data for the map frontend."""
    stmt = (
        select(Event)
        .join(Post, Event.post_id == Post.id)
        .options(selectinload(Event.post))
        .where(Event.lat.is_not(None), Event.lng.is_not(None))
        .order_by(Post.timestamp.desc())
        .limit(limit)
    )

    if date_from:
        stmt = stmt.where(Post.timestamp >= date_from)
    if date_to:
        stmt = stmt.where(Post.timestamp <= date_to)
    if source_types:
        stmt = stmt.where(Post.source_type.in_(source_types))
    if min_precision and min_precision in PRECISION_INCLUDE:
        allowed = PRECISION_INCLUDE[min_precision]
        stmt = stmt.where(Event.precision.in_(allowed))

    result = await db.execute(stmt)
    events = result.scalars().all()

    out: List[EventWithPost] = []
    for event in events:
        post = event.post
        out.append(
            EventWithPost(
                id=event.id,
                lat=event.lat,
                lng=event.lng,
                place_name=event.place_name,
                confidence=event.confidence,
                precision=getattr(event, "precision", None),
                post=PostSummary(
                    id=post.id,
                    source_type=post.source_type,
                    source_id=post.source_id,
                    author=post.author,
                    content=(post.content or "")[:200],
                    timestamp=post.timestamp,
                ),
            )
        )
    return out
