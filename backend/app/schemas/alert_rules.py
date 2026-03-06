"""Pydantic schemas for alert rules and events."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# AlertRule schemas
# ---------------------------------------------------------------------------

class AlertRuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    enabled: bool = True
    rule_type: str  # 'keyword', 'velocity', 'correlation', 'geo_proximity', 'silence'
    severity: str = "routine"  # 'flash', 'urgent', 'routine'

    # Level 1: keyword
    keywords: Optional[List[str]] = None
    keyword_mode: Optional[str] = None  # 'any', 'all', 'regex'
    source_types: Optional[List[str]] = None

    # Level 2: velocity
    entity_name: Optional[str] = None
    velocity_threshold: Optional[float] = None
    velocity_window_minutes: Optional[int] = None

    # Level 3: correlation
    directives: Optional[Dict[str, Any]] = None

    # Geo-proximity
    geo_lat: Optional[float] = None
    geo_lng: Optional[float] = None
    geo_radius_km: Optional[float] = None
    geo_label: Optional[str] = None

    # Silence detection
    silence_entity: Optional[str] = None
    silence_source_type: Optional[str] = None
    silence_expected_interval_minutes: Optional[int] = None

    cooldown_minutes: int = 60
    delivery_channels: List[str] = Field(default_factory=lambda: ["in_app"])
    telegram_chat_id: Optional[str] = None
    webhook_url: Optional[str] = None


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    rule_type: Optional[str] = None
    severity: Optional[str] = None

    keywords: Optional[List[str]] = None
    keyword_mode: Optional[str] = None
    source_types: Optional[List[str]] = None

    entity_name: Optional[str] = None
    velocity_threshold: Optional[float] = None
    velocity_window_minutes: Optional[int] = None

    directives: Optional[Dict[str, Any]] = None

    # Geo-proximity
    geo_lat: Optional[float] = None
    geo_lng: Optional[float] = None
    geo_radius_km: Optional[float] = None
    geo_label: Optional[str] = None

    # Silence detection
    silence_entity: Optional[str] = None
    silence_source_type: Optional[str] = None
    silence_expected_interval_minutes: Optional[int] = None

    cooldown_minutes: Optional[int] = None
    delivery_channels: Optional[List[str]] = None
    telegram_chat_id: Optional[str] = None
    webhook_url: Optional[str] = None


class AlertRuleResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: Optional[str]
    enabled: bool
    rule_type: str
    severity: str

    keywords: Optional[List[str]]
    keyword_mode: Optional[str]
    source_types: Optional[List[str]]

    entity_name: Optional[str]
    velocity_threshold: Optional[float]
    velocity_window_minutes: Optional[int]

    directives: Optional[Dict[str, Any]]

    # Geo-proximity
    geo_lat: Optional[float]
    geo_lng: Optional[float]
    geo_radius_km: Optional[float]
    geo_label: Optional[str]

    # Silence detection
    silence_entity: Optional[str]
    silence_source_type: Optional[str]
    silence_expected_interval_minutes: Optional[int]
    silence_last_seen: Optional[datetime]

    cooldown_minutes: int
    delivery_channels: Optional[List[str]]
    telegram_chat_id: Optional[str]
    webhook_url: Optional[str]

    last_fired_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# AlertEvent schemas
# ---------------------------------------------------------------------------

class AlertEventResponse(BaseModel):
    id: uuid.UUID
    rule_id: uuid.UUID
    user_id: uuid.UUID
    severity: str
    title: str
    summary: Optional[str]
    matched_post_ids: Optional[List[uuid.UUID]]
    matched_entities: Optional[List[str]]
    context: Optional[Dict[str, Any]]
    acknowledged: bool
    acknowledged_at: Optional[datetime]
    fired_at: datetime

    # Joined rule info for convenience
    rule_name: Optional[str] = None
    rule_type: Optional[str] = None

    class Config:
        from_attributes = True


class AlertEventListResponse(BaseModel):
    items: List[AlertEventResponse]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Test result schema
# ---------------------------------------------------------------------------

class RuleTestResult(BaseModel):
    rule_id: str
    rule_type: str
    posts_checked: int
    match_count: int
    matches: List[Dict[str, Any]]
