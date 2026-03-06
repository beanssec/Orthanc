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
