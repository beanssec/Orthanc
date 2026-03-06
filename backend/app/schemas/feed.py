from __future__ import annotations
from datetime import datetime
from uuid import UUID
from typing import Any, Optional, List
from pydantic import BaseModel


class EventResponse(BaseModel):
    id: UUID
    lat: float
    lng: float
    place_name: Optional[str]
    confidence: float

    class Config:
        from_attributes = True


class PostResponse(BaseModel):
    id: UUID
    source_type: str
    source_id: str
    author: Optional[str] = None
    content: Optional[str] = None
    timestamp: Optional[datetime] = None
    ingested_at: datetime
    event: Optional[EventResponse] = None

    # Media fields (migration 009)
    media_type: Optional[str] = None
    media_path: Optional[str] = None
    media_size_bytes: Optional[int] = None
    media_mime: Optional[str] = None
    media_thumbnail_path: Optional[str] = None
    media_metadata: Optional[Any] = None
    authenticity_score: Optional[float] = None
    authenticity_analysis: Optional[str] = None
    authenticity_checked_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FeedFilter(BaseModel):
    source_types: Optional[List[str]] = None
    keyword: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
