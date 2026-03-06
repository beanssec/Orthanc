from __future__ import annotations
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class UserCreate(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: str


class UserResponse(BaseModel):
    id: UUID
    username: str
    created_at: datetime

    class Config:
        from_attributes = True
