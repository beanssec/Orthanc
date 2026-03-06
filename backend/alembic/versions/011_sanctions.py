"""Add sanctions tables.

Revision ID: 011_sanctions
Revises: 010_acled
Create Date: 2026-03-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "011_sanctions"
down_revision: Union[str, None] = "010_acled"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pg_trgm extension for fuzzy matching
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # 1. sanctions_entities — cached OpenSanctions data
    op.create_table(
        "sanctions_entities",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("aliases", sa.ARRAY(sa.Text), nullable=True, server_default="{}"),
        sa.Column("datasets", sa.ARRAY(sa.Text), nullable=True, server_default="{}"),
        sa.Column("countries", sa.ARRAY(sa.Text), nullable=True, server_default="{}"),
        sa.Column("properties", sa.JSON, nullable=True, server_default="{}"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # GIN trigram index on name for fast fuzzy matching
    op.create_index(
        "ix_sanctions_entities_name_trgm",
        "sanctions_entities",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )

    # 2. entity_sanctions_matches — links platform entities to sanctions matches
    op.create_table(
        "entity_sanctions_matches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sanctions_entity_id",
            sa.String(255),
            sa.ForeignKey("sanctions_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("matched_on", sa.String(50), nullable=True),  # 'name' or 'alias'
        sa.Column("datasets", sa.ARRAY(sa.Text), nullable=True, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_sanctions_matches_entity",
        "entity_sanctions_matches",
        ["entity_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_sanctions_matches_entity", table_name="entity_sanctions_matches")
    op.drop_table("entity_sanctions_matches")
    op.drop_index("ix_sanctions_entities_name_trgm", table_name="sanctions_entities")
    op.drop_table("sanctions_entities")
