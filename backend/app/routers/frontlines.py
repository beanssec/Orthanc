"""Frontline snapshot API router."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.frontline_service import frontline_service

router = APIRouter(prefix="/frontlines", tags=["frontlines"])


@router.get("/snapshots")
async def list_snapshots(days: int = Query(default=90, ge=1, le=365)):
    """List available snapshot dates (most recent first)."""
    return await frontline_service.get_snapshots(days=days)


@router.get("/snapshots/{snapshot_date}")
async def get_snapshot(snapshot_date: str, source: str = Query(default="deepstate")):
    """
    Return frontline GeoJSON for a specific date.
    Date format: YYYY-MM-DD
    """
    geojson = await frontline_service.get_snapshot(snapshot_date, source_id=source)
    if geojson is None:
        raise HTTPException(
            status_code=404,
            detail=f"No snapshot found for date={snapshot_date} source={source}",
        )
    return geojson


@router.get("/dates")
async def get_date_range(source: str = Query(default="deepstate")):
    """Return the earliest and latest available snapshot dates."""
    return await frontline_service.get_date_range(source_id=source)


@router.post("/snapshots/take")
async def take_snapshot_now(source: str = Query(default="deepstate")):
    """Manually trigger a frontline snapshot."""
    result = await frontline_service.take_snapshot(source_id=source)
    return result
