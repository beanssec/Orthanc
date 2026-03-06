"""Entity relationship and entity property models."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class EntityRelationship(Base):
    """Typed directional or bidirectional relationship between two entities."""
    __tablename__ = "entity_relationships"
    __table_args__ = (
        UniqueConstraint("source_entity_id", "target_entity_id", "relationship_type"),
        Index("ix_entity_rel_source", "source_entity_id"),
        Index("ix_entity_rel_target", "target_entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5")
    evidence_post_ids: Mapped[Optional[list[uuid.UUID]]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=True
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    source_entity: Mapped["Entity"] = relationship(  # noqa: F821
        "Entity", foreign_keys=[source_entity_id]
    )
    target_entity: Mapped["Entity"] = relationship(  # noqa: F821
        "Entity", foreign_keys=[target_entity_id]
    )
    creator: Mapped[Optional["User"]] = relationship(  # noqa: F821
        "User", foreign_keys=[created_by]
    )


class EntityProperty(Base):
    """Extensible key-value property attached to an entity."""
    __tablename__ = "entity_properties"
    __table_args__ = (
        UniqueConstraint("entity_id", "key"),
        Index("ix_entity_props", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    entity: Mapped["Entity"] = relationship("Entity", foreign_keys=[entity_id])  # noqa: F821
    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by])  # noqa: F821
