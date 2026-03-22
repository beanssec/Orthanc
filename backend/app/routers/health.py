"""Health check endpoints — no auth required (except /health/diagnostics)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from app.middleware.auth import get_current_user

_start_time = time.time()

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """Full health check — DB, collectors, services."""
    from app.db import AsyncSessionLocal
    from sqlalchemy import text

    checks: dict = {}

    # DB connectivity
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"

    # Post count (quick table sanity check)
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT count(*) FROM posts"))
            count = result.scalar()
        checks["posts"] = count
    except Exception:
        checks["posts"] = "error"

    checks["uptime_seconds"] = int(time.time() - _start_time)

    status = "healthy" if checks.get("database") == "ok" else "degraded"
    return {"status": status, "checks": checks}


@router.get("/health/ready")
async def readiness():
    """Simple readiness probe for Docker / load balancers."""
    from app.db import AsyncSessionLocal
    from sqlalchemy import text

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return {"ready": True}
    except Exception:
        return JSONResponse(status_code=503, content={"ready": False})


@router.get("/health/dependencies")
async def dependency_health() -> dict[str, Any]:
    """Check connectivity to all external dependencies.

    Returns a dict of dependency_name → "ok" | "error: <reason>" | "not_configured".
    HTTP status 200 if all configured dependencies are reachable,
    503 if any required dependency is down.
    """
    from app.db import AsyncSessionLocal
    from sqlalchemy import text

    status: dict[str, str] = {}
    degraded = False

    # ── Postgres ──────────────────────────────────────────────────────────────
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        status["postgres"] = "ok"
    except Exception as e:
        status["postgres"] = f"error: {e}"
        degraded = True

    # ── OpenRouter ────────────────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.head("https://openrouter.ai/api/v1/models")
            status["openrouter"] = "ok" if r.status_code < 500 else f"error: HTTP {r.status_code}"
    except Exception as e:
        status["openrouter"] = f"error: {e}"

    # ── xAI API ───────────────────────────────────────────────────────────────
    try:
        from app.config import settings  # type: ignore[attr-defined]
        xai_key = getattr(settings, "XAI_API_KEY", None)
    except Exception:
        xai_key = None

    if xai_key:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.head(
                    "https://api.x.ai/v1/models",
                    headers={"Authorization": f"Bearer {xai_key}"},
                )
                status["xai"] = "ok" if r.status_code < 500 else f"error: HTTP {r.status_code}"
        except Exception as e:
            status["xai"] = f"error: {e}"
    else:
        status["xai"] = "not_configured"

    # ── Ollama (optional) ─────────────────────────────────────────────────────
    try:
        from app.config import settings as _s  # type: ignore[attr-defined]
        ollama_url = getattr(_s, "OLLAMA_BASE_URL", None)
    except Exception:
        ollama_url = None

    if ollama_url:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{ollama_url.rstrip('/')}/api/tags")
                status["ollama"] = "ok" if r.status_code < 500 else f"error: HTTP {r.status_code}"
        except Exception as e:
            status["ollama"] = f"error: {e}"
    else:
        status["ollama"] = "not_configured"

    # ── Redis (optional) ──────────────────────────────────────────────────────
    try:
        from app.config import settings as _rs  # type: ignore[attr-defined]
        redis_url = getattr(_rs, "REDIS_URL", None)
    except Exception:
        redis_url = None

    if redis_url:
        try:
            import redis.asyncio as aioredis  # type: ignore[import]
            r_client = aioredis.from_url(redis_url, socket_connect_timeout=3)
            await r_client.ping()
            await r_client.aclose()
            status["redis"] = "ok"
        except ImportError:
            status["redis"] = "error: redis package not installed"
        except Exception as e:
            status["redis"] = f"error: {e}"
    else:
        status["redis"] = "not_configured"

    overall = "healthy" if not degraded else "degraded"
    return {
        "status": overall,
        "dependencies": status,
        "checked_at": time.time(),
    }


@router.get("/health/diagnostics")
async def system_diagnostics(
    hours: int = Query(24, ge=1, le=168),
    current_user: Any = Depends(get_current_user),
) -> dict:
    """System diagnostics — authenticated endpoint.

    Returns collector status, source health, task model config,
    LLM usage summary, and recent LLM calls.
    """
    from app.db import AsyncSessionLocal
    from app.models.llm_usage import LLMUsage  # noqa: PLC0415
    from app.models.source import Source  # noqa: PLC0415
    from app.models.task_model_override import TaskModelOverride  # noqa: PLC0415
    from app.services.llm_usage_service import llm_usage_service  # noqa: PLC0415
    from app.collectors.orchestrator import orchestrator  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with AsyncSessionLocal() as db:
        # ── Source health ────────────────────────────────────────────────────
        sources_result = await db.execute(
            select(
                Source.type,
                Source.handle,
                Source.last_polled,
                Source.error_count,
                Source.last_error,
                Source.enabled,
            )
            .where(Source.enabled == True)  # noqa: E712
            .order_by(Source.error_count.desc())
        )
        sources_list = sources_result.all()

        # ── Task model overrides ─────────────────────────────────────────────
        overrides_result = await db.execute(
            select(
                TaskModelOverride.task,
                TaskModelOverride.model_id,
                TaskModelOverride.updated_at,
            )
            .order_by(TaskModelOverride.task)
        )
        overrides_list = overrides_result.all()

        # ── Recent LLM calls ─────────────────────────────────────────────────
        recent_result = await db.execute(
            select(LLMUsage)
            .where(LLMUsage.timestamp >= cutoff)
            .order_by(LLMUsage.timestamp.desc())
            .limit(50)
        )
        recent_list = recent_result.scalars().all()

    # ── LLM usage summary ────────────────────────────────────────────────────
    usage = await llm_usage_service.get_usage_summary(hours=hours)

    # ── Collector status ─────────────────────────────────────────────────────
    try:
        collector_status = orchestrator.get_collector_status()
    except Exception as exc:
        collector_status = {"error": str(exc)}

    return {
        "collector_status": collector_status,
        "source_health": [
            {
                "type": s.type,
                "handle": s.handle,
                "last_polled": s.last_polled.isoformat() if s.last_polled else None,
                "error_count": s.error_count,
                "last_error": s.last_error,
                "enabled": s.enabled,
            }
            for s in sources_list
        ],
        "task_models": [
            {
                "task": o.task,
                "model_id": o.model_id,
                "updated_at": o.updated_at.isoformat(),
            }
            for o in overrides_list
        ],
        "llm_usage_summary": usage,
        "recent_llm_calls": [
            {
                "timestamp": r.timestamp.isoformat(),
                "provider": r.provider,
                "model": r.model,
                "task": r.task,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "latency_ms": r.latency_ms,
                "cost_usd": r.cost_usd,
                "error": r.error,
            }
            for r in recent_list
        ],
    }
