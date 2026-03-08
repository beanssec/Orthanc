"""018 - LLM usage tracking"""

revision = "018_llm_usage"
down_revision = "017_narratives"

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


def upgrade():
    op.create_table(
        "llm_usage",
        sa.Column(
            "id",
            UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "user_id",
            UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("task", sa.String(100), nullable=False),
        sa.Column("tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("cost_usd", sa.Float, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
    )

    op.create_index("idx_llm_usage_timestamp", "llm_usage", ["timestamp"])
    op.create_index("idx_llm_usage_task", "llm_usage", ["task"])


def downgrade():
    op.drop_index("idx_llm_usage_task", table_name="llm_usage")
    op.drop_index("idx_llm_usage_timestamp", table_name="llm_usage")
    op.drop_table("llm_usage")
