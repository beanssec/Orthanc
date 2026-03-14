"""task_model_overrides — persist user task→model selections

Adds a table to durably store per-user task→model overrides so selections
survive restarts/logouts.  Backward-safe: existing rows are unaffected and
the application falls back to DEFAULT_TASK_MODELS when no row exists.

Revision ID: 029_task_model_overrides
Revises: 028_brief_confidence
Create Date: 2026-03-14
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "029_task_model_overrides"
down_revision = "028_brief_confidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_model_overrides",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("task", sa.String(128), nullable=False),
        sa.Column("model_id", sa.String(256), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "task", name="uq_task_model_override_user_task"),
    )
    op.create_index(
        "ix_task_model_overrides_user_id",
        "task_model_overrides",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_task_model_overrides_user_id", table_name="task_model_overrides")
    op.drop_table("task_model_overrides")
