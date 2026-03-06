"""Alert rules and correlation engine tables.

Revision ID: 006_alert_rules
Revises: 005
Create Date: 2026-03-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "006_alert_rules"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New alert_rules table
    op.create_table(
        "alert_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("enabled", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column("rule_type", sa.String, nullable=False),  # 'keyword', 'velocity', 'correlation'
        sa.Column(
            "severity",
            sa.String,
            server_default=sa.text("'routine'"),
            nullable=False,
        ),  # 'flash', 'urgent', 'routine'
        # Level 1: keyword config
        sa.Column("keywords", postgresql.ARRAY(sa.String), nullable=True),
        sa.Column("keyword_mode", sa.String, nullable=True),  # 'any', 'all', 'regex'
        sa.Column("source_types", postgresql.ARRAY(sa.String), nullable=True),
        # Level 2: velocity config
        sa.Column("entity_name", sa.String, nullable=True),
        sa.Column("velocity_threshold", sa.Float, nullable=True),
        sa.Column("velocity_window_minutes", sa.Integer, nullable=True),
        # Level 3: correlation directives
        sa.Column("directives", postgresql.JSONB, nullable=True),
        sa.Column("cooldown_minutes", sa.Integer, server_default=sa.text("60"), nullable=False),
        sa.Column(
            "delivery_channels",
            postgresql.ARRAY(sa.String),
            server_default=sa.text("'{in_app}'"),
            nullable=True,
        ),
        sa.Column("telegram_chat_id", sa.String, nullable=True),
        sa.Column("webhook_url", sa.String, nullable=True),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index("ix_alert_rules_user_id", "alert_rules", ["user_id"])
    op.create_index("ix_alert_rules_enabled", "alert_rules", ["enabled"])

    # Alert events (firing history)
    op.create_table(
        "alert_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("alert_rules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("severity", sa.String, nullable=False),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column(
            "matched_post_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=True,
        ),
        sa.Column("matched_entities", postgresql.ARRAY(sa.String), nullable=True),
        sa.Column("context", postgresql.JSONB, nullable=True),
        sa.Column(
            "acknowledged",
            sa.Boolean,
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fired_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_alert_events_rule_id", "alert_events", ["rule_id"])
    op.create_index("ix_alert_events_user_id", "alert_events", ["user_id"])
    op.create_index("ix_alert_events_fired_at", "alert_events", ["fired_at"])


def downgrade() -> None:
    op.drop_index("ix_alert_events_fired_at", table_name="alert_events")
    op.drop_index("ix_alert_events_user_id", table_name="alert_events")
    op.drop_index("ix_alert_events_rule_id", table_name="alert_events")
    op.drop_table("alert_events")
    op.drop_index("ix_alert_rules_enabled", table_name="alert_rules")
    op.drop_index("ix_alert_rules_user_id", table_name="alert_rules")
    op.drop_table("alert_rules")
