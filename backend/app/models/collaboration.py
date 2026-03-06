"""Per-user collaboration models: notes, bookmarks, tags."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class UserNote(Base):
    """A user's private note attached to any object (entity, post, event)."""
    __tablename__ = "user_notes"
    __table_args__ = (
        Index("ix_user_notes_target", "target_type", "target_id"),
        Index("ix_user_notes_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String, nullable=False)  # 'entity', 'post', 'event'
    target_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])  # noqa: F821


class UserBookmark(Base):
    """A user's bookmark on any object."""
    __tablename__ = "user_bookmarks"
    __table_args__ = (
        UniqueConstraint("user_id", "target_type", "target_id"),
        Index("ix_user_bookmarks_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String, nullable=False)  # 'entity', 'post', 'event', 'brief'
    target_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])  # noqa: F821


class UserTag(Base):
    """A user-defined tag on any object."""
    __tablename__ = "user_tags"
    __table_args__ = (
        UniqueConstraint("user_id", "target_type", "target_id", "tag"),
        Index("ix_user_tags_user", "user_id"),
        Index("ix_user_tags_tag", "tag"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    tag: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])  # noqa: F821
