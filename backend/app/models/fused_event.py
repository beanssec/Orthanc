import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Double, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class FusedEvent(Base):
    __tablename__ = "fused_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    component_post_ids: Mapped[Optional[list]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True, server_default=text("'{}'")
    )
    component_source_types: Mapped[Optional[list]] = mapped_column(
        ARRAY(Text), nullable=True, server_default=text("'{}'")
    )
    centroid_lat: Mapped[Optional[float]] = mapped_column(Double(), nullable=True)
    centroid_lng: Mapped[Optional[float]] = mapped_column(Double(), nullable=True)
    radius_km: Mapped[Optional[float]] = mapped_column(Double(), nullable=True)
    time_window_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    time_window_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    event_types: Mapped[Optional[list]] = mapped_column(
        ARRAY(Text), nullable=True, server_default=text("'{}'")
    )
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="routine"
    )
    ai_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    entity_names: Mapped[Optional[list]] = mapped_column(
        ARRAY(Text), nullable=True, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
