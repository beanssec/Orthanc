"""Entity relationships, entity properties, and collaboration features.

Revision ID: 008_entity_relationships
Revises: 007_alert_enhancements
Create Date: 2026-03-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "008_entity_relationships"
down_revision: Union[str, None] = "007_alert_enhancements"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── entity_relationships ─────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS entity_relationships (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            source_entity_id UUID REFERENCES entities(id) ON DELETE CASCADE NOT NULL,
            target_entity_id UUID REFERENCES entities(id) ON DELETE CASCADE NOT NULL,
            relationship_type VARCHAR NOT NULL,
            confidence FLOAT DEFAULT 0.5,
            evidence_post_ids UUID[],
            created_by UUID REFERENCES users(id),
            notes TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE(source_entity_id, target_entity_id, relationship_type)
        )
    """))
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_entity_rel_source ON entity_relationships(source_entity_id)
    """))
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_entity_rel_target ON entity_relationships(target_entity_id)
    """))

    # ── entity_properties ────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS entity_properties (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            entity_id UUID REFERENCES entities(id) ON DELETE CASCADE NOT NULL,
            key VARCHAR NOT NULL,
            value TEXT NOT NULL,
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE(entity_id, key)
        )
    """))
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_entity_props ON entity_properties(entity_id)
    """))

    # ── user_notes ───────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS user_notes (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
            target_type VARCHAR NOT NULL,
            target_id UUID NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """))
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_user_notes_target ON user_notes(target_type, target_id)
    """))
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_user_notes_user ON user_notes(user_id)
    """))

    # ── user_bookmarks ───────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS user_bookmarks (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
            target_type VARCHAR NOT NULL,
            target_id UUID NOT NULL,
            label VARCHAR,
            created_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE(user_id, target_type, target_id)
        )
    """))
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_user_bookmarks_user ON user_bookmarks(user_id)
    """))

    # ── user_tags ────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS user_tags (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
            target_type VARCHAR NOT NULL,
            target_id UUID NOT NULL,
            tag VARCHAR NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE(user_id, target_type, target_id, tag)
        )
    """))
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_user_tags_user ON user_tags(user_id)
    """))
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_user_tags_tag ON user_tags(tag)
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS user_tags"))
    conn.execute(sa.text("DROP TABLE IF EXISTS user_bookmarks"))
    conn.execute(sa.text("DROP TABLE IF EXISTS user_notes"))
    conn.execute(sa.text("DROP TABLE IF EXISTS entity_properties"))
    conn.execute(sa.text("DROP TABLE IF EXISTS entity_relationships"))
