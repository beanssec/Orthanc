from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class EntityBase(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    canonical_name: str
    mention_count: int
    first_seen: datetime
    last_seen: datetime

    model_config = {"from_attributes": True}


class EntitySchema(EntityBase):
    pass


class EntityMentionSchema(BaseModel):
    id: uuid.UUID
    post_id: uuid.UUID
    context_snippet: str | None
    extracted_at: datetime

    model_config = {"from_attributes": True}


class EntityDetailSchema(EntityBase):
    mentions: list[EntityMentionSchema]


class EntityConnectionItem(BaseModel):
    entity: EntitySchema
    co_occurrences: int


class EntityPagedResponse(BaseModel):
    """Paginated entity search response — Sprint 28 pagination foundation."""

    items: list[EntitySchema]
    total: int
    limit: int
    offset: int


# ── Merge-candidate schemas (Sprint 27 Checkpoint 2) ──────────────────────────

class MergeCandidateEntity(BaseModel):
    """Slim entity summary embedded in a merge candidate pair."""
    id: uuid.UUID
    name: str
    type: str
    canonical_name: str
    mention_count: int


class MergeCandidateItem(BaseModel):
    """A suggested merge pair with confidence and signal reasons."""
    primary: MergeCandidateEntity
    duplicate: MergeCandidateEntity
    confidence: float
    reasons: list[str]


class MergeCandidateResponse(BaseModel):
    """Top-level response for GET /entities/merge-candidates."""
    candidates: list[MergeCandidateItem]
    total: int
    min_confidence: float
    same_type_only: bool


# ── Merge action schemas (Sprint 27 Checkpoint 3) ─────────────────────────────

class MergeRequest(BaseModel):
    """
    Request body for POST /entities/{primary_id}/merge.

    secondary_ids   — one or more entity IDs to be absorbed into the primary.
    preserve_aliases — when True (default), the secondary's name and
                       canonical_name are preserved as aliases on the primary
                       before the secondary is deleted.
    """
    secondary_ids: list[uuid.UUID]
    preserve_aliases: bool = True


class MergeResult(BaseModel):
    """Response from POST /entities/{primary_id}/merge."""
    status: str                      # "merged"
    primary_id: uuid.UUID
    merged_ids: list[uuid.UUID]      # secondary IDs that were consumed
    mentions_reassigned: int         # EntityMention rows moved to primary
    aliases_added: int               # new EntityAlias rows on primary
    aliases_skipped_duplicate: int   # aliases that already existed on primary
