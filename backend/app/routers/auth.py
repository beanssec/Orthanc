from __future__ import annotations
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from app.db import get_db, AsyncSessionLocal
from app.models import User, Credential, Source
from app.schemas.auth import UserCreate, UserLogin, Token, UserResponse
from app.middleware.auth import create_access_token, create_refresh_token, get_current_user
from app.services.collector_manager import collector_manager
from app.services.crypto import decrypt_credentials
from app.collectors.orchestrator import orchestrator
from app.services.model_router import model_router, OpenRouterProvider, XAIProvider, OllamaProvider, OpenAICompatibleProvider
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jose import JWTError, jwt
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])
ph = PasswordHasher()
logger = logging.getLogger("orthanc.auth")


_POST_LOGIN_STATUS: dict[str, dict] = {}


def _set_init_status(user_id: str, **updates) -> None:
    current = _POST_LOGIN_STATUS.get(user_id, {
        "authenticated": True,
        "initializing": False,
        "providers_initialized": False,
        "collectors_started": False,
        "init_error": None,
    })
    current.update(updates)
    _POST_LOGIN_STATUS[user_id] = current


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: UserCreate, db: AsyncSession = Depends(get_db)) -> UserResponse:
    result = await db.execute(select(User).where(User.username == body.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken")

    hashed = ph.hash(body.password)
    user = User(id=uuid.uuid4(), username=body.username, password_hash=hashed)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(body: UserLogin, db: AsyncSession = Depends(get_db)) -> Token:
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    try:
        ph.verify(user.password_hash, body.password)
    except VerifyMismatchError:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user_id = str(user.id)
    _set_init_status(
        user_id,
        authenticated=True,
        initializing=True,
        providers_initialized=False,
        collectors_started=False,
        init_error=None,
    )

    # Post-login initialization runs in background so /auth/login remains fast.
    async def _post_login_init(uid: str, user_uuid: uuid.UUID, plaintext_password: str) -> None:
        try:
            async with AsyncSessionLocal() as session:
                creds_result = await session.execute(select(Credential).where(Credential.user_id == user_uuid))
                credentials = creds_result.scalars().all()

                src_result = await session.execute(
                    select(Source.type).where(Source.user_id == user_uuid, Source.enabled.is_(True))
                )
                enabled_source_types = {row[0] for row in src_result.fetchall()}

            needed_providers = set(enabled_source_types)
            needed_providers.update({"openrouter", "x", "ollama", "openai_compatible"})

            for cred in credentials:
                if cred.provider not in needed_providers:
                    continue
                try:
                    keys = decrypt_credentials(cred.encrypted_blob, cred.nonce, plaintext_password)
                    await collector_manager.unlock(uid, cred.provider, keys)
                except Exception:
                    logger.warning("Credential unlock failed for provider %s", cred.provider, exc_info=True)

            try:
                or_keys = await collector_manager.get_keys(uid, "openrouter")
                if or_keys and or_keys.get("api_key"):
                    model_router.register_provider("openrouter", OpenRouterProvider(or_keys["api_key"]))

                x_keys = await collector_manager.get_keys(uid, "x")
                if x_keys and x_keys.get("api_key"):
                    model_router.register_provider("xai", XAIProvider(x_keys["api_key"]))

                ollama_keys = await collector_manager.get_keys(uid, "ollama")
                if ollama_keys:
                    base_url = ollama_keys.get("api_key", "http://localhost:11434")
                    model_router.register_provider("ollama", OllamaProvider(base_url))

                compat_keys = await collector_manager.get_keys(uid, "openai_compatible")
                if compat_keys:
                    model_router.register_provider(
                        "openai_compatible",
                        OpenAICompatibleProvider(
                            base_url=compat_keys.get("base_url", compat_keys.get("api_key", "")),
                            api_key=compat_keys.get("api_key_secret", ""),
                        ),
                    )
                _set_init_status(uid, providers_initialized=True)
            except Exception as e:
                logger.warning("Failed to register LLM providers: %s", e)
                _set_init_status(uid, providers_initialized=False, init_error=f"provider init failed: {e}")

            try:
                await orchestrator.start_user_collectors(uid)
                _set_init_status(uid, collectors_started=True)
            except Exception:
                logger.warning("Background collector start failed for user %s", uid, exc_info=True)
                _set_init_status(uid, collectors_started=False, init_error="collector startup failed")
        except Exception:
            logger.warning("Post-login initialization failed for user %s", uid, exc_info=True)
            _set_init_status(uid, init_error="post-login initialization failed")
        finally:
            _set_init_status(uid, initializing=False)

    asyncio.create_task(_post_login_init(user_id, user.id, body.password))

    access_token = create_access_token({"sub": user_id, "username": user.username})
    refresh_token = create_refresh_token({"sub": user_id})
    return Token(access_token=access_token, token_type="bearer", refresh_token=refresh_token)


@router.get("/session-status")
async def session_status(current_user: User = Depends(get_current_user)) -> dict:
    user_id = str(current_user.id)
    status_payload = _POST_LOGIN_STATUS.get(user_id)
    if not status_payload:
        return {
            "authenticated": True,
            "initializing": False,
            "providers_initialized": False,
            "collectors_started": False,
            "init_error": None,
        }
    return status_payload


@router.post("/refresh", response_model=Token)
async def refresh_token(token: str, db: AsyncSession = Depends(get_db)) -> Token:
    credentials_exception = HTTPException(status_code=401, detail="Invalid refresh token")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise credentials_exception
        user_id: str = payload.get("sub")
        if not user_id:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise credentials_exception

    access_token = create_access_token({"sub": user_id, "username": user.username})
    new_refresh = create_refresh_token({"sub": user_id})
    return Token(access_token=access_token, token_type="bearer", refresh_token=new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(current_user: User = Depends(get_current_user)) -> None:
    user_id = str(current_user.id)
    await orchestrator.stop_user_collectors(user_id)
    await collector_manager.lock(user_id)
    _POST_LOGIN_STATUS.pop(user_id, None)
