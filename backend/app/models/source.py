import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    handle: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_polled: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    config_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # ── Media download settings (migration 009) ───────────────────────────────
    download_images: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    download_videos: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    max_image_size_mb: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("10")
    )
    max_video_size_mb: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("100")
    )

    user: Mapped["User"] = relationship(back_populates="sources")  # noqa: F821
    bias_profiles: Mapped[list["SourceBiasProfile"]] = relationship(  # noqa: F821
        back_populates="source", cascade="all, delete-orphan"
    )
