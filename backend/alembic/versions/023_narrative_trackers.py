"""Add narrative tracker tables for operator-defined longitudinal tracking.

Revision ID: 023_narrative_trackers
Revises: 022_timeline_perf_indexes
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "023_narrative_trackers"
down_revision = "022_timeline_perf_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrative_trackers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_narrative_trackers_owner_status", "narrative_trackers", ["owner_user_id", "status"])
    op.create_index("ix_narrative_trackers_owner_name", "narrative_trackers", ["owner_user_id", "name"], unique=True)

    op.create_table(
        "narrative_tracker_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tracker_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("narrative_trackers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tracker_id", "version", name="uq_tracker_version"),
    )
    op.create_index("ix_tracker_versions_tracker", "narrative_tracker_versions", ["tracker_id"])

    op.create_table(
        "narrative_tracker_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tracker_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("narrative_trackers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tracker_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("narrative_tracker_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("narrative_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("narratives.id", ondelete="CASCADE"), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tracker_id", "tracker_version_id", "narrative_id", name="uq_tracker_version_narrative"),
    )
    op.create_index("ix_tracker_matches_tracker", "narrative_tracker_matches", ["tracker_id"])
    op.create_index("ix_tracker_matches_narrative", "narrative_tracker_matches", ["narrative_id"])

    op.create_table(
        "narrative_tracker_monthly_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tracker_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("narrative_trackers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tracker_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("narrative_tracker_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("month_bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("matched_narratives", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_posts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("avg_divergence_score", sa.Float(), nullable=True),
        sa.Column("avg_evidence_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tracker_id", "tracker_version_id", "month_bucket", name="uq_tracker_monthly_snapshot"),
    )
    op.create_index("ix_tracker_monthly_tracker", "narrative_tracker_monthly_snapshots", ["tracker_id", "month_bucket"])


def downgrade() -> None:
    op.drop_index("ix_tracker_monthly_tracker", table_name="narrative_tracker_monthly_snapshots")
    op.drop_table("narrative_tracker_monthly_snapshots")

    op.drop_index("ix_tracker_matches_narrative", table_name="narrative_tracker_matches")
    op.drop_index("ix_tracker_matches_tracker", table_name="narrative_tracker_matches")
    op.drop_table("narrative_tracker_matches")

    op.drop_index("ix_tracker_versions_tracker", table_name="narrative_tracker_versions")
    op.drop_table("narrative_tracker_versions")

    op.drop_index("ix_narrative_trackers_owner_name", table_name="narrative_trackers")
    op.drop_index("ix_narrative_trackers_owner_status", table_name="narrative_trackers")
    op.drop_table("narrative_trackers")
