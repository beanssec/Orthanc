"""ICIJ + OCCRP entity enrichment endpoints."""
from fastapi import APIRouter, Depends, Query
from app.middleware.auth import get_current_user
from app.models import User
from app.services.icij_service import icij_service
from app.services.occrp_service import occrp_service
from app.services.collector_manager import collector_manager

router = APIRouter(prefix="/investigations", tags=["investigations"])


@router.get("/icij/search")
async def search_icij(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, ge=1, le=50),
    _user: User = Depends(get_current_user),
):
    """Search ICIJ Offshore Leaks database."""
    return await icij_service.search(q, limit=limit)


@router.get("/occrp/search")
async def search_occrp(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
):
    """Search OCCRP Aleph database."""
    # Get OCCRP API key if configured
    keys = await collector_manager.get_keys(str(current_user.id), "occrp")
    api_key = keys.get("api_key") if keys else None
    return await occrp_service.search(q, api_key=api_key, limit=limit)
