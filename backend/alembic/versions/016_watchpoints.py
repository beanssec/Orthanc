"""016 - satellite watchpoints for change detection"""
revision = "016_watchpoints"
down_revision = "015_vessel_tracks"

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


def upgrade():
    op.create_table(
        "sat_watchpoints",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lng", sa.Float, nullable=False),
        sa.Column("radius_km", sa.Float, server_default="10.0"),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("enabled", sa.Boolean, server_default="true"),
        sa.Column("last_checked", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_image_date", sa.String(20), nullable=True),
        sa.Column("change_threshold", sa.Float, server_default="0.05"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "sat_snapshots",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "watchpoint_id",
            UUID(),
            sa.ForeignKey("sat_watchpoints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("image_date", sa.String(20), nullable=False),
        sa.Column("product_id", sa.String(100), nullable=True),
        sa.Column("cloud_cover", sa.Float, nullable=True),
        sa.Column("thumbnail_path", sa.String(500), nullable=True),
        sa.Column("pixel_hash", sa.String(64), nullable=True),
        sa.Column("change_score", sa.Float, nullable=True),
        sa.Column("change_detected", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_sat_snapshots_watchpoint", "sat_snapshots", ["watchpoint_id"])
    op.create_index("ix_sat_snapshots_date", "sat_snapshots", ["image_date"])


def downgrade():
    op.drop_table("sat_snapshots")
    op.drop_table("sat_watchpoints")
