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


# ── Reliability sub-schema (Sprint 29 C1) ────────────────────────────────────

class SourceReliabilityInfo(BaseModel):
    """Embedded reliability snapshot — all fields nullable for safety."""
    reliability_score: Optional[float] = None
    confidence_band: Optional[str] = None
    analyst_override: Optional[float] = None
    analyst_note: Optional[str] = None
    scoring_inputs: Optional[dict[str, Any]] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SourceReliabilityOverride(BaseModel):
    """Body for analyst override endpoint (Sprint 29 C3)."""
    analyst_override: Optional[float] = None
    analyst_note: Optional[str] = None

    class Config:
        # allow extra=False for safety
        extra = "forbid"


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

    # ── Reliability fields (Sprint 29 C1) — all Optional, fully backward-safe
    reliability: Optional[SourceReliabilityInfo] = None

    class Config:
        from_attributes = True
