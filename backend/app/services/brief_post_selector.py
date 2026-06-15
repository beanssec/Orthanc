"""Intelligent post selector for intelligence briefs.

Fills a budget of posts from 5 prioritised tiers:
  1. Fired alerts          (~10%)  — posts that triggered alerts
  2. Fusion events         (~20%)  — posts from correlated event clusters
  3. Narrative reps        (~30%)  — best post per active narrative
  4. Trending entities     (~15%)  — posts mentioning high-mention entities
  5. Time-sliced fill      (rest)  — uniform temporal sampling as backstop

Each tier is independent and deduplicates against already-selected IDs.
On any tier failure the selector logs a warning and continues.

TODO: Replace ID-based deduplication with embedding cosine-similarity dedup
      (threshold ~0.85) to also remove semantically duplicate posts that were
      ingested from different sources.  This requires a vector store or an
      on-the-fly embedding call and is deferred to a future sprint.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select

from app.db import AsyncSessionLocal
from app.models.post import Post

logger = logging.getLogger("orthanc.brief_post_selector")

# Severity ordering helpers
_ALERT_SEVERITY_ORDER = {"flash": 0, "urgent": 1, "routine": 2}
_FUSION_SEVERITY_ORDER = {"critical": 0, "elevated": 1, "routine": 2}


def _alert_sev_key(sev: str) -> int:
    return _ALERT_SEVERITY_ORDER.get((sev or "routine").lower(), 99)


def _fusion_sev_key(sev: str) -> int:
    return _FUSION_SEVERITY_ORDER.get((sev or "routine").lower(), 99)


def _apply_post_filters(
    query,
    source_types: list[str] | None,
    topic: str | None,
):
    """Apply source_type and topic filters to a Post-level query."""
    if source_types:
        query = query.where(Post.source_type.in_(source_types))
    if topic and topic.strip():
        query = query.where(Post.content.ilike(f"%{topic.strip()}%"))
    return query


@dataclass(frozen=True)
class TemporalSamplingPlan:
    """Plan for time-sliced backfill in the brief post selector."""

    posts_per_slice: int
    n_slices: int
    slice_seconds: float


def _compute_temporal_sampling_plan(remaining: int, hours: int) -> TemporalSamplingPlan:
    """Scale temporal sampling with the remaining post budget.

    The selector used to be effectively capped at 24 slices x 2 posts. Large
    context models can consume far more evidence, so larger budgets deliberately
    use more slices and a richer per-slice sample while retaining an upper bound
    to avoid hundreds of tiny database queries.
    """
    posts_per_slice = 4 if remaining >= 400 else 3 if remaining >= 150 else 2
    raw_n_slices = (remaining + posts_per_slice - 1) // posts_per_slice
    n_slices = max(4, min(168, raw_n_slices, remaining))
    window_seconds = hours * 3600
    return TemporalSamplingPlan(
        posts_per_slice=posts_per_slice,
        n_slices=n_slices,
        slice_seconds=window_seconds / n_slices,
    )


def _add_selection(
    selected: list[dict],
    selected_ids: set[uuid.UUID],
    post: Post,
    *,
    reason: str,
    tier: int,
    priority_score: float,
    budget: int,
) -> bool:
    """Append a post selection once, enforcing global budget and de-dupe."""
    if len(selected) >= budget or post.id in selected_ids:
        return False
    selected.append({
        "post": post,
        "selection_reason": reason,
        "tier": tier,
        "priority_score": priority_score,
    })
    selected_ids.add(post.id)
    return True


async def select_posts_for_brief(
    hours: int,
    budget: int = 200,
    source_types: list[str] | None = None,
    topic: str | None = None,
) -> list[dict]:
    """Select the most intelligence-relevant posts for a brief.

    Returns a list of dicts with keys:
        post             – Post ORM instance
        selection_reason – human-readable tag explaining why this post was picked
        tier             – integer 1-5
        priority_score   – float for downstream sorting/display
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    selected: list[dict] = []
    selected_ids: set[uuid.UUID] = set()

    # ── Tier allocations ─────────────────────────────────────────────────────
    tier1_budget = max(1, int(budget * 0.10))
    tier2_budget = max(1, int(budget * 0.20))
    tier3_budget = max(1, int(budget * 0.30))
    tier4_budget = max(1, int(budget * 0.15))
    # tier5 gets whatever is left

    # ── Tier 1: Fired alerts ─────────────────────────────────────────────────
    try:
        from app.models.alert_rule import AlertEvent

        async with AsyncSessionLocal() as session:
            ae_result = await session.execute(
                select(AlertEvent)
                .where(AlertEvent.fired_at >= cutoff)
                .order_by(AlertEvent.fired_at.desc())
            )
            alert_events = ae_result.scalars().all()

        # Sort: flash first, then urgent, then routine; within tier by fired_at desc
        alert_events = sorted(
            alert_events, key=lambda ae: (_alert_sev_key(ae.severity), -ae.fired_at.timestamp())
        )

        tier1_added = 0
        for ae in alert_events:
            if tier1_added >= tier1_budget:
                break
            post_ids = ae.matched_post_ids or []
            if not post_ids:
                continue

            async with AsyncSessionLocal() as session:
                q = select(Post).where(Post.id.in_(post_ids), Post.timestamp >= cutoff)
                q = _apply_post_filters(q, source_types, topic)
                result = await session.execute(q)
                posts = result.scalars().all()

            for p in posts:
                if p.id in selected_ids:
                    continue
                if tier1_added >= tier1_budget:
                    break
                if _add_selection(
                    selected,
                    selected_ids,
                    p,
                    reason=f"ALERT: {ae.title}",
                    tier=1,
                    priority_score=1.0 - _alert_sev_key(ae.severity) * 0.1,
                    budget=budget,
                ):
                    tier1_added += 1

        logger.debug("Tier 1 (alerts): added %d posts", tier1_added)

    except Exception as exc:
        logger.warning("brief_post_selector Tier 1 (alerts) failed: %s", exc)

    # ── Tier 2: Fusion events ────────────────────────────────────────────────
    try:
        from app.models.fused_event import FusedEvent

        async with AsyncSessionLocal() as session:
            fe_result = await session.execute(
                select(FusedEvent)
                .where(FusedEvent.created_at >= cutoff)
                .order_by(FusedEvent.created_at.desc())
            )
            fused_events = fe_result.scalars().all()

        # Sort: critical first, then elevated, then routine; then by component count desc
        fused_events = sorted(
            fused_events,
            key=lambda fe: (
                _fusion_sev_key(fe.severity),
                -len(fe.component_post_ids or []),
            ),
        )

        tier2_added = 0
        for fe in fused_events:
            if tier2_added >= tier2_budget:
                break
            post_ids = fe.component_post_ids or []
            if not post_ids:
                continue

            source_count = len(set(fe.component_source_types or []))

            async with AsyncSessionLocal() as session:
                q = select(Post).where(Post.id.in_(post_ids), Post.timestamp >= cutoff)
                q = _apply_post_filters(q, source_types, topic)
                result = await session.execute(q)
                candidate_posts = result.scalars().all()

            # Pick the richest (longest content) post from this fusion event
            candidate_posts = [cp for cp in candidate_posts if cp.id not in selected_ids]
            if not candidate_posts:
                continue
            best = max(candidate_posts, key=lambda p: len(p.content or ""))

            if _add_selection(
                selected,
                selected_ids,
                best,
                reason=f"FUSION: {source_count} sources, {fe.severity}",
                tier=2,
                priority_score=0.9 - _fusion_sev_key(fe.severity) * 0.1,
                budget=budget,
            ):
                tier2_added += 1

        logger.debug("Tier 2 (fusion): added %d posts", tier2_added)

    except Exception as exc:
        logger.warning("brief_post_selector Tier 2 (fusion) failed: %s", exc)

    # ── Tier 3: Narrative representatives ────────────────────────────────────
    try:
        from app.models.narrative import Narrative, NarrativePost

        async with AsyncSessionLocal() as session:
            narr_result = await session.execute(
                select(Narrative)
                .where(
                    Narrative.status == "active",
                    Narrative.last_updated >= cutoff,
                )
                .order_by(
                    Narrative.post_count.desc(),
                    Narrative.divergence_score.desc(),
                )
            )
            narratives = narr_result.scalars().all()

        tier3_added = 0
        for narr in narratives:
            if tier3_added >= tier3_budget:
                break

            async with AsyncSessionLocal() as session:
                # Get post IDs associated with this narrative
                np_result = await session.execute(
                    select(NarrativePost.post_id)
                    .where(NarrativePost.narrative_id == narr.id)
                )
                np_post_ids = [r[0] for r in np_result.all()]

            if not np_post_ids:
                continue

            # Fetch posts and filter
            async with AsyncSessionLocal() as session:
                q = select(Post).where(Post.id.in_(np_post_ids), Post.timestamp >= cutoff)
                q = _apply_post_filters(q, source_types, topic)
                q = q.order_by(Post.timestamp.desc())
                result = await session.execute(q)
                candidate_posts = result.scalars().all()

            candidate_posts = [cp for cp in candidate_posts if cp.id not in selected_ids]
            if not candidate_posts:
                continue

            # Pick most recent post (already ordered by timestamp desc)
            best = candidate_posts[0]
            title = narr.canonical_title or narr.title

            if _add_selection(
                selected,
                selected_ids,
                best,
                reason=f"NARRATIVE: {title}",
                tier=3,
                priority_score=0.8,
                budget=budget,
            ):
                tier3_added += 1

        logger.debug("Tier 3 (narratives): added %d posts", tier3_added)

    except Exception as exc:
        logger.warning("brief_post_selector Tier 3 (narratives) failed: %s", exc)

    # ── Tier 4: Trending entities ─────────────────────────────────────────────
    try:
        from app.models.entity import Entity, EntityMention

        async with AsyncSessionLocal() as session:
            ent_result = await session.execute(
                select(Entity)
                .where(Entity.last_seen >= cutoff)
                .order_by(Entity.mention_count.desc())
                .limit(20)
            )
            trending_entities = ent_result.scalars().all()

        tier4_added = 0
        for entity in trending_entities:
            if tier4_added >= tier4_budget:
                break

            async with AsyncSessionLocal() as session:
                # Find a recent post mentioning this entity that isn't already selected
                em_result = await session.execute(
                    select(EntityMention.post_id)
                    .where(EntityMention.entity_id == entity.id)
                    .limit(50)
                )
                mention_post_ids = [r[0] for r in em_result.all()]

            if not mention_post_ids:
                continue

            async with AsyncSessionLocal() as session:
                q = select(Post).where(
                    Post.id.in_(mention_post_ids),
                    Post.timestamp >= cutoff,
                )
                q = _apply_post_filters(q, source_types, topic)
                q = q.order_by(Post.timestamp.desc())
                result = await session.execute(q)
                candidate_posts = result.scalars().all()

            candidate_posts = [cp for cp in candidate_posts if cp.id not in selected_ids]
            if not candidate_posts:
                continue

            best = candidate_posts[0]
            display_name = entity.canonical_name or entity.name

            if _add_selection(
                selected,
                selected_ids,
                best,
                reason=f"TRENDING: {display_name} ({entity.mention_count} mentions)",
                tier=4,
                priority_score=0.7,
                budget=budget,
            ):
                tier4_added += 1

        logger.debug("Tier 4 (entities): added %d posts", tier4_added)

    except Exception as exc:
        logger.warning("brief_post_selector Tier 4 (entities) failed: %s", exc)

    # ── Tier 5: Time-sliced temporal fill ────────────────────────────────────
    try:
        remaining = budget - len(selected)
        if remaining > 0:
            # Scale temporal sampling with the requested budget.  The previous
            # max-24-slices x 2-posts implementation hard-capped the backstop at
            # 48 posts, so large-context brief models rarely received more than
            # a small fraction of their requested post budget.
            sampling_plan = _compute_temporal_sampling_plan(remaining, hours)

            tier5_added = 0
            for i in range(sampling_plan.n_slices):
                if len(selected) >= budget:
                    break

                slice_start = cutoff + timedelta(seconds=i * sampling_plan.slice_seconds)
                slice_end = cutoff + timedelta(seconds=(i + 1) * sampling_plan.slice_seconds)
                ts_label = (
                    f"{slice_start.strftime('%H:%M')}-{slice_end.strftime('%H:%M')} UTC"
                )

                async with AsyncSessionLocal() as session:
                    q = select(Post).where(
                        Post.timestamp >= slice_start,
                        Post.timestamp < slice_end,
                        Post.id.notin_(selected_ids),
                    )
                    q = _apply_post_filters(q, source_types, topic)
                    # Prefer richer posts (longer content)
                    q = q.order_by(func.length(Post.content).desc()).limit(sampling_plan.posts_per_slice)
                    result = await session.execute(q)
                    slice_posts = result.scalars().all()

                for p in slice_posts:
                    if p.id in selected_ids:
                        continue
                    if len(selected) >= budget:
                        break
                    if _add_selection(
                        selected,
                        selected_ids,
                        p,
                        reason=f"TEMPORAL: {ts_label}",
                        tier=5,
                        priority_score=0.5,
                        budget=budget,
                    ):
                        tier5_added += 1

            logger.debug("Tier 5 (temporal): added %d posts across %d slices", tier5_added, sampling_plan.n_slices)

            # Dense periods can leave some slices empty. If there is still room,
            # backfill from the richest remaining posts in the full window so the
            # selector honours large context budgets instead of stopping early.
            if len(selected) < budget:
                backfill_limit = budget - len(selected)
                async with AsyncSessionLocal() as session:
                    q = select(Post).where(
                        Post.timestamp >= cutoff,
                        Post.id.notin_(selected_ids),
                    )
                    q = _apply_post_filters(q, source_types, topic)
                    q = q.order_by(func.length(Post.content).desc()).limit(backfill_limit)
                    result = await session.execute(q)
                    backfill_posts = result.scalars().all()

                backfill_added = 0
                for p in backfill_posts:
                    if p.id in selected_ids or len(selected) >= budget:
                        continue
                    if _add_selection(
                        selected,
                        selected_ids,
                        p,
                        reason="TEMPORAL: high-signal backfill",
                        tier=5,
                        priority_score=0.45,
                        budget=budget,
                    ):
                        backfill_added += 1
                logger.debug("Tier 5 (backfill): added %d posts", backfill_added)

    except Exception as exc:
        logger.warning("brief_post_selector Tier 5 (temporal) failed: %s", exc)

    logger.info(
        "brief_post_selector: selected %d / %d posts (hours=%d, source_types=%s, topic=%s)",
        len(selected), budget, hours, source_types, topic,
    )
    return selected


