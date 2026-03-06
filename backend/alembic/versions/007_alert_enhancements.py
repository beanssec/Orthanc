"""Geo-proximity and silence detection columns for alert_rules.

Revision ID: 007_alert_enhancements
Revises: 006_alert_rules
Create Date: 2026-03-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007_alert_enhancements"
down_revision: Union[str, None] = "006_alert_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Geo-proximity columns
    op.add_column("alert_rules", sa.Column("geo_lat", sa.Float, nullable=True))
    op.add_column("alert_rules", sa.Column("geo_lng", sa.Float, nullable=True))
    op.add_column("alert_rules", sa.Column("geo_radius_km", sa.Float, nullable=True))
    op.add_column("alert_rules", sa.Column("geo_label", sa.String, nullable=True))

    # Silence detection columns
    op.add_column("alert_rules", sa.Column("silence_entity", sa.String, nullable=True))
    op.add_column("alert_rules", sa.Column("silence_source_type", sa.String, nullable=True))
    op.add_column(
        "alert_rules",
        sa.Column("silence_expected_interval_minutes", sa.Integer, nullable=True),
    )
    op.add_column(
        "alert_rules",
        sa.Column("silence_last_seen", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("alert_rules", "silence_last_seen")
    op.drop_column("alert_rules", "silence_expected_interval_minutes")
    op.drop_column("alert_rules", "silence_source_type")
    op.drop_column("alert_rules", "silence_entity")
    op.drop_column("alert_rules", "geo_label")
    op.drop_column("alert_rules", "geo_radius_km")
    op.drop_column("alert_rules", "geo_lng")
    op.drop_column("alert_rules", "geo_lat")
