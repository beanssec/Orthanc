"""Pydantic schemas for API key endpoints — Sprint 30 Checkpoint 1.

Security rules enforced at the schema level:
- key_hash is NEVER included in any response schema
- plaintext key is ONLY present in CreateApiKeyResponse (returned once)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ── Request Schemas ───────────────────────────────────────────────────────────

class CreateApiKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Human-readable label for the key")
    scopes: List[str] = Field(
        default_factory=list,
        description=(
            "List of permission scopes (e.g. ['read:feed', 'read:entities']). "
            "Empty list = read-only access to all resources."
        ),
    )


# ── Response Schemas ──────────────────────────────────────────────────────────

class ApiKeyResponse(BaseModel):
    """Safe representation — no hash, no plaintext key."""
    id: uuid.UUID
    name: str
    prefix: str
    scopes: List[str]
    created_at: datetime
    last_used_at: Optional[datetime]
    revoked_at: Optional[datetime]
    is_active: bool

    model_config = {"from_attributes": True}


class CreateApiKeyResponse(BaseModel):
    """Returned ONCE on creation — includes plaintext key that cannot be recovered."""
    key: str = Field(..., description="Full API key — shown only once, store it securely")
    api_key: ApiKeyResponse


class RevokeApiKeyResponse(BaseModel):
    id: uuid.UUID
    revoked: bool
    message: str
