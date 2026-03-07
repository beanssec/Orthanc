from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.routers.auth import get_current_user
from app.models.narrative import (
    Narrative, NarrativePost, Claim, ClaimEvidence,
    SourceGroup, SourceGroupMember, SourceBiasProfile, PostEmbedding,
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

@router.get("/{narrative_id}")
async def get_narrative(
    narrative_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get full narrative detail with posts, stances, and claims."""
    import uuid
    result = await db.execute(
        select(Narrative).where(Narrative.id == uuid.UUID(narrative_id))
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


@router.get("/{narrative_id}/timeline")
async def narrative_timeline(
    narrative_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Hourly post count by source group for a narrative."""
    import uuid
    from collections import defaultdict

    # Get posts with source info
    result = await db.execute(
        select(Post.timestamp, Post.source_type, Source.id.label("source_id"))
        .join(NarrativePost, NarrativePost.post_id == Post.id)
        .outerjoin(Source, Source.id == Post.source_id)
        .where(NarrativePost.narrative_id == uuid.UUID(narrative_id))
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


@router.get("/{narrative_id}/claims")
async def narrative_claims(
    narrative_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get all claims with their evidence for a narrative."""
    import uuid

    claims_result = await db.execute(
        select(Claim).where(Claim.narrative_id == uuid.UUID(narrative_id))
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


@router.post("/{narrative_id}/refresh")
async def refresh_narrative(
    narrative_id: str,
    current_user=Depends(get_current_user),
):
    """Force re-cluster and re-classify a narrative (placeholder)."""
    return {"status": "refresh queued", "narrative_id": narrative_id}


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
    result = await db.execute(
        select(
            SourceGroup.name,
            SourceGroup.color,
            NarrativePost.stance,
            func.count().label("count"),
        )
        .join(Post, Post.id == NarrativePost.post_id)
        .outerjoin(Source, Source.id == Post.source_id)
        .outerjoin(SourceGroupMember, SourceGroupMember.source_id == Source.id)
        .outerjoin(SourceGroup, SourceGroup.id == SourceGroupMember.source_group_id)
        .where(NarrativePost.narrative_id == narrative_id)
        .group_by(SourceGroup.name, SourceGroup.color, NarrativePost.stance)
    )
    rows = result.all()

    groups: dict = {}
    for group_name, color, stance, count in rows:
        gname = group_name or "unassigned"
        if gname not in groups:
            groups[gname] = {"color": color or "#9ca3af", "stances": {}}
        groups[gname]["stances"][stance or "unclassified"] = count

    return groups


async def _build_source_group_map(db: AsyncSession) -> dict:
    """Build a source_id → group_name mapping."""
    result = await db.execute(
        select(SourceGroupMember.source_id, SourceGroup.name)
        .join(SourceGroup, SourceGroup.id == SourceGroupMember.source_group_id)
    )
    return {str(row[0]): row[1] for row in result.all()}
