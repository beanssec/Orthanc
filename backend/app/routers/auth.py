from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from app.db import get_db
from app.models import User, Credential
from app.schemas.auth import UserCreate, UserLogin, Token, UserResponse
from app.middleware.auth import create_access_token, create_refresh_token, get_current_user
from app.services.collector_manager import collector_manager
from app.services.crypto import decrypt_credentials
from app.collectors.orchestrator import orchestrator
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jose import JWTError, jwt
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])
ph = PasswordHasher()


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

    # Decrypt stored credentials into memory
    creds_result = await db.execute(select(Credential).where(Credential.user_id == user.id))
    credentials = creds_result.scalars().all()
    for cred in credentials:
        try:
            keys = decrypt_credentials(cred.encrypted_blob, cred.nonce, body.password)
            await collector_manager.unlock(user_id, cred.provider, keys)
        except Exception:
            pass  # Credential decryption failure is non-fatal at login

    # Start background collectors for this user (non-fatal)
    try:
        await orchestrator.start_user_collectors(user_id)
    except Exception:
        pass

    access_token = create_access_token({"sub": user_id, "username": user.username})
    refresh_token = create_refresh_token({"sub": user_id})
    return Token(access_token=access_token, token_type="bearer", refresh_token=refresh_token)


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
