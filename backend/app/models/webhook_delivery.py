"""Webhook Delivery model — Sprint 32 Checkpoint 4 (TASK-88).

Tracks each outbound webhook delivery attempt for a ScheduledBrief.
Records the URL, payload hash, response status, and outcome so operators
can audit delivery history and debug failures.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class WebhookDelivery(Base):
    """One webhook delivery attempt for a ScheduledBrief."""

    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    # The scheduled brief this delivery belongs to
    scheduled_brief_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scheduled_briefs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Destination
    url: Mapped[str] = mapped_column(String(2048), nullable=False)

    # SHA-256 hex digest of the JSON payload (for de-dup / auditing)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # HTTP outcome
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # First 1024 chars of the response body for debugging
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Delivery outcome
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Wall-clock timestamp of the attempt
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Optional error message when success=False
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationship back to ScheduledBrief (lazy noload — always queried explicitly)
    scheduled_brief = relationship(
        "ScheduledBrief",
        back_populates="webhook_deliveries",
        lazy="noload",
    )
