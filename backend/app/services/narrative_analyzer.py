"""Narrative analyzer — background service that runs stance classification,
claim extraction, and evidence correlation for narratives produced by the
clustering engine.

Runs every 15 minutes, 5 minutes after startup (so the clustering engine has
had time to create narratives first).

Pipeline per cycle:
  1. Find narrative_posts where stance IS NULL.
  2. Group by narrative_id.
  3. For each narrative:
     a. Classify stances for unclassified posts (stance_classifier).
     b. For claims with locations, run evidence linker.
     c. Recompute divergence_score, evidence_score, and consensus.
"""
from __future__ import annotations

import asyncio
import logging
import math
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select

from app.db import AsyncSessionLocal
from app.models.narrative import (
    Claim,
    ClaimEvidence,
    Narrative,
    NarrativePost,
    SourceGroup,
    SourceGroupMember,
)
from app.models.post import Post
from app.models.source import Source
from app.services.evidence_linker import evidence_linker
from app.services.stance_classifier import stance_classifier
from app.services.source_reliability_helper import (  # Sprint 29 CP2
    reliability_weight,
    effective_score,
    weighted_average,
    NEUTRAL_WEIGHT,
)

logger = logging.getLogger("orthanc.analyzer")

# ──────────────────────────────────────────────────────────────────────────────
# JSD helpers for divergence scoring
# ──────────────────────────────────────────────────────────────────────────────

STANCES = ["confirming", "denying", "attributing", "contextualizing", "deflecting", "speculating"]


def _jsd(distributions: list[list[float]]) -> float:
    """Compute multi-distribution Jensen-Shannon Divergence.

    Args:
        distributions: list of probability distributions (each sums to 1.0)
    Returns:
        JSD value between 0.0 (identical) and 1.0 (maximally different)
    """
    if len(distributions) < 2:
        return 0.0

    n = len(distributions)
    # Mean distribution
    m = [sum(d[i] for d in distributions) / n for i in range(len(distributions[0]))]

    # KL divergence from each distribution to mean
    def _kl(p: list[float], q: list[float]) -> float:
        total = 0.0
        for pi, qi in zip(p, q):
            if pi > 0 and qi > 0:
                total += pi * math.log2(pi / qi)
        return total

    jsd = sum(_kl(d, m) for d in distributions) / n
    # Normalise to 0-1 (max JSD for binary distributions = 1.0 with log2)
    return min(1.0, jsd)


def _stance_distribution(stances: list[tuple[str, float]]) -> list[float]:
    """Convert list of (stance, weight) pairs to a probability distribution over STANCES."""
    counts = {s: 0.0 for s in STANCES}
    for stance, weight in stances:
        if stance in counts:
            counts[stance] += weight
    total = sum(counts.values())
    if total == 0:
        return [1.0 / len(STANCES)] * len(STANCES)  # uniform
    return [counts[s] / total for s in STANCES]


