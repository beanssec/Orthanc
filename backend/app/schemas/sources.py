from __future__ import annotations
from datetime import datetime
from uuid import UUID
from typing import Any, Optional
from pydantic import BaseModel


class SourceCreate(BaseModel):
    type: str
    handle: str
    display_name: str
    config_json: dict[str, Any] = {}
    download_images: bool = False
    download_videos: bool = False
    max_image_size_mb: float = 10.0
    max_video_size_mb: float = 100.0


class SourceUpdate(BaseModel):
    display_name: Optional[str] = None
    enabled: Optional[bool] = None
    config_json: Optional[dict[str, Any]] = None
    download_images: Optional[bool] = None
    download_videos: Optional[bool] = None
    max_image_size_mb: Optional[float] = None
    max_video_size_mb: Optional[float] = None


class SourceResponse(BaseModel):
    id: UUID
    type: str
    handle: str
    display_name: str
    enabled: bool
    last_polled: Optional[datetime]
    config_json: dict[str, Any]
    download_images: bool
    download_videos: bool
    max_image_size_mb: float
    max_video_size_mb: float

    class Config:
        from_attributes = True
