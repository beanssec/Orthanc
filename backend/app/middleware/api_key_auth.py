"""API key authentication helpers — Sprint 30 / Checkpoint 2.

Provides two public callables:

``authenticate_api_key(request, db)``
    Low-level verifier.  Extracts the raw key from the request headers,
    hashes it, looks up ``api_keys.key_hash``, rejects revoked keys,
    updates ``last_used_at``, and returns the owning ``User``.
    Raises ``HTTPException(401)`` on any failure.

``get_user_from_api_key``
    FastAPI dependency that wraps ``authenticate_api_key`` for direct use
    in ``Depends()``.

Header formats accepted (evaluated in order):
    1. ``Authorization: Bearer ow_<token>``
    2. ``X-API-Key: ow_<token>``

The ``ow_`` prefix is not mandatory for X-API-Key (bare tokens are also
accepted) so that callers who stripped the prefix can still authenticate.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import ApiKey, User

logger = logging.getLogger("orthanc.api_key_auth")

# How many seconds between last_used_at updates.
# Avoids a write on every single request for high-frequency agents.
_LAST_USED_THROTTLE_SECONDS = 60


def _hash_key(raw_key: str) -> str:
    """Return SHA-256 hex digest of ``raw_key``."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _extract_raw_key(request: Request) -> str | None:
    """Return the raw API key from request headers, or None if absent.

    Checks (in order):
      1. ``Authorization: Bearer ow_<token>`` — only if token starts with ``ow_``
      2. ``X-API-Key: <token>``              — accepts with or without ``ow_`` prefix
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        bearer_token = auth_header[len("Bearer "):]
        if bearer_token.startswith("ow_"):
            return bearer_token

    x_api_key = request.headers.get("X-API-Key", "").strip()
    if x_api_key:
        return x_api_key

    return None


async def authenticate_api_key(
    request: Request,
    db: AsyncSession,
) -> User:
    """Verify an inbound API key and return the owning ``User``.

    Raises ``HTTPException(401)`` if:
    - no API key header is present
    - the key hash is not found in the database
    - the key has been revoked

    Updates ``api_keys.last_used_at`` (throttled to once per minute per key).
    """
    raw_key = _extract_raw_key(request)
    if raw_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    key_hash = _hash_key(raw_key)

    # Look up the key record
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash)
    )
    api_key: ApiKey | None = result.scalar_one_or_none()

    if api_key is None:
        logger.warning("API key lookup failed — hash not found (prefix: %s)", raw_key[:10])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not api_key.is_active:
        logger.warning(
            "Rejected revoked API key id=%s prefix=%s revoked_at=%s",
            api_key.id,
            api_key.prefix,
            api_key.revoked_at,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ── Update last_used_at (throttled) ────────────────────────────────────
    now = datetime.now(timezone.utc)
    needs_update = (
        api_key.last_used_at is None
        or (now - api_key.last_used_at.replace(tzinfo=timezone.utc)).total_seconds()
        >= _LAST_USED_THROTTLE_SECONDS
    )
    if needs_update:
        await db.execute(
            update(ApiKey)
            .where(ApiKey.id == api_key.id)
            .values(last_used_at=now)
        )
        await db.commit()
        logger.debug("Updated last_used_at for API key id=%s", api_key.id)

    # ── Resolve owning user ────────────────────────────────────────────────
    user_result = await db.execute(
        select(User).where(User.id == api_key.user_id)
    )
    user: User | None = user_result.scalar_one_or_none()

    if user is None:
        # Orphaned key — user was deleted but key wasn't cascade-deleted (shouldn't happen)
        logger.error("API key id=%s has no owning user (user_id=%s)", api_key.id, api_key.user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key owner not found",
        )

    logger.debug("API key auth OK: key_id=%s user=%s", api_key.id, user.username)
    return user


async def get_user_from_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency: authenticate via API key only.

    Suitable for endpoints that are exclusively machine-facing.
    For endpoints that accept both JWT and API key, use ``get_agent_auth``
    in ``app.routers.agent`` instead.
    """
    return await authenticate_api_key(request, db)
