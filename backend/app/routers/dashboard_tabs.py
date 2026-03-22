"""Dashboard tab CRUD — per-user configurable dashboard layouts."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.models.dashboard_tab import DashboardTab

router = APIRouter(prefix="/dashboard-tabs", tags=["dashboard"])


class TabCreate(BaseModel):
    name: str
    icon: Optional[str] = None
    position: int = 0
    layout: list = []

class TabUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    position: Optional[int] = None
    layout: Optional[list] = None

class TabResponse(BaseModel):
    id: str
    name: str
    icon: Optional[str]
    position: int
    is_default: bool
    layout: list
    created_at: str
    updated_at: str


def _tab_to_response(tab: DashboardTab) -> dict:
    return {
        "id": str(tab.id),
        "name": tab.name,
        "icon": tab.icon,
        "position": tab.position,
        "is_default": tab.is_default,
        "layout": tab.layout or [],
        "created_at": tab.created_at.isoformat(),
        "updated_at": tab.updated_at.isoformat(),
    }


@router.get("/")
async def list_tabs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DashboardTab)
        .where(DashboardTab.user_id == current_user.id)
        .order_by(DashboardTab.position)
    )
    tabs = result.scalars().all()

    # Auto-seed defaults if user has no tabs
    if not tabs:
        tabs = await _seed_default_tabs(current_user.id, db)

    return [_tab_to_response(t) for t in tabs]


@router.post("/")
async def create_tab(
    body: TabCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tab = DashboardTab(
        user_id=current_user.id,
        name=body.name,
        icon=body.icon,
        position=body.position,
        layout=body.layout,
    )
    db.add(tab)
    await db.commit()
    await db.refresh(tab)
    return _tab_to_response(tab)


@router.put("/{tab_id}")
async def update_tab(
    tab_id: uuid.UUID,
    body: TabUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DashboardTab).where(
            DashboardTab.id == tab_id,
            DashboardTab.user_id == current_user.id,
        )
    )
    tab = result.scalars().first()
    if not tab:
        raise HTTPException(status_code=404, detail="Tab not found")

    if body.name is not None:
        tab.name = body.name
    if body.icon is not None:
        tab.icon = body.icon
    if body.position is not None:
        tab.position = body.position
    if body.layout is not None:
        tab.layout = body.layout
    tab.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(tab)
    return _tab_to_response(tab)


@router.delete("/{tab_id}")
async def delete_tab(
    tab_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DashboardTab).where(
            DashboardTab.id == tab_id,
            DashboardTab.user_id == current_user.id,
        )
    )
    tab = result.scalars().first()
    if not tab:
        raise HTTPException(status_code=404, detail="Tab not found")

    await db.delete(tab)
    await db.commit()
    return {"status": "deleted"}


@router.post("/seed-defaults")
async def seed_defaults(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-seed default tabs (deletes existing defaults first)."""
    # Delete existing defaults
    result = await db.execute(
        select(DashboardTab).where(
            DashboardTab.user_id == current_user.id,
            DashboardTab.is_default == True,
        )
    )
    for tab in result.scalars().all():
        await db.delete(tab)
    await db.flush()

    tabs = await _seed_default_tabs(current_user.id, db)
    return [_tab_to_response(t) for t in tabs]


