"""TaskModelOverride — persists user-specific task→model selections."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TaskModelOverride(Base):
    """Durable storage for per-user task→model assignments.

    One row per (user_id, task) pair — unique constraint ensures clean upsert
    via INSERT … ON CONFLICT DO UPDATE.
    """

    __tablename__ = "task_model_overrides"

    __table_args__ = (
        UniqueConstraint("user_id", "task", name="uq_task_model_override_user_task"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task: Mapped[str] = mapped_column(String(128), nullable=False)
    model_id: Mapped[str] = mapped_column(String(256), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )
