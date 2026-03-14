"""Agent Access API — machine-consumable endpoints for Orthanc data.

Sprint 30 · Checkpoint 2 — Dual auth layer (JWT ∨ API-key).

Auth posture:
  ``get_agent_auth`` accepts EITHER a valid JWT bearer token (human session)
  OR a valid ``ow_<token>`` API key (machine client).  Revoked keys are
  rejected.  ``last_used_at`` is updated on successful API-key auth.
  Scope stamps are written to ``request.state`` so downstream ``require_scope``
  checks work correctly.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.middleware.api_key_auth import authenticate_api_key, _extract_raw_key
from app.middleware.scopes import (
    SCOPE_AGENT_READ,
    stamp_jwt_auth,
    stamp_api_key_scopes,
)
from app.models import ApiKey, Post, Source, User
from app.models.alert_rule import AlertEvent, AlertRule
from app.models.entity import Entity, EntityAlias, EntityMention
from app.models.entity_relationship import EntityRelationship
from app.models.narrative import Narrative, NarrativePost

logger = logging.getLogger("orthanc.routers.agent")

router = APIRouter(prefix="/agent", tags=["agent"])

# Optional Bearer extractor — auto_error=False so we can fall through to API-key logic
_optional_bearer = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


# ── Dual-auth dependency ──────────────────────────────────────────────────────


async def get_agent_auth(
    request: Request,
    db: AsyncSession = Depends(get_db),
    bearer_token: Optional[str] = Depends(_optional_bearer),
) -> User:
    """Dual-auth dependency for agent endpoints.

    Accepts either:
    - A valid JWT ``Authorization: Bearer <jwt>`` (human/session auth)
    - A valid ``Authorization: Bearer ow_<token>`` or ``X-API-Key: <token>``
      (machine/API-key auth)

    Revoked API keys are rejected with HTTP 401.
    On successful API-key auth, ``last_used_at`` is updated and the key's
    scopes are stamped onto ``request.state`` for scope checks.
    """
    # ── 1. Try JWT path ───────────────────────────────────────────────────
    # bearer_token is set by _optional_bearer if an Authorization: Bearer
    # header is present AND the token does NOT start with "ow_".
    # (ow_ prefix tokens fall through to API-key path below.)
    if bearer_token and not bearer_token.startswith("ow_"):
        try:
            payload = jwt.decode(
                bearer_token,
                settings.JWT_SECRET,
                algorithms=[settings.JWT_ALGORITHM],
            )
            if payload.get("type") != "access":
                raise JWTError("Not an access token")
            user_id: str = payload.get("sub")
            if not user_id:
                raise JWTError("Missing sub claim")
        except JWTError as exc:
            logger.debug("JWT decode failed in dual-auth: %s", exc)
            # Fall through to API-key path
        else:
            # Valid JWT — resolve user
            from sqlalchemy import select as sa_select
            result = await db.execute(
                sa_select(User).where(User.id == user_id)
            )
            user: User | None = result.scalar_one_or_none()
            if user is not None:
                stamp_jwt_auth(request)
                return user
            # JWT valid but user gone — fall through (will fail API-key too)

    # ── 2. Try API-key path ───────────────────────────────────────────────
    # authenticate_api_key handles header extraction, hashing, DB lookup,
    # revocation check, last_used_at update, and user resolution.
    # It raises HTTPException(401) if no valid key is found.
    raw_key = _extract_raw_key(request)
    if raw_key is not None:
        user = await authenticate_api_key(request, db)
        # Stamp scopes onto request state for downstream require_scope checks
        from sqlalchemy import select as _sel
        key_result = await db.execute(
            _sel(ApiKey).where(
                ApiKey.key_hash == __import__('hashlib').sha256(raw_key.encode()).hexdigest()
            )
        )
        api_key_obj: ApiKey | None = key_result.scalar_one_or_none()
        scopes = list(api_key_obj.scopes) if api_key_obj else []
        stamp_api_key_scopes(request, scopes)
        logger.info(
            "Agent endpoint accessed via API key: user=%s scopes=%s path=%s",
            user.username,
            scopes,
            request.url.path,
        )
        return user

    # ── 3. Nothing worked ─────────────────────────────────────────────────
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required: provide a valid JWT or API key",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _confidence_hint(score: float) -> str:
    """Convert a float score to a terse confidence label."""
    if score >= 0.80:
        return "high"
    if score >= 0.50:
        return "medium"
    return "low"


# ── GET /agent/sitrep ─────────────────────────────────────────────────────────


@router.get(
    "/sitrep",
    summary="Machine-readable situation report",
    response_description="Dense JSON snapshot of current intelligence state",
)
async def agent_sitrep(
    hours: int = Query(24, ge=1, le=168, description="Lookback window in hours"),
    narrative_limit: int = Query(10, ge=1, le=50),
    entity_limit: int = Query(15, ge=1, le=100),
    alert_limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_agent_auth),
) -> dict[str, Any]:
    """Return a dense situation report suitable for agent consumption.

    Includes:
    - ``meta``        — timestamp and query parameters
    - ``narratives``  — recent active narratives with confidence hints
    - ``alerts``      — recent alert events ordered by severity
    - ``entities``    — top entities by mention count
    - ``sources``     — source ingestion activity summary
    - ``feed_pulse``  — post volume by source type in the window
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    # ── Narratives ────────────────────────────────────────────────────────────
    narr_rows = (
        await db.execute(
            select(Narrative)
            .where(Narrative.status == "active", Narrative.last_updated >= cutoff)
            .order_by(desc(Narrative.post_count))
            .limit(narrative_limit)
        )
    ).scalars().all()

    narratives = [
        {
            "id": str(n.id),
            "title": n.canonical_title or n.title,
            "claim": n.canonical_claim,
            "status": n.status,
            "type": n.narrative_type,
            "confirmation": n.confirmation_status,
            "post_count": n.post_count,
            "source_count": n.source_count,
            "divergence_score": round(n.divergence_score, 3),
            "evidence_score": round(n.evidence_score, 3),
            "confidence": _confidence_hint(n.evidence_score),
            "consensus": n.consensus,
            "keywords": n.topic_keywords or [],
            "first_seen": _iso(n.first_seen),
            "last_updated": _iso(n.last_updated),
        }
        for n in narr_rows
    ]

    # ── Alert events ──────────────────────────────────────────────────────────
    _severity_order = {"flash": 0, "urgent": 1, "routine": 2}

    alert_event_rows = (
        await db.execute(
            select(AlertEvent, AlertRule.name, AlertRule.severity, AlertRule.rule_type)
            .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
            .where(AlertEvent.triggered_at >= cutoff)
            .order_by(desc(AlertEvent.triggered_at))
            .limit(alert_limit)
        )
    ).all()

    alerts = [
        {
            "id": str(row.AlertEvent.id),
            "rule_name": row.name,
            "severity": row.severity,
            "rule_type": row.rule_type,
            "summary": row.AlertEvent.summary,
            "triggered_at": _iso(row.AlertEvent.triggered_at),
            "post_count": row.AlertEvent.post_count,
            "entity_names": row.AlertEvent.entity_names or [],
        }
        for row in alert_event_rows
    ]
    # Sort: flash first, then urgent, then routine
    alerts.sort(key=lambda a: _severity_order.get(a["severity"], 9))

    # ── Top entities ──────────────────────────────────────────────────────────
    entity_rows = (
        await db.execute(
            select(Entity)
            .order_by(desc(Entity.mention_count))
            .limit(entity_limit)
        )
    ).scalars().all()

    entities = [
        {
            "id": str(e.id),
            "name": e.canonical_name or e.name,
            "type": e.type,
            "mention_count": e.mention_count,
            "first_seen": _iso(e.first_seen),
            "last_seen": _iso(e.last_seen),
        }
        for e in entity_rows
    ]

    # ── Source activity ───────────────────────────────────────────────────────
    source_rows = (
        await db.execute(
            select(Source)
            .where(Source.enabled.is_(True))
            .order_by(Source.last_polled.desc().nullslast())
            .limit(50)
        )
    ).scalars().all()

    sources = [
        {
            "name": s.display_name or s.handle,
            "type": s.type,
            "last_polled": _iso(s.last_polled),
            "health": (
                "pending" if s.last_polled is None
                else "stale" if (now - s.last_polled.replace(tzinfo=timezone.utc) if s.last_polled.tzinfo is None else now - s.last_polled).total_seconds() > 7200
                else "ok"
            ),
        }
        for s in source_rows
    ]

    # ── Feed pulse (post volume by source_type in window) ─────────────────────
    pulse_rows = (
        await db.execute(
            select(Post.source_type, func.count(Post.id).label("count"))
            .where(Post.ingested_at >= cutoff)
            .group_by(Post.source_type)
            .order_by(desc(func.count(Post.id)))
        )
    ).all()

    feed_pulse = {row.source_type: row.count for row in pulse_rows}
    total_posts_in_window = sum(feed_pulse.values())

    return {
        "meta": {
            "generated_at": _iso(now),
            "window_hours": hours,
            "endpoint": "sitrep",
        },
        "narratives": narratives,
        "alerts": alerts,
        "entities": entities,
        "sources": sources,
        "feed_pulse": {
            "window_hours": hours,
            "total_posts": total_posts_in_window,
            "by_source_type": feed_pulse,
        },
    }