async def fetch_arc_context(hours: int, max_arcs: int = 20) -> list[dict]:
    """Fetch active arc summaries for brief context injection.

    Returns list of dicts:
        [{title, summary, arc_type, narrative_count, total_post_count, first_seen, last_updated}]

    Returns empty list if the NarrativeArc table doesn't exist yet or on any error.
    """
    try:
        from app.models.narrative import NarrativeArc

        # Only include arcs with activity within the brief's time window
        activity_cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(NarrativeArc)
                .where(NarrativeArc.status == "active")
                .where(NarrativeArc.summary.isnot(None))
                .where(NarrativeArc.last_updated >= activity_cutoff)
                .order_by(NarrativeArc.total_post_count.desc())
                .limit(max_arcs)
            )
            arcs = result.scalars().all()

        return [
            {
                "title": arc.title,
                "summary": arc.summary,
                "arc_type": arc.arc_type,
                "narrative_count": arc.narrative_count,
                "total_post_count": arc.total_post_count,
                "first_seen": arc.first_seen.isoformat() if arc.first_seen else None,
                "last_updated": arc.last_updated.isoformat() if arc.last_updated else None,
            }
            for arc in arcs
        ]
    except Exception as exc:
        logger.debug("fetch_arc_context: failed (non-fatal): %s", exc)
        return []


