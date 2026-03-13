"""Add analyst metadata columns to entity_relationships.

Revision ID: 021_entity_relationship_metadata
Revises: 020_entity_relationships
Create Date: 2026-03-12
"""

from alembic import op

revision = "021_entity_relationship_metadata"
down_revision = "020_entity_relationships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE entity_relationships
        ADD COLUMN IF NOT EXISTS relationship_type VARCHAR NOT NULL DEFAULT 'associated'
    """)
    op.execute("""
        ALTER TABLE entity_relationships
        ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5
    """)
    op.execute("""
        ALTER TABLE entity_relationships
        ADD COLUMN IF NOT EXISTS notes TEXT
    """)
    op.execute("""
        ALTER TABLE entity_relationships
        ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id) ON DELETE SET NULL
    """)
    op.execute("""
        ALTER TABLE entity_relationships
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_entity_rel_type
        ON entity_relationships(relationship_type)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_entity_rel_type")
    op.execute("ALTER TABLE entity_relationships DROP COLUMN IF EXISTS created_at")
    op.execute("ALTER TABLE entity_relationships DROP COLUMN IF EXISTS created_by")
    op.execute("ALTER TABLE entity_relationships DROP COLUMN IF EXISTS notes")
    op.execute("ALTER TABLE entity_relationships DROP COLUMN IF EXISTS confidence")
    op.execute("ALTER TABLE entity_relationships DROP COLUMN IF EXISTS relationship_type")
