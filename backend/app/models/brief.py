"""Brief ORM model."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Brief(Base):
    __tablename__ = "briefs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    model: Mapped[str] = mapped_column(String, nullable=False)
    model_name: Mapped[str | None] = mapped_column(String, nullable=True)
    hours: Mapped[int] = mapped_column(Integer, nullable=False)
    post_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    cost_estimate: Mapped[str | None] = mapped_column(String, nullable=True)

    # ── Confidence / reliability metadata (Sprint 29 Checkpoint 4) ───────────
    # Optional — absent for briefs generated before this feature was shipped.
    # confidence_score: 0.0–1.0 weighted average of source reliability weights
    # confidence_label: human-readable band e.g. "high confidence", "conflicting reporting"
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_label: Mapped[str | None] = mapped_column(String(64), nullable=True)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # relationship back to user (lazy, optional)
    user = relationship("User", back_populates="briefs", lazy="noload")
