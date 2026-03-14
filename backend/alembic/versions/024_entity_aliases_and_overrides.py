"""Add entity aliases and type override tables.

Revision ID: 024_entity_aliases_and_overrides
Revises: 023_narrative_trackers
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "024_entity_aliases_and_overrides"
down_revision = "023_narrative_trackers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entity_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias_text", sa.String(), nullable=False),
        sa.Column("alias_norm", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("source", sa.String(), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_entity_aliases_norm", "entity_aliases", ["alias_norm"])
    op.create_index("ix_entity_aliases_entity", "entity_aliases", ["entity_id"])

    op.create_table(
        "entity_type_overrides",
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("override_type", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("entity_type_overrides")
    op.drop_index("ix_entity_aliases_entity", table_name="entity_aliases")
    op.drop_index("ix_entity_aliases_norm", table_name="entity_aliases")
    op.drop_table("entity_aliases")
