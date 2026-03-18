"""api_key_scope

Adds scope column to api_keys table for TASK-89 API key scoping.

Values: "read_write" (default) or "read_only".
Read-only keys are blocked from POST/PUT/PATCH/DELETE endpoints by middleware.

Revision ID: 038_api_key_scope
Revises: 037_webhook_deliveries
Create Date: 2026-03-16
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "038_api_key_scope"
down_revision = "037_webhook_deliveries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column(
            "scope",
            sa.String(length=16),
            nullable=False,
            server_default="read_write",
        ),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "scope")
