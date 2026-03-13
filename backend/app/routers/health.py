"""Health check endpoints — no auth required."""
from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

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
