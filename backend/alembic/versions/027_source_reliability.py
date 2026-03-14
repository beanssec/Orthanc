"""source_reliability — Sprint 29 Checkpoint 1

Revision ID: 027
Revises: 026
Create Date: 2026-03-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_reliability",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        # Core score
        sa.Column("reliability_score", sa.Float(), nullable=True),
        # Confidence band label: "high" | "medium" | "low" | "unrated"
        sa.Column("confidence_band", sa.String(32), nullable=True),
        # Analyst override
        sa.Column("analyst_override", sa.Float(), nullable=True),
        sa.Column("analyst_note", sa.String(1024), nullable=True),
        # Raw scoring inputs (open JSONB)
        sa.Column("scoring_inputs", postgresql.JSONB(), nullable=True),
        # Timestamps
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "ix_source_reliability_source_id",
        "source_reliability",
        ["source_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_source_reliability_source_id", table_name="source_reliability")
    op.drop_table("source_reliability")
