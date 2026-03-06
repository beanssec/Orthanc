"""Global unified search API — searches across posts, entities, events, and briefs."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.middleware.auth import get_current_user
from app.models.brief import Brief
from app.models.entity import Entity, EntityMention
from app.models.event import Event
from app.models.post import Post
from app.models.user import User

logger = logging.getLogger("orthanc.routers.search")

router = APIRouter(tags=["search"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snippet(text_val: str | None, query: str, max_len: int = 200) -> str:
    """Extract a content snippet around the first match of query."""
    if not text_val:
        return ""
    t = text_val
    idx = t.lower().find(query.lower())
    if idx == -1:
        return t[:max_len]
    # Show context around match
    start = max(0, idx - 60)
    end = min(len(t), idx + len(query) + 140)
    snippet = ("…" if start > 0 else "") + t[start:end] + ("…" if end < len(t) else "")
    return snippet


def _extract_title_from_brief(content: str | None) -> str:
    """Extract title from the first markdown heading in a brief's summary."""
    if not content:
        return "Untitled Brief"
    # Try ## heading first, then # heading
    for pattern in [r"^#+\s+(.+)$", r"^\*\*(.+?)\*\*"]:
        match = re.search(pattern, content, re.MULTILINE)
        if match:
            return match.group(1).strip()[:100]
    # Fall back to first non-empty line
    for line in content.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:100]
    return "Untitled Brief"


# ---------------------------------------------------------------------------
# Per-type search coroutines
# ---------------------------------------------------------------------------

async def _search_posts(
    q: str,
    db: AsyncSession,
    limit: int,
    since: datetime | None,
) -> list[dict[str, Any]]:
    stmt = (
        select(Post)
        .where(
            (Post.content.ilike(f"%{q}%")) | (Post.author.ilike(f"%{q}%"))
        )
        .order_by(Post.timestamp.desc())
        .limit(limit)
    )
    if since:
        stmt = stmt.where(Post.timestamp >= since)
    result = await db.execute(stmt)
    posts = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "source_type": p.source_type,
            "author": p.author or "",
            "snippet": _snippet(p.content, q),
            "timestamp": p.timestamp.isoformat() if p.timestamp else None,
        }
        for p in posts
    ]


async def _search_entities(
    q: str,
    db: AsyncSession,
    limit: int,
    since: datetime | None,
) -> list[dict[str, Any]]:
    stmt = (
        select(Entity)
        .where(Entity.name.ilike(f"%{q}%"))
        .order_by(Entity.mention_count.desc())
        .limit(limit)
    )
    if since:
        stmt = stmt.where(Entity.last_seen >= since)
    result = await db.execute(stmt)
    entities = result.scalars().all()
    return [
        {
            "id": str(e.id),
            "name": e.name,
            "type": e.type,
            "mention_count": e.mention_count,
        }
        for e in entities
    ]


async def _search_events(
    q: str,
    db: AsyncSession,
    limit: int,
    since: datetime | None,
) -> list[dict[str, Any]]:
    stmt = (
        select(Event)
        .join(Post, Event.post_id == Post.id)
        .options(selectinload(Event.post))
        .where(Event.place_name.ilike(f"%{q}%"))
        .order_by(Post.timestamp.desc())
        .limit(limit)
    )
    if since:
        stmt = stmt.where(Post.timestamp >= since)
    result = await db.execute(stmt)
    events = result.scalars().all()
    return [
        {
            "id": str(ev.id),
            "place_name": ev.place_name or "",
            "lat": ev.lat,
            "lng": ev.lng,
            "post_id": str(ev.post_id),
            "timestamp": ev.post.timestamp.isoformat() if ev.post and ev.post.timestamp else None,
        }
        for ev in events
    ]


async def _search_briefs(
    q: str,
    db: AsyncSession,
    limit: int,
    since: datetime | None,
) -> list[dict[str, Any]]:
    stmt = (
        select(Brief)
        .where(Brief.summary.ilike(f"%{q}%"))
        .order_by(Brief.generated_at.desc())
        .limit(limit)
    )
    if since:
        stmt = stmt.where(Brief.generated_at >= since)
    result = await db.execute(stmt)
    briefs = result.scalars().all()
    return [
        {
            "id": str(b.id),
            "title": _extract_title_from_brief(b.summary),
            "model_id": b.model,
            "created_at": b.generated_at.isoformat() if b.generated_at else None,
            "snippet": _snippet(b.summary, q),
        }
        for b in briefs
    ]


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------

ALL_TYPES = {"posts", "entities", "events", "briefs"}


@router.get("/search")
async def search_all(
    q: str = Query(..., min_length=1, max_length=500),
    types: Optional[str] = Query(default=None),  # comma-separated: posts,entities,events,briefs
    limit: int = Query(default=20, ge=1, le=100),
    hours: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Search across all data types simultaneously."""
    # Parse requested types
    if types:
        requested = {t.strip().lower() for t in types.split(",") if t.strip()}
        search_types = requested & ALL_TYPES
    else:
        search_types = ALL_TYPES

    # Time filter
    since: datetime | None = None
    if hours:
        since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)

    # Build coroutine map
    coro_map: dict[str, Any] = {}
    if "posts" in search_types:
        coro_map["posts"] = _search_posts(q, db, limit, since)
    if "entities" in search_types:
        coro_map["entities"] = _search_entities(q, db, limit, since)
    if "events" in search_types:
        coro_map["events"] = _search_events(q, db, limit, since)
    if "briefs" in search_types:
        coro_map["briefs"] = _search_briefs(q, db, limit, since)

    # Run all searches concurrently — if one fails, return others
    keys = list(coro_map.keys())
    settled = await asyncio.gather(*[coro_map[k] for k in keys], return_exceptions=True)

    results: dict[str, list] = {"posts": [], "entities": [], "events": [], "briefs": []}
    for key, outcome in zip(keys, settled):
        if isinstance(outcome, Exception):
            logger.warning("Search query for '%s' failed on type '%s': %s", q, key, outcome)
        else:
            results[key] = outcome

    counts = {k: len(v) for k, v in results.items()}
    total = sum(counts.values())

    return {
        "query": q,
        "results": results,
        "counts": counts,
        "total": total,
    }
