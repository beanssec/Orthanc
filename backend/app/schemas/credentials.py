from __future__ import annotations
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel
from typing import Literal


class CredentialCreate(BaseModel):
    provider: Literal["telegram", "x", "openrouter", "shodan", "discord", "ais", "acled", "occrp"]
    api_keys: dict


class CredentialResponse(BaseModel):
    id: UUID
    provider: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CredentialStatus(BaseModel):
    provider: str
    configured: bool
    collector_active: bool
