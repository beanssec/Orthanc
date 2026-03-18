"""tracker_match_rationale

Adds match_rationale (text) to narrative_tracker_matches for TASK-72 match reasoning.

Revision ID: 035_tracker_match_rationale
Revises: 034_narrative_merge
Create Date: 2026-03-16
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "035_tracker_match_rationale"
down_revision = "034_narrative_merge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "narrative_tracker_matches",
        sa.Column("match_rationale", sa.Text(), nullable=True),
    )
    op.add_column(
        "narrative_tracker_matches",
        sa.Column("relevance_score", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("narrative_tracker_matches", "relevance_score")
    op.drop_column("narrative_tracker_matches", "match_rationale")
