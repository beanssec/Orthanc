from __future__ import annotations
import asyncio
import logging
import uuid
from datetime import datetime
from typing import List, Optional, Set
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.db import get_db, AsyncSessionLocal
from app.models import User, Post, Event, Entity, EntityMention
from app.schemas.feed import PostResponse, FeedFilter
from app.middleware.auth import get_current_user

logger = logging.getLogger("orthanc.feed")

router = APIRouter(tags=["feed"])

# Simple in-memory pub/sub for WebSocket broadcasting
_ws_subscribers: Set[asyncio.Queue] = set()


async def _evaluate_post_alerts(post_data: dict) -> None:
    """Fire-and-forget: evaluate alert rules for a new post."""
    try:
        from app.services import correlation_engine
        async with AsyncSessionLocal() as db:
            await correlation_engine.evaluate_post(post_data, db)
    except Exception:
        logger.exception("Alert evaluation failed for post %s", post_data.get("id"))


async def broadcast_post(post_data: dict) -> None:
    """Broadcast a new post to all WebSocket subscribers + evaluate alert rules."""
    dead = set()
    for q in _ws_subscribers:
        try:
            q.put_nowait(post_data)
        except asyncio.QueueFull:
            dead.add(q)
    _ws_subscribers.difference_update(dead)

    # Alert evaluation — fire-and-forget, never block broadcast
    asyncio.create_task(_evaluate_post_alerts(post_data))


def _post_to_dict(post: Post) -> dict:
    event = None
    if post.events:
        e = post.events[0]
        event = {
            "id": str(e.id),
            "lat": e.lat,
            "lng": e.lng,
            "place_name": e.place_name,
            "confidence": e.confidence,
        }
    return {
        "id": str(post.id),
        "source_type": post.source_type,
        "source_id": str(post.source_id),
        "author": post.author,
        "content": post.content,
        "timestamp": post.timestamp.isoformat(),
        "ingested_at": post.ingested_at.isoformat(),
        "event": event,
    }


class TranslateRequest(BaseModel):
    text: str
    target_lang: str = "en"


# ── Paginated response models ──────────────────────────────────────────────────

class PaginatedFeedResponse(BaseModel):
    items: List[PostResponse]
    total: int
    page: int
    page_size: int


class FacetItem(BaseModel):
    value: str
    count: int


class FacetsResponse(BaseModel):
    source_types: List[FacetItem]
    authors: List[FacetItem]
    media_types: List[FacetItem]
    has_geo_count: int
    total_posts: int


# ── Filter builder ─────────────────────────────────────────────────────────────