async def fetch_divergence_context(
    hours: int,
    min_divergence: float = 0.3,
    max_items: int = 10,
) -> list[dict]:
    """Fetch high-divergence events for brief context injection.

    Returns events where source groups significantly disagree,
    along with the per-group dominant stance breakdown.

    Returns empty list on any failure.
    """
    try:
        from app.models.narrative import Narrative
        from app.services.consensus_service import consensus_service

        activity_cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Narrative.id, Narrative.title, Narrative.divergence_score, Narrative.post_count)
                .where(
                    Narrative.status == "active",
                    Narrative.divergence_score >= min_divergence,
                    Narrative.last_updated >= activity_cutoff,
                )
                .order_by(Narrative.divergence_score.desc())
                .limit(max_items)
            )
            rows = result.all()

        if not rows:
            return []

        items: list[dict] = []
        for narrative_id, title, divergence_score, post_count in rows:
            try:
                consensus = await consensus_service.compute_event_consensus(narrative_id)
                dominant = consensus.get("dominant_stance_by_group", {})
                items.append({
                    "title": title,
                    "divergence_score": divergence_score,
                    "groups": dominant,
                    "post_count": post_count,
                })
            except Exception as exc:
                logger.debug(
                    "fetch_divergence_context: skipped narrative %s: %s",
                    narrative_id, exc,
                )

        return items

    except Exception as exc:
        logger.debug("fetch_divergence_context: failed (non-fatal): %s", exc)
        return []
