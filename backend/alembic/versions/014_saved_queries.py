"""Add saved_queries and query_history tables for OQL.

Revision ID: 014_saved_queries
Revises: 013_investigations
Create Date: 2026-03-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "014_saved_queries"
down_revision: Union[str, None] = "013_investigations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "saved_queries",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("query_text", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("visualization_config", postgresql.JSONB, nullable=True),
        sa.Column("is_pinned", sa.Boolean, server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "query_history",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query_text", sa.Text, nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("row_count", sa.Integer, nullable=True),
        sa.Column("duration_ms", sa.Float, nullable=True),
    )

    op.create_index("ix_query_history_user_executed", "query_history", ["user_id", "executed_at"])
    op.create_index("ix_saved_queries_user", "saved_queries", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_saved_queries_user", table_name="saved_queries")
    op.drop_index("ix_query_history_user_executed", table_name="query_history")
    op.drop_table("query_history")
    op.drop_table("saved_queries")
