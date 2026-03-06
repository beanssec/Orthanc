import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Entity(Base):
    """A named entity extracted from post content."""
    __tablename__ = "entities"
    __table_args__ = (
        Index("ix_entities_type", "type"),
        Index("ix_entities_canonical", "canonical_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)  # PERSON, ORG, GPE, EVENT, NORP
    canonical_name: Mapped[str] = mapped_column(String, nullable=False)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    mentions: Mapped[list["EntityMention"]] = relationship(back_populates="entity", cascade="all, delete-orphan")


class EntityMention(Base):
    """A mention of an entity in a specific post."""
    __tablename__ = "entity_mentions"
    __table_args__ = (
        Index("ix_entity_mentions_entity", "entity_id"),
        Index("ix_entity_mentions_post", "post_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), nullable=False
    )
    context_snippet: Mapped[str | None] = mapped_column(String, nullable=True)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    entity: Mapped["Entity"] = relationship(back_populates="mentions")
    post: Mapped["Post"] = relationship()  # noqa: F821
