"""015 - vessel tracks for maritime intelligence"""
revision = "015_vessel_tracks"
down_revision = "014_saved_queries"

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


def upgrade():
    op.create_table(
        "vessel_tracks",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("mmsi", sa.String(20), nullable=False),
        sa.Column("imo", sa.String(20), nullable=True),
        sa.Column("vessel_name", sa.String(200), nullable=True),
        sa.Column("vessel_type", sa.String(50), nullable=True),
        sa.Column("flag", sa.String(10), nullable=True),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lng", sa.Float, nullable=False),
        sa.Column("speed", sa.Float, nullable=True),
        sa.Column("heading", sa.Float, nullable=True),
        sa.Column("course", sa.Float, nullable=True),
        sa.Column("destination", sa.String(200), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_vessel_tracks_mmsi_ts", "vessel_tracks", ["mmsi", "timestamp"])
    op.create_index("ix_vessel_tracks_ts", "vessel_tracks", ["timestamp"])

    # Watchlist for vessels of interest
    op.create_table(
        "vessel_watchlist",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mmsi", sa.String(20), nullable=False),
        sa.Column("vessel_name", sa.String(200), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("alert_on_dark", sa.Boolean, server_default="true"),
        sa.Column("alert_on_sts", sa.Boolean, server_default="true"),
        sa.Column("alert_on_port_call", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_vessel_watchlist_mmsi", "vessel_watchlist", ["mmsi"])

    # Maritime alerts/events
    op.create_table(
        "maritime_events",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("event_type", sa.String(30), nullable=False),  # dark_ship, sts_transfer, port_call, deviation
        sa.Column("mmsi", sa.String(20), nullable=False),
        sa.Column("vessel_name", sa.String(200), nullable=True),
        sa.Column("lat", sa.Float, nullable=True),
        sa.Column("lng", sa.Float, nullable=True),
        sa.Column("details", JSONB, nullable=True),
        sa.Column("severity", sa.String(20), server_default="'routine'"),  # routine, notable, critical
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_maritime_events_type", "maritime_events", ["event_type"])
    op.create_index("ix_maritime_events_mmsi", "maritime_events", ["mmsi"])


def downgrade():
    op.drop_table("maritime_events")
    op.drop_table("vessel_watchlist")
    op.drop_table("vessel_tracks")
