"""GDELT API endpoints."""
from fastapi import APIRouter, Depends, Query
from app.middleware.auth import get_current_user
from app.models import User
from app.services.gdelt_service import gdelt_service
from app.services.gdelt_geo_service import gdelt_geo_service

router = APIRouter(prefix="/gdelt", tags=["gdelt"])


@router.get("/articles")
async def search_gdelt_articles(
    q: str = Query(..., min_length=1, description="Search query"),
    max_records: int = Query(default=75, ge=1, le=250),
    timespan: str = Query(default="7d"),
    _user: User = Depends(get_current_user),
):
    """Search GDELT for global news articles."""
    return await gdelt_service.search_articles(q, max_records=max_records, timespan=timespan)


@router.get("/geo")
async def get_gdelt_geo(
    q: str = Query(..., min_length=1, description="Search query for heatmap"),
    timespan: str = Query(default="7d"),
    _user: User = Depends(get_current_user),
):
    """Get GDELT geographic media attention heatmap as GeoJSON."""
    return await gdelt_geo_service.get_heatmap(q, timespan=timespan)
