"""Financial intelligence tables: holdings, quotes, entity_ticker_map, signals

Revision ID: 004
Revises: 003
Create Date: 2026-03-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Default entity → ticker mappings to seed
DEFAULT_ENTITY_TICKER_MAP = [
    # Geopolitical → Commodities
    ("Iran", "GPE", "CL=F", "COMMODITY", "geopolitical", 0.9),
    ("Strait of Hormuz", "LOC", "CL=F", "COMMODITY", "geopolitical", 0.95),
    ("Saudi Arabia", "GPE", "CL=F", "COMMODITY", "geopolitical", 0.85),
    ("OPEC", "ORG", "CL=F", "COMMODITY", "geopolitical", 0.9),
    ("Russia", "GPE", "NG=F", "COMMODITY", "geopolitical", 0.8),
    ("Ukraine", "GPE", "ZW=F", "COMMODITY", "geopolitical", 0.75),
    # Geopolitical → Defense
    ("Iran", "GPE", "LMT", "NYSE", "geopolitical", 0.7),
    ("Iran", "GPE", "RTX", "NYSE", "geopolitical", 0.7),
    ("Iran", "GPE", "NOC", "NYSE", "geopolitical", 0.7),
    # Geopolitical → Sectors
    ("China", "GPE", "FXI", "NYSE", "geopolitical", 0.6),
    ("Taiwan", "GPE", "TSM", "NYSE", "geopolitical", 0.7),
    ("TSMC", "ORG", "TSM", "NYSE", "direct", 0.95),
    # ASX relevant
    ("Australia", "GPE", "^AXJO", "INDEX", "geopolitical", 0.5),
    ("China", "GPE", "BHP", "ASX", "geopolitical", 0.7),
    ("iron ore", "COMMODITY", "BHP", "ASX", "sector", 0.9),
    ("lithium", "COMMODITY", "PLS", "ASX", "sector", 0.9),
    ("gold", "COMMODITY", "NCM", "ASX", "sector", 0.9),
]


def upgrade() -> None:
    # Portfolio holdings
    op.create_table(
        "holdings",
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
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("exchange", sa.String(), nullable=True, server_default="NYSE"),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_cost", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True, server_default="USD"),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_holdings_user", "holdings", ["user_id"])
    op.create_unique_constraint(
        "uq_holdings_user_ticker_exchange",
        "holdings",
        ["user_id", "ticker", "exchange"],
    )

    # Cached market quotes
    op.create_table(
        "quotes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("exchange", sa.String(), nullable=True, server_default="NYSE"),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("change_pct", sa.Float(), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("market_cap", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True, server_default="USD"),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_quotes_ticker", "quotes", ["ticker", "exchange"])
    op.create_index(
        "ix_quotes_fetched",
        "quotes",
        ["fetched_at"],
        postgresql_ops={"fetched_at": "DESC"},
    )

    # Entity-to-ticker mappings
    op.create_table(
        "entity_ticker_map",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("entity_name", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=True),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("exchange", sa.String(), nullable=True, server_default="NYSE"),
        sa.Column("relationship", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True, server_default="0.7"),
    )
    op.create_index("ix_entity_ticker_entity", "entity_ticker_map", ["entity_name"])

    # Financial signals / opportunities
    op.create_table(
        "signals",
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
        sa.Column("signal_type", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=True, server_default="medium"),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("affected_tickers", sa.Text(), nullable=True),  # JSON array
        sa.Column("trigger_entities", sa.Text(), nullable=True),  # JSON array
        sa.Column("trigger_post_count", sa.Integer(), nullable=True),
        sa.Column("portfolio_impact", sa.String(), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_signals_user", "signals", ["user_id"])
    op.create_index(
        "ix_signals_generated",
        "signals",
        ["generated_at"],
        postgresql_ops={"generated_at": "DESC"},
    )

    # Seed default entity-ticker mappings
    entity_ticker_table = sa.table(
        "entity_ticker_map",
        sa.column("entity_name", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("ticker", sa.String),
        sa.column("exchange", sa.String),
        sa.column("relationship", sa.String),
        sa.column("confidence", sa.Float),
    )
    op.bulk_insert(
        entity_ticker_table,
        [
            {
                "entity_name": row[0],
                "entity_type": row[1],
                "ticker": row[2],
                "exchange": row[3],
                "relationship": row[4],
                "confidence": row[5],
            }
            for row in DEFAULT_ENTITY_TICKER_MAP
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_signals_generated", table_name="signals")
    op.drop_index("ix_signals_user", table_name="signals")
    op.drop_table("signals")

    op.drop_index("ix_entity_ticker_entity", table_name="entity_ticker_map")
    op.drop_table("entity_ticker_map")

    op.drop_index("ix_quotes_fetched", table_name="quotes")
    op.drop_index("ix_quotes_ticker", table_name="quotes")
    op.drop_table("quotes")

    op.drop_constraint("uq_holdings_user_ticker_exchange", "holdings", type_="unique")
    op.drop_index("ix_holdings_user", table_name="holdings")
    op.drop_table("holdings")
