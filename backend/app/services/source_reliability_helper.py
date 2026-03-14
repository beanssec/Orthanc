"""Source Reliability Helper — Sprint 29, Checkpoint 2.

Provides clean, safe utility functions for consuming SourceReliability data
inside the narrative and tracker pipelines.

Design principles:
- Every function degrades safely when reliability data is absent or partially populated.
- The helper never raises; callers may always rely on fallback values.
- Functions are pure / testable where possible; async DB helpers are clearly marked.
- Import from this module wherever reliability weighting is needed — avoids ad-hoc
  logic being scattered across analyzer and router code.

Typical usage
-------------
    from app.services.source_reliability_helper import (
        effective_score,
        reliability_weight,
        weighted_average,
        fetch_narrative_reliability_weights,
    )

    # Inline weight from an ORM object (already loaded)
    w = reliability_weight(effective_score(source.reliability))

    # Bulk pre-fetch for a set of narrative_ids (tracker loop)
    weights = await fetch_narrative_reliability_weights(db, narrative_ids)
    narrative_quality = weights.get(narrative_id)  # float or None if unknown
"""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import select

logger = logging.getLogger("orthanc.reliability_helper")

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ── Constants ────────────────────────────────────────────────────────────────

# Weight assigned when no reliability data exists yet.
# 0.5 is deliberately neutral — it neither boosts nor suppresses unknown sources.
NEUTRAL_WEIGHT: float = 0.5

# Floor weight: even the lowest-scoring source contributes minimally.
# Prevents a single low-quality source from dominating by exclusion.
WEIGHT_FLOOR: float = 0.2

# Confidence band → approximate score when only the band is available
_BAND_SCORE: dict[str, float] = {
    "high": 0.85,
    "medium": 0.55,
    "low": 0.25,
    "unrated": NEUTRAL_WEIGHT,
}


# ── Pure helpers ─────────────────────────────────────────────────────────────

def effective_score(reliability_obj) -> Optional[float]:
    """Return the effective reliability score from a SourceReliability ORM object.

    Precedence:
      1. analyst_override (explicit human correction)
      2. reliability_score (computed signal)
      3. confidence_band  (categorical fallback)
      4. None             (unknown)

    Always returns None rather than raising if the object is None/unloaded.
    """
    if reliability_obj is None:
        return None
    try:
        if reliability_obj.analyst_override is not None:
            val = float(reliability_obj.analyst_override)
            return max(0.0, min(1.0, val))
        if reliability_obj.reliability_score is not None:
            val = float(reliability_obj.reliability_score)
            return max(0.0, min(1.0, val))
        band = (reliability_obj.confidence_band or "").lower().strip()
        if band in _BAND_SCORE:
            return _BAND_SCORE[band]
    except Exception as exc:  # noqa: BLE001
        logger.debug("effective_score: could not read reliability object: %s", exc)
    return None


def reliability_weight(score: Optional[float]) -> float:
    """Convert a reliability score (or None) into a positive weight.

    Mapping:
      None → NEUTRAL_WEIGHT (0.5) — safe fallback for unknown sources
      0.0  → WEIGHT_FLOOR   (0.2) — never fully silence any source
      1.0  → 1.0

    Linear interpolation between WEIGHT_FLOOR and 1.0 for known scores.
    """
    if score is None:
        return NEUTRAL_WEIGHT
    clamped = max(0.0, min(1.0, float(score)))
    # Linear: WEIGHT_FLOOR + clamped * (1.0 - WEIGHT_FLOOR)
    return WEIGHT_FLOOR + clamped * (1.0 - WEIGHT_FLOOR)


def weighted_average(values: list[float], weights: list[float]) -> Optional[float]:
    """Compute a weighted mean.

    Returns None if the input lists are empty or if total weight is zero.
    Caller is responsible for providing equal-length lists.
    """
    if not values or not weights:
        return None
    total_weight = sum(weights)
    if total_weight == 0.0:
        return None
    weighted_sum = sum(v * w for v, w in zip(values, weights))
    return weighted_sum / total_weight


