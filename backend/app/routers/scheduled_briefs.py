"""Scheduled Briefs API router — Sprint 31 Checkpoint 1.

Provides CRUD for durable ScheduledBrief records and read-only access to
run history.  All endpoints are scoped to the authenticated user.

Routes:
  POST   /scheduled-briefs/           Create a new scheduled brief
  GET    /scheduled-briefs/           List all scheduled briefs for user
  GET    /scheduled-briefs/{id}       Get a single scheduled brief
  PATCH  /scheduled-briefs/{id}       Update a scheduled brief
  DELETE /scheduled-briefs/{id}       Delete a scheduled brief
  GET    /scheduled-briefs/{id}/runs  List run history for a schedule
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, desc

from app.db import AsyncSessionLocal
from app.middleware.auth import get_current_user
from app.models import User
from app.models.scheduled_brief import ScheduledBrief, ScheduledBriefRun
from app.models.webhook_delivery import WebhookDelivery

logger = logging.getLogger("orthanc.routers.scheduled_briefs")

router = APIRouter(prefix="/scheduled-briefs", tags=["scheduled-briefs"])


# ── Pydantic schemas ─────────────────────────────────────────────────────────


class ScheduledBriefCreate(BaseModel):
    name: str = Field(default="Daily Brief", max_length=255)
    enabled: bool = True
    schedule_hour_utc: Optional[int] = Field(default=8, ge=0, le=23)
    cron_expr: Optional[str] = Field(default=None, max_length=100)
    model_id: str = Field(default="grok-3-mini", max_length=128)
    time_window_hours: int = Field(default=24, ge=1, le=168)
    topic_filter: Optional[str] = None
    source_filters: Optional[list[str]] = None
    delivery_method: str = Field(default="internal", max_length=64)


class ScheduledBriefUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    enabled: Optional[bool] = None
    schedule_hour_utc: Optional[int] = Field(default=None, ge=0, le=23)
    cron_expr: Optional[str] = Field(default=None, max_length=100)
    model_id: Optional[str] = Field(default=None, max_length=128)
    time_window_hours: Optional[int] = Field(default=None, ge=1, le=168)
    topic_filter: Optional[str] = None
    source_filters: Optional[list[str]] = None
    delivery_method: Optional[str] = Field(default=None, max_length=64)


# ── Serializers ──────────────────────────────────────────────────────────────


def schedule_to_dict(s: ScheduledBrief) -> dict:
    return {
        "id": str(s.id),
        "user_id": str(s.user_id),
        "name": s.name,
        "enabled": s.enabled,
        "schedule_hour_utc": s.schedule_hour_utc,
        "cron_expr": s.cron_expr,
        "model_id": s.model_id,
        "time_window_hours": s.time_window_hours,
        "topic_filter": s.topic_filter,
        "source_filters": s.source_filters,
        "delivery_method": s.delivery_method,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
        "last_status": s.last_status,
        "last_error": s.last_error,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def run_to_dict(r: ScheduledBriefRun) -> dict:
    return {
        "id": str(r.id),
        "schedule_id": str(r.schedule_id),
        "user_id": str(r.user_id),
        "status": r.status,
        "error_message": r.error_message,
        "brief_id": str(r.brief_id) if r.brief_id else None,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _get_schedule_or_404(
    schedule_id: str,
    current_user: User,
) -> ScheduledBrief:
    try:
        sid = uuid.UUID(schedule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid schedule ID")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledBrief).where(
                ScheduledBrief.id == sid,
                ScheduledBrief.user_id == current_user.id,
            )
        )
        sched = result.scalar_one_or_none()

    if not sched:
        raise HTTPException(status_code=404, detail="Scheduled brief not found")
    return sched


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/", status_code=201)
async def create_scheduled_brief(
    body: ScheduledBriefCreate,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Create a new durable scheduled brief for the current user."""
    sched = ScheduledBrief(
        user_id=current_user.id,
        name=body.name,
        enabled=body.enabled,
        schedule_hour_utc=body.schedule_hour_utc,
        cron_expr=body.cron_expr,
        model_id=body.model_id,
        time_window_hours=body.time_window_hours,
        topic_filter=body.topic_filter,
        source_filters=body.source_filters,
        delivery_method=body.delivery_method,
    )
    async with AsyncSessionLocal() as db:
        db.add(sched)
        await db.commit()
        await db.refresh(sched)

    logger.info(
        "Created scheduled brief id=%s user=%s name=%r",
        sched.id,
        current_user.id,
        sched.name,
    )
    return schedule_to_dict(sched)


