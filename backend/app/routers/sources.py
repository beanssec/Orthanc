from __future__ import annotations
import asyncio
import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from app.db import get_db
from app.models import User, Source
from app.models.source_reliability import SourceReliability
from app.schemas.sources import SourceCreate, SourceUpdate, SourceResponse, SourceReliabilityInfo, SourceReliabilityOverride
from app.middleware.auth import get_current_user
import app.services.source_reliability_service as reliability_svc

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


def _to_response(source: Source) -> SourceResponse:
    """Map ORM Source (with optional joined reliability) → SourceResponse."""
    rel_info: Optional[SourceReliabilityInfo] = None
    if source.reliability is not None:
        rel_info = SourceReliabilityInfo.model_validate(source.reliability)

    return SourceResponse(
        id=source.id,
        type=source.type,
        handle=source.handle,
        display_name=source.display_name or source.handle,
        enabled=source.enabled,
        last_polled=source.last_polled,
        config_json=source.config_json or {},
        download_images=source.download_images,
        download_videos=source.download_videos,
        max_image_size_mb=source.max_image_size_mb,
        max_video_size_mb=source.max_video_size_mb,
        reliability=rel_info,
        # Sprint 32 C3 classification fields
        source_class=getattr(source, "source_class", None),
        default_reliability_prior=getattr(source, "default_reliability_prior", None),
        ecosystem=getattr(source, "ecosystem", None),
        risk_note=getattr(source, "risk_note", None),
    )


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

    # Seed an initial reliability row for the new source
    try:
        await reliability_svc.compute_and_upsert(source, db)
        await db.commit()
        await db.refresh(source, ["reliability"])
    except Exception:
        pass  # Non-blocking — reliability is best-effort

    # Restart the relevant collector so it picks up the new source
    _trigger_collector_restart(body.type, str(current_user.id))

    return _to_response(source)


@router.get("/", response_model=List[SourceResponse])
async def list_sources(
    type: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[SourceResponse]:
    q = (
        select(Source)
        .options(selectinload(Source.reliability))
        .where(Source.user_id == current_user.id)
    )
    if type:
        q = q.where(Source.type == type)
    result = await db.execute(q)
    return [_to_response(s) for s in result.scalars().all()]


@router.get("/health")
async def source_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Per-source health status: last_polled, error_count, status."""
    result = await db.execute(
        select(Source)
        .options(selectinload(Source.reliability))
        .where(Source.user_id == current_user.id)
        .order_by(Source.handle)
    )
    sources = result.scalars().all()

    health = []
    for s in sources:
        status_str = "active"
        if not s.enabled:
            status_str = "disabled"
        elif s.last_polled is None:
            status_str = "never_polled"
        elif (datetime.utcnow() - s.last_polled.replace(tzinfo=None)).total_seconds() > 3600:
            status_str = "stale"

        rel = s.reliability
        health.append({
            "id": str(s.id),
            "name": s.display_name or s.handle,
            "type": s.type,
            "enabled": s.enabled,
            "status": status_str,
            "last_polled": s.last_polled.isoformat() if s.last_polled else None,
            "reliability_score": rel.reliability_score if rel else None,
            "confidence_band": rel.confidence_band if rel else None,
        })

    return {"sources": health, "total": len(health)}


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SourceResponse:
    result = await db.execute(
        select(Source)
        .options(selectinload(Source.reliability))
        .where(Source.id == source_id, Source.user_id == current_user.id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return _to_response(source)


@router.put("/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: uuid.UUID,
    body: SourceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SourceResponse:
    result = await db.execute(
        select(Source)
        .options(selectinload(Source.reliability))
        .where(Source.id == source_id, Source.user_id == current_user.id)
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
    await db.refresh(source, ["reliability"])

    # Restart the relevant collector so it picks up the updated source config
    _trigger_collector_restart(source.type, str(current_user.id))

    return _to_response(source)


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


# ── Sprint 29 C1: Reliability endpoints ─────────────────────────────────────

@router.post("/{source_id}/reliability/score", response_model=SourceReliabilityInfo)
async def score_source_reliability(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SourceReliabilityInfo:
    """Trigger reliability scoring for a single source.

    Idempotent — safe to call repeatedly.  Returns the updated reliability row.
    """
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.user_id == current_user.id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    rel = await reliability_svc.compute_and_upsert(source, db)
    await db.commit()
    return SourceReliabilityInfo.model_validate(rel)


@router.patch("/{source_id}/reliability/override", response_model=SourceReliabilityInfo)
async def set_analyst_override(
    source_id: uuid.UUID,
    body: SourceReliabilityOverride,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SourceReliabilityInfo:
    """Set or clear analyst override score and/or note for a source.

    Upserts a reliability row if one doesn't exist yet.
    Pass null for analyst_override to clear the override.
    """
    # Verify ownership
    source_result = await db.execute(
        select(Source)
        .options(selectinload(Source.reliability))
        .where(Source.id == source_id, Source.user_id == current_user.id)
    )
    source = source_result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    # Upsert reliability row
    rel_result = await db.execute(
        select(SourceReliability).where(SourceReliability.source_id == source_id)
    )
    rel = rel_result.scalar_one_or_none()
    if rel is None:
        rel = SourceReliability(source_id=source_id)
        db.add(rel)

    # Apply override fields — explicit None from body means "clear"
    if "analyst_override" in body.model_fields_set or body.analyst_override is not None:
        rel.analyst_override = body.analyst_override
    if "analyst_note" in body.model_fields_set or body.analyst_note is not None:
        rel.analyst_note = body.analyst_note

    await db.commit()
    await db.refresh(rel)
    return SourceReliabilityInfo.model_validate(rel)


@router.post("/reliability/score-all")
async def score_all_reliability(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Bulk-score reliability for all sources owned by the current user.

    Returns a summary count.  This is a best-effort operation — errors per
    source are swallowed and logged so a single bad source doesn't abort the run.
    """
    result = await db.execute(
        select(Source).where(Source.user_id == current_user.id)
    )
    sources = result.scalars().all()

    processed = 0
    errors = 0
    for source in sources:
        try:
            await reliability_svc.compute_and_upsert(source, db)
            processed += 1
        except Exception as exc:
            errors += 1

    await db.commit()
    return {"processed": processed, "errors": errors}
