"""SourceReliability model — Sprint 29, Checkpoint 1.

Dedicated table so Source is not altered destructively.
One row per source; upserted by the reliability scoring service.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class SourceReliability(Base):
    __tablename__ = "source_reliability"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # ── Core reliability signal ───────────────────────────────────────────────
    # Normalised 0.0–1.0 (1.0 = maximally reliable)
    reliability_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ── Confidence band / label ───────────────────────────────────────────────
    # e.g. "high", "medium", "low", "unrated"
    confidence_band: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # ── Analyst override ──────────────────────────────────────────────────────
    # When an analyst manually overrides the computed score.
    analyst_override: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    analyst_note: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # ── Scoring rationale / input signals ────────────────────────────────────
    # JSONB blob capturing the raw inputs used to compute the score.
    # Schema is open for now so we can evolve signals without migrations.
    # Expected keys: corroboration_rate, contradiction_rate, source_type_prior,
    #                activity_score, evidence_quality_avg, post_count, ...
    scoring_inputs: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # ── Timestamps ───────────────────────────────────────────────────────────
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    source: Mapped["Source"] = relationship(back_populates="reliability")  # noqa: F821