class NarrativeAnalyzer:
    """Background service: classify stances + extract claims + link evidence."""

    POLL_INTERVAL = 900  # 15 minutes

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    # ──────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Narrative analyzer started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Narrative analyzer stopped")

    # ──────────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────────

    async def _loop(self) -> None:
        # Wait 5 minutes before first run — let clustering engine produce narratives
        logger.info("Narrative analyzer: waiting 5 min before first run …")
        await asyncio.sleep(300)
        while self._running:
            try:
                await self._analyze_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Narrative analyzer cycle error: %s", exc, exc_info=True)
            await asyncio.sleep(self.POLL_INTERVAL)

    # ──────────────────────────────────────────────
    # Analysis cycle
    # ──────────────────────────────────────────────

    async def _analyze_cycle(self) -> None:
        """Find unanalysed narratives and process them."""
        # 1. Find narrative_ids that have at least one unclassified post
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(NarrativePost.narrative_id)
                .where(NarrativePost.stance.is_(None))
                .distinct()
            )
            narrative_ids: list[uuid.UUID] = result.scalars().all()

        if not narrative_ids:
            logger.debug("Narrative analyzer: nothing to analyse this cycle")
            return

        logger.info("Narrative analyzer: processing %d narratives …", len(narrative_ids))

        for nid in narrative_ids:
            if not self._running:
                break
            try:
                await self._process_narrative(nid)
            except Exception as exc:
                logger.error("Error processing narrative %s: %s", nid, exc, exc_info=True)

    async def _process_narrative(self, narrative_id: uuid.UUID) -> None:
        """Full pipeline for a single narrative."""
        # a. Stance classification (also extracts claims if AI available)
        await stance_classifier.classify_narrative(narrative_id)

        # b. Evidence linking for newly created claims
        await self._link_evidence_for_narrative(narrative_id)

        # c. Recompute scores and consensus
        divergence = await self._compute_divergence(narrative_id)
        evidence_score = await self._compute_evidence_score(narrative_id)
        consensus = await self._determine_consensus(narrative_id, divergence, evidence_score)

        # d. Persist scores back to Narrative row
        async with AsyncSessionLocal() as session:
            narrative = await session.get(Narrative, narrative_id)
            if narrative:
                narrative.divergence_score = divergence
                narrative.evidence_score = evidence_score
                narrative.consensus = consensus
                session.add(narrative)
                await session.commit()

        logger.info(
            "Narrative %s — divergence=%.2f evidence=%.2f consensus=%s",
            narrative_id, divergence, evidence_score, consensus,
        )

    async def _link_evidence_for_narrative(self, narrative_id: uuid.UUID) -> None:
        """Run the evidence linker on claims that have no evidence yet."""
        async with AsyncSessionLocal() as session:
            # Find claims with evidence_count == 0 (unprocessed)
            result = await session.execute(
                select(Claim).where(
                    Claim.narrative_id == narrative_id,
                    Claim.evidence_count == 0,
                )
            )
            claims = result.scalars().all()

        for claim in claims:
            try:
                evidence_list = await evidence_linker.check_claim(claim)
                if evidence_list:
                    await evidence_linker.persist_evidence(claim, evidence_list)
            except Exception as exc:
                logger.warning("Evidence linking failed for claim %s: %s", claim.id, exc)

    # ──────────────────────────────────────────────
    # Scoring
    # ──────────────────────────────────────────────

    async def _compute_divergence(self, narrative_id: uuid.UUID) -> float:
        """Compute divergence: how much do source groups disagree?

        Uses Jensen-Shannon Divergence on stance distributions per source group,
        combined with contradiction ratio and temporal spread.

        Combined score = 0.50 * JSD + 0.30 * contradiction_ratio + 0.20 * temporal_divergence

        Source group is determined by matching Post.author against Source handles/display names
        (avoids the broken join on Source.handle == Post.source_id which never matches
        Telegram or RSS posts).
        """
        group_stances: dict[str, list[tuple[str, float]]] = defaultdict(list)
        group_timestamps: dict[str, list[datetime]] = defaultdict(list)

        async with AsyncSessionLocal() as session:
            # Step 1: Build source handle → group mapping
            group_result = await session.execute(
                select(Source.handle, Source.type, SourceGroup.name)
                .join(SourceGroupMember, SourceGroupMember.source_id == Source.id)
                .join(SourceGroup, SourceGroup.id == SourceGroupMember.source_group_id)
            )
            handle_to_group: dict[str, str] = {}
            for handle, src_type, group_name in group_result.all():
                if handle:
                    handle_to_group[handle.lower()] = group_name

            # Step 2: Get posts with stance, author, source info, and timestamp
            posts_result = await session.execute(
                select(
                    NarrativePost.stance,
                    Post.author,
                    Post.source_type,
                    Post.source_id,
                    Post.timestamp,
                )
                .join(Post, NarrativePost.post_id == Post.id)
                .where(
                    NarrativePost.narrative_id == narrative_id,
                    NarrativePost.stance.isnot(None),
                )
            )

            for stance, author, source_type, source_id, timestamp in posts_result.all():
                if not stance:
                    continue

                # Find source group by matching author against known handles
                group = "unknown"
                if author:
                    author_lower = author.lower()
                    # Direct match on author string
                    group = handle_to_group.get(author_lower, "unknown")
                    # Substring match for Telegram channel titles vs handles
                    if group == "unknown":
                        for handle, gname in handle_to_group.items():
                            if handle in author_lower or author_lower in handle:
                                group = gname
                                break
                # For RSS, try matching source_id against known handles
                if group == "unknown" and source_type == "rss":
                    for handle, gname in handle_to_group.items():
                        if handle in (source_id or ""):
                            group = gname
                            break

                group_stances[group].append((stance, 1.0))
                if timestamp:
                    group_timestamps[group].append(timestamp)

            # Step 3: Get contradiction ratio from evidence roles
            evidence_result = await session.execute(
                select(NarrativePost.evidence_role, func.count())
                .where(
                    NarrativePost.narrative_id == narrative_id,
                    NarrativePost.evidence_role.isnot(None),
                )
                .group_by(NarrativePost.evidence_role)
            )
            evidence_counts = {role: count for role, count in evidence_result.all()}

        # Need at least 2 known groups (not just "unknown")
        known_groups = {g: s for g, s in group_stances.items() if g != "unknown"}
        if len(known_groups) < 2:
            # Fall back to including unknown if it has enough data
            if len(group_stances) < 2:
                return 0.0
            known_groups = dict(group_stances)

        # Compute JSD across stance distributions
        distributions = [_stance_distribution(stances) for stances in known_groups.values()]
        jsd = _jsd(distributions)

        # Compute contradiction ratio from evidence roles
        supports = evidence_counts.get("supports", 0)
        contradicts = evidence_counts.get("contradicts", 0)
        if supports + contradicts > 0:
            contradiction_ratio = contradicts / (supports + contradicts)
        else:
            contradiction_ratio = 0.0

        # Compute temporal divergence (normalised std dev of first-post-per-group timestamps)
        temporal_div = 0.0
        if len(group_timestamps) >= 2:
            first_per_group = [min(ts) for ts in group_timestamps.values() if ts]
            if len(first_per_group) >= 2:
                mean_ts = sum(t.timestamp() for t in first_per_group) / len(first_per_group)
                variance = sum((t.timestamp() - mean_ts) ** 2 for t in first_per_group) / len(first_per_group)
                std_seconds = variance ** 0.5
                # Normalise: 0 = simultaneous, 1.0 = 6+ hours apart
                temporal_div = min(1.0, std_seconds / (6 * 3600))

        # Combined score
        combined = 0.50 * jsd + 0.30 * contradiction_ratio + 0.20 * temporal_div
        return round(min(1.0, combined), 3)

    async def _compute_evidence_score(self, narrative_id: uuid.UUID) -> float:
        """Average confidence across all claim evidence records for this narrative."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(func.avg(ClaimEvidence.confidence))
                .join(Claim, ClaimEvidence.claim_id == Claim.id)
                .where(Claim.narrative_id == narrative_id)
            )
            avg = result.scalar()

        if avg is None:
            return 0.0
        return round(float(avg), 3)

    async def _determine_consensus(
        self,
        narrative_id: uuid.UUID,
        divergence: float,
        evidence_score: float,
    ) -> str:
        """Determine narrative consensus label.

        - confirmed   : evidence_score > 0.7 AND divergence < 0.3
        - disputed    : evidence_score > 0.3 AND divergence > 0.5
        - denied      : reliability-weighted denial stance is majority
        - unverified  : evidence_score < 0.3

        Sprint 29 CP2: denial ratio is now computed as a reliability-weighted
        fraction so that denials from low-credibility sources carry less weight.
        Falls back to unweighted counting when reliability data is absent.
        """
        try:
            from app.models.source_reliability import SourceReliability  # noqa: PLC0415
            reliability_available = True
        except ImportError:
            reliability_available = False

        denial_weight_total = 0.0
        total_weight = 0.0

        async with AsyncSessionLocal() as session:
            if reliability_available:
                try:
                    result = await session.execute(
                        select(
                            NarrativePost.stance,
                            SourceReliability.reliability_score,
                            SourceReliability.analyst_override,
                            SourceReliability.confidence_band,
                        )
                        .join(Post, NarrativePost.post_id == Post.id)
                        .join(
                            Source,
                            (Source.type == Post.source_type) & (Source.handle == Post.source_id),
                            isouter=True,
                        )
                        .join(
                            SourceReliability,
                            SourceReliability.source_id == Source.id,
                            isouter=True,
                        )
                        .where(
                            NarrativePost.narrative_id == narrative_id,
                            NarrativePost.stance.isnot(None),
                        )
                    )
                    rows = result.all()
                    if rows:
                        for stance, rs, ao, band in rows:
                            class _Stub:
                                reliability_score = rs
                                analyst_override = ao
                                confidence_band = band

                            w = reliability_weight(effective_score(_Stub()))
                            total_weight += w
                            if stance == "denying":
                                denial_weight_total += w
                except Exception as exc:
                    logger.debug(
                        "_determine_consensus: reliability join failed (%s) — using equal weights",
                        exc,
                    )
                    reliability_available = False

            if not reliability_available or total_weight == 0.0:
                # Legacy fallback: unweighted stance list
                result = await session.execute(
                    select(NarrativePost.stance)
                    .where(
                        NarrativePost.narrative_id == narrative_id,
                        NarrativePost.stance.isnot(None),
                    )
                )
                stances = [row[0] for row in result.all()]
                if not stances:
                    return "unverified"
                denial_weight_total = float(stances.count("denying"))
                total_weight = float(len(stances))

        if total_weight == 0.0:
            return "unverified"

        denial_ratio = denial_weight_total / total_weight

        if denial_ratio >= 0.5:
            return "denied"

        if evidence_score > 0.7 and divergence < 0.3:
            return "confirmed"

        if evidence_score > 0.3 and divergence > 0.5:
            return "disputed"

        return "unverified"


# ──────────────────────────────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────────────────────────────

narrative_analyzer = NarrativeAnalyzer()
