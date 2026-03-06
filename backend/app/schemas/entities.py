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
