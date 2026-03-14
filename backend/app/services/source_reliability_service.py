"""Source Reliability Service — Sprint 29, Checkpoint 1.

Computes a normalised reliability score (0.0–1.0) for a given Source using
first-pass signals derived from data already present in the system.

Design goals
------------
- Additive / backward-safe: no existing code modified, just call this service.
- Extensible: add new scoring signals by appending to _compute_inputs().
- Async-first: all I/O is async, safe to call from FastAPI route handlers.
- Upsert semantics: one row per source in source_reliability; idempotent.

Scoring signals (v1)
--------------------
1. source_type_prior      — known-reliability priors per source type.
2. activity_score         — penalise sources that haven't posted recently.
3. post_volume            — log-scaled confidence boost for high-volume sources.
4. authenticity_avg       — average authenticity_score from posts (if available).
5. (placeholder) corroboration_rate — requires cross-source evidence linking;
   left as None until evidence_linker / narrative data is wired in Sprint 29 C2.

Band mapping
------------
  ≥ 0.75  → "high"
  ≥ 0.50  → "medium"
  ≥ 0.25  → "low"
  < 0.25  → "unrated"
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.post import Post
from app.models.source import Source
from app.models.source_reliability import SourceReliability

# ── Source-type priors ────────────────────────────────────────────────────────
# These represent editorial baseline trust, not empirical evidence.
# Scale: 0.0–1.0.  Absent types default to 0.5.
SOURCE_TYPE_PRIOR: dict[str, float] = {
    "rss": 0.65,           # Published outlets — moderate trust
    "telegram": 0.45,      # Anonymous channels — lower prior
    "x": 0.50,             # Mixed quality
    "bluesky": 0.52,
    "mastodon": 0.55,
    "reddit": 0.50,
    "discord": 0.42,
    "youtube": 0.55,
    "acled": 0.80,         # Curated conflict data
    "sentinel": 0.75,      # Copernicus satellite — high confidence
    "firms": 0.78,         # NASA FIRMS fire data
    "ais": 0.72,           # AIS vessel tracks — fairly reliable
    "shodan": 0.70,        # Technical scan data — objective
    "cashtag": 0.40,       # Financial chatter — lower prior
    "flight": 0.75,
}


def _band(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.50:
        return "medium"
    if score >= 0.25:
        return "low"
    return "unrated"


async def _compute_inputs(
    source: Source,
    db: AsyncSession,
) -> dict:
    """Gather scoring signals for a single source and return a raw-inputs dict."""
    now = datetime.now(timezone.utc)

    # 1. Source type prior
    type_prior = SOURCE_TYPE_PRIOR.get(source.type, 0.5)

    # 2. Activity score — how recently did the source produce posts?
    #    1.0 = posted in the last hour; decays to 0.0 over 7 days.
    if source.last_polled:
        age_hours = (now - source.last_polled).total_seconds() / 3600
        activity_score = max(0.0, 1.0 - (age_hours / 168))  # 168 h = 7 days
    else:
        activity_score = 0.0

    # 3. Post volume (last 30 days) — log-scaled confidence multiplier
    thirty_ago = now - timedelta(days=30)
    count_result = await db.execute(
        select(func.count(Post.id)).where(
            Post.source_type == source.type,
            Post.source_id == source.handle,
            Post.ingested_at >= thirty_ago,
        )
    )
    post_count: int = count_result.scalar_one_or_none() or 0
    # log10(1+n) / log10(1001) → 0.0 at n=0, ~1.0 at n=1000
    volume_score = math.log10(1 + post_count) / math.log10(1001)
    volume_score = min(1.0, volume_score)

    # 4. Authenticity average from posts with scored media
    auth_result = await db.execute(
        select(func.avg(Post.authenticity_score)).where(
            Post.source_type == source.type,
            Post.source_id == source.handle,
            Post.authenticity_score.isnot(None),
        )
    )
    authenticity_avg: Optional[float] = auth_result.scalar_one_or_none()

    # 5. Corroboration / contradiction — reserved for C2; placeholder here.
    corroboration_rate: Optional[float] = None
    contradiction_rate: Optional[float] = None

    return {
        "source_type_prior": type_prior,
        "activity_score": activity_score,
        "post_count_30d": post_count,
        "volume_score": volume_score,
        "authenticity_avg": authenticity_avg,
        "corroboration_rate": corroboration_rate,
        "contradiction_rate": contradiction_rate,
        "computed_at": now.isoformat(),
    }


def _score_from_inputs(inputs: dict) -> float:
    """Combine scoring inputs into a single 0–1 reliability score.

    Weights are intentionally conservative for v1.  We'll tune in C2 once
    corroboration_rate data is available.
    """
    w_prior = 0.40
    w_activity = 0.25
    w_volume = 0.15
    w_auth = 0.20

    score = inputs["source_type_prior"] * w_prior
    score += inputs["activity_score"] * w_activity
    score += inputs["volume_score"] * w_volume

    auth = inputs.get("authenticity_avg")
    if auth is not None:
        score += float(auth) * w_auth
    else:
        # No media authenticity data — redistribute weight to prior
        score += inputs["source_type_prior"] * w_auth

    return round(min(1.0, max(0.0, score)), 4)


async def compute_and_upsert(
    source: Source,
    db: AsyncSession,
    analyst_override: Optional[float] = None,
    analyst_note: Optional[str] = None,
) -> SourceReliability:
    """Compute reliability for *source* and upsert into source_reliability.

    If analyst_override is supplied, that value takes precedence for the
    confidence_band label but the computed score is still stored separately.
    """
    inputs = await _compute_inputs(source, db)
    computed_score = _score_from_inputs(inputs)

    effective_score = analyst_override if analyst_override is not None else computed_score
    band = _band(effective_score)

    # Upsert
    result = await db.execute(
        select(SourceReliability).where(SourceReliability.source_id == source.id)
    )
    rel = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if rel is None:
        rel = SourceReliability(
            id=uuid.uuid4(),
            source_id=source.id,
            reliability_score=computed_score,
            confidence_band=band,
            analyst_override=analyst_override,
            analyst_note=analyst_note,
            scoring_inputs=inputs,
            created_at=now,
            updated_at=now,
        )
        db.add(rel)
    else:
        rel.reliability_score = computed_score
        rel.confidence_band = band
        rel.scoring_inputs = inputs
        rel.updated_at = now
        if analyst_override is not None:
            rel.analyst_override = analyst_override
        if analyst_note is not None:
            rel.analyst_note = analyst_note

    await db.flush()
    return rel


async def compute_all_sources(db: AsyncSession) -> int:
    """Bulk-score every source in the database.  Returns count processed.

    Called by a background job or one-shot endpoint; not called on hot path.
    """
    result = await db.execute(select(Source))
    sources = result.scalars().all()

    for source in sources:
        await compute_and_upsert(source, db)

    await db.commit()
    return len(sources)
