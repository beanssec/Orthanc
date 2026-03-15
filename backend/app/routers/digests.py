"""
Digests API Router — Sprint 31, Checkpoint 3.

Thin on-demand endpoints for tracker and alert digests.  These wrap the
digest_generator service functions so the UI (and future schedule runners)
can trigger or preview digests without going through the scheduler.

Routes:
  GET  /digests/tracker          Tracker digest for authenticated user
  GET  /digests/alerts           Alert digest for authenticated user
  GET  /digests/combined         Combined tracker + alert digest
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.middleware.auth import get_current_user
from app.models import User
from app.services.digest_generator import (
    generate_alert_digest,
    generate_combined_digest,
    generate_tracker_digest,
)

logger = logging.getLogger("orthanc.routers.digests")

router = APIRouter(prefix="/digests", tags=["digests"])


@router.get("/tracker")
async def get_tracker_digest(
    hours: int = Query(default=24, ge=1, le=168, description="Look-back window in hours"),
    max_trackers: int = Query(default=10, ge=1, le=50),
    max_narratives: int = Query(default=5, ge=1, le=20),
    current_user: User = Depends(get_current_user),
):
    """Return a tracker digest for the authenticated user.

    The digest lists active narrative trackers and their recent narrative
    matches, annotated with confidence signals (evidence, divergence,
    confirmation status).
    """
    result = await generate_tracker_digest(
        user_id=str(current_user.id),
        hours=hours,
        max_trackers=max_trackers,
        max_narratives_per_tracker=max_narratives,
    )
    return JSONResponse(content=result)


@router.get("/alerts")
async def get_alert_digest(
    hours: int = Query(default=24, ge=1, le=168, description="Look-back window in hours"),
    max_events: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    """Return an alert digest for the authenticated user.

    Events are grouped flash → urgent → routine, newest first within each
    tier. Rule names are resolved automatically.
    """
    result = await generate_alert_digest(
        user_id=str(current_user.id),
        hours=hours,
        max_events=max_events,
    )
    return JSONResponse(content=result)


@router.get("/combined")
async def get_combined_digest(
    hours: int = Query(default=24, ge=1, le=168, description="Look-back window in hours"),
    include_trackers: bool = Query(default=True),
    include_alerts: bool = Query(default=True),
    current_user: User = Depends(get_current_user),
):
    """Return a combined tracker + alert digest for the authenticated user.

    Suitable for direct delivery as a single Telegram message or webhook POST.
    The ``text_summary`` field merges both sections.
    """
    result = await generate_combined_digest(
        user_id=str(current_user.id),
        hours=hours,
        include_trackers=include_trackers,
        include_alerts=include_alerts,
    )
    return JSONResponse(content=result)
