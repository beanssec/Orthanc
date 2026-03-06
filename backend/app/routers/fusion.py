"""Fusion API — cross-source intelligence event endpoints."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.services.fusion_service import fusion_service
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("orthanc.routers.fusion")

router = APIRouter(prefix="/fusion", tags=["fusion"])


@router.get("/events")
async def get_fused_events(
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=50, ge=1, le=200),
    severity: Optional[str] = Query(default=None, description="Filter: flash, urgent, routine"),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Get recent fused intelligence events (multi-source corroborated)."""
    events = await fusion_service.get_recent(hours=hours, limit=limit)
    if severity:
        events = [e for e in events if e["severity"] == severity]
    return events


@router.get("/events/{event_id}")
async def get_fused_event(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a single fused intelligence event with all component post IDs."""
    event = await fusion_service.get_by_id(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Fused event not found")
    return event


@router.get("/layers/fusion")
async def get_fusion_layer(
    hours: int = Query(default=48, ge=1, le=720),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return fused events as GeoJSON FeatureCollection for map overlay."""
    events = await fusion_service.get_recent(hours=hours, limit=200)

    SEVERITY_COLORS = {
        "flash": "#ef4444",
        "urgent": "#f97316",
        "routine": "#3b82f6",
    }

    features = []
    for e in events:
        if e["centroid_lat"] is None or e["centroid_lng"] is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [e["centroid_lng"], e["centroid_lat"]],
            },
            "properties": {
                "id": e["id"],
                "severity": e["severity"],
                "source_count": e["source_count"],
                "post_count": e["post_count"],
                "summary": (e["ai_summary"] or "")[:200],
                "entity_names": e["entity_names"],
                "source_types": e["component_source_types"],
                "radius_km": e["radius_km"],
                "created_at": e["created_at"],
                "color": SEVERITY_COLORS.get(e["severity"], "#6b7280"),
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "count": len(features),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
