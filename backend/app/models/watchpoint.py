"""Satellite watchpoint and snapshot models."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class SatWatchpoint(Base):
    __tablename__ = "sat_watchpoints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    radius_km: Mapped[float] = mapped_column(Float, default=10.0)
    category: Mapped[Optional[str]] = mapped_column(String(50))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_image_date: Mapped[Optional[str]] = mapped_column(String(20))
    change_threshold: Mapped[float] = mapped_column(Float, default=0.05)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    snapshots: Mapped[list[SatSnapshot]] = relationship(
        "SatSnapshot", back_populates="watchpoint", cascade="all, delete-orphan"
    )


class SatSnapshot(Base):
    __tablename__ = "sat_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    watchpoint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sat_watchpoints.id", ondelete="CASCADE")
    )
    image_date: Mapped[str] = mapped_column(String(20))
    product_id: Mapped[Optional[str]] = mapped_column(String(100))
    cloud_cover: Mapped[Optional[float]] = mapped_column(Float)
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(500))
    pixel_hash: Mapped[Optional[str]] = mapped_column(String(64))
    change_score: Mapped[Optional[float]] = mapped_column(Float)
    change_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    watchpoint: Mapped[SatWatchpoint] = relationship("SatWatchpoint", back_populates="snapshots")
