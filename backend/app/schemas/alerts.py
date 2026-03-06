from __future__ import annotations
from datetime import datetime
from uuid import UUID
from typing import Optional
from pydantic import BaseModel


class AlertCreate(BaseModel):
    keyword: str
    delivery_type: str
    delivery_target: str


class AlertUpdate(BaseModel):
    keyword: Optional[str] = None
    delivery_type: Optional[str] = None
    delivery_target: Optional[str] = None
    enabled: Optional[bool] = None


class AlertResponse(BaseModel):
    id: UUID
    keyword: str
    delivery_type: str
    delivery_target: str
    enabled: bool

    class Config:
        from_attributes = True


class AlertHitResponse(BaseModel):
    id: UUID
    alert_id: UUID
    post_id: UUID
    triggered_at: datetime

    class Config:
        from_attributes = True
