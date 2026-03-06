"""Investigation case management endpoints."""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user
from app.models import User
from app.models.case import Case, CaseItem, CaseTimeline

router = APIRouter(prefix="/cases", tags=["cases"])


# ── Pydantic schemas ───────────────────────────────────────

class CaseCreate(BaseModel):
    title: str
    description: Optional[str] = None
    classification: str = "unclassified"


class CaseUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    classification: Optional[str] = None


class CaseItemCreate(BaseModel):
    item_type: str
    item_id: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    metadata: Optional[dict] = None


# ── Helpers ────────────────────────────────────────────────

def _case_to_dict(case: Case) -> dict:
    return {
        "id": str(case.id),
        "user_id": str(case.user_id),
        "title": case.title,
        "description": case.description,
        "classification": case.classification,
        "status": case.status,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
        "item_count": len(case.items) if case.items else 0,
    }


def _item_to_dict(item: CaseItem) -> dict:
    return {
        "id": str(item.id),
        "case_id": str(item.case_id),
        "item_type": item.item_type,
        "item_id": str(item.item_id) if item.item_id else None,
        "title": item.title,
        "content": item.content,
        "lat": item.lat,
        "lng": item.lng,
        "metadata": item.metadata_ or {},
        "added_by": str(item.added_by) if item.added_by else None,
        "added_at": item.added_at.isoformat() if item.added_at else None,
    }


def _timeline_to_dict(entry: CaseTimeline) -> dict:
    return {
        "id": str(entry.id),
        "case_id": str(entry.case_id),
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
        "event_type": entry.event_type,
        "description": entry.description,
        "added_by": str(entry.added_by) if entry.added_by else None,
    }


async def _add_timeline(
    db: AsyncSession,
    case_id: uuid.UUID,
    event_type: str,
    description: str,
    user_id: uuid.UUID,
) -> None:
    entry = CaseTimeline(
        case_id=case_id,
        event_type=event_type,
        description=description,
        added_by=user_id,
    )
    db.add(entry)


