"""Scheduled Brief ORM models — Sprint 31 Checkpoint 1.

Provides durable, per-user scheduled brief configurations plus a lightweight
run-history table so the execution runner can track what happened and when.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ScheduledBrief(Base):
    """A durable, user-owned brief schedule stored in Postgres.

    Supports:
    - Simple daily scheduling via ``schedule_hour_utc``
    - Future cron-style scheduling via ``cron_expr`` (parsed by caller)
    - Model selection, time window, topic filter, source filters
    - Enabled / disabled toggle
    - Delivery method placeholder (default "internal")
    - Last-run / next-run bookkeeping
    """

    __tablename__ = "scheduled_briefs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Identity ─────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Daily Brief")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ── Timing ───────────────────────────────────────────────────────────────
    # Simple hour-of-day (UTC) trigger — e.g. 8 → fires at 08:xx UTC each day.
    # Takes precedence when set.  Set to NULL to rely on cron_expr instead.
    schedule_hour_utc: Mapped[int | None] = mapped_column(Integer, nullable=True, default=8)

    # Future: full cron expression, e.g. "0 8 * * 1-5" (Mon–Fri 08:00 UTC).
    # The runner uses this only if schedule_hour_utc is NULL.
    cron_expr: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── Content config ───────────────────────────────────────────────────────
    model_id: Mapped[str] = mapped_column(String(128), nullable=False, default="grok-3-mini")
    time_window_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)

    # Optional free-text topic filter passed to brief_generator
    topic_filter: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional list of source-type strings, e.g. ["rss", "reddit"]
    # Stored as a Postgres text[] array — may be NULL (= all sources)
    source_filters: Mapped[list[str] | None] = mapped_column(
        ARRAY(String()),
        nullable=True,
    )

    # ── Delivery ─────────────────────────────────────────────────────────────
    # "internal"  → save to briefs table (default)
    # "telegram"  → (future) send to user's Telegram DM
    # "webhook"   → (future) POST to a configured webhook URL
    delivery_method: Mapped[str] = mapped_column(
        String(64), nullable=False, default="internal"
    )

    # ── Execution state ──────────────────────────────────────────────────────
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # "success" | "error" | "running"
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Timestamps ───────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    user = relationship("User", back_populates="scheduled_briefs", lazy="noload")
    runs = relationship(
        "ScheduledBriefRun",
        back_populates="schedule",
        lazy="noload",
        cascade="all, delete-orphan",
        order_by="ScheduledBriefRun.started_at.desc()",
    )


class ScheduledBriefRun(Base):
    """One execution record for a ScheduledBrief.

    Created by the runner when a scheduled brief fires.  Tracks status,
    any error, timing, and optionally the Brief that was produced.
    """

    __tablename__ = "scheduled_brief_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scheduled_briefs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised for efficient per-user history queries without a join
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    # ── Status ───────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="running"
    )  # "running" | "success" | "error"
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # FK to the Brief that was produced (NULL if failed or delivery != internal)
    brief_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("briefs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Timing ───────────────────────────────────────────────────────────────
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    schedule = relationship("ScheduledBrief", back_populates="runs", lazy="noload")
