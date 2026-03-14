import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    credentials: Mapped[list["Credential"]] = relationship(back_populates="user")  # noqa: F821
    sources: Mapped[list["Source"]] = relationship(back_populates="user")  # noqa: F821
    alerts: Mapped[list["Alert"]] = relationship(back_populates="user")  # noqa: F821
    alert_rules: Mapped[list["AlertRule"]] = relationship(back_populates="user", lazy="noload")  # noqa: F821
    briefs: Mapped[list["Brief"]] = relationship(back_populates="user", lazy="noload")  # noqa: F821
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user", lazy="noload")  # noqa: F821
