from __future__ import annotations
import os
import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db
from app.models import User, Credential
from app.schemas.credentials import CredentialCreate, CredentialResponse, CredentialStatus
from app.middleware.auth import get_current_user
from app.services.collector_manager import collector_manager
from app.services.crypto import encrypt_credentials

router = APIRouter(prefix="/credentials", tags=["credentials"])

KNOWN_PROVIDERS = ["telegram", "x", "openrouter", "shodan", "discord", "ais", "acled"]


@router.post("/", response_model=CredentialResponse, status_code=status.HTTP_201_CREATED)
async def store_credentials(
    body: CredentialCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CredentialResponse:
    # We need the user's plaintext password to derive the encryption key.
    # Convention: the keys dict must contain "_password" field for the master password.
    # Actually — we encrypt using the user's password which is NOT available post-login.
    # For MVP, we use a per-credential random salt and store under the session password.
    # Since we don't have the password here, we store using the access token sub + a
    # server-side secret as the password (HMAC approach).
    # A proper implementation would require the password on this endpoint.
    # For MVP: accept password in the request body implicitly through api_keys["_password"].
    master_password = body.api_keys.pop("_password", None)
    if not master_password:
        raise HTTPException(
            status_code=400,
            detail="api_keys must include '_password' field with user's master password for encryption",
        )

    salt = os.urandom(16)
    encrypted_blob, nonce = encrypt_credentials(body.api_keys, master_password, salt)

    # Upsert: remove existing credential for this provider
    existing = await db.execute(
        select(Credential).where(
            Credential.user_id == current_user.id,
            Credential.provider == body.provider,
        )
    )
    existing_cred = existing.scalar_one_or_none()
    if existing_cred:
        existing_cred.encrypted_blob = encrypted_blob
        existing_cred.nonce = nonce
        cred = existing_cred
    else:
        cred = Credential(
            id=uuid.uuid4(),
            user_id=current_user.id,
            provider=body.provider,
            encrypted_blob=encrypted_blob,
            nonce=nonce,
        )
        db.add(cred)

    await db.commit()
    await db.refresh(cred)

    # Unlock in memory
    await collector_manager.unlock(str(current_user.id), body.provider, body.api_keys)

    return cred


@router.get("/", response_model=List[CredentialResponse])
async def list_credentials(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[CredentialResponse]:
    result = await db.execute(
        select(Credential).where(Credential.user_id == current_user.id)
    )
    return result.scalars().all()


@router.get("/status", response_model=List[CredentialStatus])
async def credentials_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[CredentialStatus]:
    result = await db.execute(
        select(Credential.provider).where(Credential.user_id == current_user.id)
    )
    configured_providers = {row[0] for row in result.fetchall()}
    user_id = str(current_user.id)

    return [
        CredentialStatus(
            provider=p,
            configured=p in configured_providers,
            collector_active=collector_manager.is_active(user_id, p),
        )
        for p in KNOWN_PROVIDERS
    ]


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credentials(
    provider: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await db.execute(
        select(Credential).where(
            Credential.user_id == current_user.id,
            Credential.provider == provider,
        )
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    await db.delete(cred)
    await db.commit()
    await collector_manager.lock(str(current_user.id), provider)
