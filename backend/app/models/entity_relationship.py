import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
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
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    sample_post_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="'[]'")

    entity_a: Mapped["Entity"] = relationship(foreign_keys=[entity_a_id])  # noqa: F821
    entity_b: Mapped["Entity"] = relationship(foreign_keys=[entity_b_id])  # noqa: F821
