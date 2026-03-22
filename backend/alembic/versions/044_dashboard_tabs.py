"""Dashboard tabs with widget layouts."""
from alembic import op
import sqlalchemy as sa

revision = "044_dashboard_tabs"
down_revision = "043_strike_counts"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "dashboard_tabs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("icon", sa.String(10), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_default", sa.Boolean(), server_default="false"),
        sa.Column("layout", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_dashboard_tab_user_name"),
    )

def downgrade() -> None:
    op.drop_table("dashboard_tabs")
