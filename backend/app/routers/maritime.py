"""Maritime intelligence API endpoints."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.models.vessel import MaritimeEvent, VesselTrack, VesselWatchlist
from app.services.maritime_intel_service import maritime_intel_service

logger = logging.getLogger("orthanc.routers.maritime")

router = APIRouter(tags=["maritime"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class WatchlistAddRequest(BaseModel):
    mmsi: str
    vessel_name: Optional[str] = None
    reason: Optional[str] = None
    alert_on_dark: bool = True
    alert_on_sts: bool = True
    alert_on_port_call: bool = True


# ---------------------------------------------------------------------------
# Maritime events
# ---------------------------------------------------------------------------

@router.get("/maritime/events")
async def get_maritime_events(
    event_type: Optional[str] = Query(default=None, description="Filter: dark_ship, sts_transfer, port_call"),
    severity: Optional[str] = Query(default=None, description="Filter: routine, notable, critical"),
    hours: int = Query(default=72, ge=1, le=720),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """List recent maritime intelligence events (dark ships, STS transfers, port calls)."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    stmt = (
        select(MaritimeEvent)
        .where(MaritimeEvent.detected_at >= cutoff)
        .order_by(MaritimeEvent.detected_at.desc())
        .limit(limit)
    )

    if event_type:
        stmt = stmt.where(MaritimeEvent.event_type == event_type)
    if severity:
        stmt = stmt.where(MaritimeEvent.severity == severity)

    result = await db.execute(stmt)
    events = result.scalars().all()

    return [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "mmsi": e.mmsi,
            "vessel_name": e.vessel_name,
            "lat": e.lat,
            "lng": e.lng,
            "severity": e.severity,
            "details": e.details,
            "detected_at": e.detected_at.isoformat() if e.detected_at else None,
            "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
        }
        for e in events
    ]


# ---------------------------------------------------------------------------
# Vessel tracks
# ---------------------------------------------------------------------------

