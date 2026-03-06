"""Add external_id column to posts for generic dedup (ACLED, GDELT, etc.).

Revision ID: 010_acled
Revises: 009_media_support
Create Date: 2026-03-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "010_acled"
down_revision: Union[str, None] = "009_media_support"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        ALTER TABLE posts
            ADD COLUMN IF NOT EXISTS external_id VARCHAR(255)
    """))
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_posts_external_id ON posts (external_id)
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_posts_external_id"))
    conn.execute(sa.text("ALTER TABLE posts DROP COLUMN IF EXISTS external_id"))
