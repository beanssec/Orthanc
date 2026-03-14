"""brief_confidence — Sprint 29 Checkpoint 4

Adds optional confidence_score and confidence_label columns to the briefs
table.  Both are nullable so existing rows are unaffected (backward-safe).

Revision ID: 028
Revises: 027
Create Date: 2026-03-14
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "briefs",
        sa.Column("confidence_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "briefs",
        sa.Column("confidence_label", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("briefs", "confidence_label")
    op.drop_column("briefs", "confidence_score")
