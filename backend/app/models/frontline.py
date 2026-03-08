"""Frontline snapshot model."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import Date, DateTime, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FrontlineSnapshot(Base):
    __tablename__ = "frontline_snapshots"

    __table_args__ = (
        UniqueConstraint("date", "source", name="uq_frontline_date_source"),
        Index("idx_frontline_date", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    date: Mapped[date] = mapped_column(Date(), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="deepstate")
    geojson: Mapped[dict] = mapped_column(JSONB(), nullable=False)
    geometry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_metadata: Mapped[Optional[dict]] = mapped_column(
        "metadata", JSONB(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
