"""Pydantic schemas for the Events API."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PostSummary(BaseModel):
    id: uuid.UUID
    source_type: str
    source_id: str
    author: Optional[str] = None
    content: Optional[str] = None  # truncated to 200 chars
    timestamp: Optional[datetime] = None

    model_config = {"from_attributes": True}


class EventWithPost(BaseModel):
    id: uuid.UUID
    lat: Optional[float] = None
    lng: Optional[float] = None
    place_name: Optional[str] = None
    confidence: Optional[float] = None
    precision: Optional[str] = None
    post: PostSummary

    model_config = {"from_attributes": True}


class BackfillResponse(BaseModel):
    processed: int
    events_created: int
    message: str = "Backfill started in background"
