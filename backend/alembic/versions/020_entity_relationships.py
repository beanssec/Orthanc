"""Entity co-occurrence relationship table.

Revision ID: 020_entity_relationships
Revises: 019_frontline_snapshots
Create Date: 2026-03-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "020_entity_relationships"
down_revision = "019_frontline_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE entity_relationships (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_a_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            entity_b_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            weight INTEGER NOT NULL DEFAULT 1,
            first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
            sample_post_ids JSONB DEFAULT '[]',
            UNIQUE(entity_a_id, entity_b_id)
        )
    """)
    op.execute("CREATE INDEX idx_entity_rel_a ON entity_relationships(entity_a_id)")
    op.execute("CREATE INDEX idx_entity_rel_b ON entity_relationships(entity_b_id)")
    op.execute("CREATE INDEX idx_entity_rel_weight ON entity_relationships(weight DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_entity_rel_weight")
    op.execute("DROP INDEX IF EXISTS idx_entity_rel_b")
    op.execute("DROP INDEX IF EXISTS idx_entity_rel_a")
    op.execute("DROP TABLE IF EXISTS entity_relationships")
