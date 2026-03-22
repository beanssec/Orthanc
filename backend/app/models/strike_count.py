import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class StrikeCount(Base):
    __tablename__ = "strike_counts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()")
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    actor: Mapped[str] = mapped_column(String(50), nullable=False)
    strike_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sortie_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_post_ids: Mapped[Optional[list]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=True)
    extraction_method: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
