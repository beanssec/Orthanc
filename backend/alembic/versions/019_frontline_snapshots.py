"""019 - Frontline snapshots"""

revision = "019_frontline_snapshots"
down_revision = "018_llm_usage"

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


def upgrade():
    op.create_table(
        "frontline_snapshots",
        sa.Column(
            "id",
            UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "source",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'deepstate'"),
        ),
        sa.Column("geojson", JSONB(), nullable=False),
        sa.Column("geometry_hash", sa.String(64), nullable=False),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_frontline_date_source",
        "frontline_snapshots",
        ["date", "source"],
    )
    op.create_index("idx_frontline_date", "frontline_snapshots", ["date"])


def downgrade():
    op.drop_index("idx_frontline_date", table_name="frontline_snapshots")
    op.drop_constraint(
        "uq_frontline_date_source", "frontline_snapshots", type_="unique"
    )
    op.drop_table("frontline_snapshots")