# ── GET /agent/entities/{id}/dossier ─────────────────────────────────────────


@router.get(
    "/entities/{entity_id}/dossier",
    summary="Full entity dossier for agent consumption",
    response_description="Dense JSON entity profile",
)
async def agent_entity_dossier(
    entity_id: uuid.UUID,
    mention_limit: int = Query(20, ge=1, le=100, description="Recent mentions to include"),
    narrative_limit: int = Query(10, ge=1, le=50, description="Related narratives to include"),
    relationship_limit: int = Query(20, ge=1, le=100, description="Top relationships to include"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_agent_auth),
) -> dict[str, Any]:
    """Return a full entity dossier: core info, aliases, recent posts,
    related narratives, and co-occurrence relationships.

    All data is structured for direct machine consumption.
    """
    # ── Core entity ───────────────────────────────────────────────────────────
    entity = (
        await db.execute(select(Entity).where(Entity.id == entity_id))
    ).scalar_one_or_none()

    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")

    # ── Aliases ───────────────────────────────────────────────────────────────
    alias_rows = (
        await db.execute(
            select(EntityAlias)
            .where(EntityAlias.entity_id == entity_id)
            .order_by(desc(EntityAlias.confidence))
        )
    ).scalars().all()

    aliases = [
        {
            "text": a.alias_text,
            "confidence": round(a.confidence, 3),
            "source": a.source,
        }
        for a in alias_rows
    ]

    # ── Recent mentions (with post snippets) ─────────────────────────────────
    mention_rows = (
        await db.execute(
            select(EntityMention, Post)
            .join(Post, EntityMention.post_id == Post.id)
            .where(EntityMention.entity_id == entity_id)
            .order_by(desc(Post.timestamp))
            .limit(mention_limit)
        )
    ).all()

    recent_mentions = [
        {
            "post_id": str(row.EntityMention.post_id),
            "source_type": row.Post.source_type,
            "author": row.Post.author,
            "timestamp": _iso(row.Post.timestamp),
            "ingested_at": _iso(row.Post.ingested_at),
            "snippet": row.EntityMention.context_snippet or (
                (row.Post.content or "")[:300] if row.Post.content else None
            ),
        }
        for row in mention_rows
    ]

    # ── Related narratives (narratives where this entity appears in posts) ────
    # Sub-select: post IDs that mention this entity
    entity_post_ids_sq = (
        select(EntityMention.post_id)
        .where(EntityMention.entity_id == entity_id)
        .scalar_subquery()
    )

    narrative_rows = (
        await db.execute(
            select(Narrative)
            .join(NarrativePost, NarrativePost.narrative_id == Narrative.id)
            .where(NarrativePost.post_id.in_(entity_post_ids_sq))
            .distinct()
            .order_by(desc(Narrative.post_count))
            .limit(narrative_limit)
        )
    ).scalars().all()

    related_narratives = [
        {
            "id": str(n.id),
            "title": n.canonical_title or n.title,
            "claim": n.canonical_claim,
            "status": n.status,
            "type": n.narrative_type,
            "evidence_score": round(n.evidence_score, 3),
            "confidence": _confidence_hint(n.evidence_score),
            "post_count": n.post_count,
            "last_updated": _iso(n.last_updated),
        }
        for n in narrative_rows
    ]

    # ── Co-occurrence relationships ───────────────────────────────────────────
    rel_rows = (
        await db.execute(
            select(EntityRelationship, Entity)
            .join(
                Entity,
                (Entity.id == EntityRelationship.entity_a_id) | (Entity.id == EntityRelationship.entity_b_id),
            )
            .where(
                ((EntityRelationship.entity_a_id == entity_id) | (EntityRelationship.entity_b_id == entity_id))
                & (Entity.id != entity_id)
            )
            .order_by(desc(EntityRelationship.weight))
            .limit(relationship_limit)
        )
    ).all()

    relationships = [
        {
            "peer_entity_id": str(row.Entity.id),
            "peer_name": row.Entity.canonical_name or row.Entity.name,
            "peer_type": row.Entity.type,
            "relationship_type": row.EntityRelationship.relationship_type,
            "weight": row.EntityRelationship.weight,
            "confidence": round(row.EntityRelationship.confidence, 3),
            "first_seen": _iso(row.EntityRelationship.first_seen),
            "last_seen": _iso(row.EntityRelationship.last_seen),
        }
        for row in rel_rows
    ]

    return {
        "meta": {
            "generated_at": _iso(datetime.now(timezone.utc)),
            "endpoint": "entity_dossier",
            "entity_id": str(entity_id),
        },
        "entity": {
            "id": str(entity.id),
            "name": entity.name,
            "canonical_name": entity.canonical_name,
            "type": entity.type,
            "mention_count": entity.mention_count,
            "first_seen": _iso(entity.first_seen),
            "last_seen": _iso(entity.last_seen),
        },
        "aliases": aliases,
        "recent_mentions": recent_mentions,
        "related_narratives": related_narratives,
        "relationships": relationships,
    }


