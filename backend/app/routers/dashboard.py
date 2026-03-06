"""Dashboard stats API router."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.orchestrator import orchestrator
from app.db import get_db
from app.middleware.auth import get_current_user
from app.models import Credential, Event, Post, Source, User
from app.models.entity import Entity

logger = logging.getLogger("orthanc.routers.dashboard")

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/setup-status")
async def get_setup_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Check what the user has configured — used by the first-run setup wizard."""
    # Count sources for this user
    sources_result = await db.execute(
        select(func.count()).select_from(Source).where(Source.user_id == current_user.id)
    )
    sources_count: int = sources_result.scalar() or 0

    # Get configured credential providers for this user
    credentials_result = await db.execute(
        select(Credential.provider).where(Credential.user_id == current_user.id)
    )
    configured_providers: List[str] = [row[0] for row in credentials_result.fetchall()]

    # Count total posts (global — posts don't have user_id)
    posts_result = await db.execute(select(func.count()).select_from(Post))
    posts_count: int = posts_result.scalar() or 0

    return {
        "has_sources": sources_count > 0,
        "has_credentials": len(configured_providers) > 0,
        "configured_providers": configured_providers,
        "source_count": sources_count,
        "post_count": posts_count,
        "setup_complete": sources_count > 0,
    }


@router.get("/stats")
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return aggregated dashboard statistics."""
    now = datetime.now(tz=timezone.utc)
    cutoff_24h = now - timedelta(hours=24)

    # Total counts
    total_posts_result = await db.execute(select(func.count(Post.id)))
    total_posts = total_posts_result.scalar() or 0

    total_events_result = await db.execute(select(func.count(Event.id)))
    total_events = total_events_result.scalar() or 0

    total_entities_result = await db.execute(select(func.count(Entity.id)))
    total_entities = total_entities_result.scalar() or 0

    total_sources_result = await db.execute(
        select(func.count(Source.id)).where(Source.enabled.is_(True))
    )
    total_sources = total_sources_result.scalar() or 0

    # Posts last 24h
    posts_24h_result = await db.execute(
        select(func.count(Post.id)).where(Post.ingested_at >= cutoff_24h)
    )
    posts_last_24h = posts_24h_result.scalar() or 0

    # Posts by source type
    source_type_result = await db.execute(
        select(Post.source_type, func.count(Post.id)).group_by(Post.source_type)
    )
    posts_by_source_type: dict[str, int] = {}
    for row in source_type_result.fetchall():
        posts_by_source_type[row[0]] = row[1]

    # Top 10 entities by mention count
    top_entities_result = await db.execute(
        select(Entity.name, Entity.type, Entity.mention_count)
        .order_by(Entity.mention_count.desc())
        .limit(10)
    )
    top_entities = [
        {"name": row[0], "type": row[1], "mention_count": row[2]}
        for row in top_entities_result.fetchall()
    ]

    # Source health — last polled time per source
    sources_result = await db.execute(
        select(Source).where(Source.enabled.is_(True)).order_by(Source.last_polled.desc().nullslast())
    )
    sources = sources_result.scalars().all()
    source_health = []
    for src in sources:
        last_polled = src.last_polled.isoformat() if src.last_polled else None
        # Determine health: ok if polled within 2x poll interval, warning otherwise
        status = "ok"
        if src.last_polled is None:
            status = "pending"
        elif (now - src.last_polled).total_seconds() > 7200:  # 2 hours
            status = "stale"
        source_health.append({
            "name": src.display_name or src.handle,
            "type": src.type,
            "last_polled": last_polled,
            "status": status,
        })

    # Collector status from orchestrator
    collector_status = orchestrator.get_collector_status()

    return {
        "total_posts": total_posts,
        "total_events": total_events,
        "total_entities": total_entities,
        "total_sources": total_sources,
        "posts_last_24h": posts_last_24h,
        "posts_by_source_type": posts_by_source_type,
        "top_entities": top_entities,
        "recent_alerts": [],
        "collector_status": collector_status,
        "source_health": source_health,
    }


@router.get("/velocity")
async def get_velocity(
    hours: int = Query(default=24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Post ingestion velocity — hourly buckets."""
    since = datetime.utcnow() - timedelta(hours=hours)
    result = await db.execute(
        text("""
            SELECT date_trunc('hour', ingested_at) as bucket,
                   source_type,
                   count(*) as count
            FROM posts
            WHERE ingested_at >= :since
            GROUP BY bucket, source_type
            ORDER BY bucket
        """),
        {"since": since},
    )
    rows = result.fetchall()
    buckets: dict = {}
    for row in rows:
        key = row.bucket.isoformat()
        if key not in buckets:
            buckets[key] = {"hour": key, "counts": {}, "total": 0}
        buckets[key]["counts"][row.source_type] = row.count
        buckets[key]["total"] += row.count
    return sorted(buckets.values(), key=lambda x: x["hour"])


@router.get("/source-health")
async def get_source_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Source/collector health summary."""
    result = await db.execute(
        text("""
            SELECT source_type,
                   count(*) as total_posts,
                   max(ingested_at) as last_post,
                   count(*) FILTER (WHERE ingested_at >= now() - interval '1 hour') as posts_1h,
                   count(*) FILTER (WHERE ingested_at >= now() - interval '24 hours') as posts_24h
            FROM posts
            GROUP BY source_type
            ORDER BY max(ingested_at) DESC
        """)
    )
    return [
        {
            "source_type": row.source_type,
            "total_posts": row.total_posts,
            "last_post": row.last_post.isoformat() if row.last_post else None,
            "posts_1h": row.posts_1h,
            "posts_24h": row.posts_24h,
            "status": "active" if row.posts_1h > 0 else ("idle" if row.posts_24h > 0 else "stale"),
        }
        for row in result.fetchall()
    ]


@router.get("/trending-entities")
async def get_trending_entities(
    hours: int = Query(default=6, ge=1, le=48),
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Top entities by mention count in recent window."""
    since = datetime.utcnow() - timedelta(hours=hours)
    result = await db.execute(
        text("""
            SELECT e.name, e.type, count(em.id) as mentions
            FROM entities e
            JOIN entity_mentions em ON em.entity_id = e.id
            JOIN posts p ON p.id = em.post_id
            WHERE p.ingested_at >= :since
            GROUP BY e.name, e.type
            ORDER BY mentions DESC
            LIMIT :limit
        """),
        {"since": since, "limit": limit},
    )
    return [{"name": r.name, "type": r.type, "mentions": r.mentions} for r in result.fetchall()]


@router.get("/geo-hotspots")
async def get_geo_hotspots(
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Top geographic locations by event count."""
    since = datetime.utcnow() - timedelta(hours=hours)
    result = await db.execute(
        text("""
            SELECT e.place_name, e.lat, e.lng, count(*) as event_count
            FROM events e
            JOIN posts p ON p.id = e.post_id
            WHERE p.ingested_at >= :since AND e.place_name IS NOT NULL
            GROUP BY e.place_name, e.lat, e.lng
            ORDER BY event_count DESC
            LIMIT :limit
        """),
        {"since": since, "limit": limit},
    )
    return [
        {"place_name": r.place_name, "lat": r.lat, "lng": r.lng, "count": r.event_count}
        for r in result.fetchall()
    ]
