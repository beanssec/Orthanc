"""Add canonical narrative intelligence fields to narratives table.

Revision ID: 025_narrative_canonical_fields
Revises: 024_entity_aliases_and_overrides
Create Date: 2026-03-14
"""

from alembic import op
import sqlalchemy as sa


revision = "025_narrative_canonical_fields"
down_revision = "024_entity_aliases_and_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("narratives", sa.Column("raw_title", sa.Text(), nullable=True))
    op.add_column("narratives", sa.Column("canonical_title", sa.Text(), nullable=True))
    op.add_column("narratives", sa.Column("canonical_claim", sa.Text(), nullable=True))
    op.add_column("narratives", sa.Column("narrative_type", sa.String(50), nullable=True))
    op.add_column("narratives", sa.Column("label_confidence", sa.Float(), nullable=True))
    op.add_column("narratives", sa.Column("confirmation_status", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("narratives", "confirmation_status")
    op.drop_column("narratives", "label_confidence")
    op.drop_column("narratives", "narrative_type")
    op.drop_column("narratives", "canonical_claim")
    op.drop_column("narratives", "canonical_title")
    op.drop_column("narratives", "raw_title")
