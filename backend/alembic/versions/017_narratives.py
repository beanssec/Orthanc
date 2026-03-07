"""017 - narrative intelligence engine"""

revision = "017_narratives"
down_revision = "016_watchpoints"

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY


def upgrade():
    # Narrative clusters
    op.create_table(
        "narratives",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), server_default="'active'"),  # active, resolved, stale
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("post_count", sa.Integer, server_default="0"),
        sa.Column("source_count", sa.Integer, server_default="0"),
        sa.Column("divergence_score", sa.Float, server_default="0"),
        sa.Column("evidence_score", sa.Float, server_default="0"),
        sa.Column("consensus", sa.String(50), nullable=True),  # confirmed, disputed, denied, unverified
        sa.Column("topic_keywords", ARRAY(sa.Text), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # Posts <-> narratives (M:N)
    op.create_table(
        "narrative_posts",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("narrative_id", UUID(), sa.ForeignKey("narratives.id", ondelete="CASCADE"), nullable=False),
        sa.Column("post_id", UUID(), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stance", sa.String(30), nullable=True),
        sa.Column("stance_confidence", sa.Float, nullable=True),
        sa.Column("stance_summary", sa.Text, nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("narrative_id", "post_id", name="uq_narrative_post"),
    )

    # Claims extracted from narratives
    op.create_table(
        "claims",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("narrative_id", UUID(), sa.ForeignKey("narratives.id", ondelete="CASCADE"), nullable=False),
        sa.Column("claim_text", sa.Text, nullable=False),
        sa.Column("claim_type", sa.String(30), nullable=True),  # factual, attribution, prediction, opinion
        sa.Column("location_lat", sa.Float, nullable=True),
        sa.Column("location_lng", sa.Float, nullable=True),
        sa.Column("entity_names", ARRAY(sa.Text), nullable=True),
        sa.Column("status", sa.String(20), server_default="'unverified'"),
        sa.Column("evidence_count", sa.Integer, server_default="0"),
        sa.Column("first_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_claimed_by", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # Evidence for claims
    op.create_table(
        "claim_evidence",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("claim_id", UUID(), sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_type", sa.String(30), nullable=True),
        sa.Column("evidence_source", sa.Text, nullable=True),
        sa.Column("evidence_data", JSONB, nullable=True),
        sa.Column("supports", sa.Boolean, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # Source groups (western, russian, osint, etc.)
    op.create_table(
        "source_groups",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("color", sa.String(7), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # Source <-> group membership
    op.create_table(
        "source_group_members",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("source_group_id", UUID(), sa.ForeignKey("source_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", UUID(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("source_group_id", "source_id", name="uq_group_source"),
    )

    # Source bias profiles (computed periodically)
    op.create_table(
        "source_bias_profiles",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("source_id", UUID(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("alignment_score", sa.Float, nullable=True),
        sa.Column("reliability_score", sa.Float, nullable=True),
        sa.Column("coverage_bias", JSONB, nullable=True),
        sa.Column("speed_rank", sa.Float, nullable=True),
        sa.Column("stance_distribution", JSONB, nullable=True),
        sa.Column("total_narratives", sa.Integer, server_default="0"),
        sa.Column("total_claims", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # Post embeddings for semantic clustering
    op.create_table(
        "post_embeddings",
        sa.Column("post_id", UUID(), sa.ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("embedding", JSONB, nullable=False),  # list of floats — JSON since pgvector not guaranteed
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # Indexes
    op.create_index("ix_narratives_status", "narratives", ["status"])
    op.create_index("ix_narratives_last_updated", "narratives", ["last_updated"])
    op.create_index("ix_narrative_posts_narrative", "narrative_posts", ["narrative_id"])
    op.create_index("ix_narrative_posts_post", "narrative_posts", ["post_id"])
    op.create_index("ix_claims_narrative", "claims", ["narrative_id"])
    op.create_index("ix_claim_evidence_claim", "claim_evidence", ["claim_id"])
    op.create_index("ix_source_bias_source", "source_bias_profiles", ["source_id"])


def downgrade():
    op.drop_table("post_embeddings")
    op.drop_table("source_bias_profiles")
    op.drop_table("source_group_members")
    op.drop_table("source_groups")
    op.drop_table("claim_evidence")
    op.drop_table("claims")
    op.drop_table("narrative_posts")
    op.drop_table("narratives")
