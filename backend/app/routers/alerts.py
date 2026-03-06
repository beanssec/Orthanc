"""Alert routes — backward-compatible CRUD for old simple alerts + new rule-based system."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user
from app.models import User, Alert, AlertHit
from app.models.alert_rule import AlertEvent, AlertRule
from app.schemas.alerts import AlertCreate, AlertUpdate, AlertResponse, AlertHitResponse
from app.schemas.alert_rules import (
    AlertRuleCreate,
    AlertRuleResponse,
    AlertRuleUpdate,
    AlertEventResponse,
    AlertEventListResponse,
    RuleTestResult,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])


# ===========================================================================
# Legacy simple alert endpoints (backward-compatible)
# ===========================================================================

@router.post("/", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
async def create_alert(
    body: AlertCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertResponse:
    alert = Alert(
        id=uuid.uuid4(),
        user_id=current_user.id,
        keyword=body.keyword,
        delivery_type=body.delivery_type,
        delivery_target=body.delivery_target,
        enabled=True,
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert


@router.get("/hits", response_model=List[AlertHitResponse])
async def list_alert_hits(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[AlertHitResponse]:
    user_alert_ids = select(Alert.id).where(Alert.user_id == current_user.id)
    result = await db.execute(
        select(AlertHit)
        .where(AlertHit.alert_id.in_(user_alert_ids))
        .order_by(AlertHit.triggered_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return result.scalars().all()


# ===========================================================================
# New rule-based alert system
# ===========================================================================

@router.post("/rules/", response_model=AlertRuleResponse, status_code=201)
async def create_rule(
    body: AlertRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertRuleResponse:
    rule = AlertRule(
        id=uuid.uuid4(),
        user_id=current_user.id,
        name=body.name,
        description=body.description,
        enabled=body.enabled,
        rule_type=body.rule_type,
        severity=body.severity,
        keywords=body.keywords,
        keyword_mode=body.keyword_mode,
        source_types=body.source_types,
        entity_name=body.entity_name,
        velocity_threshold=body.velocity_threshold,
        velocity_window_minutes=body.velocity_window_minutes,
        directives=body.directives,
        # Geo-proximity
        geo_lat=body.geo_lat,
        geo_lng=body.geo_lng,
        geo_radius_km=body.geo_radius_km,
        geo_label=body.geo_label,
        # Silence detection
        silence_entity=body.silence_entity,
        silence_source_type=body.silence_source_type,
        silence_expected_interval_minutes=body.silence_expected_interval_minutes,
        cooldown_minutes=body.cooldown_minutes,
        delivery_channels=body.delivery_channels,
        telegram_chat_id=body.telegram_chat_id,
        webhook_url=body.webhook_url,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)

    # Invalidate rule cache so the engine picks up the new rule
    from app.services import correlation_engine
    correlation_engine.invalidate_rule_cache()

    return rule


@router.get("/rules/", response_model=List[AlertRuleResponse])
async def list_rules(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[AlertRuleResponse]:
    result = await db.execute(
        select(AlertRule)
        .where(AlertRule.user_id == current_user.id)
        .order_by(AlertRule.created_at.desc())
    )
    return result.scalars().all()


@router.get("/rules/{rule_id}", response_model=AlertRuleResponse)
async def get_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertRuleResponse:
    result = await db.execute(
        select(AlertRule).where(
            AlertRule.id == rule_id, AlertRule.user_id == current_user.id
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.put("/rules/{rule_id}", response_model=AlertRuleResponse)
async def update_rule(
    rule_id: uuid.UUID,
    body: AlertRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertRuleResponse:
    result = await db.execute(
        select(AlertRule).where(
            AlertRule.id == rule_id, AlertRule.user_id == current_user.id
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    update_fields = body.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(rule, field, value)
    rule.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(rule)

    from app.services import correlation_engine
    correlation_engine.invalidate_rule_cache()

    return rule


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await db.execute(
        select(AlertRule).where(
            AlertRule.id == rule_id, AlertRule.user_id == current_user.id
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.delete(rule)
    await db.commit()

    from app.services import correlation_engine
    correlation_engine.invalidate_rule_cache()


# ---------------------------------------------------------------------------
# Alert events (history)
# ---------------------------------------------------------------------------

@router.get("/events/", response_model=AlertEventListResponse)
async def list_alert_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    severity: Optional[str] = Query(default=None),
    acknowledged: Optional[bool] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertEventListResponse:
    filters = [AlertEvent.user_id == current_user.id]
    if severity:
        filters.append(AlertEvent.severity == severity)
    if acknowledged is not None:
        filters.append(AlertEvent.acknowledged.is_(acknowledged))

    count_result = await db.execute(
        select(func.count(AlertEvent.id)).where(*filters)
    )
    total = count_result.scalar_one_or_none() or 0

    result = await db.execute(
        select(AlertEvent, AlertRule.name.label("rule_name"), AlertRule.rule_type)
        .join(AlertRule, AlertEvent.rule_id == AlertRule.id, isouter=True)
        .where(*filters)
        .order_by(AlertEvent.fired_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = result.all()

    items = []
    for row in rows:
        event = row[0]
        rule_name = row[1]
        rule_type = row[2]
        item = AlertEventResponse(
            id=event.id,
            rule_id=event.rule_id,
            user_id=event.user_id,
            severity=event.severity,
            title=event.title,
            summary=event.summary,
            matched_post_ids=event.matched_post_ids,
            matched_entities=event.matched_entities,
            context=event.context,
            acknowledged=event.acknowledged,
            acknowledged_at=event.acknowledged_at,
            fired_at=event.fired_at,
            rule_name=rule_name,
            rule_type=rule_type,
        )
        items.append(item)

    return AlertEventListResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("/events/{event_id}/acknowledge", response_model=AlertEventResponse)
async def acknowledge_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertEventResponse:
    result = await db.execute(
        select(AlertEvent).where(
            AlertEvent.id == event_id, AlertEvent.user_id == current_user.id
        )
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    event.acknowledged = True
    event.acknowledged_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(event)

    # Also get rule info
    rule_result = await db.execute(select(AlertRule).where(AlertRule.id == event.rule_id))
    rule = rule_result.scalar_one_or_none()

    return AlertEventResponse(
        id=event.id,
        rule_id=event.rule_id,
        user_id=event.user_id,
        severity=event.severity,
        title=event.title,
        summary=event.summary,
        matched_post_ids=event.matched_post_ids,
        matched_entities=event.matched_entities,
        context=event.context,
        acknowledged=event.acknowledged,
        acknowledged_at=event.acknowledged_at,
        fired_at=event.fired_at,
        rule_name=rule.name if rule else None,
        rule_type=rule.rule_type if rule else None,
    )


# ---------------------------------------------------------------------------
# Test / dry-run
# ---------------------------------------------------------------------------

@router.post("/rules/{rule_id}/test", response_model=RuleTestResult)
async def test_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RuleTestResult:
    result = await db.execute(
        select(AlertRule).where(
            AlertRule.id == rule_id, AlertRule.user_id == current_user.id
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    from app.services import correlation_engine
    test_result = await correlation_engine.dry_run_rule(rule, db)
    return RuleTestResult(**test_result)


# ---------------------------------------------------------------------------
# Legacy GET /  and single alert endpoints — keep backward compat
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[AlertResponse])
async def list_alerts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[AlertResponse]:
    result = await db.execute(select(Alert).where(Alert.user_id == current_user.id))
    return result.scalars().all()


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertResponse:
    result = await db.execute(
        select(Alert).where(Alert.id == alert_id, Alert.user_id == current_user.id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.put("/{alert_id}", response_model=AlertResponse)
async def update_alert(
    alert_id: uuid.UUID,
    body: AlertUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertResponse:
    result = await db.execute(
        select(Alert).where(Alert.id == alert_id, Alert.user_id == current_user.id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if body.keyword is not None:
        alert.keyword = body.keyword
    if body.delivery_type is not None:
        alert.delivery_type = body.delivery_type
    if body.delivery_target is not None:
        alert.delivery_target = body.delivery_target
    if body.enabled is not None:
        alert.enabled = body.enabled

    await db.commit()
    await db.refresh(alert)
    return alert


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await db.execute(
        select(Alert).where(Alert.id == alert_id, Alert.user_id == current_user.id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    await db.delete(alert)
    await db.commit()
