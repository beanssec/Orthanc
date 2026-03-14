from datetime import datetime, timezone
from collections import defaultdict
import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger("orthanc.narratives")
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.user import User
from app.routers.auth import get_current_user
from app.models.narrative import (
    Narrative, NarrativePost, Claim, ClaimEvidence,
    SourceGroup, SourceGroupMember, SourceBiasProfile, PostEmbedding,
    NarrativeTracker, NarrativeTrackerVersion, NarrativeTrackerMatch, NarrativeTrackerMonthlySnapshot,
)
from app.models.post import Post
from app.models.source import Source

router = APIRouter(prefix="/narratives", tags=["narratives"])


# ─── Narratives ────────────────────────────────────────────────────────────────

@router.get("/")
async def list_narratives(
    status: str = Query("active", description="Filter by status: active, stale, resolved, all"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    min_divergence: float = Query(None, ge=0, le=1),
    min_posts: int = Query(None, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List narratives with filters."""
    query = select(Narrative)
    if status != "all":
        query = query.where(Narrative.status == status)
    if min_divergence is not None:
        query = query.where(Narrative.divergence_score >= min_divergence)
    if min_posts is not None:
        query = query.where(Narrative.post_count >= min_posts)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Get page
    query = query.order_by(desc(Narrative.last_updated)).offset(offset).limit(limit)
    result = await db.execute(query)
    narratives = result.scalars().all()

    return {
        "items": [_serialize_narrative(n) for n in narratives],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/trending")
async def trending_narratives(
    hours: int = Query(6, ge=1, le=72),
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Top narratives by post volume in the last N hours."""
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    result = await db.execute(
        select(Narrative)
        .where(Narrative.status == "active", Narrative.last_updated >= cutoff)
        .order_by(desc(Narrative.post_count))
        .limit(limit)
    )
    narratives = result.scalars().all()
    return [_serialize_narrative(n) for n in narratives]


@router.get("/source-groups/", tags=["source-groups"])
async def list_source_groups(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List all source groups with member counts."""
    result = await db.execute(select(SourceGroup).order_by(SourceGroup.name))
    groups = result.scalars().all()

    output = []
    for g in groups:
        # Count members
        count = await db.execute(
            select(func.count()).select_from(SourceGroupMember)
            .where(SourceGroupMember.source_group_id == g.id)
        )
        member_count = count.scalar() or 0

        # Get member source names
        members_result = await db.execute(
            select(Source.display_name, Source.type)
            .join(SourceGroupMember, SourceGroupMember.source_id == Source.id)
            .where(SourceGroupMember.source_group_id == g.id)
            .order_by(Source.display_name)
        )
        members = members_result.all()

        output.append({
            "id": str(g.id),
            "name": g.name,
            "display_name": g.display_name,
            "color": g.color,
            "description": g.description,
            "member_count": member_count,
            "members": [{"name": m[0], "type": m[1]} for m in members],
        })

    return output


@router.post("/source-groups/")
async def create_source_group(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a custom source group."""
    group = SourceGroup(
        name=data["name"],
        display_name=data.get("display_name", data["name"]),
        color=data.get("color", "#9ca3af"),
        description=data.get("description"),
    )
    db.add(group)
    await db.commit()
    return {"id": str(group.id), "name": group.name, "status": "created"}


@router.post("/source-groups/{group_id}/members")
async def add_group_member(
    group_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Add a source to a group."""
    import uuid
    member = SourceGroupMember(
        source_group_id=uuid.UUID(group_id),
        source_id=uuid.UUID(data["source_id"]),
    )
    db.add(member)
    try:
        await db.commit()
        return {"status": "added"}
    except Exception:
        await db.rollback()
        raise HTTPException(409, "Source already in this group")


@router.delete("/source-groups/{group_id}/members/{source_id}")
async def remove_group_member(
    group_id: str,
    source_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Remove a source from a group."""
    import uuid
    result = await db.execute(
        select(SourceGroupMember).where(
            SourceGroupMember.source_group_id == uuid.UUID(group_id),
            SourceGroupMember.source_id == uuid.UUID(source_id),
        )
    )
    member = result.scalars().first()
    if not member:
        raise HTTPException(404, "Member not found")
    await db.delete(member)
    await db.commit()
    return {"status": "removed"}


@router.get("/bias/profiles", tags=["bias"])
async def list_bias_profiles(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get latest bias profile for all sources."""
    result = await db.execute(
        select(SourceBiasProfile, Source.display_name, Source.type)
        .join(Source, Source.id == SourceBiasProfile.source_id)
        .order_by(desc(SourceBiasProfile.created_at))
    )
    profiles = result.all()

    # Deduplicate to latest per source
    seen = set()
    output = []
    for profile, source_name, source_type in profiles:
        if str(profile.source_id) in seen:
            continue
        seen.add(str(profile.source_id))
        output.append({
            "source_id": str(profile.source_id),
            "source_name": source_name,
            "source_type": source_type,
            "alignment_score": profile.alignment_score,
            "reliability_score": profile.reliability_score,
            "speed_rank": profile.speed_rank,
            "stance_distribution": profile.stance_distribution,
            "total_narratives": profile.total_narratives,
            "total_claims": profile.total_claims,
            "period_start": profile.period_start.isoformat() if profile.period_start else None,
            "period_end": profile.period_end.isoformat() if profile.period_end else None,
        })

    return output


@router.get("/bias/compass", tags=["bias"])
async def bias_compass(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Data for the bias compass scatter plot: alignment (x) vs reliability (y)."""
    result = await db.execute(
        select(SourceBiasProfile, Source.display_name, Source.type)
        .join(Source, Source.id == SourceBiasProfile.source_id)
        .order_by(desc(SourceBiasProfile.created_at))
    )
    profiles = result.all()

    # Get source group colors
    group_colors = {}
    groups_result = await db.execute(
        select(SourceGroupMember.source_id, SourceGroup.color, SourceGroup.name)
        .join(SourceGroup, SourceGroup.id == SourceGroupMember.source_group_id)
    )
    for source_id, color, group_name in groups_result.all():
        group_colors[str(source_id)] = {"color": color, "group": group_name}

    seen = set()
    points = []
    for profile, source_name, source_type in profiles:
        sid = str(profile.source_id)
        if sid in seen:
            continue
        seen.add(sid)

        if profile.alignment_score is None or profile.reliability_score is None:
            continue

        gc = group_colors.get(sid, {"color": "#9ca3af", "group": "unassigned"})
        points.append({
            "source_id": sid,
            "source_name": source_name,
            "source_type": source_type,
            "x": profile.alignment_score,   # -1 (western) to +1 (eastern)
            "y": profile.reliability_score,  # 0 (unreliable) to 1 (reliable)
            "color": gc["color"],
            "group": gc["group"],
        })

    return {"points": points}


# NOTE: static-prefix routes (/trending, /source-groups/*, /bias/*) must be
# registered BEFORE the wildcard /{narrative_id} routes so FastAPI doesn't
# greedily match them as UUIDs.

@router.get("/{narrative_id:uuid}")
async def get_narrative(
    narrative_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get full narrative detail with posts, stances, and claims."""
    result = await db.execute(
        select(Narrative).where(Narrative.id == narrative_id)
    )
    narrative = result.scalars().first()
    if not narrative:
        raise HTTPException(404, "Narrative not found")

    # Get posts with stances
    posts_result = await db.execute(
        select(NarrativePost, Post)
        .join(Post, Post.id == NarrativePost.post_id)
        .where(NarrativePost.narrative_id == narrative.id)
        .order_by(desc(Post.timestamp))
    )
    posts = posts_result.all()

    # Get claims
    claims_result = await db.execute(
        select(Claim)
        .where(Claim.narrative_id == narrative.id)
        .order_by(Claim.first_claimed_at)
    )
    claims = claims_result.scalars().all()

    # Get stance distribution by source group
    stance_by_group = await _get_stance_by_group(db, narrative.id)

    detail = _serialize_narrative(narrative)
    detail["posts"] = [
        {
            "id": str(post.id),
            "source_type": post.source_type,
            "author": post.author,
            "content": (post.content or "")[:500],
            "timestamp": post.timestamp.isoformat() if post.timestamp else None,
            "stance": np_row.stance,
            "stance_confidence": np_row.stance_confidence,
            "stance_summary": np_row.stance_summary,
        }
        for np_row, post in posts
    ]
    detail["claims"] = [
        {
            "id": str(c.id),
            "claim_text": c.claim_text,
            "claim_type": c.claim_type,
            "status": c.status,
            "evidence_count": c.evidence_count or 0,
            "first_claimed_at": c.first_claimed_at.isoformat() if c.first_claimed_at else None,
            "first_claimed_by": c.first_claimed_by,
            "location": {"lat": c.location_lat, "lng": c.location_lng} if c.location_lat else None,
        }
        for c in claims
    ]
    detail["stance_by_group"] = stance_by_group

    return detail


@router.get("/{narrative_id:uuid}/timeline")
async def narrative_timeline(
    narrative_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Hourly post count by source group for a narrative."""
    from collections import defaultdict

    # Get posts with source info
    result = await db.execute(
        select(Post.timestamp, Post.source_type, Post.source_id)
        .join(NarrativePost, NarrativePost.post_id == Post.id)
        .where(NarrativePost.narrative_id == narrative_id)
        .order_by(Post.timestamp)
    )
    posts = result.all()

    # Get source group memberships
    group_map = await _build_source_group_map(db)

    # Bucket by hour and group
    buckets: dict = defaultdict(lambda: defaultdict(int))
    for ts, source_type, source_id in posts:
        if not ts:
            continue
        hour = ts.replace(minute=0, second=0, microsecond=0)
        group = group_map.get(str(source_id), "unknown") if source_id else "unknown"
        buckets[hour.isoformat()][group] += 1

    return {"timeline": {k: dict(v) for k, v in buckets.items()}}


@router.get("/{narrative_id:uuid}/claims")
async def narrative_claims(
    narrative_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get all claims with their evidence for a narrative."""

    claims_result = await db.execute(
        select(Claim).where(Claim.narrative_id == narrative_id)
    )
    claims = claims_result.scalars().all()

    output = []
    for claim in claims:
        evidence_result = await db.execute(
            select(ClaimEvidence).where(ClaimEvidence.claim_id == claim.id)
        )
        evidence = evidence_result.scalars().all()

        output.append({
            "id": str(claim.id),
            "claim_text": claim.claim_text,
            "claim_type": claim.claim_type,
            "status": claim.status,
            "evidence_count": claim.evidence_count or 0,
            "first_claimed_at": claim.first_claimed_at.isoformat() if claim.first_claimed_at else None,
            "first_claimed_by": claim.first_claimed_by,
            "location": {"lat": claim.location_lat, "lng": claim.location_lng} if claim.location_lat else None,
            "entity_names": claim.entity_names or [],
            "evidence": [
                {
                    "id": str(e.id),
                    "evidence_type": e.evidence_type,
                    "evidence_source": e.evidence_source,
                    "supports": e.supports,
                    "confidence": e.confidence,
                    "detected_at": e.detected_at.isoformat() if e.detected_at else None,
                }
                for e in evidence
            ],
        })

    return output


@router.post("/{narrative_id:uuid}/refresh")
async def refresh_narrative(
    narrative_id: uuid.UUID,
    current_user=Depends(get_current_user),
):
    """Force re-cluster and re-classify a narrative (placeholder)."""
    return {"status": "refresh queued", "narrative_id": narrative_id}


# ─── Tracker APIs (FEAT-001) ──────────────────────────────────────────────────


def _ensure_trackers_enabled() -> None:
    if not settings.NARRATIVE_TRACKERS_ENABLED:
        raise HTTPException(status_code=404, detail="Narrative trackers are disabled")


def _month_bucket(ts: datetime) -> datetime:
    ts = ts.astimezone(timezone.utc)
    return datetime(ts.year, ts.month, 1, tzinfo=timezone.utc)


def _normalize_criteria(data: dict) -> dict:
    """Normalise and validate criteria dict stored in NarrativeTrackerVersion.

    Versioned search parameters for a tracker.  All fields are optional and
    additive — unknown keys are dropped to prevent criteria bloat.

    Supported fields
    ----------------
    keywords        : list[str] | comma-separated str  — full-text matching
    entity_ids      : list[str]  — entity UUIDs to restrict matching
    claim_patterns  : list[str]  — keyword/regex patterns for claim matching
    min_divergence  : float      — minimum narrative divergence score (0–1)
    min_evidence    : float      — minimum narrative evidence score (0–1)
    """
    # ── keywords ────────────────────────────────────────────────────────────
    keywords = data.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]
    keywords = [str(k).strip().lower() for k in keywords if str(k).strip()]
    unique_keywords: list[str] = []
    for k in keywords:
        if k not in unique_keywords:
            unique_keywords.append(k)

    # ── entity_ids ──────────────────────────────────────────────────────────
    entity_ids = data.get("entity_ids") or []
    if not isinstance(entity_ids, list):
        entity_ids = []
    entity_ids = [str(e).strip() for e in entity_ids if str(e).strip()]

    # ── claim_patterns ──────────────────────────────────────────────────────
    claim_patterns = data.get("claim_patterns") or []
    if not isinstance(claim_patterns, list):
        claim_patterns = []
    claim_patterns = [str(p).strip() for p in claim_patterns if str(p).strip()]

    return {
        "keywords": unique_keywords,
        "entity_ids": entity_ids,
        "claim_patterns": claim_patterns,
        "min_divergence": float(data.get("min_divergence") or 0),
        "min_evidence": float(data.get("min_evidence") or 0),
    }


def _serialize_tracker(
    tracker: "NarrativeTracker",
    latest_version: "NarrativeTrackerVersion | None",
) -> dict:
    """Shared serialization helper for NarrativeTracker responses."""
    return {
        "id": str(tracker.id),
        "name": tracker.name,
        # Legacy field retained for backward compat
        "objective": tracker.objective,
        # Sprint 26 CP1: richer hypothesis fields
        "description": tracker.description,
        "hypothesis": tracker.hypothesis,
        "entity_ids": tracker.entity_ids or [],
        "claim_patterns": tracker.claim_patterns or [],
        "model_policy": tracker.model_policy,
        "status": tracker.status,
        "created_at": tracker.created_at.isoformat() if tracker.created_at else None,
        "updated_at": tracker.updated_at.isoformat() if tracker.updated_at else None,
        "version": latest_version.version if latest_version else 0,
        "criteria": latest_version.criteria if latest_version else {},
    }


async def _get_latest_tracker_version(db: AsyncSession, tracker_id: uuid.UUID) -> NarrativeTrackerVersion | None:
    result = await db.execute(
        select(NarrativeTrackerVersion)
        .where(NarrativeTrackerVersion.tracker_id == tracker_id)
        .order_by(desc(NarrativeTrackerVersion.version))
        .limit(1)
    )
    return result.scalars().first()


def _compute_match_score(
    keyword_hit_rate: float,
    pattern_score: float,
    entity_score: float,
    has_keywords: bool,
    has_patterns: bool,
    has_entities: bool,
) -> float:
    """Compute composite match score from available signals.

    When only keywords are set this degrades to the old keyword_hit_rate
    behaviour exactly, so existing trackers are unaffected.
    """
    if not has_keywords and not has_patterns and not has_entities:
        return 1.0  # No criteria: match everything

    # Weights are assigned proportionally; absent signals contribute 0 weight.
    weighted_sum = 0.0
    total_weight = 0.0

    if has_keywords:
        w = 0.5 if (has_patterns or has_entities) else 1.0
        weighted_sum += keyword_hit_rate * w
        total_weight += w

    if has_patterns:
        w = 0.3
        weighted_sum += pattern_score * w
        total_weight += w

    if has_entities:
        w = 0.2
        weighted_sum += entity_score * w
        total_weight += w

    return weighted_sum / total_weight if total_weight > 0 else 0.0


def _classify_evidence_relation(
    narrative: "Narrative",
    match_score: float,
    pattern_matched: bool,
    entity_matched: bool,
    source_quality: float | None = None,
) -> str:
    """Heuristic evidence-relation classification.

    Returns one of: supports | contradicts | contextual | unclear

    Heuristics (in priority order):
    1. Strong refutation signals → contradicts
    2. Strong confirmation + high match → supports
    3. Medium relevance signal → contextual
    4. Fallback → unclear

    Sprint 29 CP2 — source_quality integration:
    When ``source_quality`` (average reliability weight of sources that
    contributed to this narrative, 0.0–1.0) is provided:
    - High quality (≥ 0.7): slightly lower threshold for "supports" — we trust
      the signal more.
    - Low quality (≤ 0.3): slightly raise threshold for "supports" — require
      stronger evidence before promoting to "supports".
    - None / absent: falls back to original thresholds exactly.

    This keeps the function additive and backward-safe.
    """
    confirmation = (narrative.confirmation_status or "").lower()
    consensus = (narrative.consensus or "").lower()

    # ── Threshold adjustment based on source quality ─────────────────────────
    # supports_threshold: min match_score to label as "supports" (high match path)
    # supports_evidence_threshold: min match_score when narrative confirms + evidence
    if source_quality is not None:
        if source_quality >= 0.7:
            # High-reliability sources → lower bar slightly
            supports_threshold = 0.65          # was 0.75
            supports_evidence_threshold = 0.50  # was 0.60
        elif source_quality <= 0.3:
            # Low-reliability sources → raise bar
            supports_threshold = 0.85          # was 0.75
            supports_evidence_threshold = 0.70  # was 0.60
        else:
            supports_threshold = 0.75
            supports_evidence_threshold = 0.60
    else:
        # No reliability data — original thresholds preserved exactly
        supports_threshold = 0.75
        supports_evidence_threshold = 0.60

    # ── 1. Refutation signals ────────────────────────────────────────────────
    if confirmation in ("refuted", "debunked", "false", "disproven") or \
            consensus in ("contradicted", "false", "debunked"):
        if match_score >= 0.25:
            return "contradicts"

    # ── 2. Confirmation / strong support signals ─────────────────────────────
    if match_score >= supports_evidence_threshold:
        if confirmation in ("confirmed", "verified", "true") or \
                narrative.evidence_score >= 0.6:
            return "supports"

    # High match rate alone is strong enough to be "supports"
    if match_score >= supports_threshold:
        return "supports"

    # ── 3. Medium relevance → contextual ────────────────────────────────────
    if match_score >= 0.35:
        return "contextual"
    if entity_matched and match_score >= 0.15:
        return "contextual"
    if pattern_matched and match_score >= 0.15:
        return "contextual"

    # ── 4. Fallback ──────────────────────────────────────────────────────────
    return "unclear"


async def _recompute_tracker(db: AsyncSession, tracker: NarrativeTracker, version: NarrativeTrackerVersion) -> dict:
    """Recompute matches for a tracker version using rich signal matching.

    Signal priority (all additive, all backward-safe):
      keywords       — from criteria (old behaviour preserved when only field set)
      claim_patterns — from criteria *union* tracker.claim_patterns
      entity_ids     — from criteria *union* tracker.entity_ids (resolved to names)

    Each match gets an evidence_relation classification via _classify_evidence_relation.

    Sprint 29 CP2 — source reliability integration:
    Before scoring candidates, a bulk reliability weight map is precomputed for
    all candidate narrative ids.  Each narrative's average source reliability
    weight is passed to ``_classify_evidence_relation`` as ``source_quality``,
    allowing the relation classification to be more precise when reliable sources
    are present.  Falls back to original thresholds when no reliability data
    exists (source_quality=None).

    Optional LLM assist (Sprint 26 CP3)
    ------------------------------------
    When ``tracker.model_policy`` has ``{"enabled": true}``, the top-N heuristic
    candidates are passed to ``llm_refine_batch`` which calls the model to
    re-classify ``evidence_relation``.  Heuristic values are preserved on any
    model failure — the LLM path is strictly additive and never blocks.
    """
    criteria = version.criteria or {}
    keywords = [str(k).strip().lower() for k in (criteria.get("keywords") or []) if str(k).strip()]
    min_divergence = float(criteria.get("min_divergence") or 0)
    min_evidence = float(criteria.get("min_evidence") or 0)

    # ── claim_patterns: union of criteria + tracker-level ───────────────────
    crit_patterns = [str(p).strip() for p in (criteria.get("claim_patterns") or []) if str(p).strip()]
    tracker_patterns = [str(p).strip() for p in (tracker.claim_patterns or []) if str(p).strip()]
    # dedup preserving order
    seen_pat: set[str] = set()
    merged_patterns: list[str] = []
    for p in crit_patterns + tracker_patterns:
        if p not in seen_pat:
            seen_pat.add(p)
            merged_patterns.append(p)

    compiled_patterns: list[re.Pattern] = []
    for pat in merged_patterns:
        try:
            compiled_patterns.append(re.compile(pat, re.IGNORECASE))
        except re.error:
            compiled_patterns.append(re.compile(re.escape(pat), re.IGNORECASE))

    # ── entity_ids: union of criteria + tracker-level, resolved to names ────
    crit_eids = [str(e).strip() for e in (criteria.get("entity_ids") or []) if str(e).strip()]
    tracker_eids = [str(e).strip() for e in (tracker.entity_ids or []) if str(e).strip()]
    merged_eids: list[str] = list(dict.fromkeys(crit_eids + tracker_eids))  # dedup, order-stable

    entity_names: list[str] = []
    if merged_eids:
        from app.models.entity import Entity as EntityModel
        valid_uuids: list[uuid.UUID] = []
        for eid in merged_eids:
            try:
                valid_uuids.append(uuid.UUID(eid))
            except ValueError:
                pass
        if valid_uuids:
            ent_result = await db.execute(
                select(EntityModel.canonical_name).where(EntityModel.id.in_(valid_uuids))
            )
            entity_names = [r[0].lower() for r in ent_result.all() if r[0]]

    has_keywords = bool(keywords)
    has_patterns = bool(compiled_patterns)
    has_entities = bool(entity_names)

    # ── Fetch candidates ─────────────────────────────────────────────────────
    result = await db.execute(
        select(Narrative)
        .where(
            Narrative.divergence_score >= min_divergence,
            Narrative.evidence_score >= min_evidence,
        )
        .order_by(desc(Narrative.last_updated))
    )
    candidates = result.scalars().all()

    # ── Replace prior match artefacts for this tracker version ───────────────
    old_matches = await db.execute(
        select(NarrativeTrackerMatch).where(
            NarrativeTrackerMatch.tracker_id == tracker.id,
            NarrativeTrackerMatch.tracker_version_id == version.id,
        )
    )
    for row in old_matches.scalars().all():
        await db.delete(row)

    old_snaps = await db.execute(
        select(NarrativeTrackerMonthlySnapshot).where(
            NarrativeTrackerMonthlySnapshot.tracker_id == tracker.id,
            NarrativeTrackerMonthlySnapshot.tracker_version_id == version.id,
        )
    )
    for row in old_snaps.scalars().all():
        await db.delete(row)

    # ── Sprint 29 CP2: precompute source reliability weights for all candidates ──
    # One bulk query covering all candidate narrative_ids; falls back to empty
    # dict (source_quality=None for all narratives) if the table is absent.
    narrative_reliability_weights: dict[uuid.UUID, float] = {}
    if candidates:
        try:
            from app.services.source_reliability_helper import (  # noqa: PLC0415
                fetch_narrative_reliability_weights,
            )
            candidate_ids = [n.id for n in candidates]
            narrative_reliability_weights = await fetch_narrative_reliability_weights(
                db, candidate_ids
            )
            if narrative_reliability_weights:
                logger.debug(
                    "Tracker %s: loaded reliability weights for %d/%d narratives",
                    tracker.id,
                    len(narrative_reliability_weights),
                    len(candidate_ids),
                )
        except Exception as exc:
            # Degrade safely — reliability weighting is strictly additive
            logger.debug(
                "Tracker %s: reliability weight preload failed (%s) — "
                "source_quality will be None for all narratives",
                tracker.id, exc,
            )

    # ── Score each candidate ─────────────────────────────────────────────────
    # Each entry: (narrative, score, pattern_matched, entity_matched, evidence_relation)
    matched: list[tuple[Narrative, float, bool, bool, str]] = []

    for n in candidates:
        haystack = " ".join([
            n.title or "",
            n.summary or "",
            n.canonical_claim or "",
            " ".join(n.topic_keywords or []),
        ]).lower()

        # keyword signal
        keyword_hit_rate = 0.0
        if has_keywords:
            hits = sum(1 for kw in keywords if kw in haystack)
            keyword_hit_rate = hits / len(keywords)

        # claim_pattern signal
        pattern_matched = False
        pattern_score = 0.0
        if has_patterns:
            pattern_hits = sum(1 for pat in compiled_patterns if pat.search(haystack))
            pattern_matched = pattern_hits > 0
            pattern_score = pattern_hits / len(compiled_patterns)

        # entity signal
        entity_matched = False
        entity_score = 0.0
        if has_entities:
            entity_hits = sum(1 for en in entity_names if en in haystack)
            entity_matched = entity_hits > 0
            entity_score = entity_hits / len(entity_names)

        # Filter: must have at least one signal hit when criteria are set
        if has_keywords or has_patterns or has_entities:
            if keyword_hit_rate == 0.0 and not pattern_matched and not entity_matched:
                continue

        score = _compute_match_score(
            keyword_hit_rate, pattern_score, entity_score,
            has_keywords, has_patterns, has_entities,
        )

        # Source quality hint for this narrative (None if no reliability data)
        source_quality = narrative_reliability_weights.get(n.id)

        # Heuristic evidence_relation — always computed as safe baseline
        heuristic_relation = _classify_evidence_relation(
            n, score, pattern_matched, entity_matched,
            source_quality=source_quality,
        )
        matched.append((n, score, pattern_matched, entity_matched, heuristic_relation))

    # ── Optional LLM refinement pass (Sprint 26 CP3) ─────────────────────────
    # Only activated when model_policy.enabled == true.  Falls back to heuristic
    # relations on any error — safe by design.
    llm_assist_used = False
    if matched and tracker.model_policy and tracker.model_policy.get("enabled"):
        try:
            from app.services.tracker_llm_assist import llm_refine_batch
            from app.services.model_router import model_router as _model_router
            matched = await llm_refine_batch(tracker, matched, _model_router)
            llm_assist_used = True
            logger.info(
                "LLM assist activated for tracker=%s (policy=%s)",
                tracker.id, tracker.model_policy,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "LLM assist import/invocation failed for tracker=%s: %s — "
                "heuristic relations preserved",
                tracker.id, exc,
            )

    # ── Create match rows with evidence_relation ─────────────────────────────
    month_rollup: dict[datetime, dict] = defaultdict(lambda: {
        "matched_narratives": 0,
        "total_posts": 0,
        "sum_divergence": 0.0,
        "sum_evidence": 0.0,
    })

    for narrative, score, pattern_matched, entity_matched, evidence_relation in matched:
        db.add(NarrativeTrackerMatch(
            tracker_id=tracker.id,
            tracker_version_id=version.id,
            narrative_id=narrative.id,
            match_score=score,
            evidence_relation=evidence_relation,
        ))
        month = _month_bucket(narrative.last_updated or narrative.created_at)
        bucket = month_rollup[month]
        bucket["matched_narratives"] += 1
        bucket["total_posts"] += (narrative.post_count or 0)
        bucket["sum_divergence"] += (narrative.divergence_score or 0)
        bucket["sum_evidence"] += (narrative.evidence_score or 0)

    for month, stats in month_rollup.items():
        count = max(stats["matched_narratives"], 1)
        db.add(NarrativeTrackerMonthlySnapshot(
            tracker_id=tracker.id,
            tracker_version_id=version.id,
            month_bucket=month,
            matched_narratives=stats["matched_narratives"],
            total_posts=stats["total_posts"],
            avg_divergence_score=stats["sum_divergence"] / count,
            avg_evidence_score=stats["sum_evidence"] / count,
        ))

    await db.commit()
    return {
        "matched_narratives": len(matched),
        "months": len(month_rollup),
        "keywords": keywords,
        "claim_patterns": merged_patterns,
        "entity_ids_resolved": len(entity_names),
        "llm_assist_used": llm_assist_used,
    }


@router.get("/trackers")
async def list_trackers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_trackers_enabled()
    result = await db.execute(
        select(NarrativeTracker)
        .where(NarrativeTracker.owner_user_id == current_user.id)
        .order_by(desc(NarrativeTracker.updated_at))
    )
    trackers = result.scalars().all()

    items = []
    for t in trackers:
        latest_version = await _get_latest_tracker_version(db, t.id)
        items.append(_serialize_tracker(t, latest_version))
    return {"trackers": items}


@router.post("/trackers")
async def create_tracker(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_trackers_enabled()
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    objective = (payload.get("objective") or "").strip() or None
    description = (payload.get("description") or "").strip() or None
    hypothesis = (payload.get("hypothesis") or "").strip() or None

    entity_ids = payload.get("entity_ids") or []
    if not isinstance(entity_ids, list):
        entity_ids = []
    entity_ids = [str(e).strip() for e in entity_ids if str(e).strip()]

    claim_patterns = payload.get("claim_patterns") or []
    if not isinstance(claim_patterns, list):
        claim_patterns = []
    claim_patterns = [str(p).strip() for p in claim_patterns if str(p).strip()]

    model_policy = payload.get("model_policy") if isinstance(payload.get("model_policy"), dict) else None

    # Build criteria from explicit criteria dict, but also allow top-level
    # shorthand (keywords passed at root level) for backward compat.
    raw_criteria = payload.get("criteria") or {}
    if not raw_criteria.get("keywords") and payload.get("keywords"):
        raw_criteria.setdefault("keywords", payload["keywords"])
    criteria = _normalize_criteria(raw_criteria)

    existing = await db.execute(
        select(NarrativeTracker).where(
            NarrativeTracker.owner_user_id == current_user.id,
            NarrativeTracker.name == name,
        )
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="Tracker with this name already exists")

    tracker = NarrativeTracker(
        owner_user_id=current_user.id,
        name=name,
        objective=objective,
        description=description,
        hypothesis=hypothesis,
        entity_ids=entity_ids or None,
        claim_patterns=claim_patterns or None,
        model_policy=model_policy,
        status="active",
    )
    db.add(tracker)
    await db.flush()

    version = NarrativeTrackerVersion(
        tracker_id=tracker.id,
        version=1,
        criteria=criteria,
        created_by_user_id=current_user.id,
    )
    db.add(version)
    await db.commit()

    return _serialize_tracker(tracker, version)


@router.get("/trackers/{tracker_id}")
async def get_tracker(
    tracker_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_trackers_enabled()
    tracker_uuid = uuid.UUID(tracker_id)
    result = await db.execute(
        select(NarrativeTracker).where(
            NarrativeTracker.id == tracker_uuid,
            NarrativeTracker.owner_user_id == current_user.id,
        )
    )
    tracker = result.scalars().first()
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")

    latest_version = await _get_latest_tracker_version(db, tracker.id)

    matches_result = await db.execute(
        select(NarrativeTrackerMatch, Narrative)
        .join(Narrative, Narrative.id == NarrativeTrackerMatch.narrative_id)
        .where(
            NarrativeTrackerMatch.tracker_id == tracker.id,
            NarrativeTrackerMatch.tracker_version_id == (latest_version.id if latest_version else None),
        )
        .order_by(desc(NarrativeTrackerMatch.match_score), desc(Narrative.last_updated))
        .limit(50)
    )

    matches = [
        {
            "narrative_id": str(n.id),
            "title": n.title,
            "status": n.status,
            "last_updated": n.last_updated.isoformat() if n.last_updated else None,
            "post_count": n.post_count or 0,
            "match_score": m.match_score,
            # Sprint 26 CP1: evidence_relation placeholder (populated by CP2 matching engine)
            "evidence_relation": m.evidence_relation,
        }
        for m, n in matches_result.all()
    ]

    detail = _serialize_tracker(tracker, latest_version)
    detail["matches"] = matches
    return detail


@router.patch("/trackers/{tracker_id}")
async def update_tracker(
    tracker_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_trackers_enabled()
    tracker_uuid = uuid.UUID(tracker_id)
    result = await db.execute(
        select(NarrativeTracker).where(
            NarrativeTracker.id == tracker_uuid,
            NarrativeTracker.owner_user_id == current_user.id,
        )
    )
    tracker = result.scalars().first()
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")

    name = payload.get("name")
    if isinstance(name, str) and name.strip():
        tracker.name = name.strip()

    if "objective" in payload:
        objective = payload.get("objective")
        tracker.objective = objective.strip() if isinstance(objective, str) and objective.strip() else None

    if "description" in payload:
        description = payload.get("description")
        tracker.description = description.strip() if isinstance(description, str) and description.strip() else None

    if "hypothesis" in payload:
        hypothesis = payload.get("hypothesis")
        tracker.hypothesis = hypothesis.strip() if isinstance(hypothesis, str) and hypothesis.strip() else None

    if "entity_ids" in payload:
        entity_ids = payload.get("entity_ids") or []
        if not isinstance(entity_ids, list):
            entity_ids = []
        tracker.entity_ids = [str(e).strip() for e in entity_ids if str(e).strip()] or None

    if "claim_patterns" in payload:
        claim_patterns = payload.get("claim_patterns") or []
        if not isinstance(claim_patterns, list):
            claim_patterns = []
        tracker.claim_patterns = [str(p).strip() for p in claim_patterns if str(p).strip()] or None

    if "model_policy" in payload:
        mp = payload.get("model_policy")
        tracker.model_policy = mp if isinstance(mp, dict) else None

    if "status" in payload and payload["status"] in {"active", "paused", "archived"}:
        tracker.status = payload["status"]

    if "criteria" in payload:
        latest_version = await _get_latest_tracker_version(db, tracker.id)
        next_version = (latest_version.version + 1) if latest_version else 1
        criteria = _normalize_criteria(payload.get("criteria") or {})
        db.add(NarrativeTrackerVersion(
            tracker_id=tracker.id,
            version=next_version,
            criteria=criteria,
            created_by_user_id=current_user.id,
        ))

    tracker.updated_at = datetime.now(timezone.utc)
    await db.commit()

    latest_version = await _get_latest_tracker_version(db, tracker.id)
    return _serialize_tracker(tracker, latest_version)


@router.post("/trackers/{tracker_id}/deactivate")
async def deactivate_tracker(
    tracker_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_trackers_enabled()
    tracker_uuid = uuid.UUID(tracker_id)
    result = await db.execute(
        select(NarrativeTracker).where(
            NarrativeTracker.id == tracker_uuid,
            NarrativeTracker.owner_user_id == current_user.id,
        )
    )
    tracker = result.scalars().first()
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")

    tracker.status = "paused"
    tracker.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "paused", "tracker_id": str(tracker.id)}


@router.get("/trackers/{tracker_id}/monthly")
async def tracker_monthly_timeline(
    tracker_id: str,
    months: int = Query(12, ge=1, le=36),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_trackers_enabled()
    tracker_uuid = uuid.UUID(tracker_id)
    tracker_result = await db.execute(
        select(NarrativeTracker).where(
            NarrativeTracker.id == tracker_uuid,
            NarrativeTracker.owner_user_id == current_user.id,
        )
    )
    tracker = tracker_result.scalars().first()
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")

    latest_version = await _get_latest_tracker_version(db, tracker.id)
    if not latest_version:
        return {"tracker_id": tracker_id, "timeline": []}

    snaps_result = await db.execute(
        select(NarrativeTrackerMonthlySnapshot)
        .where(
            NarrativeTrackerMonthlySnapshot.tracker_id == tracker.id,
            NarrativeTrackerMonthlySnapshot.tracker_version_id == latest_version.id,
        )
        .order_by(desc(NarrativeTrackerMonthlySnapshot.month_bucket))
        .limit(months)
    )
    rows = list(reversed(snaps_result.scalars().all()))

    return {
        "tracker_id": str(tracker.id),
        "version": latest_version.version,
        "timeline": [
            {
                "month": r.month_bucket.isoformat() if r.month_bucket else None,
                "matched_narratives": r.matched_narratives,
                "total_posts": r.total_posts,
                "avg_divergence_score": r.avg_divergence_score,
                "avg_evidence_score": r.avg_evidence_score,
            }
            for r in rows
        ],
    }


@router.post("/trackers/{tracker_id}/recompute")
async def recompute_tracker(
    tracker_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_trackers_enabled()
    tracker_uuid = uuid.UUID(tracker_id)
    tracker_result = await db.execute(
        select(NarrativeTracker).where(
            NarrativeTracker.id == tracker_uuid,
            NarrativeTracker.owner_user_id == current_user.id,
        )
    )
    tracker = tracker_result.scalars().first()
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")

    latest_version = await _get_latest_tracker_version(db, tracker.id)
    if not latest_version:
        raise HTTPException(status_code=400, detail="Tracker has no criteria version")

    summary = await _recompute_tracker(db, tracker, latest_version)
    tracker.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "recomputed", "tracker_id": str(tracker.id), "summary": summary}


# ─── Helper functions ──────────────────────────────────────────────────────────

def _serialize_narrative(n: Narrative) -> dict:
    return {
        "id": str(n.id),
        "title": n.title,
        "summary": n.summary,
        "status": n.status,
        "first_seen": n.first_seen.isoformat() if n.first_seen else None,
        "last_updated": n.last_updated.isoformat() if n.last_updated else None,
        "post_count": n.post_count or 0,
        "source_count": n.source_count or 0,
        "divergence_score": n.divergence_score or 0,
        "evidence_score": n.evidence_score or 0,
        "consensus": n.consensus,
        "topic_keywords": n.topic_keywords or [],
        # Canonical narrative intelligence fields (Sprint 25)
        "raw_title": n.raw_title,
        "canonical_title": n.canonical_title,
        "canonical_claim": n.canonical_claim,
        "narrative_type": n.narrative_type,
        "label_confidence": n.label_confidence,
        "confirmation_status": n.confirmation_status,
    }


async def _get_stance_by_group(db: AsyncSession, narrative_id) -> dict:
    """Get stance distribution grouped by source group."""
    # Build source_id → (group_name, color) map
    group_result = await db.execute(
        select(SourceGroupMember.source_id, SourceGroup.name, SourceGroup.color)
        .join(SourceGroup, SourceGroup.id == SourceGroupMember.source_group_id)
    )
    source_group_map: dict = {}
    for src_id, gname, gcolor in group_result.all():
        source_group_map[str(src_id)] = (gname, gcolor)

    # Get posts with stances
    result = await db.execute(
        select(Post.source_id, NarrativePost.stance)
        .join(Post, Post.id == NarrativePost.post_id)
        .where(NarrativePost.narrative_id == narrative_id)
    )
    rows = result.all()

    # Match posts to groups by checking if post.source_id is in the group map
    # source_id may be a UUID string or a name — try both
    groups: dict = {}
    for source_id, stance in rows:
        group_name, color = source_group_map.get(source_id, (None, None))
        if not group_name:
            # Try matching by source name in members table
            group_name = "unassigned"
            color = "#9ca3af"
        gname = group_name
        if gname not in groups:
            groups[gname] = {"color": color or "#9ca3af", "stances": {}}
        groups[gname]["stances"][stance or "unclassified"] = \
            groups[gname]["stances"].get(stance or "unclassified", 0) + 1

    return groups


async def _build_source_group_map(db: AsyncSession) -> dict:
    """Build a source_id → group_name mapping."""
    result = await db.execute(
        select(SourceGroupMember.source_id, SourceGroup.name)
        .join(SourceGroup, SourceGroup.id == SourceGroupMember.source_group_id)
    )
    return {str(row[0]): row[1] for row in result.all()}
