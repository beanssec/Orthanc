"""Collaboration router — notes, bookmarks, tags."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user
from app.models import User
from app.models.collaboration import UserBookmark, UserNote, UserTag

router = APIRouter(tags=["collaboration"])

VALID_TARGET_TYPES = {"entity", "post", "event", "brief"}


# ── Pydantic schemas ──────────────────────────────────────
class NoteCreate(BaseModel):
    content: str


class NoteUpdate(BaseModel):
    content: str


class BookmarkCreate(BaseModel):
    label: Optional[str] = None


class TagCreate(BaseModel):
    tag: str


# ── Helpers ───────────────────────────────────────────────
def _note_dict(n: UserNote) -> dict:
    return {
        "id": str(n.id),
        "user_id": str(n.user_id),
        "target_type": n.target_type,
        "target_id": str(n.target_id),
        "content": n.content,
        "created_at": n.created_at.isoformat(),
        "updated_at": n.updated_at.isoformat(),
    }


def _bookmark_dict(b: UserBookmark) -> dict:
    return {
        "id": str(b.id),
        "user_id": str(b.user_id),
        "target_type": b.target_type,
        "target_id": str(b.target_id),
        "label": b.label,
        "created_at": b.created_at.isoformat(),
    }


def _tag_dict(t: UserTag) -> dict:
    return {
        "id": str(t.id),
        "user_id": str(t.user_id),
        "target_type": t.target_type,
        "target_id": str(t.target_id),
        "tag": t.tag,
        "created_at": t.created_at.isoformat(),
    }


# ═══════════════════════════════════════════════════════════
# NOTES
# ═══════════════════════════════════════════════════════════

@router.get("/notes/{target_type}/{target_id}")
async def get_notes(
    target_type: str,
    target_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    if target_type not in VALID_TARGET_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid target_type. Valid: {sorted(VALID_TARGET_TYPES)}")
    result = await db.execute(
        select(UserNote)
        .where(UserNote.target_type == target_type, UserNote.target_id == target_id)
        .order_by(UserNote.created_at.desc())
    )
    return [_note_dict(n) for n in result.scalars().all()]


@router.post("/notes/{target_type}/{target_id}", status_code=201)
async def create_note(
    target_type: str,
    target_id: uuid.UUID,
    body: NoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if target_type not in VALID_TARGET_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid target_type. Valid: {sorted(VALID_TARGET_TYPES)}")
    note = UserNote(
        user_id=current_user.id,
        target_type=target_type,
        target_id=target_id,
        content=body.content,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return _note_dict(note)


@router.put("/notes/{note_id}")
async def update_note(
    note_id: uuid.UUID,
    body: NoteUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    result = await db.execute(select(UserNote).where(UserNote.id == note_id))
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your note")
    note.content = body.content
    note.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(note)
    return _note_dict(note)


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(
    note_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await db.execute(select(UserNote).where(UserNote.id == note_id))
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your note")
    await db.delete(note)
    await db.commit()


# ═══════════════════════════════════════════════════════════
# BOOKMARKS
# ═══════════════════════════════════════════════════════════

@router.get("/bookmarks/check/{target_type}/{target_id}")
async def check_bookmark(
    target_type: str,
    target_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    result = await db.execute(
        select(UserBookmark).where(
            UserBookmark.user_id == current_user.id,
            UserBookmark.target_type == target_type,
            UserBookmark.target_id == target_id,
        )
    )
    bm = result.scalar_one_or_none()
    return {"bookmarked": bm is not None, "bookmark": _bookmark_dict(bm) if bm else None}


@router.get("/bookmarks/")
async def list_bookmarks(
    target_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    query = select(UserBookmark).where(UserBookmark.user_id == current_user.id)
    if target_type:
        query = query.where(UserBookmark.target_type == target_type)
    query = query.order_by(UserBookmark.created_at.desc())
    result = await db.execute(query)
    return [_bookmark_dict(b) for b in result.scalars().all()]


@router.post("/bookmarks/{target_type}/{target_id}", status_code=201)
async def add_bookmark(
    target_type: str,
    target_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    body: Optional[BookmarkCreate] = None,
) -> dict:
    if target_type not in VALID_TARGET_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid target_type. Valid: {sorted(VALID_TARGET_TYPES)}")

    existing = await db.execute(
        select(UserBookmark).where(
            UserBookmark.user_id == current_user.id,
            UserBookmark.target_type == target_type,
            UserBookmark.target_id == target_id,
        )
    )
    bm = existing.scalar_one_or_none()
    if bm:
        return _bookmark_dict(bm)

    bm = UserBookmark(
        user_id=current_user.id,
        target_type=target_type,
        target_id=target_id,
        label=body.label if body else None,
    )
    db.add(bm)
    await db.commit()
    await db.refresh(bm)
    return _bookmark_dict(bm)


@router.delete("/bookmarks/{target_type}/{target_id}", status_code=204)
async def remove_bookmark(
    target_type: str,
    target_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await db.execute(
        select(UserBookmark).where(
            UserBookmark.user_id == current_user.id,
            UserBookmark.target_type == target_type,
            UserBookmark.target_id == target_id,
        )
    )
    bm = result.scalar_one_or_none()
    if bm:
        await db.delete(bm)
        await db.commit()


# ═══════════════════════════════════════════════════════════
# TAGS
# ═══════════════════════════════════════════════════════════

@router.get("/tags/search")
async def search_tags(
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    result = await db.execute(
        select(UserTag).where(
            UserTag.user_id == current_user.id,
            UserTag.tag.ilike(f"%{q}%"),
        ).order_by(UserTag.created_at.desc())
    )
    return [_tag_dict(t) for t in result.scalars().all()]


@router.get("/tags/{target_type}/{target_id}")
async def get_tags(
    target_type: str,
    target_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    result = await db.execute(
        select(UserTag).where(
            UserTag.user_id == current_user.id,
            UserTag.target_type == target_type,
            UserTag.target_id == target_id,
        ).order_by(UserTag.tag)
    )
    return [_tag_dict(t) for t in result.scalars().all()]


@router.post("/tags/{target_type}/{target_id}", status_code=201)
async def add_tag(
    target_type: str,
    target_id: uuid.UUID,
    body: TagCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if target_type not in VALID_TARGET_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid target_type. Valid: {sorted(VALID_TARGET_TYPES)}")

    tag_value = body.tag.strip().lower()
    if not tag_value:
        raise HTTPException(status_code=400, detail="Tag cannot be empty")

    existing = await db.execute(
        select(UserTag).where(
            UserTag.user_id == current_user.id,
            UserTag.target_type == target_type,
            UserTag.target_id == target_id,
            UserTag.tag == tag_value,
        )
    )
    ut = existing.scalar_one_or_none()
    if ut:
        return _tag_dict(ut)

    ut = UserTag(
        user_id=current_user.id,
        target_type=target_type,
        target_id=target_id,
        tag=tag_value,
    )
    db.add(ut)
    await db.commit()
    await db.refresh(ut)
    return _tag_dict(ut)


@router.delete("/tags/{target_type}/{target_id}/{tag}", status_code=204)
async def remove_tag(
    target_type: str,
    target_id: uuid.UUID,
    tag: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await db.execute(
        select(UserTag).where(
            UserTag.user_id == current_user.id,
            UserTag.target_type == target_type,
            UserTag.target_id == target_id,
            UserTag.tag == tag.lower(),
        )
    )
    ut = result.scalar_one_or_none()
    if ut:
        await db.delete(ut)
        await db.commit()
