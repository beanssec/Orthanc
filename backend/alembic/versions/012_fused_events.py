"""Add fused_events table for cross-source intelligence fusion.

Revision ID: 012_fused_events
Revises: 011_sanctions
Create Date: 2026-03-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "012_fused_events"
down_revision: Union[str, None] = "011_sanctions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fused_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "component_post_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=True,
            server_default="{}",
        ),
        sa.Column(
            "component_source_types",
            sa.ARRAY(sa.Text),
            nullable=True,
            server_default="{}",
        ),
        sa.Column("centroid_lat", sa.Double(), nullable=True),
        sa.Column("centroid_lng", sa.Double(), nullable=True),
        sa.Column("radius_km", sa.Double(), nullable=True),
        sa.Column("time_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "event_types",
            sa.ARRAY(sa.Text),
            nullable=True,
            server_default="{}",
        ),
        sa.Column(
            "severity",
            sa.String(20),
            nullable=False,
            server_default="routine",
        ),
        sa.Column("ai_summary", sa.Text, nullable=True),
        sa.Column(
            "entity_names",
            sa.ARRAY(sa.Text),
            nullable=True,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_fused_events_created",
        "fused_events",
        ["created_at"],
        postgresql_ops={"created_at": "DESC"},
    )
    op.create_index("ix_fused_events_severity", "fused_events", ["severity"])


def downgrade() -> None:
    op.drop_index("ix_fused_events_severity", table_name="fused_events")
    op.drop_index("ix_fused_events_created", table_name="fused_events")
    op.drop_table("fused_events")
