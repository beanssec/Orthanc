from datetime import datetime, timezone
from collections import defaultdict
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
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
    keywords = data.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]
    keywords = [str(k).strip().lower() for k in keywords if str(k).strip()]
    unique_keywords: list[str] = []
    for k in keywords:
        if k not in unique_keywords:
            unique_keywords.append(k)

    return {
        "keywords": unique_keywords,
        "min_divergence": float(data.get("min_divergence") or 0),
        "min_evidence": float(data.get("min_evidence") or 0),
    }


async def _get_latest_tracker_version(db: AsyncSession, tracker_id: uuid.UUID) -> NarrativeTrackerVersion | None:
    result = await db.execute(
        select(NarrativeTrackerVersion)
        .where(NarrativeTrackerVersion.tracker_id == tracker_id)
        .order_by(desc(NarrativeTrackerVersion.version))
        .limit(1)
    )
    return result.scalars().first()


async def _recompute_tracker(db: AsyncSession, tracker: NarrativeTracker, version: NarrativeTrackerVersion) -> dict:
    criteria = version.criteria or {}
    keywords = [str(k).strip().lower() for k in (criteria.get("keywords") or []) if str(k).strip()]
    min_divergence = float(criteria.get("min_divergence") or 0)
    min_evidence = float(criteria.get("min_evidence") or 0)

    result = await db.execute(
        select(Narrative)
        .where(
            Narrative.divergence_score >= min_divergence,
            Narrative.evidence_score >= min_evidence,
        )
        .order_by(desc(Narrative.last_updated))
    )
    candidates = result.scalars().all()

    # Replace prior match artifacts for current tracker version.
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

    matched: list[tuple[Narrative, float]] = []
    for n in candidates:
        haystack = " ".join([
            n.title or "",
            n.summary or "",
            " ".join(n.topic_keywords or []),
        ]).lower()

        score = 0.0
        if keywords:
            hits = sum(1 for kw in keywords if kw in haystack)
            if hits == 0:
                continue
            score = hits / max(len(keywords), 1)
        else:
            score = 1.0

        matched.append((n, score))

    month_rollup: dict[datetime, dict] = defaultdict(lambda: {
        "matched_narratives": 0,
        "total_posts": 0,
        "sum_divergence": 0.0,
        "sum_evidence": 0.0,
    })

    for narrative, score in matched:
        db.add(NarrativeTrackerMatch(
            tracker_id=tracker.id,
            tracker_version_id=version.id,
            narrative_id=narrative.id,
            match_score=score,
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
        items.append({
            "id": str(t.id),
            "name": t.name,
            "objective": t.objective,
            "status": t.status,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            "version": latest_version.version if latest_version else 0,
            "criteria": latest_version.criteria if latest_version else {},
        })
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
    criteria = _normalize_criteria(payload.get("criteria") or {})

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

    return {
        "id": str(tracker.id),
        "name": tracker.name,
        "objective": tracker.objective,
        "status": tracker.status,
        "version": 1,
        "criteria": criteria,
    }


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
        }
        for m, n in matches_result.all()
    ]

    return {
        "id": str(tracker.id),
        "name": tracker.name,
        "objective": tracker.objective,
        "status": tracker.status,
        "updated_at": tracker.updated_at.isoformat() if tracker.updated_at else None,
        "version": latest_version.version if latest_version else 0,
        "criteria": latest_version.criteria if latest_version else {},
        "matches": matches,
    }


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

    return {"status": "updated", "tracker_id": str(tracker.id)}


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
