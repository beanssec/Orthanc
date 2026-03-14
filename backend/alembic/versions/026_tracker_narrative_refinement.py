"""Refine narrative trackers toward analyst-defined standing hypotheses.

Adds richer metadata fields to narrative_trackers (hypothesis, description,
entity_ids, claim_patterns, model_policy) and groundwork columns on
narrative_tracker_matches for future evidence classification
(evidence_relation).  All changes are additive — existing rows / code remain
fully backward-compatible.

Revision ID: 026_tracker_narrative_refinement
Revises: 025_narrative_canonical_fields
Create Date: 2026-03-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "026_tracker_narrative_refinement"
down_revision = "025_narrative_canonical_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── narrative_trackers: richer hypothesis / metadata fields ──────────────
    op.add_column(
        "narrative_trackers",
        sa.Column("description", sa.Text(), nullable=True,
                  comment="Human-readable description of what this tracker monitors"),
    )
    op.add_column(
        "narrative_trackers",
        sa.Column("hypothesis", sa.Text(), nullable=True,
                  comment="The specific analytical hypothesis or claim being tracked"),
    )
    op.add_column(
        "narrative_trackers",
        sa.Column("entity_ids", postgresql.ARRAY(sa.Text()), nullable=True,
                  comment="Entity UUIDs (as text) that this tracker is focused on"),
    )
    op.add_column(
        "narrative_trackers",
        sa.Column("claim_patterns", postgresql.ARRAY(sa.Text()), nullable=True,
                  comment="Keyword/regex patterns for matching claims to this tracker"),
    )
    op.add_column(
        "narrative_trackers",
        sa.Column("model_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment="LLM / model instructions for evidence classification on this tracker"),
    )

    # ── narrative_tracker_matches: evidence_relation groundwork ──────────────
    # Anticipates Sprint 26 CP2: supports / contradicts / contextual / unclear
    op.add_column(
        "narrative_tracker_matches",
        sa.Column(
            "evidence_relation",
            sa.String(length=20),
            nullable=True,
            comment="Evidence classification relative to tracker hypothesis: "
                    "supports | contradicts | contextual | unclear | NULL (unclassified)",
        ),
    )
    op.create_index(
        "ix_tracker_matches_evidence_relation",
        "narrative_tracker_matches",
        ["tracker_id", "evidence_relation"],
    )


def downgrade() -> None:
    op.drop_index("ix_tracker_matches_evidence_relation",
                  table_name="narrative_tracker_matches")
    op.drop_column("narrative_tracker_matches", "evidence_relation")

    op.drop_column("narrative_trackers", "model_policy")
    op.drop_column("narrative_trackers", "claim_patterns")
    op.drop_column("narrative_trackers", "entity_ids")
    op.drop_column("narrative_trackers", "hypothesis")
    op.drop_column("narrative_trackers", "description")
