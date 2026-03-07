"""Sanctions API router — OpenSanctions integration."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user
from app.models import User
from app.services.sanctions_service import sanctions_service

router = APIRouter(prefix="/sanctions", tags=["sanctions"])


@router.get("/status")
async def sanctions_status(
    _: User = Depends(get_current_user),
) -> dict:
    """Return sanctions DB status — last updated, entity count, download state, etc."""
    return await sanctions_service.status()


@router.post("/refresh")
async def trigger_sanctions_refresh(
    _: User = Depends(get_current_user),
) -> dict:
    """Manually trigger a sanctions data download and refresh.

    The bulk file is ~200 MB so the download runs in the background.
    Poll /sanctions/status to check progress.
    """
    result = await sanctions_service.trigger_download()
    return result


@router.get("/search")
async def search_sanctions(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    threshold: float = Query(0.3, ge=0.0, le=1.0),
    _: User = Depends(get_current_user),
) -> list[dict]:
    """Search the sanctions database directly by entity name."""
    results = await sanctions_service.search_sanctions(query=q, limit=limit, threshold=threshold)
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "entity_type": r["entity_type"],
            "datasets": r["datasets"] or [],
            "countries": r["countries"] or [],
            "aliases": r["aliases"] or [],
            "score": round(float(r["score"]), 4),
            "opensanctions_url": f"https://opensanctions.org/entities/{r['id']}/",
        }
        for r in results
    ]


@router.get("/matches/{entity_id}")
async def get_sanctions_matches(
    entity_id: uuid.UUID,
    _: User = Depends(get_current_user),
) -> list[dict]:
    """Get stored sanctions matches for a platform entity.

    Returns pre-computed matches. To compute fresh matches, use POST /sanctions/check/{entity_id}.
    """
    matches = await sanctions_service.get_entity_matches(entity_id)
    return matches


@router.post("/check/{entity_id}")
async def check_entity_sanctions(
    entity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """Run a fresh sanctions check for a specific platform entity.

    Requires the sanctions database to have been populated first (/sanctions/refresh).
    """
    from sqlalchemy import select
    from app.models.entity import Entity

    result = await db.execute(select(Entity).where(Entity.id == entity_id))
    entity = result.scalars().first()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    matches = await sanctions_service.check_entity(
        entity_id=entity_id,
        entity_name=entity.name,
        entity_type=entity.type,
    )

    return {
        "entity_id": str(entity_id),
        "entity_name": entity.name,
        "matches_found": len(matches),
        "matches": matches,
    }


# ---------------------------------------------------------------------------
# EU Consolidated Financial Sanctions List
# ---------------------------------------------------------------------------


@router.post("/eu/download")
async def download_eu_sanctions(
    _: User = Depends(get_current_user),
) -> dict:
    """Trigger EU consolidated sanctions list download (on-demand).

    The XML file is fetched from the EU Financial Sanctions Files portal and
    held in memory.  Poll /sanctions/eu/stats to check the loaded count.
    """
    from app.services.eu_sanctions_service import eu_sanctions_service  # noqa: PLC0415

    count = await eu_sanctions_service.download_and_parse()
    return {"source": "eu_consolidated", "entities": count, "status": "loaded"}


@router.get("/eu/stats")
async def eu_sanctions_stats(
    _: User = Depends(get_current_user),
) -> dict:
    """Return EU sanctions list load status."""
    from app.services.eu_sanctions_service import eu_sanctions_service  # noqa: PLC0415

    return {
        "source": "eu_consolidated",
        "entities": eu_sanctions_service.count,
        "last_updated": (
            eu_sanctions_service.last_updated.isoformat()
            if eu_sanctions_service.last_updated
            else None
        ),
    }


@router.get("/eu/search")
async def search_eu_sanctions(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    _: User = Depends(get_current_user),
) -> dict:
    """Search the EU consolidated sanctions list (case-insensitive substring)."""
    from app.services.eu_sanctions_service import eu_sanctions_service  # noqa: PLC0415

    if not eu_sanctions_service.count:
        return {
            "error": "EU sanctions list not loaded. POST /sanctions/eu/download first.",
            "results": [],
        }

    results = eu_sanctions_service.search(q, limit)
    return {"source": "eu_consolidated", "total": len(results), "results": results}


# ---------------------------------------------------------------------------
# UK OFSI Consolidated Sanctions List
# ---------------------------------------------------------------------------


@router.post("/uk/download")
async def download_uk_sanctions(
    _: User = Depends(get_current_user),
) -> dict:
    """Trigger UK OFSI consolidated sanctions list download (on-demand).

    The CSV is fetched from OFSI blob storage and held in memory.
    Poll /sanctions/uk/stats to check the loaded count.
    """
    from app.services.uk_sanctions_service import uk_sanctions_service  # noqa: PLC0415

    count = await uk_sanctions_service.download_and_parse()
    return {"source": "uk_ofsi", "entities": count, "status": "loaded"}


@router.get("/uk/stats")
async def uk_sanctions_stats(
    _: User = Depends(get_current_user),
) -> dict:
    """Return UK OFSI sanctions list load status."""
    from app.services.uk_sanctions_service import uk_sanctions_service  # noqa: PLC0415

    return {
        "source": "uk_ofsi",
        "entities": uk_sanctions_service.count,
        "last_updated": (
            uk_sanctions_service.last_updated.isoformat()
            if uk_sanctions_service.last_updated
            else None
        ),
    }


@router.get("/uk/search")
async def search_uk_sanctions(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    _: User = Depends(get_current_user),
) -> dict:
    """Search the UK OFSI sanctions list (case-insensitive substring)."""
    from app.services.uk_sanctions_service import uk_sanctions_service  # noqa: PLC0415

    if not uk_sanctions_service.count:
        return {
            "error": "UK sanctions list not loaded. POST /sanctions/uk/download first.",
            "results": [],
        }

    results = uk_sanctions_service.search(q, limit)
    return {"source": "uk_ofsi", "total": len(results), "results": results}


# ---------------------------------------------------------------------------
# Combined cross-list search
# ---------------------------------------------------------------------------


@router.get("/search/all")
async def search_all_sanctions(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    _: User = Depends(get_current_user),
) -> dict:
    """Search across EU and UK sanctions lists simultaneously.

    Note: OpenSanctions results are available via GET /sanctions/search.
    This endpoint covers the EU consolidated list and UK OFSI list only.
    """
    from app.services.eu_sanctions_service import eu_sanctions_service  # noqa: PLC0415
    from app.services.uk_sanctions_service import uk_sanctions_service  # noqa: PLC0415

    results: dict = {"query": q, "sources": {}}

    if eu_sanctions_service.count:
        eu_results = eu_sanctions_service.search(q, limit)
        results["sources"]["eu_consolidated"] = {
            "count": len(eu_results),
            "results": eu_results,
        }

    if uk_sanctions_service.count:
        uk_results = uk_sanctions_service.search(q, limit)
        results["sources"]["uk_ofsi"] = {
            "count": len(uk_results),
            "results": uk_results,
        }

    if not results["sources"]:
        results["note"] = (
            "No lists loaded. POST /sanctions/eu/download and/or "
            "/sanctions/uk/download first."
        )

    return results
