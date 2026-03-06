"""Media support: download images/videos, EXIF, authenticity scoring.

Revision ID: 009_media_support
Revises: 008_entity_relationships
Create Date: 2026-03-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "009_media_support"
down_revision: Union[str, None] = "008_entity_relationships"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── posts: media columns ──────────────────────────────────────────────────
    conn.execute(sa.text("""
        ALTER TABLE posts
            ADD COLUMN IF NOT EXISTS media_type VARCHAR,
            ADD COLUMN IF NOT EXISTS media_path VARCHAR,
            ADD COLUMN IF NOT EXISTS media_size_bytes BIGINT,
            ADD COLUMN IF NOT EXISTS media_mime VARCHAR,
            ADD COLUMN IF NOT EXISTS media_thumbnail_path VARCHAR,
            ADD COLUMN IF NOT EXISTS media_metadata JSONB,
            ADD COLUMN IF NOT EXISTS authenticity_score FLOAT,
            ADD COLUMN IF NOT EXISTS authenticity_analysis TEXT,
            ADD COLUMN IF NOT EXISTS authenticity_checked_at TIMESTAMPTZ
    """))

    # ── sources: media download settings ─────────────────────────────────────
    conn.execute(sa.text("""
        ALTER TABLE sources
            ADD COLUMN IF NOT EXISTS download_images BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS download_videos BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS max_image_size_mb FLOAT DEFAULT 10,
            ADD COLUMN IF NOT EXISTS max_video_size_mb FLOAT DEFAULT 100
    """))


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("""
        ALTER TABLE posts
            DROP COLUMN IF EXISTS media_type,
            DROP COLUMN IF EXISTS media_path,
            DROP COLUMN IF EXISTS media_size_bytes,
            DROP COLUMN IF EXISTS media_mime,
            DROP COLUMN IF EXISTS media_thumbnail_path,
            DROP COLUMN IF EXISTS media_metadata,
            DROP COLUMN IF EXISTS authenticity_score,
            DROP COLUMN IF EXISTS authenticity_analysis,
            DROP COLUMN IF EXISTS authenticity_checked_at
    """))

    conn.execute(sa.text("""
        ALTER TABLE sources
            DROP COLUMN IF EXISTS download_images,
            DROP COLUMN IF EXISTS download_videos,
            DROP COLUMN IF EXISTS max_image_size_mb,
            DROP COLUMN IF EXISTS max_video_size_mb
    """))
