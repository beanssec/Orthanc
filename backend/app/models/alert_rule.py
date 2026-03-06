import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class AlertRule(Base):
    __tablename__ = "alert_rules"

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
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    rule_type: Mapped[str] = mapped_column(String, nullable=False)  # keyword, velocity, correlation
    severity: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'routine'")
    )  # flash, urgent, routine

    # Level 1: keyword config
    keywords: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String), nullable=True)
    keyword_mode: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # any, all, regex
    source_types: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String), nullable=True)

    # Level 2: velocity config
    entity_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    velocity_threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    velocity_window_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Level 3: correlation directives
    directives: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    # Geo-proximity config
    geo_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    geo_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    geo_radius_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    geo_label: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Silence detection config
    silence_entity: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    silence_source_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    silence_expected_interval_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    silence_last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    cooldown_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("60")
    )
    delivery_channels: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(String), server_default=text("'{in_app}'"), nullable=True
    )
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    webhook_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_fired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="alert_rules")  # noqa: F821
    events: Mapped[list["AlertEvent"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("alert_rules.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    matched_post_ids: Mapped[Optional[list[uuid.UUID]]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True
    )
    matched_entities: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String), nullable=True)
    context: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    acknowledged: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    # Relationships
    rule: Mapped["AlertRule"] = relationship(back_populates="events")
    user: Mapped["User"] = relationship()  # noqa: F821
