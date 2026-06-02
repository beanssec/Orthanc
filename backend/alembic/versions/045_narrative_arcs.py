"""Narrative arcs — persistent evolving storylines grouping related narratives."""
from alembic import op
import sqlalchemy as sa

revision = "045_narrative_arcs"
down_revision = "044_dashboard_tabs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create narrative_arcs table
    op.create_table(
        "narrative_arcs",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("arc_type", sa.String(50), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_updated", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("narrative_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_post_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_narrative_arcs_status", "narrative_arcs", ["status"])

    # Create narrative_arc_summaries table
    op.create_table(
        "narrative_arc_summaries",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("arc_id", sa.UUID(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("post_count", sa.Integer(), nullable=True),
        sa.Column("narrative_count", sa.Integer(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("model", sa.String(256), nullable=True),
        sa.ForeignKeyConstraint(["arc_id"], ["narrative_arcs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_narrative_arc_summaries_arc_id", "narrative_arc_summaries", ["arc_id"])

    # Add arc_id column to narratives
    op.add_column("narratives", sa.Column("arc_id", sa.UUID(), nullable=True))
    op.create_index("ix_narratives_arc_id", "narratives", ["arc_id"])
    op.create_foreign_key(
        "fk_narratives_arc_id",
        "narratives",
        "narrative_arcs",
        ["arc_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_narratives_arc_id", "narratives", type_="foreignkey")
    op.drop_index("ix_narratives_arc_id", table_name="narratives")
    op.drop_column("narratives", "arc_id")

    op.drop_index("ix_narrative_arc_summaries_arc_id", table_name="narrative_arc_summaries")
    op.drop_table("narrative_arc_summaries")

    op.drop_index("ix_narrative_arcs_status", table_name="narrative_arcs")
    op.drop_table("narrative_arcs")
