from __future__ import annotations
import asyncio
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db
from app.models import User, Source
from app.schemas.sources import SourceCreate, SourceUpdate, SourceResponse
from app.middleware.auth import get_current_user

router = APIRouter(prefix="/sources", tags=["sources"])


def _trigger_collector_restart(source_type: str, user_id: str) -> None:
    """Fire-and-forget: restart the relevant collector after a source change."""
    from app.collectors.orchestrator import orchestrator  # avoid circular import at module load

    if source_type in ("x", "telegram", "shodan", "discord"):
        asyncio.ensure_future(orchestrator.start_user_collectors(user_id))
    elif source_type == "rss":
        asyncio.ensure_future(orchestrator.start_rss())
    elif source_type == "reddit":
        asyncio.ensure_future(orchestrator.start_reddit())
    elif source_type == "youtube":
        asyncio.ensure_future(orchestrator.start_youtube())
    elif source_type == "bluesky":
        asyncio.ensure_future(orchestrator.start_bluesky())
    elif source_type == "mastodon":
        asyncio.ensure_future(orchestrator.start_mastodon())


@router.post("/", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    body: SourceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SourceResponse:
    source = Source(
        id=uuid.uuid4(),
        user_id=current_user.id,
        type=body.type,
        handle=body.handle,
        display_name=body.display_name,
        config_json=body.config_json,
        enabled=True,
        download_images=body.download_images,
        download_videos=body.download_videos,
        max_image_size_mb=body.max_image_size_mb,
        max_video_size_mb=body.max_video_size_mb,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    # Restart the relevant collector so it picks up the new source
    _trigger_collector_restart(body.type, str(current_user.id))

    return source


@router.get("/", response_model=List[SourceResponse])
async def list_sources(
    type: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[SourceResponse]:
    q = select(Source).where(Source.user_id == current_user.id)
    if type:
        q = q.where(Source.type == type)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SourceResponse:
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.user_id == current_user.id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.put("/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: uuid.UUID,
    body: SourceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SourceResponse:
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.user_id == current_user.id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    if body.display_name is not None:
        source.display_name = body.display_name
    if body.enabled is not None:
        source.enabled = body.enabled
    if body.config_json is not None:
        source.config_json = body.config_json
    if body.download_images is not None:
        source.download_images = body.download_images
    if body.download_videos is not None:
        source.download_videos = body.download_videos
    if body.max_image_size_mb is not None:
        source.max_image_size_mb = body.max_image_size_mb
    if body.max_video_size_mb is not None:
        source.max_video_size_mb = body.max_video_size_mb

    await db.commit()
    await db.refresh(source)

    # Restart the relevant collector so it picks up the updated source config
    _trigger_collector_restart(source.type, str(current_user.id))

    return source


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.user_id == current_user.id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    source_type = source.type  # capture before deletion
    await db.delete(source)
    await db.commit()

    # Restart the relevant collector so it stops polling the deleted source
    _trigger_collector_restart(source_type, str(current_user.id))
