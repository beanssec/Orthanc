"""Daily strike count tracking."""
from alembic import op
import sqlalchemy as sa

revision = "043_strike_counts"
down_revision = "042_post_translation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strike_counts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("actor", sa.String(50), nullable=False),  # 'us', 'israel', 'iran', 'hezbollah'
        sa.Column("strike_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sortie_count", sa.Integer(), nullable=True),
        sa.Column("target_count", sa.Integer(), nullable=True),
        sa.Column("source_post_ids", sa.ARRAY(sa.UUID()), nullable=True),
        sa.Column("extraction_method", sa.String(20), nullable=True),  # 'llm' or 'keyword'
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", "actor", name="uq_strike_date_actor"),
    )


def downgrade() -> None:
    op.drop_table("strike_counts")
