"""Webhook ingestion router — allows external systems to push posts into Orthanc."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user
from app.models import Post, User
from app.models.entity import Entity, EntityMention
from app.models.event import Event
from app.routers.feed import broadcast_post
from app.services.entity_extractor import entity_extractor
from app.services.geo_extractor import geo_extractor

logger = logging.getLogger("orthanc.routers.webhook")

router = APIRouter(prefix="/webhook", tags=["webhook"])


class WebhookIngestRequest(BaseModel):
    source_name: str
    content: str
    author: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class WebhookIngestResponse(BaseModel):
    id: str
    source_type: str
    source_id: str
    author: Optional[str]
    content: Optional[str]
    timestamp: Optional[str]
    ingested_at: Optional[str]


@router.post("/ingest", response_model=WebhookIngestResponse, status_code=201)
async def ingest_webhook(
    body: WebhookIngestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookIngestResponse:
    """Ingest a post from an external source (n8n, Zapier, curl, etc.)."""
    # Parse timestamp
    ts: datetime
    if body.timestamp:
        try:
            ts = datetime.fromisoformat(body.timestamp.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid timestamp format: {body.timestamp!r}")
    else:
        ts = datetime.now(tz=timezone.utc)

    # Build a unique source_id from content hash + timestamp
    source_id = f"webhook_{body.source_name}_{uuid.uuid4().hex[:12]}"

    post = Post(
        source_type="webhook",
        source_id=source_id,
        author=body.author or body.source_name,
        content=body.content,
        raw_json={
            "source_name": body.source_name,
            "metadata": body.metadata or {},
            "ingested_by": str(current_user.id),
        },
        timestamp=ts,
    )
    db.add(post)
    await db.flush()

    # Broadcast live
    await broadcast_post({
        "id": str(post.id),
        "source_type": post.source_type,
        "source_id": post.source_id,
        "author": post.author,
        "content": post.content,
        "timestamp": post.timestamp.isoformat() if post.timestamp else None,
        "ingested_at": post.ingested_at.isoformat() if post.ingested_at else None,
        "event": None,
    })

    # Geo extraction
    try:
        geo_events = await geo_extractor.process_post(str(post.id), body.content)
        for evt in geo_events:
            event = Event(
                post_id=post.id,
                lat=evt["lat"],
                lng=evt["lng"],
                place_name=evt["place_name"],
                confidence=evt["confidence"],
            )
            db.add(event)
    except Exception as geo_exc:
        logger.warning("Geo extraction failed for webhook post %s: %s", post.id, geo_exc)

    # Entity extraction
    try:
        extracted = entity_extractor.extract_entities(body.content)
        for ent in extracted:
            canonical = entity_extractor.canonical_name(ent["name"])
            existing_ent = await db.execute(
                select(Entity).where(
                    Entity.canonical_name == canonical,
                    Entity.type == ent["type"],
                )
            )
            entity_obj = existing_ent.scalar_one_or_none()
            if entity_obj:
                entity_obj.mention_count += 1
                entity_obj.last_seen = datetime.now(tz=timezone.utc)
            else:
                entity_obj = Entity(
                    name=ent["name"],
                    type=ent["type"],
                    canonical_name=canonical,
                    mention_count=1,
                )
                db.add(entity_obj)
                await db.flush()
            mention = EntityMention(
                entity_id=entity_obj.id,
                post_id=post.id,
                context_snippet=ent["context_snippet"],
            )
            db.add(mention)
    except Exception as ent_exc:
        logger.warning("Entity extraction failed for webhook post %s: %s", post.id, ent_exc)

    await db.commit()
    await db.refresh(post)

    logger.info("Webhook ingest: post %s from source %r", post.id, body.source_name)

    return WebhookIngestResponse(
        id=str(post.id),
        source_type=post.source_type,
        source_id=post.source_id,
        author=post.author,
        content=post.content,
        timestamp=post.timestamp.isoformat() if post.timestamp else None,
        ingested_at=post.ingested_at.isoformat() if post.ingested_at else None,
    )
