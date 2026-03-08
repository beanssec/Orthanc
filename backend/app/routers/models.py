"""REST API for LLM model management and usage reporting."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db, AsyncSessionLocal
from app.middleware.auth import get_current_user
from app.services.model_router import model_router
from app.services.llm_usage_service import LLMUsageService

logger = logging.getLogger("orthanc.routers.models")

router = APIRouter(prefix="/models", tags=["models"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _usage_service() -> LLMUsageService:
    return LLMUsageService(AsyncSessionLocal)


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
):
    """Get current task-to-model assignments."""
    tasks = {}
    for task_const in [
        model_router.TASK_BRIEF,
        model_router.TASK_STANCE,
        model_router.TASK_TRANSLATE,
        model_router.TASK_EMBED,
        model_router.TASK_SUMMARISE,
        model_router.TASK_ENRICH,
        model_router.TASK_IMAGE,
        model_router.TASK_NARRATIVE_TITLE,
    ]:
        tasks[task_const] = {
            "task": task_const,
            "model": model_router.get_task_model(task_const),
            "overridden": task_const in model_router._task_overrides,
        }
    return {"tasks": tasks}


@router.post("/tasks/{task}")
async def set_task_model(
    task: str,
    body: SetTaskModelRequest,
    current_user=Depends(get_current_user),
):
    """Override which model handles a specific task."""
    valid_tasks = {
        model_router.TASK_BRIEF,
        model_router.TASK_STANCE,
        model_router.TASK_TRANSLATE,
        model_router.TASK_EMBED,
        model_router.TASK_SUMMARISE,
        model_router.TASK_ENRICH,
        model_router.TASK_IMAGE,
        model_router.TASK_NARRATIVE_TITLE,
    }
    if task not in valid_tasks:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task '{task}'. Valid tasks: {sorted(valid_tasks)}",
        )
    model_router.set_task_model(task, body.model_id)
    return {"task": task, "model_id": body.model_id, "status": "updated"}


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
