"""Brief Confidence Layer — Sprint 29, Checkpoint 4.

Computes structured confidence metadata for a set of posts whose source
reliability weights have been pre-fetched.  Designed to be called from
brief_generator.generate_brief() just before building the AI prompt.

Design goals
------------
- Additive & backward-safe: callers receive a plain dict; existing code
  that ignores these keys is unaffected.
- Degrade gracefully: when no reliability data is available for any post,
  we emit a neutral "unrated" result rather than raising.
- Structured for agents: the returned dict is JSON-serialisable and stable
  so downstream API consumers can act on it programmatically.

Confidence labels
-----------------
  high        ≥ 0.70 weighted average, ≥ 40% posts with known reliability
  medium      ≥ 0.45 weighted average, or < 40% coverage
  low         < 0.45 weighted average
  conflicting ≥ 20% high-weight posts AND ≥ 20% low-weight posts simultaneously
  early/weak  < 10% posts have any reliability data
"""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from app.services.source_reliability_helper import (
    NEUTRAL_WEIGHT,
    WEIGHT_FLOOR,
    confidence_label_from_score,
    fetch_source_reliability_for_posts,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("orthanc.brief_confidence")

# Thresholds
HIGH_WEIGHT_CUTOFF = 0.70   # post weight considered "high confidence"
LOW_WEIGHT_CUTOFF = 0.40    # post weight considered "low confidence"
CONFLICT_FRACTION = 0.20    # fraction of high AND low posts that triggers "conflicting"
COVERAGE_EARLY_SIGNAL = 0.10  # < 10% posts with reliability data → early/weak


def _build_label(
    avg_weight: float,
    coverage: float,
    conflicting: bool,
    early_signal: bool,
) -> str:
    """Derive the primary confidence label from aggregated metrics."""
    if early_signal:
        return "early/weak signal"
    if conflicting:
        return "conflicting reporting"
    if avg_weight >= HIGH_WEIGHT_CUTOFF and coverage >= 0.40:
        return "high confidence"
    if avg_weight >= 0.45:
        return "medium confidence"
    return "low confidence"


def _build_summary(
    label: str,
    avg_weight: float,
    coverage: float,
    high_frac: float,
    low_frac: float,
    post_count: int,
    rated_count: int,
) -> str:
    """Build a one-sentence human-readable confidence summary."""
    pct = int(coverage * 100)
    if label == "early/weak signal":
        return (
            f"Early/weak signal: only {rated_count} of {post_count} posts have source "
            "reliability data. Treat findings as provisional."
        )
    if label == "conflicting reporting":
        return (
            f"Conflicting reporting detected: {int(high_frac * 100)}% of sources are "
            f"high-reliability while {int(low_frac * 100)}% are low-reliability. "
            "Independent verification recommended."
        )
    if label == "high confidence":
        return (
            f"High confidence: {pct}% of posts have reliability data; sources are "
            f"predominantly high-rated (avg weight {avg_weight:.2f})."
        )
    if label == "medium confidence":
        return (
            f"Medium confidence: {pct}% of posts have reliability data; source mix "
            f"yields an average reliability weight of {avg_weight:.2f}."
        )
    # low confidence
    return (
        f"Low confidence: {pct}% of posts have reliability data; source quality is "
        f"below threshold (avg weight {avg_weight:.2f}). Exercise caution."
    )


async def compute_brief_confidence(
    db: "AsyncSession",
    post_ids: list[uuid.UUID],
) -> dict:
    """Compute confidence metadata for a brief covering ``post_ids``.

    Returns a structured dict that is always populated (never raises).

    Return schema
    -------------
    {
        "confidence_score":   float,        # 0.0–1.0; NEUTRAL_WEIGHT if unknown
        "confidence_label":   str,          # human-readable label
        "confidence_summary": str,          # one-sentence explanation
        "source_coverage":    float,        # fraction of posts with reliability data
        "high_confidence_fraction": float,  # fraction of posts that are high-weight
        "low_confidence_fraction":  float,  # fraction of posts that are low-weight
        "conflicting_signals": bool,
        "early_signal":        bool,
        "rated_post_count":    int,
        "total_post_count":    int,
    }
    """
    total = len(post_ids)
    if total == 0:
        return _neutral_result(0)

    # Fetch reliability weights — degrades to {} on any DB/import error
    weight_map = await fetch_source_reliability_for_posts(db, post_ids)

    rated_count = len(weight_map)
    coverage = rated_count / total if total > 0 else 0.0
    early_signal = coverage < COVERAGE_EARLY_SIGNAL

    if not weight_map:
        # No reliability data at all
        return {
            "confidence_score": NEUTRAL_WEIGHT,
            "confidence_label": "unrated",
            "confidence_summary": (
                f"No source reliability data available for the {total} posts in this brief. "
                "Confidence is unrated."
            ),
            "source_coverage": 0.0,
            "high_confidence_fraction": 0.0,
            "low_confidence_fraction": 0.0,
            "conflicting_signals": False,
            "early_signal": False,
            "rated_post_count": 0,
            "total_post_count": total,
        }

    weights = list(weight_map.values())
    avg_weight = sum(weights) / len(weights)

    # Fraction of RATED posts that are high / low
    high_count = sum(1 for w in weights if w >= HIGH_WEIGHT_CUTOFF)
    low_count = sum(1 for w in weights if w <= LOW_WEIGHT_CUTOFF)
    high_frac = high_count / rated_count
    low_frac = low_count / rated_count

    conflicting = (high_frac >= CONFLICT_FRACTION and low_frac >= CONFLICT_FRACTION)

    label = _build_label(avg_weight, coverage, conflicting, early_signal)
    summary = _build_summary(
        label, avg_weight, coverage, high_frac, low_frac, total, rated_count
    )

    return {
        "confidence_score": round(avg_weight, 4),
        "confidence_label": label,
        "confidence_summary": summary,
        "source_coverage": round(coverage, 4),
        "high_confidence_fraction": round(high_frac, 4),
        "low_confidence_fraction": round(low_frac, 4),
        "conflicting_signals": conflicting,
        "early_signal": early_signal,
        "rated_post_count": rated_count,
        "total_post_count": total,
    }


def _neutral_result(total: int) -> dict:
    return {
        "confidence_score": NEUTRAL_WEIGHT,
        "confidence_label": "unrated",
        "confidence_summary": "No posts available; confidence is unrated.",
        "source_coverage": 0.0,
        "high_confidence_fraction": 0.0,
        "low_confidence_fraction": 0.0,
        "conflicting_signals": False,
        "early_signal": False,
        "rated_post_count": 0,
        "total_post_count": total,
    }


def confidence_context_block(confidence: dict) -> str:
    """Format confidence metadata as a concise analyst note for the AI prompt.

    This block is appended to the user message so the AI can acknowledge
    data quality in its brief.
    """
    label = confidence.get("confidence_label", "unrated")
    summary = confidence.get("confidence_summary", "")
    coverage = confidence.get("source_coverage", 0.0)
    conflicting = confidence.get("conflicting_signals", False)
    early = confidence.get("early_signal", False)

    lines = [
        "--- SOURCE RELIABILITY ASSESSMENT ---",
        f"Overall confidence: {label.upper()}",
        f"Source coverage: {int(coverage * 100)}% of posts have reliability data",
        f"Summary: {summary}",
    ]
    if conflicting:
        lines.append(
            "⚠ CONFLICT FLAG: This data set contains a significant mix of high- and "
            "low-reliability sources. Note any claims that rest on low-reliability "
            "sources alone."
        )
    if early:
        lines.append(
            "⚠ EARLY/WEAK SIGNAL: Reliability data is sparse. Treat findings as "
            "provisional and flag uncertainty in the brief."
        )
    lines.append("--- END RELIABILITY ASSESSMENT ---")
    return "\n".join(lines)
