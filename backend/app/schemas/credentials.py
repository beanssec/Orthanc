from __future__ import annotations
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from typing import Literal


class CredentialCreate(BaseModel):
    provider: Literal["telegram", "x", "reddit", "openrouter", "shodan", "discord", "ais", "acled", "occrp", "ollama", "openai_compatible"]
    api_keys: dict


class CredentialResponse(BaseModel):
    id: UUID
    provider: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CredentialStatus(BaseModel):
    provider: str
    configured: bool
    collector_active: bool
