"""source_poll_interval_and_filters

Adds poll_interval_seconds, filter_keywords, and filter_mode to the sources table.

TASK-84: poll_interval_seconds — per-source poll interval override (nullable integer).
TASK-85: filter_keywords — JSON keyword list, filter_mode — include/exclude logic.

Revision ID: 036_source_poll_interval_and_filters
Revises: 035_tracker_match_rationale
Create Date: 2026-03-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "036_src_poll_filters"
down_revision = "035_tracker_match_rationale"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # TASK-84: per-source poll interval (seconds). NULL = use collector default.
    op.add_column(
        "sources",
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=True),
    )

    # TASK-85: content keyword filtering
    op.add_column(
        "sources",
        sa.Column(
            "filter_keywords",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "sources",
        sa.Column("filter_mode", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sources", "filter_mode")
    op.drop_column("sources", "filter_keywords")
    op.drop_column("sources", "poll_interval_seconds")
