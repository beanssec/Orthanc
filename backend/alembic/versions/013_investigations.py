"""Add investigation case management tables.

Revision ID: 013_investigations
Revises: 011_sanctions
Create Date: 2026-03-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "013_investigations"
down_revision: Union[str, None] = "012_fused_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create cases table
    op.create_table(
        "cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("classification", sa.String(50), nullable=True, server_default="unclassified"),
        sa.Column("status", sa.String(20), nullable=True, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_cases_user", "cases", ["user_id"])
    op.create_index("ix_cases_status", "cases", ["status"])

    # Create case_items table
    op.create_table(
        "case_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_type", sa.String(50), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("lat", sa.Float, nullable=True),
        sa.Column("lng", sa.Float, nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True, server_default="{}"),
        sa.Column("added_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_case_items_case", "case_items", ["case_id"])
    op.create_index("ix_case_items_type", "case_items", ["item_type"])

    # Create case_timeline table
    op.create_table(
        "case_timeline",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("added_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_case_timeline_case", "case_timeline", ["case_id"])


def downgrade() -> None:
    op.drop_index("ix_case_timeline_case", "case_timeline")
    op.drop_table("case_timeline")
    op.drop_index("ix_case_items_type", "case_items")
    op.drop_index("ix_case_items_case", "case_items")
    op.drop_table("case_items")
    op.drop_index("ix_cases_status", "cases")
    op.drop_index("ix_cases_user", "cases")
    op.drop_table("cases")