def confidence_label_from_score(score: float) -> str:
    """Convert a 0–1 reliability/confidence score to a human-readable label.

    Used for logging and for surfacing quality hints to callers.
    """
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    if score >= 0.20:
        return "low"
    return "unrated"


# ── Async DB helpers ─────────────────────────────────────────────────────────

async def fetch_narrative_reliability_weights(
    db: "AsyncSession",
    narrative_ids: list[uuid.UUID],
) -> dict[uuid.UUID, float]:
    """Bulk-fetch average effective reliability weights for a list of narratives.

    For each narrative, computes the mean reliability weight across all posts'
    sources.  Returns a dict of narrative_id → average_weight.

    Narratives with no source reliability data are absent from the returned dict;
    callers should use NEUTRAL_WEIGHT as the fallback.

    This is designed to be called *once* at the top of a tracker recompute cycle
    to avoid per-narrative DB round-trips.
    """
    if not narrative_ids:
        return {}

    try:
        # Import here to avoid circular imports at module load time
        from app.models.narrative import NarrativePost  # noqa: PLC0415
        from app.models.post import Post  # noqa: PLC0415
        from app.models.source import Source  # noqa: PLC0415
        from app.models.source_reliability import SourceReliability  # noqa: PLC0415
    except ImportError as exc:
        logger.debug("fetch_narrative_reliability_weights: model import failed: %s", exc)
        return {}

    try:
        result = await db.execute(
            select(
                NarrativePost.narrative_id,
                SourceReliability.reliability_score,
                SourceReliability.analyst_override,
                SourceReliability.confidence_band,
            )
            .join(Post, Post.id == NarrativePost.post_id)
            .join(
                Source,
                (Source.type == Post.source_type) & (Source.handle == Post.source_id),
            )
            .join(SourceReliability, SourceReliability.source_id == Source.id)
            .where(NarrativePost.narrative_id.in_(narrative_ids))
        )
        rows = result.all()
    except Exception as exc:
        # Table may not exist yet (Checkpoint 1 migration not run) — degrade safely
        logger.debug(
            "fetch_narrative_reliability_weights: DB query failed (table absent?): %s", exc
        )
        return {}

    # Aggregate weights per narrative
    buckets: dict[uuid.UUID, list[float]] = {}
    for nid, rs, ao, band in rows:
        # Build a lightweight stand-in to reuse effective_score logic
        class _Stub:
            reliability_score = rs
            analyst_override = ao
            confidence_band = band

        score = effective_score(_Stub())
        w = reliability_weight(score)
        buckets.setdefault(nid, []).append(w)

    return {nid: sum(ws) / len(ws) for nid, ws in buckets.items() if ws}


async def fetch_source_reliability_for_posts(
    db: "AsyncSession",
    post_ids: list[uuid.UUID],
) -> dict[uuid.UUID, float]:
    """Return a map of post_id → reliability_weight for a list of posts.

    Posts whose source has no reliability record are absent from the result;
    callers should use NEUTRAL_WEIGHT as the fallback.
    """
    if not post_ids:
        return {}

    try:
        from app.models.post import Post  # noqa: PLC0415
        from app.models.source import Source  # noqa: PLC0415
        from app.models.source_reliability import SourceReliability  # noqa: PLC0415
    except ImportError as exc:
        logger.debug("fetch_source_reliability_for_posts: model import failed: %s", exc)
        return {}

    try:
        result = await db.execute(
            select(
                Post.id,
                SourceReliability.reliability_score,
                SourceReliability.analyst_override,
                SourceReliability.confidence_band,
            )
            .join(
                Source,
                (Source.type == Post.source_type) & (Source.handle == Post.source_id),
            )
            .join(SourceReliability, SourceReliability.source_id == Source.id)
            .where(Post.id.in_(post_ids))
        )
        rows = result.all()
    except Exception as exc:
        logger.debug(
            "fetch_source_reliability_for_posts: DB query failed: %s", exc
        )
        return {}

    out: dict[uuid.UUID, float] = {}
    for pid, rs, ao, band in rows:
        class _Stub:
            reliability_score = rs
            analyst_override = ao
            confidence_band = band

        score = effective_score(_Stub())
        out[pid] = reliability_weight(score)

    return out
