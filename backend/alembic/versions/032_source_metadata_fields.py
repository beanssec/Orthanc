"""source_metadata_fields — Sprint 32 Checkpoint 3

Adds four nullable classification columns to the sources table:
  * source_class            — classification label (official / state_media / etc.)
  * default_reliability_prior — reliability band (high / medium / low)
  * ecosystem               — thematic/geographic domain (sanctions, iran, etc.)
  * risk_note               — free-text analyst note

Revision ID: 032_source_metadata_fields
Revises: 031_scheduled_briefs
Create Date: 2026-03-15
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "032_source_metadata_fields"
down_revision = "031_scheduled_briefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("source_class", sa.String(64), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column("default_reliability_prior", sa.String(16), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column("ecosystem", sa.String(128), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column("risk_note", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sources", "risk_note")
    op.drop_column("sources", "ecosystem")
    op.drop_column("sources", "default_reliability_prior")
    op.drop_column("sources", "source_class")
