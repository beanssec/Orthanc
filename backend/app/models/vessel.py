"""SQLAlchemy models for maritime intelligence — vessel tracks, watchlist, events."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class VesselTrack(Base):
    """Historical AIS position record for a vessel."""

    __tablename__ = "vessel_tracks"
    __table_args__ = (
        Index("ix_vessel_tracks_mmsi_ts", "mmsi", "timestamp"),
        Index("ix_vessel_tracks_ts", "timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    mmsi: Mapped[str] = mapped_column(String(20), nullable=False)
    imo: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    vessel_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    vessel_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    flag: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    speed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    heading: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    course: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    destination: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class VesselWatchlist(Base):
    """User-defined watchlist of vessels of interest."""

    __tablename__ = "vessel_watchlist"
    __table_args__ = (
        Index("ix_vessel_watchlist_mmsi", "mmsi"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    mmsi: Mapped[str] = mapped_column(String(20), nullable=False)
    vessel_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    alert_on_dark: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    alert_on_sts: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    alert_on_port_call: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped["User"] = relationship("User")  # noqa: F821


class MaritimeEvent(Base):
    """Detected maritime intelligence event (dark ship, STS transfer, port call)."""

    __tablename__ = "maritime_events"
    __table_args__ = (
        Index("ix_maritime_events_type", "event_type"),
        Index("ix_maritime_events_mmsi", "mmsi"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    # dark_ship, sts_transfer, port_call, deviation
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    mmsi: Mapped[str] = mapped_column(String(20), nullable=False)
    vessel_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # routine, notable, critical
    severity: Mapped[str] = mapped_column(String(20), nullable=False, server_default="'routine'")
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