async def _get_case_or_404(db: AsyncSession, case_id: str, user_id: uuid.UUID) -> Case:
    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Case not found")
    result = await db.execute(select(Case).where(Case.id == cid, Case.user_id == user_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


# ── Case CRUD ──────────────────────────────────────────────

@router.post("/", status_code=201)
async def create_case(
    body: CaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = Case(
        user_id=current_user.id,
        title=body.title,
        description=body.description,
        classification=body.classification,
        status="open",
    )
    db.add(case)
    await db.flush()

    await _add_timeline(
        db, case.id, "created",
        f'Case "{case.title}" created',
        current_user.id,
    )
    await db.commit()
    await db.refresh(case)
    return _case_to_dict(case)


@router.get("/")
async def list_cases(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(Case).where(Case.user_id == current_user.id)
    if status_filter:
        q = q.where(Case.status == status_filter)
    q = q.order_by(Case.updated_at.desc())
    result = await db.execute(q)
    cases = result.scalars().all()
    return [_case_to_dict(c) for c in cases]


@router.get("/{case_id}")
async def get_case(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = await _get_case_or_404(db, case_id, current_user.id)
    data = _case_to_dict(case)
    data["items"] = [_item_to_dict(i) for i in sorted(case.items, key=lambda x: x.added_at, reverse=True)]
    data["timeline"] = [_timeline_to_dict(t) for t in sorted(case.timeline, key=lambda x: x.timestamp, reverse=True)]
    return data


@router.put("/{case_id}")
async def update_case(
    case_id: str,
    body: CaseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = await _get_case_or_404(db, case_id, current_user.id)
    changes = []
    if body.title is not None and body.title != case.title:
        changes.append(f"title → {body.title}")
        case.title = body.title
    if body.description is not None:
        case.description = body.description
    if body.status is not None and body.status != case.status:
        changes.append(f"status {case.status} → {body.status}")
        case.status = body.status
    if body.classification is not None and body.classification != case.classification:
        changes.append(f"classification → {body.classification}")
        case.classification = body.classification

    case.updated_at = datetime.now(timezone.utc)

    if changes:
        await _add_timeline(
            db, case.id, "status_changed" if body.status else "updated",
            "; ".join(changes),
            current_user.id,
        )
    await db.commit()
    await db.refresh(case)
    return _case_to_dict(case)


@router.delete("/{case_id}", status_code=204)
async def delete_case(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = await _get_case_or_404(db, case_id, current_user.id)
    await db.delete(case)
    await db.commit()


# ── Case Items ─────────────────────────────────────────────

@router.post("/{case_id}/items", status_code=201)
async def add_item(
    case_id: str,
    body: CaseItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = await _get_case_or_404(db, case_id, current_user.id)

    item_id = None
    if body.item_id:
        try:
            item_id = uuid.UUID(body.item_id)
        except ValueError:
            pass

    item = CaseItem(
        case_id=case.id,
        item_type=body.item_type,
        item_id=item_id,
        title=body.title,
        content=body.content,
        lat=body.lat,
        lng=body.lng,
        metadata_=body.metadata or {},
        added_by=current_user.id,
    )
    db.add(item)
    await db.flush()

    event_type = "note_added" if body.item_type == "note" else "item_added"
    desc = f'Added {body.item_type}: {body.title or str(item_id) or "unnamed"}'
    await _add_timeline(db, case.id, event_type, desc, current_user.id)

    case.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(item)
    return _item_to_dict(item)


@router.delete("/{case_id}/items/{item_id}", status_code=204)
async def remove_item(
    case_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = await _get_case_or_404(db, case_id, current_user.id)
    try:
        iid = uuid.UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Item not found")

    result = await db.execute(
        select(CaseItem).where(CaseItem.id == iid, CaseItem.case_id == case.id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    desc = f'Removed {item.item_type}: {item.title or str(item.item_id) or "unnamed"}'
    await _add_timeline(db, case.id, "item_removed", desc, current_user.id)

    await db.delete(item)
    case.updated_at = datetime.now(timezone.utc)
    await db.commit()


# ── Case Timeline ──────────────────────────────────────────

@router.get("/{case_id}/timeline")
async def get_timeline(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = await _get_case_or_404(db, case_id, current_user.id)
    entries = sorted(case.timeline, key=lambda x: x.timestamp, reverse=True)
    return [_timeline_to_dict(e) for e in entries]


# ── Export PDF ─────────────────────────────────────────────

@router.get("/{case_id}/export/pdf")
async def export_pdf(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = await _get_case_or_404(db, case_id, current_user.id)

    # Build markdown content for the PDF
    lines = []
    lines.append(f"# {case.title}")
    lines.append(f"")
    if case.description:
        lines.append(case.description)
        lines.append("")

    lines.append(f"**Status:** {case.status.upper()}  |  **Classification:** {case.classification.upper()}")
    lines.append(f"**Created:** {case.created_at.strftime('%Y-%m-%d %H:%M UTC') if case.created_at else 'Unknown'}")
    lines.append(f"**Items:** {len(case.items)}")
    lines.append("")

    if case.items:
        lines.append("## Evidence Items")
        for item in sorted(case.items, key=lambda x: x.added_at):
            type_label = item.item_type.upper()
            title_part = item.title or (str(item.item_id) if item.item_id else "Untitled")
            lines.append(f"- **[{type_label}]** {title_part}")
            if item.content:
                snippet = item.content[:200] + ("…" if len(item.content) > 200 else "")
                lines.append(f"  {snippet}")
            if item.lat and item.lng:
                lines.append(f"  📍 {item.lat:.4f}, {item.lng:.4f}")
        lines.append("")

    if case.timeline:
        lines.append("## Activity Log")
        for entry in sorted(case.timeline, key=lambda x: x.timestamp):
            ts = entry.timestamp.strftime("%Y-%m-%d %H:%M") if entry.timestamp else "?"
            lines.append(f"- **{ts}** — {entry.description or entry.event_type}")

    summary = "\n".join(lines)

    # Use existing OrthanIntelReport-style PDF generation
    from app.services.pdf_report import pdf_report as _report_gen

    brief_data = {
        "summary": summary,
        "model_name": "Case Export",
        "hours": 0,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "post_count": len(case.items),
    }
    pdf_bytes = _report_gen.generate(brief_data)

    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in case.title)[:50]
    filename = f"case_{safe_title.replace(' ', '_')}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