async def _seed_default_tabs(user_id: uuid.UUID, db: AsyncSession) -> list[DashboardTab]:
    """Create the 4 default dashboard tabs with preset widget layouts."""
    defaults = [
        {
            "name": "Overview",
            "icon": "📊",
            "position": 0,
            "layout": [
                {"id": "kpi-strip", "type": "builtin", "component": "KPIStrip", "grid": {"x": 0, "y": 0, "w": 12, "h": 2}},
                {"id": "source-health", "type": "builtin", "component": "SourceHealthStrip", "grid": {"x": 0, "y": 2, "w": 12, "h": 2}},
                {"id": "velocity", "type": "builtin", "component": "VelocityChart", "grid": {"x": 0, "y": 4, "w": 12, "h": 4}},
                {"id": "trending-entities", "type": "builtin", "component": "TrendingEntities", "grid": {"x": 0, "y": 8, "w": 4, "h": 4}},
                {"id": "trending-narratives", "type": "builtin", "component": "TrendingNarratives", "grid": {"x": 4, "y": 8, "w": 4, "h": 4}},
                {"id": "geo-hotspots", "type": "builtin", "component": "GeoHotspots", "grid": {"x": 8, "y": 8, "w": 4, "h": 4}},
                {"id": "recent-alerts", "type": "builtin", "component": "RecentAlerts", "grid": {"x": 0, "y": 12, "w": 6, "h": 4}},
                {"id": "activity-feed", "type": "builtin", "component": "ActivityFeed", "grid": {"x": 6, "y": 12, "w": 6, "h": 4}},
            ],
        },
        {
            "name": "Military",
            "icon": "⚔️",
            "position": 1,
            "layout": [
                {"id": "strike-chart", "type": "builtin", "component": "StrikeChart", "grid": {"x": 0, "y": 0, "w": 12, "h": 5}},
                {"id": "vip-flights", "type": "api", "title": "VIP Flight Sightings", "data_source": {"endpoint": "/layers/flights/vip", "params": {"hours": 48}}, "viz": "table", "grid": {"x": 0, "y": 5, "w": 6, "h": 4}},
                {"id": "mil-narratives", "type": "api", "title": "Military Narratives (High Divergence)", "data_source": {"endpoint": "/narratives/", "params": {"status": "active", "min_divergence": 0.3, "limit": 10}}, "viz": "table", "grid": {"x": 6, "y": 5, "w": 6, "h": 4}},
                {"id": "centcom-feed", "type": "api", "title": "CENTCOM / IDF Feed", "data_source": {"endpoint": "/feed/", "params": {"source_types": ["telegram"], "page_size": 10}}, "viz": "feed", "grid": {"x": 0, "y": 9, "w": 12, "h": 5}},
            ],
        },
        {
            "name": "Markets",
            "icon": "📈",
            "position": 2,
            "layout": [
                {"id": "oil-price", "type": "api", "title": "Oil & Energy Prices", "data_source": {"endpoint": "/finance/quotes", "params": {"tickers": "CL,BZ,NG"}}, "viz": "stat_cards", "grid": {"x": 0, "y": 0, "w": 6, "h": 3}},
                {"id": "portfolio", "type": "builtin", "component": "PortfolioSummary", "grid": {"x": 6, "y": 0, "w": 6, "h": 3}},
                {"id": "market-alerts", "type": "api", "title": "Economic Alerts", "data_source": {"endpoint": "/alerts/events/", "params": {"limit": 10}}, "viz": "table", "grid": {"x": 0, "y": 3, "w": 12, "h": 4}},
                {"id": "sanctions-feed", "type": "api", "title": "Sanctions & OFAC Activity", "data_source": {"endpoint": "/feed/", "params": {"source_types": ["official"], "page_size": 10}}, "viz": "feed", "grid": {"x": 0, "y": 7, "w": 12, "h": 5}},
            ],
        },
        {
            "name": "Diplomacy",
            "icon": "🕊️",
            "position": 3,
            "layout": [
                {"id": "divergence-leaders", "type": "api", "title": "Most Contested Narratives", "data_source": {"endpoint": "/narratives/", "params": {"status": "active", "min_divergence": 0.3, "limit": 10}}, "viz": "table", "grid": {"x": 0, "y": 0, "w": 12, "h": 5}},
                {"id": "ceasefire-alerts", "type": "api", "title": "Ceasefire / Diplomatic Signals", "data_source": {"endpoint": "/alerts/events/", "params": {"limit": 10}}, "viz": "feed", "grid": {"x": 0, "y": 5, "w": 6, "h": 5}},
                {"id": "mediator-feed", "type": "api", "title": "Mediator Country Activity", "data_source": {"endpoint": "/feed/", "params": {"source_types": ["rss"], "page_size": 10}}, "viz": "feed", "grid": {"x": 6, "y": 5, "w": 6, "h": 5}},
            ],
        },
    ]

    tabs = []
    for d in defaults:
        tab = DashboardTab(
            user_id=user_id,
            name=d["name"],
            icon=d["icon"],
            position=d["position"],
            is_default=True,
            layout=d["layout"],
        )
        db.add(tab)
        tabs.append(tab)

    await db.commit()
    for t in tabs:
        await db.refresh(t)
    return tabs