@router.get("/maritime/tracks/{mmsi}")
async def get_vessel_tracks(
    mmsi: str,
    hours: int = Query(default=48, ge=1, le=720),
    limit: int = Query(default=500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Get historical AIS track for a specific vessel by MMSI."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    stmt = (
        select(VesselTrack)
        .where(VesselTrack.mmsi == mmsi)
        .where(VesselTrack.timestamp >= cutoff)
        .order_by(VesselTrack.timestamp.asc())
        .limit(limit)
    )

    result = await db.execute(stmt)
    tracks = result.scalars().all()

    return [
        {
            "id": str(t.id),
            "mmsi": t.mmsi,
            "vessel_name": t.vessel_name,
            "lat": t.lat,
            "lng": t.lng,
            "speed": t.speed,
            "heading": t.heading,
            "course": t.course,
            "destination": t.destination,
            "vessel_type": t.vessel_type,
            "flag": t.flag,
            "timestamp": t.timestamp.isoformat() if t.timestamp else None,
        }
        for t in tracks
    ]


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

@router.get("/maritime/watchlist")
async def get_watchlist(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Get the current user's vessel watchlist."""
    stmt = (
        select(VesselWatchlist)
        .where(VesselWatchlist.user_id == current_user.id)
        .order_by(VesselWatchlist.created_at.desc())
    )
    result = await db.execute(stmt)
    items = result.scalars().all()

    return [
        {
            "id": str(w.id),
            "mmsi": w.mmsi,
            "vessel_name": w.vessel_name,
            "reason": w.reason,
            "alert_on_dark": w.alert_on_dark,
            "alert_on_sts": w.alert_on_sts,
            "alert_on_port_call": w.alert_on_port_call,
            "created_at": w.created_at.isoformat() if w.created_at else None,
        }
        for w in items
    ]


@router.post("/maritime/watchlist")
async def add_to_watchlist(
    body: WatchlistAddRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Add a vessel to the watchlist."""
    if not body.mmsi.strip():
        raise HTTPException(status_code=400, detail="mmsi is required")

    # Check for duplicate
    existing = await db.execute(
        select(VesselWatchlist).where(
            VesselWatchlist.user_id == current_user.id,
            VesselWatchlist.mmsi == body.mmsi,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Vessel already in watchlist")

    item = VesselWatchlist(
        user_id=current_user.id,
        mmsi=body.mmsi,
        vessel_name=body.vessel_name,
        reason=body.reason,
        alert_on_dark=body.alert_on_dark,
        alert_on_sts=body.alert_on_sts,
        alert_on_port_call=body.alert_on_port_call,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    return {
        "id": str(item.id),
        "mmsi": item.mmsi,
        "vessel_name": item.vessel_name,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.delete("/maritime/watchlist/{item_id}")
async def remove_from_watchlist(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Remove a vessel from the watchlist."""
    result = await db.execute(
        select(VesselWatchlist).where(
            VesselWatchlist.id == item_id,
            VesselWatchlist.user_id == current_user.id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    await db.delete(item)
    await db.commit()
    return {"deleted": item_id}


# ---------------------------------------------------------------------------
# Monitored ports with vessel counts
# ---------------------------------------------------------------------------

@router.get("/maritime/ports")
async def get_monitored_ports(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List monitored ports with current vessel counts (vessels seen in last 30 min)."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)

    # Get current vessel positions
    result = await db.execute(text("""
        SELECT DISTINCT ON (mmsi) mmsi, vessel_name, lat, lng
        FROM vessel_tracks
        WHERE timestamp >= :cutoff
        ORDER BY mmsi, timestamp DESC
    """), {"cutoff": cutoff})
    vessels = result.fetchall()

    ports_out = []
    for port in maritime_intel_service.MONITORED_PORTS:
        count = 0
        vessel_list = []
        for mmsi, vessel_name, lat, lng in vessels:
            if lat is None or lng is None:
                continue
            from app.services.maritime_intel_service import haversine_nm
            d = haversine_nm(lat, lng, port["lat"], port["lng"])
            if d <= port["radius_nm"]:
                count += 1
                vessel_list.append({"mmsi": mmsi, "vessel_name": vessel_name})

        ports_out.append({
            "name": port["name"],
            "lat": port["lat"],
            "lng": port["lng"],
            "radius_nm": port["radius_nm"],
            "vessel_count": count,
            "vessels": vessel_list[:10],  # Cap at 10 for response size
        })

    return ports_out


# ---------------------------------------------------------------------------
# GeoJSON layer for map display
# ---------------------------------------------------------------------------

@router.get("/layers/maritime-events")
async def get_maritime_events_layer(
    hours: int = Query(default=72, ge=1, le=720),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return recent maritime events as GeoJSON FeatureCollection for map overlay."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    stmt = (
        select(MaritimeEvent)
        .where(MaritimeEvent.detected_at >= cutoff)
        .where(MaritimeEvent.lat.isnot(None))
        .where(MaritimeEvent.lng.isnot(None))
        .order_by(MaritimeEvent.detected_at.desc())
        .limit(1000)
    )
    result = await db.execute(stmt)
    events = result.scalars().all()

    # Color / marker-type per event
    EVENT_STYLE = {
        "dark_ship": {"color": "#ef4444", "icon": "🚫", "label": "Dark Ship"},
        "sts_transfer": {"color": "#f97316", "icon": "🔄", "label": "STS Transfer"},
        "port_call": {"color": "#3b82f6", "icon": "⚓", "label": "Port Call"},
        "deviation": {"color": "#a855f7", "icon": "⚠️", "label": "Route Deviation"},
    }

    features = []
    for e in events:
        style = EVENT_STYLE.get(e.event_type, {"color": "#6b7280", "icon": "❓", "label": e.event_type})
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [e.lng, e.lat]},
            "properties": {
                "id": str(e.id),
                "event_type": e.event_type,
                "mmsi": e.mmsi,
                "vessel_name": e.vessel_name or "Unknown",
                "severity": e.severity,
                "details": e.details or {},
                "detected_at": e.detected_at.isoformat() if e.detected_at else None,
                "color": style["color"],
                "icon": style["icon"],
                "label": style["label"],
            },
        })

    # Also add monitored ports as reference points
    port_features = []
    for port in maritime_intel_service.MONITORED_PORTS:
        port_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [port["lng"], port["lat"]]},
            "properties": {
                "id": f"port_{port['name'].replace(' ', '_').lower()}",
                "event_type": "monitored_port",
                "vessel_name": port["name"],
                "severity": "routine",
                "details": {"radius_nm": port["radius_nm"]},
                "color": "#64748b",
                "icon": "🏭",
                "label": "Monitored Port",
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features + port_features,
        "metadata": {
            "count": len(features),
            "port_count": len(port_features),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
