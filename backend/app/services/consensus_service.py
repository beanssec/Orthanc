"""Source-group consensus and divergence detection.

Analyzes how different source groups frame the same event based on
existing stance data. No LLM calls — purely data-driven.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update

from app.db import AsyncSessionLocal
from app.models.narrative import Narrative, NarrativePost
from app.models.post import Post

logger = logging.getLogger("orthanc.consensus")


class ConsensusService:
    """Compute source-group consensus and divergence for narrative events."""

    async def compute_event_consensus(self, narrative_id: UUID) -> dict:
        """Compute per-source-group stance breakdown and divergence score for an event.

        Returns:
            {
                "groups": {
                    "western": {"confirming": 5, "denying": 0, "contextualizing": 2, ...},
                    ...
                },
                "divergence_score": 0.0-1.0,
                "dominant_stance_by_group": {"western": "confirming", ...},
                "group_post_counts": {"western": 7, ...},
            }
        """
        try:
            async with AsyncSessionLocal() as session:
                # ── Step 1: Fetch all narrative_posts joined with posts ────────
                np_alias = NarrativePost
                result = await session.execute(
                    select(
                        np_alias.stance,
                        Post.author,
                        Post.source_type,
                        Post.id.label("post_id"),
                    )
                    .join(Post, Post.id == np_alias.post_id)
                    .where(np_alias.narrative_id == narrative_id)
                )
                rows = result.all()

                if not rows:
                    return self._empty_result()

                # ── Step 2: Map each post to a source group ────────────────────
                # Build lookup: (author, source_type) -> group_name  [method a]
                # and          author -> group_name                   [method b]

                authors = list({r.author for r in rows if r.author})
                source_types = list({r.source_type for r in rows if r.source_type})

                # Method a: author_source_group_map
                asgm_map: dict[tuple[str, str], str] = {}
                if authors:
                    asgm_result = await session.execute(
                        text(
                            "SELECT author, source_type, source_group_name "
                            "FROM author_source_group_map "
                            "WHERE author = ANY(:authors)"
                        ),
                        {"authors": authors},
                    )
                    for asgm_author, asgm_st, asgm_group in asgm_result.all():
                        asgm_map[(asgm_author, asgm_st)] = asgm_group

                # Method b: sources.display_name -> source_group_members -> source_groups
                display_name_map: dict[str, str] = {}
                if authors:
                    try:
                        sgm_result = await session.execute(
                            text(
                                """
                                SELECT s.display_name, sg.name
                                FROM sources s
                                JOIN source_group_members sgm ON sgm.source_id = s.id
                                JOIN source_groups sg ON sg.id = sgm.source_group_id
                                WHERE s.display_name = ANY(:authors)
                                """
                            ),
                            {"authors": authors},
                        )
                        for dn, grp in sgm_result.all():
                            if dn not in display_name_map:
                                display_name_map[dn] = grp
                    except Exception as exc:
                        logger.debug("Method-b source group lookup failed (non-fatal): %s", exc)

                # ── Step 3: Group posts by source_group, then by stance ────────
                # group_stances: {group_name: {stance: count}}
                group_stances: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

                for row in rows:
                    stance = row.stance or "unknown"
                    author = row.author or ""
                    source_type = row.source_type or ""

                    # Try method a first
                    group = asgm_map.get((author, source_type))

                    # Fall back to method b
                    if group is None:
                        group = display_name_map.get(author)

                    # Skip posts with no group mapping
                    if group is None:
                        continue

                    group_stances[group][stance] += 1

                if not group_stances:
                    return self._empty_result()

                # ── Step 4: Dominant stance per group ─────────────────────────
                dominant_stance_by_group: dict[str, str] = {}
                group_post_counts: dict[str, int] = {}
                groups_clean: dict[str, dict[str, int]] = {}

                for group, stance_counts in group_stances.items():
                    total = sum(stance_counts.values())
                    group_post_counts[group] = total
                    groups_clean[group] = dict(stance_counts)
                    dominant = max(stance_counts, key=stance_counts.__getitem__)
                    dominant_stance_by_group[group] = dominant

                # ── Step 5: Compute divergence_score ──────────────────────────
                divergence_score = self._compute_divergence(dominant_stance_by_group)

                return {
                    "groups": groups_clean,
                    "divergence_score": divergence_score,
                    "dominant_stance_by_group": dominant_stance_by_group,
                    "group_post_counts": group_post_counts,
                }

        except Exception as exc:
            logger.warning(
                "compute_event_consensus failed for narrative %s (non-fatal): %s",
                narrative_id, exc,
            )
            return self._empty_result()

    def _compute_divergence(self, dominant_stance_by_group: dict[str, str]) -> float:
        """Compute divergence score from dominant stances across groups.

        Formula:
            divergence = 1.0 - (max_agreement / total_groups)
        where max_agreement = count of groups sharing the most common dominant stance.

        Returns 0.0 if fewer than 2 groups have posts.
        """
        if len(dominant_stance_by_group) < 2:
            return 0.0

        stance_counts: dict[str, int] = defaultdict(int)
        for stance in dominant_stance_by_group.values():
            stance_counts[stance] += 1

        total_groups = len(dominant_stance_by_group)
        max_agreement = max(stance_counts.values())

        divergence = 1.0 - (max_agreement / total_groups)
        return round(divergence, 4)

    def _empty_result(self) -> dict:
        return {
            "groups": {},
            "divergence_score": 0.0,
            "dominant_stance_by_group": {},
            "group_post_counts": {},
        }

    async def compute_batch_consensus(self, limit: int = 50) -> int:
        """Batch-compute divergence scores for active narratives with score = 0.

        Returns the number of narratives updated.
        """
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Narrative.id, Narrative.post_count)
                    .where(
                        Narrative.status == "active",
                        (Narrative.divergence_score == 0)
                        | (Narrative.divergence_score.is_(None)),
                    )
                    .order_by(Narrative.post_count.desc())
                    .limit(limit)
                )
                narratives = result.all()

            if not narratives:
                return 0

            updated = 0
            for narrative_id, _post_count in narratives:
                try:
                    consensus = await self.compute_event_consensus(narrative_id)
                    score = consensus.get("divergence_score", 0.0)

                    async with AsyncSessionLocal() as upd_session:
                        await upd_session.execute(
                            update(Narrative)
                            .where(Narrative.id == narrative_id)
                            .values(divergence_score=score)
                        )
                        await upd_session.commit()

                    updated += 1
                except Exception as exc:
                    logger.debug(
                        "compute_batch_consensus: skipped narrative %s: %s",
                        narrative_id, exc,
                    )

            return updated

        except Exception as exc:
            logger.warning("compute_batch_consensus failed (non-fatal): %s", exc)
            return 0


# Module-level singleton
consensus_service = ConsensusService()
