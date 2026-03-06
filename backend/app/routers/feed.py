from __future__ import annotations
import asyncio
import logging
import uuid
from datetime import datetime
from typing import List, Optional, Set
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.db import get_db, AsyncSessionLocal
from app.models import User, Post, Event
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


@router.post("/translate")
async def translate_text(
    body: TranslateRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Translate text using the user's configured AI credentials."""
    from app.services.translator import translator
    result = await translator.translate(body.text, body.target_lang, str(current_user.id))
    return result


@router.get("/feed/", response_model=List[PostResponse])
async def list_feed(
    source_types: Optional[List[str]] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[PostResponse]:
    filters = []
    if source_types:
        filters.append(Post.source_type.in_(source_types))
    if keyword:
        filters.append(Post.content.ilike(f"%{keyword}%"))
    if date_from:
        filters.append(Post.timestamp >= date_from)
    if date_to:
        filters.append(Post.timestamp <= date_to)

    q = select(Post).order_by(Post.timestamp.desc())
    if filters:
        q = q.where(and_(*filters))
    q = q.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(q)
    return result.scalars().all()


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
