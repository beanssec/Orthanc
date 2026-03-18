"""entity_merge_and_source_health_tracking

Adds:
  * entities.merged_into  — UUID FK to entities.id (nullable)
  * entities.merged_at    — timestamp (nullable)
  * sources.error_count   — integer default 0
  * sources.last_error    — text (nullable)
  * sources.last_success  — timestamp (nullable)

Revision ID: 033_entity_merge
Revises: 032_source_metadata_fields
Create Date: 2026-03-16
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "033_entity_merge"
down_revision = "032_source_metadata_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Entity merge tracking ──────────────────────────────────────────────
    op.add_column(
        "entities",
        sa.Column("merged_into", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_entities_merged_into",
        "entities",
        "entities",
        ["merged_into"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "entities",
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── Source error health tracking ───────────────────────────────────────
    op.add_column(
        "sources",
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sources",
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column("last_success", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sources", "last_success")
    op.drop_column("sources", "last_error")
    op.drop_column("sources", "error_count")
    op.drop_constraint("fk_entities_merged_into", "entities", type_="foreignkey")
    op.drop_column("entities", "merged_at")
    op.drop_column("entities", "merged_into")
