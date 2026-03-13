import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class EntityRelationship(Base):
    """Co-occurrence relationship between two entities across posts."""

    __tablename__ = "entity_relationships"
    __table_args__ = (
        UniqueConstraint("entity_a_id", "entity_b_id", name="uq_entity_rel_pair"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    entity_a_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_b_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # Manual analyst relationship metadata (UI CRUD)
    relationship_type: Mapped[str] = mapped_column(String, nullable=False, default="associated", server_default="associated")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5, server_default="0.5")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    sample_post_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="'[]'")

    entity_a: Mapped["Entity"] = relationship(foreign_keys=[entity_a_id])  # noqa: F821
    entity_b: Mapped["Entity"] = relationship(foreign_keys=[entity_b_id])  # noqa: F821
