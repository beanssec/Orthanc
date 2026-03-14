"""API key management endpoints — Sprint 30 Checkpoint 1.

Routes:
  POST   /api-keys        — create a new API key (returns plaintext once)
  GET    /api-keys        — list caller's API keys (no hashes, no plaintext)
  DELETE /api-keys/{id}   — revoke an API key

Security contract:
  - Raw key is generated with secrets.token_urlsafe(32) — 256 bits of entropy
  - Stored as SHA-256(raw_key) hex — never the raw value
  - prefix = "ow_" + first 8 chars of the raw token (display hint only)
  - Full plaintext key is returned exactly once in the POST response
  - key_hash is excluded from all response schemas
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user
from app.models.api_key import ApiKey
from app.models.user import User
from app.schemas.api_keys import (
    ApiKeyResponse,
    CreateApiKeyRequest,
    CreateApiKeyResponse,
    RevokeApiKeyResponse,
)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


def _hash_key(raw_key: str) -> str:
    """Return SHA-256 hex digest of the raw key string."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _generate_raw_key() -> str:
    """Generate a cryptographically random token (URL-safe base64, 43 chars)."""
    return secrets.token_urlsafe(32)


def _make_prefix(raw_key: str) -> str:
    """Return the display prefix — safe to expose."""
    return f"ow_{raw_key[:8]}"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=CreateApiKeyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new API key",
    description=(
        "Creates a new API key for the authenticated user. "
        "The full plaintext key is returned **once** in this response — "
        "it cannot be retrieved again."
    ),
)
async def create_api_key(
    body: CreateApiKeyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CreateApiKeyResponse:
    raw_key = _generate_raw_key()
    prefix = _make_prefix(raw_key)
    key_hash = _hash_key(raw_key)
    full_key = f"ow_{raw_key}"

    api_key = ApiKey(
        user_id=current_user.id,
        name=body.name,
        prefix=prefix,
        key_hash=key_hash,
        scopes=body.scopes,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return CreateApiKeyResponse(
        key=full_key,
        api_key=ApiKeyResponse(
            id=api_key.id,
            name=api_key.name,
            prefix=api_key.prefix,
            scopes=api_key.scopes,
            created_at=api_key.created_at,
            last_used_at=api_key.last_used_at,
            revoked_at=api_key.revoked_at,
            is_active=api_key.is_active,
        ),
    )


@router.get(
    "",
    response_model=List[ApiKeyResponse],
    summary="List API keys",
    description="Returns all API keys belonging to the authenticated user. Hashes are never included.",
)
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ApiKeyResponse]:
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == current_user.id)
        .order_by(ApiKey.created_at.desc())
    )
    keys = result.scalars().all()
    return [
        ApiKeyResponse(
            id=k.id,
            name=k.name,
            prefix=k.prefix,
            scopes=k.scopes,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
            revoked_at=k.revoked_at,
            is_active=k.is_active,
        )
        for k in keys
    ]


@router.delete(
    "/{key_id}",
    response_model=RevokeApiKeyResponse,
    summary="Revoke an API key",
    description=(
        "Sets revoked_at on the key to the current timestamp. "
        "Revoked keys can no longer be used for authentication."
    ),
)
async def revoke_api_key(
    key_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RevokeApiKeyResponse:
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.user_id == current_user.id,
        )
    )
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )

    if api_key.revoked_at is not None:
        return RevokeApiKeyResponse(
            id=api_key.id,
            revoked=False,
            message="Key was already revoked",
        )

    api_key.revoked_at = datetime.now(timezone.utc)
    await db.commit()

    return RevokeApiKeyResponse(
        id=api_key.id,
        revoked=True,
        message="API key revoked successfully",
    )
