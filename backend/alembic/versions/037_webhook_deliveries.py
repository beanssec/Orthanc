"""webhook_deliveries

Creates the webhook_deliveries table for TASK-88 delivery tracking.

Revision ID: 037_webhook_deliveries
Revises: 036_source_poll_interval_and_filters
Create Date: 2026-03-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "037_webhook_deliveries"
down_revision = "036_src_poll_filters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_deliveries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "scheduled_brief_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scheduled_briefs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "delivered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    # index=True on the column auto-creates the index; no explicit create_index needed


def downgrade() -> None:
    op.drop_table("webhook_deliveries")  # index auto-dropped with table
