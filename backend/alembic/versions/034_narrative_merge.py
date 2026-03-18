"""narrative_merge_tracking

Adds merged_into (nullable self-referential FK) to narratives for duplicate detection.

Revision ID: 034_narrative_merge
Revises: 033_entity_merge
Create Date: 2026-03-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "034_narrative_merge"
down_revision = "033_entity_merge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # nullable self-referential FK: smaller/duplicate narrative points to canonical one
    op.add_column(
        "narratives",
        sa.Column(
            "merged_into",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_narratives_merged_into",
        "narratives",
        "narratives",
        ["merged_into"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "narratives",
        sa.Column("merge_candidate_score", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_constraint("fk_narratives_merged_into", "narratives", type_="foreignkey")
    op.drop_column("narratives", "merge_candidate_score")
    op.drop_column("narratives", "merged_into")
