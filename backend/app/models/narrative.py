import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Narrative(Base):
    __tablename__ = "narratives"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'active'"))

    # Canonical narrative intelligence fields (Sprint 25)
    raw_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    canonical_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    canonical_claim: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    narrative_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    label_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confirmation_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    post_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    divergence_score: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    evidence_score: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    consensus: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    topic_keywords: Mapped[Optional[list]] = mapped_column(ARRAY(Text), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    # Relationships
    narrative_posts: Mapped[list["NarrativePost"]] = relationship(
        back_populates="narrative", cascade="all, delete-orphan"
    )
    claims: Mapped[list["Claim"]] = relationship(
        back_populates="narrative", cascade="all, delete-orphan"
    )


class NarrativePost(Base):
    __tablename__ = "narrative_posts"
    __table_args__ = (
        UniqueConstraint("narrative_id", "post_id", name="uq_narrative_post"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    narrative_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("narratives.id", ondelete="CASCADE"), nullable=False
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), nullable=False
    )
    stance: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    stance_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stance_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    # Relationships
    narrative: Mapped["Narrative"] = relationship(back_populates="narrative_posts")
    post: Mapped["Post"] = relationship()  # noqa: F821


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    narrative_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("narratives.id", ondelete="CASCADE"), nullable=False
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    location_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    location_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entity_names: Mapped[Optional[list]] = mapped_column(ARRAY(Text), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'unverified'"))
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    first_claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    first_claimed_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    # Relationships
    narrative: Mapped["Narrative"] = relationship(back_populates="claims")
    evidence: Mapped[list["ClaimEvidence"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    evidence_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    evidence_source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    supports: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    detected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    # Relationships
    claim: Mapped["Claim"] = relationship(back_populates="evidence")


class SourceGroup(Base):
    __tablename__ = "source_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    # Relationships
    members: Mapped[list["SourceGroupMember"]] = relationship(
        back_populates="source_group", cascade="all, delete-orphan"
    )


class SourceGroupMember(Base):
    __tablename__ = "source_group_members"
    __table_args__ = (
        UniqueConstraint("source_group_id", "source_id", name="uq_group_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    source_group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_groups.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    source_group: Mapped["SourceGroup"] = relationship(back_populates="members")
    source: Mapped["Source"] = relationship()  # noqa: F821


class SourceBiasProfile(Base):
    __tablename__ = "source_bias_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    alignment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reliability_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    coverage_bias: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    speed_rank: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stance_distribution: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    total_narratives: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total_claims: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    # Relationships
    source: Mapped["Source"] = relationship(back_populates="bias_profiles")  # noqa: F821


class PostEmbedding(Base):
    __tablename__ = "post_embeddings"

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list] = mapped_column(JSONB, nullable=False)  # list of floats
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    # Relationships
    post: Mapped["Post"] = relationship()  # noqa: F821


class NarrativeTracker(Base):
    __tablename__ = "narrative_trackers"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    # Sprint 26 CP1: richer analyst-defined hypothesis fields
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hypothesis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    entity_ids: Mapped[Optional[list]] = mapped_column(ARRAY(Text), nullable=True)
    claim_patterns: Mapped[Optional[list]] = mapped_column(ARRAY(Text), nullable=True)
    model_policy: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    versions: Mapped[list["NarrativeTrackerVersion"]] = relationship(
        back_populates="tracker", cascade="all, delete-orphan"
    )


class NarrativeTrackerVersion(Base):
    __tablename__ = "narrative_tracker_versions"
    __table_args__ = (
        UniqueConstraint("tracker_id", "version", name="uq_tracker_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    tracker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("narrative_trackers.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    criteria: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    tracker: Mapped["NarrativeTracker"] = relationship(back_populates="versions")


class NarrativeTrackerMatch(Base):
    __tablename__ = "narrative_tracker_matches"
    __table_args__ = (
        UniqueConstraint("tracker_id", "tracker_version_id", "narrative_id", name="uq_tracker_version_narrative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    tracker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("narrative_trackers.id", ondelete="CASCADE"), nullable=False
    )
    tracker_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("narrative_tracker_versions.id", ondelete="CASCADE"), nullable=False
    )
    narrative_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("narratives.id", ondelete="CASCADE"), nullable=False)
    match_score: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    # Sprint 26 CP1: groundwork for evidence classification (CP2 will populate these)
    # Values: supports | contradicts | contextual | unclear | NULL (unclassified)
    evidence_relation: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)


class NarrativeTrackerMonthlySnapshot(Base):
    __tablename__ = "narrative_tracker_monthly_snapshots"
    __table_args__ = (
        UniqueConstraint("tracker_id", "tracker_version_id", "month_bucket", name="uq_tracker_monthly_snapshot"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    tracker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("narrative_trackers.id", ondelete="CASCADE"), nullable=False
    )
    tracker_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("narrative_tracker_versions.id", ondelete="CASCADE"), nullable=False
    )
    month_bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    matched_narratives: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total_posts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    avg_divergence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_evidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
