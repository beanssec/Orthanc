"""SQLAlchemy models for OpenSanctions integration."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class SanctionsEntity(Base):
    """Cached entity from the OpenSanctions bulk dataset."""

    __tablename__ = "sanctions_entities"
    __table_args__ = (
        Index("ix_sanctions_entities_entity_type", "entity_type"),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    aliases: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True, server_default=text("'{}'"))
    datasets: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True, server_default=text("'{}'"))
    countries: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True, server_default=text("'{}'"))
    properties: Mapped[dict | None] = mapped_column(JSON, nullable=True, server_default=text("'{}'"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    matches: Mapped[list["EntitySanctionsMatch"]] = relationship(
        back_populates="sanctions_entity", cascade="all, delete-orphan"
    )


class EntitySanctionsMatch(Base):
    """A link between a platform entity and a sanctions list entry."""

    __tablename__ = "entity_sanctions_matches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    sanctions_entity_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("sanctions_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    matched_on: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 'name' or 'alias'
    datasets: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    sanctions_entity: Mapped["SanctionsEntity"] = relationship(back_populates="matches")