def _build_filters(
    source_types: Optional[List[str]] = None,
    keyword: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    author: Optional[str] = None,
    has_media: Optional[bool] = None,
    media_type: Optional[str] = None,
    has_geo: Optional[bool] = None,
    location: Optional[str] = None,
    entity: Optional[str] = None,
    min_authenticity: Optional[float] = None,
    max_authenticity: Optional[float] = None,
) -> list:
    filters = []

    if source_types:
        filters.append(Post.source_type.in_(source_types))
    if keyword:
        filters.append(Post.content.ilike(f"%{keyword}%"))
    if date_from:
        filters.append(Post.timestamp >= date_from)
    if date_to:
        filters.append(Post.timestamp <= date_to)
    if author:
        filters.append(Post.author.ilike(f"%{author}%"))
    if has_media is True:
        filters.append(Post.media_type.is_not(None))
    elif has_media is False:
        filters.append(Post.media_type.is_(None))
    if media_type:
        filters.append(Post.media_type == media_type)
    if has_geo is True:
        geo_exists = select(Event.id).where(Event.post_id == Post.id).exists()
        filters.append(geo_exists)
    elif has_geo is False:
        geo_exists = select(Event.id).where(Event.post_id == Post.id).exists()
        filters.append(~geo_exists)
    if location:
        loc_exists = (
            select(Event.id)
            .where(Event.post_id == Post.id, Event.place_name.ilike(f"%{location}%"))
            .exists()
        )
        filters.append(loc_exists)
    if entity:
        entity_exists = (
            select(EntityMention.id)
            .join(Entity, Entity.id == EntityMention.entity_id)
            .where(
                EntityMention.post_id == Post.id,
                Entity.name.ilike(f"%{entity}%"),
            )
            .exists()
        )
        filters.append(entity_exists)
    if min_authenticity is not None:
        filters.append(Post.authenticity_score >= min_authenticity)
    if max_authenticity is not None:
        filters.append(Post.authenticity_score <= max_authenticity)

    return filters


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/translate")
async def translate_text(
    body: TranslateRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Translate text using the user's configured AI credentials."""
    from app.services.translator import translator
    result = await translator.translate(body.text, body.target_lang, str(current_user.id))
    return result


@router.get("/feed/facets", response_model=FacetsResponse)
async def feed_facets(
    source_types: Optional[List[str]] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    author: Optional[str] = Query(default=None),
    has_media: Optional[bool] = Query(default=None),
    has_geo: Optional[bool] = Query(default=None),
    location: Optional[str] = Query(default=None),
    entity: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FacetsResponse:
    # Base filters (all active filters)
    base_filters = _build_filters(
        source_types, keyword, date_from, date_to,
        author, has_media, None, has_geo, location, entity,
    )

    # ── source_types facet (exclude source_types filter so all types show up) ──
    st_filters = _build_filters(
        None, keyword, date_from, date_to,
        author, has_media, None, has_geo, location, entity,
    )
    st_q = (
        select(Post.source_type, func.count(Post.id).label("cnt"))
        .group_by(Post.source_type)
        .order_by(func.count(Post.id).desc())
    )
    if st_filters:
        st_q = st_q.where(and_(*st_filters))
    st_result = await db.execute(st_q)
    source_type_facets = [
        FacetItem(value=row[0], count=row[1]) for row in st_result if row[0]
    ]

    # ── authors facet (exclude author filter, top 20) ──
    auth_filters = _build_filters(
        source_types, keyword, date_from, date_to,
        None, has_media, None, has_geo, location, entity,
    )
    auth_q = (
        select(Post.author, func.count(Post.id).label("cnt"))
        .where(Post.author.is_not(None))
        .group_by(Post.author)
        .order_by(func.count(Post.id).desc())
        .limit(20)
    )
    if auth_filters:
        auth_q = auth_q.where(and_(*auth_filters))
    auth_result = await db.execute(auth_q)
    author_facets = [
        FacetItem(value=row[0], count=row[1]) for row in auth_result if row[0]
    ]

    # ── media_types facet (apply base filters) ──
    media_q = (
        select(Post.media_type, func.count(Post.id).label("cnt"))
        .where(Post.media_type.is_not(None))
        .group_by(Post.media_type)
        .order_by(func.count(Post.id).desc())
    )
    if base_filters:
        media_q = media_q.where(and_(*base_filters))
    media_result = await db.execute(media_q)
    media_type_facets = [
        FacetItem(value=row[0], count=row[1]) for row in media_result if row[0]
    ]

    # ── has_geo_count ──
    geo_subq = select(Event.id).where(Event.post_id == Post.id).exists()
    geo_q = select(func.count(Post.id)).where(geo_subq)
    if base_filters:
        geo_q = geo_q.where(and_(*base_filters))
    geo_result = await db.execute(geo_q)
    has_geo_count = geo_result.scalar() or 0

    # ── total_posts ──
    total_q = select(func.count(Post.id))
    if base_filters:
        total_q = total_q.where(and_(*base_filters))
    total_result = await db.execute(total_q)
    total_posts = total_result.scalar() or 0

    return FacetsResponse(
        source_types=source_type_facets,
        authors=author_facets,
        media_types=media_type_facets,
        has_geo_count=has_geo_count,
        total_posts=total_posts,
    )


@router.get("/feed/", response_model=PaginatedFeedResponse)
async def list_feed(
    source_types: Optional[List[str]] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    author: Optional[str] = Query(default=None),
    has_media: Optional[bool] = Query(default=None),
    media_type: Optional[str] = Query(default=None),
    has_geo: Optional[bool] = Query(default=None),
    location: Optional[str] = Query(default=None),
    entity: Optional[str] = Query(default=None),
    min_authenticity: Optional[float] = Query(default=None),
    max_authenticity: Optional[float] = Query(default=None),
    sort: Optional[str] = Query(default="newest"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedFeedResponse:
    filters = _build_filters(
        source_types, keyword, date_from, date_to,
        author, has_media, media_type, has_geo, location, entity,
        min_authenticity, max_authenticity,
    )

    # Total count (same filters, no pagination)
    count_q = select(func.count(Post.id))
    if filters:
        count_q = count_q.where(and_(*filters))
    count_result = await db.execute(count_q)
    total = count_result.scalar() or 0

    # Data query
    order_col = Post.timestamp.asc() if sort == "oldest" else Post.timestamp.desc()
    q = select(Post).order_by(order_col)
    if filters:
        q = q.where(and_(*filters))
    q = q.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(q)
    posts = result.scalars().all()

    # Convert ORM objects to PostResponse (from_attributes handles it)
    items = [PostResponse.model_validate(post) for post in posts]

    return PaginatedFeedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/feed/{post_id}", response_model=PostResponse)
async def get_post(
    post_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PostResponse:
    result = await db.execute(select(Post).where(Post.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.websocket("/ws/feed")
async def ws_feed(websocket: WebSocket) -> None:
    from app.db import AsyncSessionLocal
    await websocket.accept()

    # Send last 50 posts on connect using a manual session
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Post).order_by(Post.timestamp.desc()).limit(50)
        )
        posts = result.scalars().all()
        post_dicts = []
        for post in reversed(posts):
            post_dicts.append({
                "id": str(post.id),
                "source_type": post.source_type,
                "source_id": str(post.source_id),
                "author": post.author,
                "content": post.content,
                "timestamp": post.timestamp.isoformat() if post.timestamp else None,
                "ingested_at": post.ingested_at.isoformat() if post.ingested_at else None,
                "event": None,
            })
    for pd in post_dicts:
        await websocket.send_json(pd)

    # Subscribe to new posts
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _ws_subscribers.add(queue)

    try:
        while True:
            try:
                post_data = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(post_data)
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    finally:
        _ws_subscribers.discard(queue)
