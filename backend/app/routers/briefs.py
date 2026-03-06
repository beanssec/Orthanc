"""AI intelligence briefs API router."""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.middleware.auth import get_current_user
from app.models import User
from app.models.brief import Brief
from app.services.brief_generator import brief_generator
from app.services.brief_scheduler import brief_scheduler
from app.services.ai_models import AI_MODELS
from app.services.collector_manager import collector_manager
from sqlalchemy import select, delete

logger = logging.getLogger("orthanc.routers.briefs")

router = APIRouter(prefix="/briefs", tags=["briefs"])


class BriefRequest(BaseModel):
    hours: int = 24
    model: Optional[str] = None
    topic: Optional[str] = None
    source_types: Optional[list[str]] = None
    custom_prompt: Optional[str] = None


class BriefScheduleRequest(BaseModel):
    enabled: bool = True
    model_id: str = "grok-3-mini"
    time_range_hours: int = 24
    schedule_hour_utc: int = 8


def brief_to_dict(b: Brief) -> dict:
    return {
        "id": str(b.id),
        "model": b.model,
        "model_name": b.model_name,
        "hours": b.hours,
        "post_count": b.post_count,
        "summary": b.summary,
        "cost_estimate": b.cost_estimate,
        "generated_at": b.generated_at.isoformat() if b.generated_at else None,
        # frontend compat aliases
        "time_range_hours": b.hours,
    }


@router.post("/generate")
async def generate_brief(
    body: BriefRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Generate an AI intelligence brief from recent posts."""
    hours = max(1, min(body.hours, 168))  # clamp to 1h–7d
    result = await brief_generator.generate_brief(
        str(current_user.id),
        hours=hours,
        model_id=body.model,
        topic=body.topic,
        source_types=body.source_types,
        custom_prompt=body.custom_prompt,
    )
    return result


@router.get("/models")
async def list_models(
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """List available AI models with descriptions and pricing.
    Marks which ones the user can use based on configured credentials."""
    user_id = str(current_user.id)

    # Check which credential providers the user has configured
    configured = set()
    for provider in ["x", "openrouter"]:
        keys = await collector_manager.get_keys(user_id, provider)
        if keys:
            configured.add(provider)

    models = []
    for m in AI_MODELS:
        models.append({
            "id": m["id"],
            "provider": m["provider"],
            "name": m["name"],
            "description": m["description"],
            "strengths": m["strengths"],
            "context_window": m["context_window"],
            "cost_per_1k_input": m["cost_per_1k_input"],
            "cost_per_1k_output": m["cost_per_1k_output"],
            "cost_estimate_per_brief": m["cost_estimate_per_brief"],
            "available": m["credential_provider"] in configured,
            "requires": m["credential_provider"],
        })
    return models


# ── Schedule endpoints (MUST be before /{brief_id} to avoid route conflict) ──


@router.get("/schedule")
async def get_brief_schedule(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Get the current user's brief schedule (or null if not set)."""
    user_id = str(current_user.id)
    schedule = brief_scheduler.get_schedule(user_id)
    return {"schedule": schedule}


@router.post("/schedule")
async def set_brief_schedule(
    body: BriefScheduleRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Set or update the user's daily brief schedule."""
    user_id = str(current_user.id)
    config = {
        "enabled": body.enabled,
        "model_id": body.model_id,
        "time_range_hours": body.time_range_hours,
        "schedule_hour_utc": body.schedule_hour_utc,
    }
    brief_scheduler.set_schedule(user_id, config)
    return {"ok": True, "schedule": brief_scheduler.get_schedule(user_id)}


@router.delete("/schedule")
async def delete_brief_schedule(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Remove the user's brief schedule."""
    brief_scheduler.remove_schedule(str(current_user.id))
    return {"ok": True}


# ── Brief CRUD ─────────────────────────────────────────────────────────────


@router.get("/")
async def list_briefs(
    current_user: User = Depends(get_current_user),
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """List saved briefs for the current user, newest first."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Brief)
            .where(Brief.user_id == current_user.id)
            .order_by(Brief.generated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        briefs = result.scalars().all()
    return [brief_to_dict(b) for b in briefs]


@router.get("/{brief_id}/pdf")
async def export_brief_pdf(
    brief_id: str,
    current_user: User = Depends(get_current_user),
) -> Response:
    """Export a saved brief as a formatted PDF intelligence report."""
    try:
        bid = uuid.UUID(brief_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid brief ID")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Brief).where(Brief.id == bid, Brief.user_id == current_user.id)
        )
        brief = result.scalar_one_or_none()

        if not brief:
            raise HTTPException(status_code=404, detail="Brief not found")

        # Try to fetch trending entities for the brief's time range
        entities: list[dict] = []
        source_stats: dict = {}
        try:
            since = brief.generated_at - timedelta(hours=brief.hours or 24)
            entity_result = await session.execute(
                text("""
                    SELECT e.name, e.type, count(em.id) as mentions
                    FROM entities e
                    JOIN entity_mentions em ON em.entity_id = e.id
                    JOIN posts p ON p.id = em.post_id
                    WHERE p.timestamp >= :since AND p.timestamp <= :until
                    GROUP BY e.name, e.type
                    ORDER BY mentions DESC
                    LIMIT 20
                """),
                {"since": since, "until": brief.generated_at},
            )
            entities = [
                {"name": r.name, "type": r.type, "mentions": r.mentions}
                for r in entity_result.fetchall()
            ]
        except Exception:
            entities = []

        try:
            since = brief.generated_at - timedelta(hours=brief.hours or 24)
            source_result = await session.execute(
                text("""
                    SELECT source_type, count(*) as cnt
                    FROM posts
                    WHERE timestamp >= :since AND timestamp <= :until
                    GROUP BY source_type
                """),
                {"since": since, "until": brief.generated_at},
            )
            source_stats = {r.source_type: r.cnt for r in source_result.fetchall()}
        except Exception:
            source_stats = {}

    brief_dict = {
        "summary": brief.summary,
        "model": brief.model,
        "model_name": brief.model_name,
        "hours": brief.hours,
        "post_count": brief.post_count,
        "cost_estimate": brief.cost_estimate,
        "generated_at": brief.generated_at.strftime("%Y-%m-%d %H:%M UTC"),
    }

    from app.services.pdf_report import pdf_report

    pdf_bytes = pdf_report.generate(brief_dict, entities or None, source_stats or None)
    filename = f"orthanc_brief_{brief.generated_at.strftime('%Y%m%d_%H%M')}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{brief_id}")
async def get_brief(
    brief_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Get a single saved brief by ID."""
    try:
        bid = uuid.UUID(brief_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid brief ID")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Brief).where(Brief.id == bid, Brief.user_id == current_user.id)
        )
        brief = result.scalar_one_or_none()

    if not brief:
        raise HTTPException(status_code=404, detail="Brief not found")
    return brief_to_dict(brief)


@router.delete("/{brief_id}")
async def delete_brief(
    brief_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Delete a saved brief."""
    try:
        bid = uuid.UUID(brief_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid brief ID")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Brief).where(Brief.id == bid, Brief.user_id == current_user.id)
        )
        brief = result.scalar_one_or_none()
        if not brief:
            raise HTTPException(status_code=404, detail="Brief not found")
        await session.delete(brief)
        await session.commit()

    return {"deleted": True, "id": brief_id}
