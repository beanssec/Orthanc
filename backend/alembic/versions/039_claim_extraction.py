"""claim_extraction

Adds claim extraction fields to the narratives table.

Stores the extracted claim assertion, claimant, type, confidence,
and extraction timestamp from the LLM-powered claim extraction pipeline.

Revision ID: 039_claim_extraction
Revises: 038_api_key_scope
Create Date: 2026-03-16
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "039_claim_extraction"
down_revision = "038_api_key_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("narratives", sa.Column("claim_text", sa.Text(), nullable=True))
    op.add_column("narratives", sa.Column("claimant", sa.Text(), nullable=True))
    op.add_column("narratives", sa.Column("claim_type", sa.String(length=50), nullable=True))
    op.add_column("narratives", sa.Column("claim_confidence", sa.Float(), nullable=True))
    op.add_column(
        "narratives",
        sa.Column("claim_extracted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("narratives", "claim_extracted_at")
    op.drop_column("narratives", "claim_confidence")
    op.drop_column("narratives", "claim_type")
    op.drop_column("narratives", "claimant")
    op.drop_column("narratives", "claim_text")
