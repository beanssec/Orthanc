"""Satellite watchpoint management API."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user
from app.models.watchpoint import SatSnapshot, SatWatchpoint

router = APIRouter(prefix="/watchpoints", tags=["watchpoints"])


@router.get("/")
async def list_watchpoints(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List all satellite watchpoints."""
    result = await db.execute(
        select(SatWatchpoint).order_by(SatWatchpoint.category, SatWatchpoint.name)
    )
    watchpoints = result.scalars().all()
    return [
        {
            "id": str(wp.id),
            "name": wp.name,
            "description": wp.description,
            "lat": wp.lat,
            "lng": wp.lng,
            "radius_km": wp.radius_km,
            "category": wp.category,
            "enabled": wp.enabled,
            "last_checked": wp.last_checked.isoformat() if wp.last_checked else None,
            "last_image_date": wp.last_image_date,
        }
        for wp in watchpoints
    ]


@router.post("/")
async def create_watchpoint(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a new satellite watchpoint."""
    wp = SatWatchpoint(
        name=data["name"],
        lat=float(data["lat"]),
        lng=float(data["lng"]),
        radius_km=float(data.get("radius_km", 10.0)),
        category=data.get("category", "custom"),
        description=data.get("description"),
    )
    db.add(wp)
    await db.commit()
    await db.refresh(wp)
    return {"id": str(wp.id), "name": wp.name, "status": "created"}


@router.patch("/{watchpoint_id}")
async def update_watchpoint(
    watchpoint_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Update an existing watchpoint."""
    result = await db.execute(
        select(SatWatchpoint).where(SatWatchpoint.id == uuid.UUID(watchpoint_id))
    )
    wp = result.scalars().first()
    if not wp:
        raise HTTPException(status_code=404, detail="Watchpoint not found")
    for field in ["name", "enabled", "radius_km", "change_threshold", "description"]:
        if field in data:
            setattr(wp, field, data[field])
    await db.commit()
    return {"id": watchpoint_id, "status": "updated"}


@router.delete("/{watchpoint_id}")
async def delete_watchpoint(
    watchpoint_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Delete a watchpoint (cascades to its snapshots)."""
    result = await db.execute(
        select(SatWatchpoint).where(SatWatchpoint.id == uuid.UUID(watchpoint_id))
    )
    wp = result.scalars().first()
    if not wp:
        raise HTTPException(status_code=404, detail="Watchpoint not found")
    await db.delete(wp)
    await db.commit()
    return {"status": "deleted"}


@router.get("/{watchpoint_id}/snapshots")
async def get_snapshots(
    watchpoint_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return the 30 most recent snapshots for a watchpoint."""
    result = await db.execute(
        select(SatSnapshot)
        .where(SatSnapshot.watchpoint_id == uuid.UUID(watchpoint_id))
        .order_by(SatSnapshot.image_date.desc())
        .limit(30)
    )
    snaps = result.scalars().all()
    return [
        {
            "id": str(s.id),
            "image_date": s.image_date,
            "cloud_cover": s.cloud_cover,
            "change_score": s.change_score,
            "change_detected": s.change_detected,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in snaps
    ]


@router.post("/check-now")
async def trigger_check(current_user=Depends(get_current_user)):
    """Manually trigger an immediate watchpoint imagery check."""
    from app.services.sentinel_service import sentinel_service

    asyncio.create_task(sentinel_service._check_all_watchpoints())
    return {"status": "check triggered"}
