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

        Algorithm:
        - Get dominant stance per source group.
        - If all groups agree → low divergence (0.0–0.3).
        - If groups have opposing stances → high divergence (0.7–1.0).
        - Western vs Russian disagreement weighted extra.
        """
        # Collect (source_group_name, stance) tuples for this narrative
        group_stances: dict[str, list[str]] = defaultdict(list)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(NarrativePost, Post, Source, SourceGroupMember, SourceGroup)
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
            rows = result.all()

        for row in rows:
            np_row, post, source, sgm, sg = row
            group_name = sg.name if sg else "unknown"
            if np_row.stance:
                group_stances[group_name].append(np_row.stance)

        if not group_stances:
            return 0.0

        # Dominant stance per group
        dominant: dict[str, str] = {}
        for grp, stances in group_stances.items():
            if stances:
                dominant[grp] = Counter(stances).most_common(1)[0][0]

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
                    weight = 2 if frozenset({g1, g2}) == frozenset({"western", "russian"}) else 1
                    opposing_count += weight

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
        - denied      : majority of stances are 'denying' across multiple groups
        - unverified  : evidence_score < 0.3
        """
        # Check for denial majority
        async with AsyncSessionLocal() as session:
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

        denial_ratio = stances.count("denying") / len(stances)

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