# ── GET /agent/feed/compact ───────────────────────────────────────────────────


@router.get(
    "/feed/compact",
    summary="Compact recent feed for agent consumption",
    response_description="Stripped post list with essential signal fields",
)
async def agent_feed_compact(
    hours: int = Query(6, ge=1, le=72, description="Lookback window in hours"),
    source_type: Optional[str] = Query(None, description="Filter by source type"),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_agent_auth),
) -> dict[str, Any]:
    """Return a stripped-down, agent-friendly post list.

    Useful for downstream agents that need raw signal without UI overhead.
    Fields: id, source_type, author, timestamp, snippet (first 500 chars),
    authenticity_score.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    q = select(Post).where(Post.ingested_at >= cutoff)
    if source_type:
        q = q.where(Post.source_type == source_type)
    q = q.order_by(desc(Post.ingested_at)).limit(limit)

    rows = (await db.execute(q)).scalars().all()

    posts = [
        {
            "id": str(p.id),
            "source_type": p.source_type,
            "source_id": p.source_id,
            "author": p.author,
            "timestamp": _iso(p.timestamp),
            "ingested_at": _iso(p.ingested_at),
            "snippet": (p.content or "")[:500] if p.content else None,
            "authenticity_score": round(p.authenticity_score, 3) if p.authenticity_score is not None else None,
            "media_type": p.media_type,
        }
        for p in rows
    ]

    return {
        "meta": {
            "generated_at": _iso(now),
            "window_hours": hours,
            "source_type_filter": source_type,
            "returned": len(posts),
            "endpoint": "feed_compact",
        },
        "posts": posts,
    }
