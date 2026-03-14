"""REST API for LLM model management and usage reporting."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db, AsyncSessionLocal
from app.middleware.auth import get_current_user
from app.models.task_model_override import TaskModelOverride
from app.services.model_router import model_router
from app.services.llm_usage_service import LLMUsageService

logger = logging.getLogger("orthanc.routers.models")

router = APIRouter(prefix="/models", tags=["models"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _usage_service() -> LLMUsageService:
    return LLMUsageService(AsyncSessionLocal)


_VALID_TASKS = frozenset([
    model_router.TASK_BRIEF,
    model_router.TASK_STANCE,
    model_router.TASK_TRANSLATE,
    model_router.TASK_EMBED,
    model_router.TASK_SUMMARISE,
    model_router.TASK_ENRICH,
    model_router.TASK_IMAGE,
    model_router.TASK_NARRATIVE_TITLE,
    model_router.TASK_NARRATIVE_LABEL,
    model_router.TASK_NARRATIVE_CONFIRMATION,
    model_router.TASK_TRACKED_NARRATIVE_MATCH,
    model_router.TASK_ENTITY_RESOLUTION_ASSIST,
])


async def _load_overrides_for_user(user_id: uuid.UUID, db: AsyncSession) -> dict[str, str]:
    """Fetch all persisted task→model overrides for a user from DB."""
    result = await db.execute(
        select(TaskModelOverride).where(TaskModelOverride.user_id == user_id)
    )
    rows = result.scalars().all()
    return {row.task: row.model_id for row in rows}


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class SetTaskModelRequest(BaseModel):
    model_id: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/")
async def list_models(
    current_user=Depends(get_current_user),
):
    """List all available models across all configured providers."""
    try:
        models = await model_router.list_all_models()
    except Exception as exc:
        logger.error("list_all_models error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"models": models, "count": len(models)}


@router.get("/tasks")
async def list_task_assignments(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current task-to-model assignments (reads persisted DB overrides)."""
    user_id: uuid.UUID = current_user.id

    # Load persisted overrides from DB for this user
    db_overrides = await _load_overrides_for_user(user_id, db)

    tasks = {}
    for task_const in _VALID_TASKS:
        # DB override takes precedence over in-memory, which takes precedence over defaults
        if task_const in db_overrides:
            model = db_overrides[task_const]
            overridden = True
        else:
            model = model_router.get_task_model(task_const)
            overridden = task_const in model_router._task_overrides

        tasks[task_const] = {
            "task": task_const,
            "model": model,
            "overridden": overridden,
        }
    return {"tasks": tasks}


@router.post("/tasks/{task}")
async def set_task_model(
    task: str,
    body: SetTaskModelRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Override which model handles a specific task. Persisted to DB."""
    if task not in _VALID_TASKS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task '{task}'. Valid tasks: {sorted(_VALID_TASKS)}",
        )

    user_id: uuid.UUID = current_user.id

    # Upsert into DB (insert or update on conflict)
    stmt = pg_insert(TaskModelOverride).values(
        user_id=user_id,
        task=task,
        model_id=body.model_id,
        updated_at=datetime.utcnow(),
    ).on_conflict_do_update(
        constraint="uq_task_model_override_user_task",
        set_={
            "model_id": body.model_id,
            "updated_at": datetime.utcnow(),
        },
    )
    await db.execute(stmt)
    await db.commit()

    # Also update the in-memory singleton so current requests use it immediately
    model_router.set_task_model(task, body.model_id)

    logger.info(
        "Task model override persisted: user=%s task=%s model=%s",
        user_id, task, body.model_id,
    )
    return {"task": task, "model_id": body.model_id, "status": "updated"}


@router.delete("/tasks/{task}")
async def reset_task_model(
    task: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a persisted task override, reverting to default."""
    if task not in _VALID_TASKS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task '{task}'. Valid tasks: {sorted(_VALID_TASKS)}",
        )

    user_id: uuid.UUID = current_user.id

    await db.execute(
        delete(TaskModelOverride).where(
            TaskModelOverride.user_id == user_id,
            TaskModelOverride.task == task,
        )
    )
    await db.commit()

    # Remove from in-memory overrides too (reverts to default)
    model_router._task_overrides.pop(task, None)

    default_model = model_router.DEFAULT_TASK_MODELS.get(task, "grok-3-mini")
    logger.info(
        "Task model override removed: user=%s task=%s (reverts to %s)",
        user_id, task, default_model,
    )
    return {"task": task, "model_id": default_model, "status": "reset_to_default"}


@router.get("/providers")
async def list_providers(
    current_user=Depends(get_current_user),
):
    """List configured providers and their connection status."""
    providers = []
    for name, provider in model_router._providers.items():
        providers.append({
            "name": name,
            "type": type(provider).__name__,
            "base_url": getattr(provider, "base_url", None),
        })
    return {"providers": providers, "count": len(providers)}


@router.post("/providers/{provider}/test")
async def test_provider(
    provider: str,
    current_user=Depends(get_current_user),
):
    """Test connectivity to a provider. Returns {"status": "ok"} or error."""
    if provider not in model_router._providers:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider}' not registered. "
                   f"Registered: {list(model_router._providers.keys())}",
        )
    p = model_router._providers[provider]
    try:
        models = await p.list_models()
        return {
            "status": "ok",
            "provider": provider,
            "models_available": len(models),
        }
    except Exception as exc:
        logger.warning("Provider test failed for %s: %s", provider, exc)
        raise HTTPException(
            status_code=503,
            detail=f"Provider '{provider}' connectivity test failed: {exc}",
        )


@router.get("/usage")
async def get_usage(
    hours: int = Query(default=24, ge=1, le=8760),
    current_user=Depends(get_current_user),
):
    """Get LLM usage summary for the past N hours."""
    svc = _usage_service()
    try:
        summary = await svc.get_usage_summary(hours=hours)
    except Exception as exc:
        logger.error("get_usage_summary error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return summary


@router.get("/usage/daily")
async def get_daily_usage(
    days: int = Query(default=7, ge=1, le=365),
    current_user=Depends(get_current_user),
):
    """Get daily LLM usage breakdown."""
    svc = _usage_service()
    try:
        daily = await svc.get_daily_usage(days=days)
    except Exception as exc:
        logger.error("get_daily_usage error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"days": days, "data": daily}
