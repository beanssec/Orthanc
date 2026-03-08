"""Graph router — entity co-occurrence graph endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.services.cooccurrence_service import cooccurrence_service

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/entities")
async def entity_graph(
    min_weight: int = Query(default=3, ge=1, le=100),
    limit: int = Query(default=200, ge=1, le=500),
    entity_type: Optional[str] = Query(default=None),
    center: Optional[str] = Query(default=None, description="Entity ID to center the graph on"),
) -> dict:
    """Get entity co-occurrence graph.

    Returns nodes and edges for the force-directed graph visualization.
    """
    try:
        return await cooccurrence_service.get_graph(
            min_weight=min_weight,
            limit=limit,
            entity_type=entity_type or None,
            center_entity_id=center or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Graph query failed") from exc


@router.get("/entities/{entity_id}/neighbors")
async def entity_neighbors(
    entity_id: str,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """Get entities most closely related to a specific entity."""
    try:
        result = await cooccurrence_service.get_entity_neighbors(
            entity_id=entity_id,
            limit=limit,
        )
        if not result["nodes"]:
            raise HTTPException(status_code=404, detail="Entity not found or has no relationships")
        return result
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Neighbors query failed") from exc
