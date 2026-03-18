"""triage_workflow

Adds triage_status and triage_notes columns to narratives table for the
Sprint Claim Extraction CP3 triage workflow.

triage_status valid values: detected, under_review, confirmed, contradicted, archived
Existing narratives that already have a canonical_claim set are seeded with
triage_status = 'detected' so analysts can immediately begin triaging them.

Revision ID: 040_triage_workflow
Revises: 038_api_key_scope
Create Date: 2026-03-16
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "040_triage_workflow"
down_revision = "039_claim_extraction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "narratives",
        sa.Column("triage_status", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "narratives",
        sa.Column("triage_notes", sa.Text(), nullable=True),
    )

    # Seed existing narratives that have a canonical_claim with 'detected'
    op.execute(
        """
        UPDATE narratives
        SET triage_status = 'detected'
        WHERE canonical_claim IS NOT NULL
          AND triage_status IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("narratives", "triage_notes")
    op.drop_column("narratives", "triage_status")
