"""evidence_classification

Adds evidence_role, evidence_confidence, and evidence_classified_at columns
to the narrative_posts table for Sprint Claim Extraction CP2.

evidence_role valid values: supports, contradicts, contextual, unclear, NULL (unclassified)

Revision ID: 041_evidence_classification
Revises: 040_triage_workflow
Create Date: 2026-03-16
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "041_evidence_classification"
down_revision = "040_triage_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "narrative_posts",
        sa.Column("evidence_role", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "narrative_posts",
        sa.Column("evidence_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "narrative_posts",
        sa.Column("evidence_classified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("narrative_posts", "evidence_classified_at")
    op.drop_column("narrative_posts", "evidence_confidence")
    op.drop_column("narrative_posts", "evidence_role")
