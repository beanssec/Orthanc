"""scheduled_briefs — Sprint 31 Checkpoint 1: Scheduled brief core

Adds two tables:
  * scheduled_briefs  — durable per-user schedule configs (model, timing, filters)
  * scheduled_brief_runs — run-history records per schedule execution

Revision ID: 031_scheduled_briefs
Revises: 030_api_keys
Create Date: 2026-03-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, UUID

# revision identifiers
revision = "031_scheduled_briefs"
down_revision = "030_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── scheduled_briefs ─────────────────────────────────────────────────────
    op.create_table(
        "scheduled_briefs",
        sa.Column(
            "id",
            UUID(),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("user_id", UUID(), nullable=False),

        # Identity
        sa.Column("name", sa.String(255), nullable=False, server_default="Daily Brief"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),

        # Timing — hour-of-day (simple) or cron expression (future)
        sa.Column("schedule_hour_utc", sa.Integer(), nullable=True, server_default="8"),
        sa.Column("cron_expr", sa.String(100), nullable=True),

        # Content config
        sa.Column("model_id", sa.String(128), nullable=False, server_default="grok-3-mini"),
        sa.Column("time_window_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("topic_filter", sa.Text(), nullable=True),
        sa.Column(
            "source_filters",
            ARRAY(sa.String()),
            nullable=True,
        ),

        # Delivery placeholder
        sa.Column(
            "delivery_method",
            sa.String(64),
            nullable=False,
            server_default="internal",
        ),

        # Execution state
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),

        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),

        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scheduled_briefs_user_id", "scheduled_briefs", ["user_id"])
    op.create_index(
        "ix_scheduled_briefs_enabled",
        "scheduled_briefs",
        ["enabled"],
        postgresql_where=sa.text("enabled = true"),
    )

    # ── scheduled_brief_runs ─────────────────────────────────────────────────
    op.create_table(
        "scheduled_brief_runs",
        sa.Column(
            "id",
            UUID(),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("schedule_id", UUID(), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("brief_id", UUID(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),

        sa.ForeignKeyConstraint(
            ["schedule_id"], ["scheduled_briefs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["brief_id"], ["briefs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scheduled_brief_runs_schedule_id",
        "scheduled_brief_runs",
        ["schedule_id"],
    )
    op.create_index(
        "ix_scheduled_brief_runs_user_id",
        "scheduled_brief_runs",
        ["user_id"],
    )
    op.create_index(
        "ix_scheduled_brief_runs_started_at",
        "scheduled_brief_runs",
        ["started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_scheduled_brief_runs_started_at", table_name="scheduled_brief_runs")
    op.drop_index("ix_scheduled_brief_runs_user_id", table_name="scheduled_brief_runs")
    op.drop_index("ix_scheduled_brief_runs_schedule_id", table_name="scheduled_brief_runs")
    op.drop_table("scheduled_brief_runs")

    op.drop_index("ix_scheduled_briefs_enabled", table_name="scheduled_briefs")
    op.drop_index("ix_scheduled_briefs_user_id", table_name="scheduled_briefs")
    op.drop_table("scheduled_briefs")