@router.get("/")
async def list_scheduled_briefs(
    current_user: User = Depends(get_current_user),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    """List all scheduled briefs for the current user.

    Returns: {items, total, limit, offset}
    """
    async with AsyncSessionLocal() as db:
        base_q = (
            select(ScheduledBrief)
            .where(ScheduledBrief.user_id == current_user.id)
        )
        count_result = await db.execute(select(func.count()).select_from(base_q.subquery()))
        total = count_result.scalar() or 0

        result = await db.execute(
            base_q.order_by(ScheduledBrief.created_at.desc()).limit(limit).offset(offset)
        )
        schedules = result.scalars().all()
    return {
        "items": [schedule_to_dict(s) for s in schedules],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{schedule_id}")
async def get_scheduled_brief(
    schedule_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Get a single scheduled brief by ID."""
    sched = await _get_schedule_or_404(schedule_id, current_user)
    return schedule_to_dict(sched)


@router.patch("/{schedule_id}")
async def update_scheduled_brief(
    schedule_id: str,
    body: ScheduledBriefUpdate,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Partially update a scheduled brief."""
    try:
        sid = uuid.UUID(schedule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid schedule ID")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledBrief).where(
                ScheduledBrief.id == sid,
                ScheduledBrief.user_id == current_user.id,
            )
        )
        sched = result.scalar_one_or_none()
        if not sched:
            raise HTTPException(status_code=404, detail="Scheduled brief not found")

        # Apply only the fields that were explicitly provided
        patch = body.model_dump(exclude_unset=True)
        for field, value in patch.items():
            setattr(sched, field, value)
        sched.updated_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(sched)

    logger.info(
        "Updated scheduled brief id=%s user=%s fields=%s",
        sched.id,
        current_user.id,
        list(patch.keys()),
    )
    return schedule_to_dict(sched)


@router.delete("/{schedule_id}")
async def delete_scheduled_brief(
    schedule_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Delete a scheduled brief and its run history."""
    try:
        sid = uuid.UUID(schedule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid schedule ID")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledBrief).where(
                ScheduledBrief.id == sid,
                ScheduledBrief.user_id == current_user.id,
            )
        )
        sched = result.scalar_one_or_none()
        if not sched:
            raise HTTPException(status_code=404, detail="Scheduled brief not found")
        await db.delete(sched)
        await db.commit()

    logger.info(
        "Deleted scheduled brief id=%s user=%s",
        sid,
        current_user.id,
    )
    return {"deleted": True, "id": schedule_id}


@router.get("/{schedule_id}/runs")
async def list_schedule_runs(
    schedule_id: str,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """List run history for a specific scheduled brief."""
    try:
        sid = uuid.UUID(schedule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid schedule ID")

    # Verify ownership
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledBrief).where(
                ScheduledBrief.id == sid,
                ScheduledBrief.user_id == current_user.id,
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Scheduled brief not found")

        runs_result = await db.execute(
            select(ScheduledBriefRun)
            .where(ScheduledBriefRun.schedule_id == sid)
            .order_by(desc(ScheduledBriefRun.started_at))
            .limit(limit)
            .offset(offset)
        )
        runs = runs_result.scalars().all()

    return [run_to_dict(r) for r in runs]


# ── TASK-88: Webhook delivery history ────────────────────────────────────────


def _delivery_to_dict(d: WebhookDelivery) -> dict:
    return {
        "id": str(d.id),
        "scheduled_brief_id": str(d.scheduled_brief_id),
        "url": d.url,
        "payload_hash": d.payload_hash,
        "status_code": d.status_code,
        "response_body": d.response_body,
        "success": d.success,
        "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
        "error_message": d.error_message,
    }


@router.get("/{schedule_id}/deliveries")
async def list_webhook_deliveries(
    schedule_id: str,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """List webhook delivery history for a specific scheduled brief."""
    try:
        sid = uuid.UUID(schedule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid schedule ID")

    async with AsyncSessionLocal() as db:
        # Verify ownership
        result = await db.execute(
            select(ScheduledBrief).where(
                ScheduledBrief.id == sid,
                ScheduledBrief.user_id == current_user.id,
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Scheduled brief not found")

        deliveries_result = await db.execute(
            select(WebhookDelivery)
            .where(WebhookDelivery.scheduled_brief_id == sid)
            .order_by(desc(WebhookDelivery.delivered_at))
            .limit(limit)
            .offset(offset)
        )
        deliveries = deliveries_result.scalars().all()

    return [_delivery_to_dict(d) for d in deliveries]
