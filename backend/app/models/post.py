import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Float, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        Index("ix_posts_timestamp", "timestamp"),
        Index("ix_posts_source_type_source_id", "source_type", "source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    author: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    # ── Generic dedup identifier (migration 010) ─────────────────────────────
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    # ── Media fields (migration 009) ──────────────────────────────────────────
    media_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # 'image', 'video', 'document' — null if no media downloaded
    media_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # relative to /app/data/media/
    media_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    media_mime: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    media_thumbnail_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # relative to /app/data/media/thumbnails/
    media_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # EXIF data, video metadata, file hash, dimensions
    authenticity_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # 0.0 = definitely AI, 1.0 = definitely real
    authenticity_analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON-encoded full analysis result
    authenticity_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    events: Mapped[list["Event"]] = relationship(back_populates="post")  # noqa: F821
    alert_hits: Mapped[list["AlertHit"]] = relationship(back_populates="post")  # noqa: F821
