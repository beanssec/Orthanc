"""Merge-candidate generation service.

Scans the entity corpus and surfaces likely duplicate entities for analyst
review.  This module is **read-only** — it never modifies any row.

Signals used
------------
1. exact_canonical_match   — two entities share the same canonical_name
2. alias_canonical_overlap — an alias of entity A resolves to the canonical
                             of entity B (or vice-versa)
3. alias_alias_overlap     — both entities share a common alias_norm

Confidence scoring
------------------
Each signal carries a base confidence.  When multiple signals fire for the
same pair the scores are combined via ``1 - (1-s1)*(1-s2)*…`` so they
accumulate but never exceed 1.0.

Primary vs duplicate
--------------------
Within each candidate pair the entity with the higher ``mention_count`` is
designated *primary*.  Ties are broken by ``first_seen`` (older is primary).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import Entity, EntityAlias

logger = logging.getLogger("orthanc.merge_candidates")

# ── Signal confidence weights ──────────────────────────────────────────────────
_CONF_EXACT_CANONICAL = 0.95
_CONF_ALIAS_CANONICAL = 0.85
_CONF_ALIAS_ALIAS = 0.80


@dataclass
class MergeCandidate:
    primary_id: uuid.UUID
    primary_name: str
    primary_type: str
    primary_canonical: str
    primary_mention_count: int

    duplicate_id: uuid.UUID
    duplicate_name: str
    duplicate_type: str
    duplicate_canonical: str
    duplicate_mention_count: int

    confidence: float
    reasons: list[str] = field(default_factory=list)


def _combine_confidence(*scores: float) -> float:
    """Non-linear combination so multiple weak signals accumulate sensibly."""
    result = 1.0
    for s in scores:
        result *= 1.0 - max(0.0, min(1.0, s))
    return round(1.0 - result, 4)


def _pick_primary(a: Entity, b: Entity) -> tuple[Entity, Entity]:
    """Return (primary, duplicate) — primary has higher mention_count."""
    if a.mention_count > b.mention_count:
        return a, b
    if b.mention_count > a.mention_count:
        return b, a
    # Tie-break: older entity is primary
    if a.first_seen and b.first_seen:
        return (a, b) if a.first_seen <= b.first_seen else (b, a)
    return a, b


def _make_candidate(
    primary: Entity,
    duplicate: Entity,
    scores: list[float],
    reasons: list[str],
) -> MergeCandidate:
    combined = _combine_confidence(*scores)
    return MergeCandidate(
        primary_id=primary.id,
        primary_name=primary.name,
        primary_type=primary.type,
        primary_canonical=primary.canonical_name,
        primary_mention_count=primary.mention_count,
        duplicate_id=duplicate.id,
        duplicate_name=duplicate.name,
        duplicate_type=duplicate.type,
        duplicate_canonical=duplicate.canonical_name,
        duplicate_mention_count=duplicate.mention_count,
        confidence=combined,
        reasons=reasons,
    )


async def generate_merge_candidates(
    db: AsyncSession,
    min_confidence: float = 0.5,
    limit: int = 200,
    same_type_only: bool = False,
) -> list[MergeCandidate]:
    """
    Return at most *limit* merge candidates with confidence >= *min_confidence*.

    Parameters
    ----------
    db              AsyncSession to query against.
    min_confidence  Discard pairs below this threshold (default 0.5).
    limit           Max candidates returned (default 200, hard-capped at 500).
    same_type_only  When True, only surface pairs that share the same entity
                    type (or effective type after overrides).  Defaults False
                    so that type-mismatches are surfaced but flagged.
    """
    limit = min(limit, 500)

    # ── 1. Load all entities ───────────────────────────────────────────────────
    entities_result = await db.execute(
        select(Entity).order_by(Entity.mention_count.desc())
    )
    entities: list[Entity] = list(entities_result.scalars().all())

    if len(entities) < 2:
        return []

    # Index structures
    entity_by_id: dict[uuid.UUID, Entity] = {e.id: e for e in entities}
    # canonical → list of entity IDs
    canonical_index: dict[str, list[uuid.UUID]] = {}
    for e in entities:
        canonical_index.setdefault(e.canonical_name, []).append(e.id)

    # ── 2. Load all aliases ────────────────────────────────────────────────────
    aliases_result = await db.execute(select(EntityAlias))
    aliases: list[EntityAlias] = list(aliases_result.scalars().all())

    # alias_norm → set of entity IDs that own this alias
    alias_to_entities: dict[str, set[uuid.UUID]] = {}
    # entity_id → set of alias_norms
    entity_to_aliases: dict[uuid.UUID, set[str]] = {}
    for a in aliases:
        alias_to_entities.setdefault(a.alias_norm, set()).add(a.entity_id)
        entity_to_aliases.setdefault(a.entity_id, set()).add(a.alias_norm)

    # ── 3. Collect candidate pairs with signals ────────────────────────────────
    # pair key = frozenset({id_a, id_b})  →  { reason → score }
    pair_signals: dict[frozenset, dict[str, float]] = {}

    def _add_signal(a_id: uuid.UUID, b_id: uuid.UUID, reason: str, score: float) -> None:
        if a_id == b_id:
            return
        key = frozenset({a_id, b_id})
        if key not in pair_signals:
            pair_signals[key] = {}
        # Keep the highest score for each distinct reason label
        if reason not in pair_signals[key] or pair_signals[key][reason] < score:
            pair_signals[key][reason] = score

    # Signal 1 — exact canonical name collision
    for canonical, ids in canonical_index.items():
        if len(ids) < 2:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                _add_signal(ids[i], ids[j], "exact_canonical_match", _CONF_EXACT_CANONICAL)

    # Signal 2 — alias of one entity matches canonical of another
    for e in entities:
        # Check if any alias_norm of this entity matches some other entity's canonical
        for anorm in entity_to_aliases.get(e.id, set()):
            matching_ids = canonical_index.get(anorm, [])
            for other_id in matching_ids:
                if other_id != e.id:
                    _add_signal(e.id, other_id, "alias_canonical_overlap", _CONF_ALIAS_CANONICAL)
        # Check if this entity's canonical matches an alias_norm of some other entity
        other_ids_with_alias = alias_to_entities.get(e.canonical_name, set())
        for other_id in other_ids_with_alias:
            if other_id != e.id:
                _add_signal(e.id, other_id, "alias_canonical_overlap", _CONF_ALIAS_CANONICAL)

    # Signal 3 — shared alias_norm across different entities
    for anorm, entity_ids in alias_to_entities.items():
        ids_list = list(entity_ids)
        if len(ids_list) < 2:
            continue
        for i in range(len(ids_list)):
            for j in range(i + 1, len(ids_list)):
                _add_signal(ids_list[i], ids_list[j], "alias_alias_overlap", _CONF_ALIAS_ALIAS)

    # ── 4. Build MergeCandidate objects ───────────────────────────────────────
    candidates: list[MergeCandidate] = []

    for pair_key, signals in pair_signals.items():
        id_a, id_b = tuple(pair_key)
        ent_a = entity_by_id.get(id_a)
        ent_b = entity_by_id.get(id_b)
        if ent_a is None or ent_b is None:
            continue

        if same_type_only and ent_a.type != ent_b.type:
            continue

        combined = _combine_confidence(*signals.values())
        if combined < min_confidence:
            continue

        primary, duplicate = _pick_primary(ent_a, ent_b)
        reasons = sorted(signals.keys())  # deterministic order

        candidates.append(
            _make_candidate(primary, duplicate, list(signals.values()), reasons)
        )

    # Sort by confidence descending, then primary mention_count descending
    candidates.sort(key=lambda c: (-c.confidence, -c.primary_mention_count))

    return candidates[:limit]
