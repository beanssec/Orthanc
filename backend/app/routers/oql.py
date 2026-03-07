"""OQL (Orthanc Query Language) execution router.

Endpoints:
    POST /oql/execute   — parse + execute an OQL query
    POST /oql/explain   — return the SQL an OQL query would run
    GET  /oql/schema    — return field schema for autocomplete
    GET  /oql/history   — recent query history for the current user
    POST /oql/save      — save a named query
    GET  /oql/saved     — list saved queries for the current user
    DELETE /oql/saved/{id} — delete a saved query
"""
from __future__ import annotations

import time
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.models.query import SavedQuery, QueryHistory
from app.services.oql_parser import (
    OQLError,
    compile_oql,
    get_schema,
    infer_col_type,
    serialize_rows,
    FIELD_MAP,
)

logger = logging.getLogger("orthanc.oql")

router = APIRouter(prefix="/oql", tags=["oql"])


# ── Request / Response models ───────────────────────────────────────────────────

class OQLRequest(BaseModel):
    query: str
    limit: int = 1000


class OQLResponse(BaseModel):
    columns: list[dict]
    rows: list[dict]
    total: int
    query_time_ms: float
    visualization_hint: str


class SaveQueryRequest(BaseModel):
    name: str
    query_text: str
    description: str | None = None
    is_pinned: bool = False
    visualization_config: dict | None = None


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _model_to_dict(instance: Any, table: str) -> dict:
    """Convert a SQLAlchemy ORM instance to a plain dict using the field map."""
    fields = list(FIELD_MAP.get(table, {}).keys())
    row = {}
    for col in fields:
        val = getattr(instance, col, None)
        row[col] = val
    return row


# ── Endpoints ───────────────────────────────────────────────────────────────────

@router.post("/execute", response_model=OQLResponse)
async def execute_oql(
    body: OQLRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Parse and execute an OQL query, returning rows + metadata."""
    start = time.monotonic()

    try:
        compiled = compile_oql(body.query, limit=min(body.limit, 5000))
    except OQLError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())
    except Exception as e:
        raise HTTPException(status_code=400, detail={"error": str(e), "position": -1})

    try:
        if compiled.is_aggregate:
            result = await db.execute(compiled.stmt)
            col_names = list(result.keys())
            raw_rows = result.fetchall()
            rows = [dict(zip(col_names, row)) for row in raw_rows]
            total = len(rows)
            columns = [{"name": c, "type": "mixed"} for c in col_names]
        else:
            # Count total
            if compiled.count_stmt is not None:
                total_result = await db.execute(compiled.count_stmt)
                total = total_result.scalar() or 0
            else:
                total = 0

            result = await db.execute(compiled.stmt)

            if compiled.select_fields:
                # Core select returning tuples
                col_names = compiled.select_fields
                raw_rows = result.fetchall()
                rows = [dict(zip(col_names, row)) for row in raw_rows]
                columns = [{"name": c, "type": infer_col_type(c, compiled.table)} for c in col_names]
            else:
                # ORM instances (scalars)
                instances = result.scalars().all()
                field_names = list(FIELD_MAP.get(compiled.table, {}).keys())
                rows = [_model_to_dict(inst, compiled.table) for inst in instances]
                columns = [{"name": c, "type": infer_col_type(c, compiled.table)} for c in field_names]

        rows = serialize_rows(rows)

    except OQLError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())
    except Exception as e:
        logger.exception("OQL execute error: %s", e)
        raise HTTPException(status_code=500, detail={"error": f"Query execution failed: {e}", "position": -1})

    elapsed_ms = (time.monotonic() - start) * 1000

    # Record query history (best-effort, non-blocking)
    try:
        history_entry = QueryHistory(
            user_id=current_user.id,
            query_text=body.query,
            row_count=len(rows),
            duration_ms=elapsed_ms,
        )
        db.add(history_entry)
        await db.commit()
    except Exception as e:
        logger.warning("Failed to record query history: %s", e)

    return OQLResponse(
        columns=columns,
        rows=rows,
        total=total,
        query_time_ms=round(elapsed_ms, 2),
        visualization_hint=compiled.viz_hint,
    )


@router.post("/explain")
async def explain_oql(
    body: OQLRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the SQL that an OQL query would execute (debugging)."""
    try:
        compiled = compile_oql(body.query, limit=body.limit)
    except OQLError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())

    try:
        stmt = compiled.stmt
        compiled_stmt = stmt.compile(compile_kwargs={"literal_binds": False})
        sql_str = str(compiled_stmt)
        params = dict(compiled_stmt.params) if hasattr(compiled_stmt, "params") else {}
    except Exception as e:
        sql_str = f"[Could not compile: {e}]"
        params = {}

    return {
        "sql": sql_str,
        "params": params,
        "table": compiled.table,
        "visualization_hint": compiled.viz_hint,
        "is_aggregate": compiled.is_aggregate,
    }


@router.get("/schema")
async def oql_schema(
    current_user: User = Depends(get_current_user),
):
    """Return the full field schema for autocomplete."""
    return get_schema()


@router.get("/history")
async def oql_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Return recent query history for the current user."""
    result = await db.execute(
        select(QueryHistory)
        .where(QueryHistory.user_id == current_user.id)
        .order_by(QueryHistory.executed_at.desc())
        .limit(limit)
    )
    entries = result.scalars().all()
    return {
        "history": [
            {
                "id": str(e.id),
                "query_text": e.query_text,
                "executed_at": e.executed_at.isoformat() if e.executed_at else None,
                "row_count": e.row_count,
                "duration_ms": e.duration_ms,
            }
            for e in entries
        ]
    }


@router.post("/save")
async def save_query(
    body: SaveQueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save a named OQL query."""
    # Validate query before saving
    try:
        compile_oql(body.query_text, limit=1)
    except OQLError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())

    entry = SavedQuery(
        user_id=current_user.id,
        name=body.name,
        query_text=body.query_text,
        description=body.description,
        is_pinned=body.is_pinned,
        visualization_config=body.visualization_config,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return {
        "id": str(entry.id),
        "name": entry.name,
        "query_text": entry.query_text,
        "description": entry.description,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


@router.get("/saved")
async def list_saved_queries(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List saved queries for the current user."""
    result = await db.execute(
        select(SavedQuery)
        .where(SavedQuery.user_id == current_user.id)
        .order_by(SavedQuery.is_pinned.desc(), SavedQuery.created_at.desc())
    )
    entries = result.scalars().all()
    return {
        "saved": [
            {
                "id": str(e.id),
                "name": e.name,
                "query_text": e.query_text,
                "description": e.description,
                "is_pinned": e.is_pinned,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ]
    }


@router.delete("/saved/{query_id}")
async def delete_saved_query(
    query_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a saved query (must belong to current user)."""
    import uuid
    try:
        uid = uuid.UUID(query_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid query ID")

    result = await db.execute(
        select(SavedQuery)
        .where(SavedQuery.id == uid, SavedQuery.user_id == current_user.id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Saved query not found")

    await db.delete(entry)
    await db.commit()
    return {"deleted": True}
