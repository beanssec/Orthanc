"""
Telegram authentication router.

Handles the multi-step Telethon auth flow:
  1. POST /telegram/auth/start   — send code to phone
  2. POST /telegram/auth/verify  — submit received code
  3. POST /telegram/auth/2fa     — submit 2FA password (if required)
  4. GET  /telegram/auth/status  — check whether this user's session is authorised
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from telethon import TelegramClient
from telethon.errors import (
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

from app.middleware.auth import get_current_user
from app.models import User
from app.services.collector_manager import collector_manager

logger = logging.getLogger("orthanc.collectors.telegram")

router = APIRouter(prefix="/telegram/auth", tags=["telegram-auth"])

SESSION_DIR = "/app/data/telegram_sessions"

# In-memory store for pending auth clients: user_id -> TelegramClient
# These are short-lived — only needed during the auth flow.
_pending_clients: dict[str, TelegramClient] = {}


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class AuthStartRequest(BaseModel):
    phone: str


class AuthStartResponse(BaseModel):
    status: str
    phone_code_hash: str


class AuthVerifyRequest(BaseModel):
    phone: str
    code: str
    phone_code_hash: str


class AuthVerifyResponse(BaseModel):
    status: str  # "authenticated" | "2fa_required"


class Auth2FARequest(BaseModel):
    password: str


class Auth2FAResponse(BaseModel):
    status: str  # "authenticated" | "error"


class AuthStatusResponse(BaseModel):
    authenticated: bool
    phone: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_or_build_client(user_id: str) -> TelegramClient:
    """Return (or create) a TelegramClient for the given user.

    The client is created using the API credentials already unlocked in
    collector_manager.  Raises 400 if credentials are not loaded.
    """
    if user_id in _pending_clients:
        return _pending_clients[user_id]

    keys = await collector_manager.get_keys(user_id, "telegram")
    if not keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram API credentials not loaded. Unlock credentials first.",
        )

    api_id = int(keys["api_id"])
    api_hash: str = keys["api_hash"]

    os.makedirs(SESSION_DIR, exist_ok=True)
    session_path = os.path.join(SESSION_DIR, user_id)

    client = TelegramClient(session_path, api_id, api_hash)
    return client


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/start", response_model=AuthStartResponse)
async def auth_start(
    body: AuthStartRequest,
    current_user: User = Depends(get_current_user),
) -> AuthStartResponse:
    """Step 1 — Request a login code be sent to the given phone number."""
    user_id = str(current_user.id)

    client = await _get_or_build_client(user_id)

    if not client.is_connected():
        await client.connect()

    try:
        result = await client.send_code_request(body.phone)
    except Exception as exc:
        logger.error("send_code_request failed for user %s: %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to send code: {exc}",
        ) from exc

    _pending_clients[user_id] = client
    logger.info("Code sent to %s for user %s", body.phone, user_id)

    return AuthStartResponse(
        status="code_sent",
        phone_code_hash=result.phone_code_hash,
    )


@router.post("/verify", response_model=AuthVerifyResponse)
async def auth_verify(
    body: AuthVerifyRequest,
    current_user: User = Depends(get_current_user),
) -> AuthVerifyResponse:
    """Step 2 — Verify the code received via SMS / Telegram app."""
    user_id = str(current_user.id)

    client = _pending_clients.get(user_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending auth session. Call /telegram/auth/start first.",
        )

    try:
        await client.sign_in(
            phone=body.phone,
            code=body.code,
            phone_code_hash=body.phone_code_hash,
        )
    except SessionPasswordNeededError:
        # 2FA is enabled — keep client in pending dict
        logger.info("2FA required for user %s", user_id)
        return AuthVerifyResponse(status="2fa_required")
    except (PhoneCodeInvalidError, PhoneCodeExpiredError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error("sign_in failed for user %s: %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Sign-in failed: {exc}",
        ) from exc

    # Success — remove from pending; session is now persisted to disk
    _pending_clients.pop(user_id, None)
    logger.info("User %s successfully authenticated with Telegram", user_id)
    return AuthVerifyResponse(status="authenticated")


@router.post("/2fa", response_model=Auth2FAResponse)
async def auth_2fa(
    body: Auth2FARequest,
    current_user: User = Depends(get_current_user),
) -> Auth2FAResponse:
    """Step 3 (optional) — Provide the 2FA cloud password."""
    user_id = str(current_user.id)

    client = _pending_clients.get(user_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending auth session. Call /telegram/auth/start first.",
        )

    try:
        await client.sign_in(password=body.password)
    except Exception as exc:
        logger.error("2FA sign-in failed for user %s: %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"2FA failed: {exc}",
        ) from exc

    _pending_clients.pop(user_id, None)
    logger.info("User %s passed 2FA and is now authenticated with Telegram", user_id)
    return Auth2FAResponse(status="authenticated")


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(
    current_user: User = Depends(get_current_user),
) -> AuthStatusResponse:
    """Return whether the current user's Telegram session is authorised."""
    user_id = str(current_user.id)

    keys = await collector_manager.get_keys(user_id, "telegram")
    if not keys:
        return AuthStatusResponse(authenticated=False)

    os.makedirs(SESSION_DIR, exist_ok=True)
    session_path = os.path.join(SESSION_DIR, user_id)
    api_id = int(keys["api_id"])
    api_hash: str = keys["api_hash"]

    # If the collector is already running with this session, it's authenticated
    # Don't open a second connection (causes "database is locked")
    try:
        from app.collectors.orchestrator import orchestrator
        if hasattr(orchestrator, '_telegram_collectors') and user_id in orchestrator._telegram_collectors:
            tg = orchestrator._telegram_collectors[user_id]
            if tg.is_running:
                return AuthStatusResponse(authenticated=True, phone=None)
    except Exception:
        pass

    client = TelegramClient(session_path, api_id, api_hash)
    try:
        await client.connect()
        authorised = await client.is_user_authorized()
        phone: Optional[str] = None
        if authorised:
            me = await client.get_me()
            phone = getattr(me, "phone", None)
        return AuthStatusResponse(authenticated=authorised, phone=phone)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not check Telegram auth status for user %s: %s", user_id, exc)
        return AuthStatusResponse(authenticated=False)
    finally:
        await client.disconnect()
