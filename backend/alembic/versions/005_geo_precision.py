"""Add precision column to events table.

Revision ID: 005
Revises: 004
Create Date: 2026-03-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "precision",
            sa.String(),
            nullable=True,
            server_default="unknown",
        ),
    )
    op.create_index("ix_events_precision", "events", ["precision"])


def downgrade() -> None:
    op.drop_index("ix_events_precision", table_name="events")
    op.drop_column("events", "precision")
