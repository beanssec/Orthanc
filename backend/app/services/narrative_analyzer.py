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
import uuid
from collections import Counter, defaultdict
from datetime import timezone
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

# Divergence matrix: stances that represent meaningful disagreement
_OPPOSING_PAIRS = frozenset({
    frozenset({"confirming", "denying"}),
    frozenset({"confirming", "deflecting"}),
    frozenset({"attributing", "denying"}),
    frozenset({"attributing", "deflecting"}),
})


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
        """Compute divergence score: how much do source groups disagree?

        Algorithm (Sprint 29 CP2: reliability-weighted):
        - Get dominant stance per source group using reliability-weighted voting.
          High-reliability sources contribute more weight to their group's stance.
          Sources with no reliability data are treated as neutral weight (0.5).
        - If all groups agree → low divergence (0.0–0.3).
        - If groups have opposing stances → high divergence (0.7–1.0).
        - Western vs Russian disagreement weighted extra.

        Fallback: if SourceReliability table is absent or empty, degrades to
        unweighted counting (identical to previous behaviour).
        """
        # Collect (source_group_name, stance, reliability_weight) tuples
        # group_stances maps group_name → list of (stance, weight) pairs
        group_stances: dict[str, list[tuple[str, float]]] = defaultdict(list)

        try:
            from app.models.source_reliability import SourceReliability  # noqa: PLC0415
            reliability_available = True
        except ImportError:
            reliability_available = False

        async with AsyncSessionLocal() as session:
            if reliability_available:
                try:
                    result = await session.execute(
                        select(
                            NarrativePost.stance,
                            SourceGroup.name,
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
                            SourceGroupMember,
                            SourceGroupMember.source_id == Source.id,
                            isouter=True,
                        )
                        .join(
                            SourceGroup,
                            SourceGroup.id == SourceGroupMember.source_group_id,
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
                    for stance, group_name, rs, ao, band in rows:
                        if not stance:
                            continue
                        gname = group_name or "unknown"

                        # Build a lightweight stand-in for effective_score
                        class _Stub:
                            reliability_score = rs
                            analyst_override = ao
                            confidence_band = band

                        w = reliability_weight(effective_score(_Stub()))
                        group_stances[gname].append((stance, w))
                except Exception as exc:
                    # source_reliability table not yet migrated — fall back to legacy path
                    logger.debug(
                        "_compute_divergence: reliability join failed (%s) — using equal weights",
                        exc,
                    )
                    reliability_available = False

            if not reliability_available:
                # Legacy path: equal weight 1.0 for all stances
                result = await session.execute(
                    select(NarrativePost.stance, SourceGroup.name)
                    .join(Post, NarrativePost.post_id == Post.id)
                    .join(
                        Source,
                        (Source.type == Post.source_type) & (Source.handle == Post.source_id),
                        isouter=True,
                    )
                    .join(
                        SourceGroupMember,
                        SourceGroupMember.source_id == Source.id,
                        isouter=True,
                    )
                    .join(
                        SourceGroup,
                        SourceGroup.id == SourceGroupMember.source_group_id,
                        isouter=True,
                    )
                    .where(
                        NarrativePost.narrative_id == narrative_id,
                        NarrativePost.stance.isnot(None),
                    )
                )
                for stance, group_name in result.all():
                    if stance:
                        group_stances[group_name or "unknown"].append((stance, 1.0))

        if not group_stances:
            return 0.0

        # Reliability-weighted dominant stance per group
        # Instead of a raw Counter, accumulate weights per stance
        dominant: dict[str, str] = {}
        for grp, stance_weight_pairs in group_stances.items():
            stance_scores: dict[str, float] = defaultdict(float)
            for stance, w in stance_weight_pairs:
                stance_scores[stance] += w
            if stance_scores:
                dominant[grp] = max(stance_scores, key=lambda s: stance_scores[s])

        if len(dominant) <= 1:
            return 0.1  # single group — minimal divergence

        # Count opposing pairs across groups
        group_list = list(dominant.items())
        opposing_count = 0
        total_pairs = 0
        for i in range(len(group_list)):
            for j in range(i + 1, len(group_list)):
                g1, s1 = group_list[i]
                g2, s2 = group_list[j]
                total_pairs += 1
                pair = frozenset({s1, s2})
                if pair in _OPPOSING_PAIRS:
                    # Extra weight for the canonical Western vs Russian axis
                    axis_weight = 2 if frozenset({g1, g2}) == frozenset({"western", "russian"}) else 1
                    opposing_count += axis_weight

        if total_pairs == 0:
            return 0.0

        raw = opposing_count / (total_pairs * 2)  # max weight per pair is 2
        return round(min(1.0, raw), 3)

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
