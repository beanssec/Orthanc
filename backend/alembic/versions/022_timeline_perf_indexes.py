"""Add indexes for timeline query performance.

Revision ID: 022_timeline_perf_indexes
Revises: 021_entity_relationship_metadata
Create Date: 2026-03-12
"""

from alembic import op

revision = "022_timeline_perf_indexes"
down_revision = "021_entity_relationship_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_entity_mentions_entity_post ON entity_mentions(entity_id, post_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_posts_timestamp_desc ON posts(timestamp DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_events_post_id ON events(post_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_events_post_id")
    op.execute("DROP INDEX IF EXISTS ix_posts_timestamp_desc")
    op.execute("DROP INDEX IF EXISTS ix_entity_mentions_entity_post")
