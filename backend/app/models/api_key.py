"""API Key model — Sprint 30 / Checkpoint 1.

Keys are stored hashed (SHA-256). The raw plaintext is generated once
and returned to the caller at creation time; it is never stored.

Prefix format: ``ow_<first8chars>`` — shown to users so they can identify
which key is which without exposing the full secret.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

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
    # Human-readable label chosen by the user (e.g. "my-agent-key")
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # First 8 characters of the raw key prefixed with "ow_" — safe to display
    prefix: Mapped[str] = mapped_column(String(32), nullable=False)

    # SHA-256 hex digest of the full raw key (never the raw value)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    # Scopes stored as a Postgres text array, e.g. {"read:feed", "read:entities"}
    # A NULL / empty array means read-only (most restrictive default).
    scopes: Mapped[List[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default=text("ARRAY[]::text[]")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    # Relationship back to User (lazy load; User model has no back-ref yet —
    # we add it non-intrusively via backref on this side only)
    user: Mapped["User"] = relationship(back_populates="api_keys")  # noqa: F821

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None
