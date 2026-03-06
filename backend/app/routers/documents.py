"""Document upload and parsing router — accepts PDF, DOCX, TXT, MD, CSV."""
from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user
from app.models import Post, User
from app.models.entity import Entity, EntityMention
from app.models.event import Event
from app.routers.feed import broadcast_post
from app.services.entity_extractor import entity_extractor
from app.services.geo_extractor import geo_extractor

logger = logging.getLogger("orthanc.documents")

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_CONTENT_CHARS = 50_000

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv"}
ALLOWED_MIME_PREFIXES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml",
    "text/",
    "application/octet-stream",  # browser fallback for .docx/.pdf
)


def _extract_text_from_pdf(data: bytes) -> tuple[str, int]:
    """Extract text from PDF bytes. Returns (text, page_count)."""
    try:
        from pdfminer.high_level import extract_text as pdf_extract_text
        from pdfminer.pdfpage import PDFPage

        # Count pages
        page_count = 0
        try:
            page_count = sum(1 for _ in PDFPage.get_pages(io.BytesIO(data)))
        except Exception:
            page_count = 0

        text = pdf_extract_text(io.BytesIO(data))
        return (text or "").strip(), page_count
    except Exception as exc:
        logger.warning("PDF extraction error: %s", exc)
        return "", 0


def _extract_text_from_docx(data: bytes) -> tuple[str, int]:
    """Extract text from DOCX bytes. Returns (text, page_count)."""
    try:
        import docx  # python-docx

        doc = docx.Document(io.BytesIO(data))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n\n".join(paragraphs)
        return text.strip(), 0  # DOCX doesn't expose page count easily
    except Exception as exc:
        logger.warning("DOCX extraction error: %s", exc)
        return "", 0


def _extract_text_from_csv(data: bytes) -> tuple[str, int]:
    """Read CSV as structured text rows. Returns (text, 0)."""
    try:
        import csv

        decoded = data.decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(decoded))
        rows = [" | ".join(row) for row in reader if any(cell.strip() for cell in row)]
        return "\n".join(rows).strip(), 0
    except Exception as exc:
        logger.warning("CSV extraction error: %s", exc)
        return data.decode("utf-8", errors="replace").strip(), 0


def _extract_text(filename: str, data: bytes) -> tuple[str, int]:
    """Dispatch text extraction by file extension. Returns (text, pages)."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == ".pdf":
        return _extract_text_from_pdf(data)
    elif ext == ".docx":
        return _extract_text_from_docx(data)
    elif ext == ".csv":
        return _extract_text_from_csv(data)
    else:
        # TXT, MD, and anything else — decode as UTF-8
        try:
            return data.decode("utf-8", errors="replace").strip(), 0
        except Exception:
            return "", 0


@router.post("/upload", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: Optional[str] = Form(default=None),
    source_label: Optional[str] = Form(default="upload"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Upload a document (PDF, DOCX, TXT, MD, CSV) → extract text → create post → run NER."""
    # Validate filename / extension
    filename = file.filename or "unknown"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # Read file data (enforce 50 MB limit)
    raw_data = await file.read()
    if len(raw_data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(raw_data) // (1024*1024)} MB). Max 50 MB.",
        )

    file_size = len(raw_data)
    file_type = ext.lstrip(".")

    # Extract text
    raw_text, page_count = _extract_text(filename, raw_data)
    if not raw_text.strip():
        logger.warning("Document %r yielded no extractable text", filename)

    content = raw_text[:MAX_CONTENT_CHARS]
    doc_title = title or filename

    # Create Post record
    post = Post(
        source_type="document",
        source_id=filename,
        author=current_user.username,
        content=content,
        raw_json={
            "filename": filename,
            "file_type": file_type,
            "file_size": file_size,
            "pages": page_count,
            "title": doc_title,
            "char_count": len(raw_text),
            "truncated": len(raw_text) > MAX_CONTENT_CHARS,
        },
        timestamp=datetime.now(tz=timezone.utc),
    )
    db.add(post)
    await db.flush()

    # Broadcast live
    await broadcast_post({
        "id": str(post.id),
        "source_type": post.source_type,
        "source_id": post.source_id,
        "author": post.author,
        "content": post.content,
        "timestamp": post.timestamp.isoformat() if post.timestamp else None,
        "ingested_at": post.ingested_at.isoformat() if post.ingested_at else None,
        "event": None,
    })

    # --- Async NER (non-blocking) ---
    entities_count = 0
    events_count = 0

    # Geo extraction
    try:
        geo_events = await geo_extractor.process_post(str(post.id), content)
        for evt in geo_events:
            event = Event(
                post_id=post.id,
                lat=evt["lat"],
                lng=evt["lng"],
                place_name=evt["place_name"],
                confidence=evt["confidence"],
            )
            db.add(event)
        events_count = len(geo_events)
    except Exception as geo_exc:
        logger.warning("Geo extraction failed for document post %s: %s", post.id, geo_exc)

    # Entity extraction
    try:
        extracted = entity_extractor.extract_entities(content)
        entities_count = len(extracted)
        for ent in extracted:
            canonical = entity_extractor.canonical_name(ent["name"])
            existing_ent = await db.execute(
                select(Entity).where(
                    Entity.canonical_name == canonical,
                    Entity.type == ent["type"],
                )
            )
            entity_obj = existing_ent.scalar_one_or_none()
            if entity_obj:
                entity_obj.mention_count += 1
                entity_obj.last_seen = datetime.now(tz=timezone.utc)
            else:
                entity_obj = Entity(
                    name=ent["name"],
                    type=ent["type"],
                    canonical_name=canonical,
                    mention_count=1,
                )
                db.add(entity_obj)
                await db.flush()
            mention = EntityMention(
                entity_id=entity_obj.id,
                post_id=post.id,
                context_snippet=ent["context_snippet"],
            )
            db.add(mention)
    except Exception as ent_exc:
        logger.warning("Entity extraction failed for document post %s: %s", post.id, ent_exc)

    await db.commit()
    await db.refresh(post)

    logger.info(
        "Document uploaded: post %s | file=%r | size=%d bytes | text=%d chars | entities=%d | events=%d",
        post.id, filename, file_size, len(content), entities_count, events_count,
    )

    return {
        "id": str(post.id),
        "filename": filename,
        "title": doc_title,
        "file_type": file_type,
        "file_size": file_size,
        "text_length": len(content),
        "pages": page_count,
        "entities_found": entities_count,
        "events_found": events_count,
        "timestamp": post.timestamp.isoformat() if post.timestamp else None,
    }


@router.get("/")
async def list_documents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """List uploaded documents (posts with source_type='document')."""
    offset = (page - 1) * page_size

    q = (
        select(Post)
        .where(Post.source_type == "document")
        .order_by(Post.timestamp.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(q)
    posts = result.scalars().all()

    # Count total
    from sqlalchemy import func
    count_q = select(func.count()).where(Post.source_type == "document").select_from(Post)
    count_result = await db.execute(count_q)
    total = count_result.scalar_one()

    items = []
    for p in posts:
        rj = p.raw_json or {}
        items.append({
            "id": str(p.id),
            "filename": rj.get("filename", p.source_id),
            "title": rj.get("title", p.source_id),
            "file_type": rj.get("file_type", ""),
            "file_size": rj.get("file_size", 0),
            "pages": rj.get("pages", 0),
            "char_count": rj.get("char_count", len(p.content or "")),
            "author": p.author,
            "timestamp": p.timestamp.isoformat() if p.timestamp else None,
            "ingested_at": p.ingested_at.isoformat() if p.ingested_at else None,
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }
