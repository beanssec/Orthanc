"""Correlation Engine — OSSIM-style alert rule evaluation for Orthanc.

Four alert levels:
  Level 1: Keyword match — evaluated on every new post (immediate).
  Level 2: Entity velocity — evaluated periodically every 60s.
  Level 3: Correlation directives — multi-stage, evaluated on every post + periodically.
  Level 4: Geo-proximity — evaluated on every new post that has geo data.
  Level 5: Silence detection — evaluated periodically every 5 minutes.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.models.alert_rule import AlertEvent, AlertRule
from app.models.entity import Entity, EntityMention

logger = logging.getLogger("orthanc.correlation_engine")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


# ---------------------------------------------------------------------------
# Geo distance helper
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the great-circle distance in kilometres between two points.

    Handles the degenerate case of identical points (returns 0.0) safely.
    """
    R = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    # Clamp to [0, 1] to guard against floating-point rounding > 1
    c = 2 * math.asin(math.sqrt(min(a, 1.0)))
    return R * c

SEVERITY_EMOJI = {
    "flash": "🔴",
    "urgent": "🟠",
    "routine": "🔵",
}

# ---------------------------------------------------------------------------
# Rule cache — refreshed every 60 seconds to avoid DB hammering
# ---------------------------------------------------------------------------

@dataclass
class _RuleCache:
    rules: list[AlertRule] = field(default_factory=list)
    fetched_at: float = 0.0
    ttl: float = 60.0

    def is_stale(self) -> bool:
        return (time.monotonic() - self.fetched_at) > self.ttl

    def update(self, rules: list[AlertRule]) -> None:
        self.rules = rules
        self.fetched_at = time.monotonic()


_rule_cache = _RuleCache()
_cache_lock = asyncio.Lock()


async def _get_cached_rules(db: AsyncSession) -> list[AlertRule]:
    """Return all enabled rules; refresh from DB if cache is stale."""
    async with _cache_lock:
        if _rule_cache.is_stale():
            result = await db.execute(select(AlertRule).where(AlertRule.enabled.is_(True)))
            rules = result.scalars().all()
            _rule_cache.update(list(rules))
            logger.debug("Rule cache refreshed: %d enabled rules", len(_rule_cache.rules))
    return _rule_cache.rules


def invalidate_rule_cache() -> None:
    """Call after rule create/update/delete to force refresh on next evaluation."""
    _rule_cache.fetched_at = 0.0


# ---------------------------------------------------------------------------
# Correlation state — tracks in-progress multi-stage directives in memory
# ---------------------------------------------------------------------------

@dataclass
class _CorrelationWindow:
    rule_id: uuid.UUID
    user_id: uuid.UUID
    current_stage: int  # 1-indexed, currently waiting for this stage
    started_at: datetime
    window_expires_at: datetime
    matched_post_ids: list[str] = field(default_factory=list)
    matched_entities: list[str] = field(default_factory=list)
    accumulated_severity: str = "routine"


# {str(rule_id): _CorrelationWindow}
_correlation_windows: dict[str, _CorrelationWindow] = {}
_correlation_lock = asyncio.Lock()


async def _cleanup_stale_windows() -> None:
    """Remove expired correlation windows."""
    now = datetime.now(timezone.utc)
    async with _correlation_lock:
        stale = [rid for rid, w in _correlation_windows.items() if w.window_expires_at < now]
        for rid in stale:
            logger.debug("Correlation window expired for rule %s", rid)
            del _correlation_windows[rid]


# ---------------------------------------------------------------------------
# Keyword matching helpers
# ---------------------------------------------------------------------------

def _matches_keywords(content: str, keywords: list[str], mode: str) -> bool:
    """Check if content matches the keyword rule."""
    if not keywords or not content:
        return False
    low = content.lower()
    if mode == "regex":
        pattern = keywords[0] if len(keywords) == 1 else "|".join(keywords)
        try:
            return bool(re.search(pattern, content, re.IGNORECASE))
        except re.error:
            return False
    elif mode == "all":
        return all(kw.lower() in low for kw in keywords)
    else:  # 'any' (default)
        return any(kw.lower() in low for kw in keywords)


def _post_matches_source(post_data: dict, source_types: Optional[list[str]]) -> bool:
    if not source_types:
        return True
    return post_data.get("source_type") in source_types


# ---------------------------------------------------------------------------
# Cooldown check
# ---------------------------------------------------------------------------

def _within_cooldown(rule: AlertRule) -> bool:
    """Return True if rule is still in cooldown (should NOT fire)."""
    if not rule.last_fired_at:
        return False
    cooldown = timedelta(minutes=rule.cooldown_minutes)
    return datetime.now(timezone.utc) - rule.last_fired_at < cooldown


# ---------------------------------------------------------------------------
# Alert event creation + notification delivery
# ---------------------------------------------------------------------------

async def _create_and_deliver(
    db: AsyncSession,
    rule: AlertRule,
    severity: str,
    title: str,
    summary: str,
    matched_post_ids: Optional[list[str]] = None,
    matched_entities: Optional[list[str]] = None,
    context: Optional[dict[str, Any]] = None,
) -> None:
    """Persist an AlertEvent and deliver notifications."""
    post_uuids = [uuid.UUID(pid) for pid in (matched_post_ids or []) if pid]

    event = AlertEvent(
        id=uuid.uuid4(),
        rule_id=rule.id,
        user_id=rule.user_id,
        severity=severity,
        title=title,
        summary=summary,
        matched_post_ids=post_uuids or None,
        matched_entities=matched_entities or None,
        context=context,
    )
    db.add(event)

    # Update last_fired_at on rule
    rule.last_fired_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(event)

    logger.info(
        "Alert fired: rule=%s severity=%s title=%s", rule.name, severity, title
    )

    # Deliver notifications (fire-and-forget, don't fail if delivery fails)
    asyncio.create_task(_deliver_alert(event, rule))


async def _deliver_alert(event: AlertEvent, rule: AlertRule) -> None:
    """Deliver alert via configured channels."""
    channels = rule.delivery_channels or ["in_app"]

    if "in_app" in channels:
        await _deliver_in_app(event, rule)

    if "telegram" in channels and rule.telegram_chat_id:
        await _deliver_telegram(event, rule)

    if "webhook" in channels and rule.webhook_url:
        await _deliver_webhook(event, rule)


async def _deliver_in_app(event: AlertEvent, rule: AlertRule) -> None:
    """Broadcast alert via WebSocket to subscribed clients."""
    try:
        from app.routers.feed import _ws_subscribers

        payload = {
            "type": "alert",
            "alert": {
                "id": str(event.id),
                "rule_id": str(event.rule_id),
                "rule_name": rule.name,
                "severity": event.severity,
                "title": event.title,
                "summary": event.summary,
                "fired_at": event.fired_at.isoformat() if event.fired_at else None,
                "matched_entities": event.matched_entities,
            },
        }
        dead = set()
        for q in _ws_subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.add(q)
        _ws_subscribers.difference_update(dead)
    except Exception:
        logger.exception("Failed to deliver in-app alert for event %s", event.id)


async def _deliver_telegram(event: AlertEvent, rule: AlertRule) -> None:
    """Send alert via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set; skipping Telegram delivery")
        return

    emoji = SEVERITY_EMOJI.get(event.severity, "🔔")
    text_parts = [
        f"{emoji} <b>ORTHANC ALERT</b>",
        f"<b>{event.title}</b>",
    ]
    if event.summary:
        text_parts.append(event.summary)
    text_parts.append(f"\n<i>Rule: {rule.name} | Severity: {event.severity.upper()}</i>")

    message_text = "\n".join(text_parts)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": rule.telegram_chat_id,
                    "text": message_text,
                    "parse_mode": "HTML",
                },
            )
            if resp.status_code != 200:
                logger.warning(
                    "Telegram delivery failed for rule %s: %s", rule.name, resp.text
                )
    except Exception:
        logger.exception("Failed to deliver Telegram alert for rule %s", rule.name)


async def _deliver_webhook(event: AlertEvent, rule: AlertRule) -> None:
    """POST alert payload to configured webhook URL."""
    payload = {
        "event": "alert_fired",
        "rule": {
            "id": str(rule.id),
            "name": rule.name,
            "type": rule.rule_type,
        },
        "alert": {
            "id": str(event.id),
            "severity": event.severity,
            "title": event.title,
            "summary": event.summary,
            "fired_at": event.fired_at.isoformat() if event.fired_at else None,
            "matched_entities": event.matched_entities,
            "matched_post_ids": [str(pid) for pid in (event.matched_post_ids or [])],
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(rule.webhook_url, json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "Webhook delivery failed for rule %s: %d", rule.name, resp.status_code
                )
    except Exception:
        logger.exception("Failed to deliver webhook alert for rule %s", rule.name)


# ---------------------------------------------------------------------------
# Level 1: Post evaluation (keyword + correlation stage matching)
# ---------------------------------------------------------------------------

async def evaluate_post(post_data: dict, db: AsyncSession) -> None:
    """Called on every new post. Evaluates keyword rules and correlation stage matches."""
    try:
        await _cleanup_stale_windows()
        rules = await _get_cached_rules(db)

        content = post_data.get("content") or ""
        post_id = post_data.get("id")

        for rule in rules:
            try:
                if rule.rule_type == "keyword":
                    await _eval_keyword_rule(rule, post_data, content, post_id, db)
                elif rule.rule_type == "correlation":
                    await _eval_correlation_rule_post(rule, post_data, content, post_id, db)
                elif rule.rule_type == "geo_proximity":
                    await _eval_geo_proximity_rule(rule, post_data, post_id, db)
            except Exception:
                logger.exception(
                    "Error evaluating rule %s (type=%s) on post", rule.name, rule.rule_type
                )
    except Exception:
        logger.exception("Error in evaluate_post")


async def _eval_keyword_rule(
    rule: AlertRule,
    post_data: dict,
    content: str,
    post_id: Optional[str],
    db: AsyncSession,
) -> None:
    if _within_cooldown(rule):
        return
    if not rule.keywords:
        return
    if not _post_matches_source(post_data, rule.source_types):
        return
    if _matches_keywords(content, rule.keywords, rule.keyword_mode or "any"):
        kw_preview = ", ".join(rule.keywords[:3])
        await _create_and_deliver(
            db,
            rule,
            rule.severity,
            f"Keyword alert: {rule.name}",
            f"Post matched keywords [{kw_preview}]: {content[:200]}",
            matched_post_ids=[post_id] if post_id else None,
        )


async def _eval_geo_proximity_rule(
    rule: AlertRule,
    post_data: dict,
    post_id: Optional[str],
    db: AsyncSession,
) -> None:
    """Evaluate a geo_proximity rule against a new post that has geo data."""
    if _within_cooldown(rule):
        return

    # Rule must have a configured center
    if rule.geo_lat is None or rule.geo_lng is None or not rule.geo_radius_km:
        return

    # Extract event coordinates from post_data.
    # We support several common structures:
    #   post_data["event"]["lat"] / post_data["event"]["lng"]
    #   post_data["lat"] / post_data["lng"]
    #   post_data["location"]["lat"] / post_data["location"]["lng"]
    event_lat: Optional[float] = None
    event_lng: Optional[float] = None

    for key in ("event", "location"):
        sub = post_data.get(key)
        if isinstance(sub, dict):
            lat = sub.get("lat") or sub.get("latitude")
            lng = sub.get("lng") or sub.get("longitude") or sub.get("lon")
            if lat is not None and lng is not None:
                event_lat, event_lng = float(lat), float(lng)
                break

    if event_lat is None:
        # Try top-level
        lat = post_data.get("lat") or post_data.get("latitude")
        lng = post_data.get("lng") or post_data.get("longitude") or post_data.get("lon")
        if lat is not None and lng is not None:
            event_lat, event_lng = float(lat), float(lng)

    if event_lat is None or event_lng is None:
        return  # Post has no geo data

    dist_km = haversine_km(rule.geo_lat, rule.geo_lng, event_lat, event_lng)

    if dist_km <= rule.geo_radius_km:
        label = rule.geo_label or f"{rule.geo_lat:.2f},{rule.geo_lng:.2f}"
        content = post_data.get("content") or ""
        await _create_and_deliver(
            db,
            rule,
            rule.severity,
            f"Geo-proximity alert: {label}",
            (
                f"Event detected {dist_km:.1f} km from {label} "
                f"(within {rule.geo_radius_km:.0f} km radius). "
                f"{content[:200]}"
            ),
            matched_post_ids=[post_id] if post_id else None,
            context={
                "event_lat": event_lat,
                "event_lng": event_lng,
                "center_lat": rule.geo_lat,
                "center_lng": rule.geo_lng,
                "distance_km": round(dist_km, 2),
                "radius_km": rule.geo_radius_km,
            },
        )


async def _eval_correlation_rule_post(
    rule: AlertRule,
    post_data: dict,
    content: str,
    post_id: Optional[str],
    db: AsyncSession,
) -> None:
    """Evaluate a multi-stage correlation rule against a new post."""
    if not rule.directives:
        return

    stages = rule.directives.get("stages", [])
    if not stages:
        return

    rid = str(rule.id)

    async with _correlation_lock:
        window = _correlation_windows.get(rid)

    if window is None:
        # No open window — check if Stage 1 matches
        stage1 = next((s for s in stages if s.get("stage") == 1), None)
        if stage1 and _stage_matches_post(stage1, post_data, content):
            # Open a correlation window
            time_window = stage1.get("time_window_minutes", 60)
            now = datetime.now(timezone.utc)
            new_window = _CorrelationWindow(
                rule_id=rule.id,
                user_id=rule.user_id,
                current_stage=2,
                started_at=now,
                window_expires_at=now + timedelta(minutes=time_window),
                matched_post_ids=[post_id] if post_id else [],
                accumulated_severity=stage1.get("severity", rule.severity),
            )
            async with _correlation_lock:
                _correlation_windows[rid] = new_window
            logger.info(
                "Correlation stage 1 matched for rule '%s' — window open for %d min",
                rule.name,
                time_window,
            )
    else:
        # Window is open — check current stage
        if datetime.now(timezone.utc) > window.window_expires_at:
            async with _correlation_lock:
                _correlation_windows.pop(rid, None)
            return

        current_stage_def = next(
            (s for s in stages if s.get("stage") == window.current_stage), None
        )
        if not current_stage_def:
            return

        if _stage_matches_post(current_stage_def, post_data, content):
            if post_id:
                window.matched_post_ids.append(post_id)
            stage_severity = current_stage_def.get("severity", rule.severity)
            # Escalate severity
            severity_rank = {"routine": 0, "urgent": 1, "flash": 2}
            if severity_rank.get(stage_severity, 0) > severity_rank.get(
                window.accumulated_severity, 0
            ):
                window.accumulated_severity = stage_severity

            next_stage_num = window.current_stage + 1
            next_stage_def = next(
                (s for s in stages if s.get("stage") == next_stage_num), None
            )

            if next_stage_def:
                # Advance window to next stage
                time_window = next_stage_def.get("time_window_minutes", 60)
                now = datetime.now(timezone.utc)
                window.current_stage = next_stage_num
                window.window_expires_at = now + timedelta(minutes=time_window)
                logger.info(
                    "Correlation stage %d matched for rule '%s' — advancing to stage %d",
                    window.current_stage - 1,
                    rule.name,
                    window.current_stage,
                )
            else:
                # All stages matched — fire alert
                async with _correlation_lock:
                    _correlation_windows.pop(rid, None)

                if not _within_cooldown(rule):
                    await _create_and_deliver(
                        db,
                        rule,
                        window.accumulated_severity,
                        f"Correlation alert: {rule.name}",
                        f"Multi-stage correlation rule matched ({len(stages)} stages)",
                        matched_post_ids=window.matched_post_ids,
                        matched_entities=window.matched_entities,
                        context={"stages_matched": len(stages)},
                    )


def _stage_matches_post(stage_def: dict, post_data: dict, content: str) -> bool:
    """Check if a correlation stage condition matches a post."""
    condition = stage_def.get("condition", {})
    ctype = condition.get("type")

    if ctype == "keyword_match":
        keywords = condition.get("keywords", [])
        mode = condition.get("mode", "any")
        return _matches_keywords(content, keywords, mode)

    elif ctype == "source_count":
        # Can't evaluate source_count on a single post; handled periodically
        return False

    elif ctype == "entity_velocity":
        # Can't evaluate velocity on a single post; handled periodically
        # But we can check if any of the entities are mentioned
        entities = condition.get("entities", [])
        if entities:
            low = content.lower()
            return any(e.lower() in low for e in entities)
        return False

    elif ctype == "geo_proximity":
        # Evaluate geo proximity as a stage condition
        center_lat = condition.get("lat")
        center_lng = condition.get("lng")
        radius_km = condition.get("radius_km")
        if center_lat is None or center_lng is None or not radius_km:
            return False

        event_lat: Optional[float] = None
        event_lng: Optional[float] = None
        for key in ("event", "location"):
            sub = post_data.get(key)
            if isinstance(sub, dict):
                lat = sub.get("lat") or sub.get("latitude")
                lng = sub.get("lng") or sub.get("longitude") or sub.get("lon")
                if lat is not None and lng is not None:
                    event_lat, event_lng = float(lat), float(lng)
                    break
        if event_lat is None:
            lat = post_data.get("lat") or post_data.get("latitude")
            lng = post_data.get("lng") or post_data.get("longitude") or post_data.get("lon")
            if lat is not None and lng is not None:
                event_lat, event_lng = float(lat), float(lng)

        if event_lat is None or event_lng is None:
            return False

        dist_km = haversine_km(float(center_lat), float(center_lng), event_lat, event_lng)
        return dist_km <= float(radius_km)

    return False


# ---------------------------------------------------------------------------
# Level 2: Velocity evaluation (run every 60s)
# ---------------------------------------------------------------------------

async def evaluate_velocity_rules(db: AsyncSession) -> None:
    """Run every 60 seconds. Checks entity mention rates for velocity rules."""
    try:
        rules = await _get_cached_rules(db)
        velocity_rules = [r for r in rules if r.rule_type == "velocity"]

        if not velocity_rules:
            return

        for rule in velocity_rules:
            try:
                await _eval_velocity_rule(rule, db)
            except Exception:
                logger.exception("Error evaluating velocity rule %s", rule.name)

        # Also check correlation rules for entity_velocity stages
        correlation_rules = [r for r in rules if r.rule_type == "correlation"]
        for rule in correlation_rules:
            try:
                await _eval_correlation_velocity_stages(rule, db)
            except Exception:
                logger.exception(
                    "Error evaluating correlation velocity stages for rule %s", rule.name
                )
    except Exception:
        logger.exception("Error in evaluate_velocity_rules")


async def _eval_velocity_rule(rule: AlertRule, db: AsyncSession) -> None:
    if _within_cooldown(rule):
        return
    if not rule.entity_name or not rule.velocity_threshold or not rule.velocity_window_minutes:
        return

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=rule.velocity_window_minutes)
    baseline_start = now - timedelta(days=7)
    baseline_end = window_start

    # Count in window
    result_window = await db.execute(
        select(func.count(EntityMention.id))
        .join(Entity, EntityMention.entity_id == Entity.id)
        .where(
            Entity.name.ilike(rule.entity_name),
            EntityMention.extracted_at >= window_start,
        )
    )
    count_window = result_window.scalar_one_or_none() or 0

    # Historical baseline per equal window
    result_baseline = await db.execute(
        select(func.count(EntityMention.id))
        .join(Entity, EntityMention.entity_id == Entity.id)
        .where(
            Entity.name.ilike(rule.entity_name),
            EntityMention.extracted_at >= baseline_start,
            EntityMention.extracted_at < baseline_end,
        )
    )
    count_baseline_total = result_baseline.scalar_one_or_none() or 0

    # How many windows fit in 7 days?
    num_baseline_windows = (7 * 24 * 60) / rule.velocity_window_minutes
    baseline_per_window = count_baseline_total / max(num_baseline_windows, 1)
    spike_ratio = count_window / max(baseline_per_window, 0.5)

    if spike_ratio >= rule.velocity_threshold and count_window >= 2:
        await _create_and_deliver(
            db,
            rule,
            rule.severity,
            f"Velocity alert: {rule.entity_name}",
            (
                f"'{rule.entity_name}' mentioned {count_window} times in last "
                f"{rule.velocity_window_minutes} min "
                f"({spike_ratio:.1f}x above baseline of {baseline_per_window:.1f})"
            ),
            matched_entities=[rule.entity_name],
        )


async def _eval_correlation_velocity_stages(rule: AlertRule, db: AsyncSession) -> None:
    """Evaluate entity_velocity condition in correlation stages periodically."""
    if not rule.directives:
        return

    stages = rule.directives.get("stages", [])
    rid = str(rule.id)

    async with _correlation_lock:
        window = _correlation_windows.get(rid)

    if window is None:
        # Check Stage 1 for velocity conditions
        stage1 = next((s for s in stages if s.get("stage") == 1), None)
        if stage1 and stage1.get("condition", {}).get("type") == "entity_velocity":
            matched, entities = await _check_velocity_condition(stage1["condition"], db)
            if matched:
                time_window = stage1.get("time_window_minutes", 60)
                now = datetime.now(timezone.utc)
                new_window = _CorrelationWindow(
                    rule_id=rule.id,
                    user_id=rule.user_id,
                    current_stage=2,
                    started_at=now,
                    window_expires_at=now + timedelta(minutes=time_window),
                    matched_entities=entities,
                    accumulated_severity=stage1.get("severity", rule.severity),
                )
                async with _correlation_lock:
                    _correlation_windows[rid] = new_window
                logger.info(
                    "Correlation Stage 1 (velocity) matched for rule '%s'", rule.name
                )
    else:
        # Check current stage
        if datetime.now(timezone.utc) > window.window_expires_at:
            async with _correlation_lock:
                _correlation_windows.pop(rid, None)
            return

        current_stage_def = next(
            (s for s in stages if s.get("stage") == window.current_stage), None
        )
        if not current_stage_def:
            return

        condition = current_stage_def.get("condition", {})
        if condition.get("type") != "entity_velocity":
            return  # Will be handled by post evaluation

        matched, entities = await _check_velocity_condition(condition, db)
        if matched:
            window.matched_entities.extend(e for e in entities if e not in window.matched_entities)
            stage_severity = current_stage_def.get("severity", rule.severity)
            severity_rank = {"routine": 0, "urgent": 1, "flash": 2}
            if severity_rank.get(stage_severity, 0) > severity_rank.get(
                window.accumulated_severity, 0
            ):
                window.accumulated_severity = stage_severity

            next_stage_num = window.current_stage + 1
            next_stage_def = next(
                (s for s in stages if s.get("stage") == next_stage_num), None
            )
            if next_stage_def:
                time_window = next_stage_def.get("time_window_minutes", 60)
                now = datetime.now(timezone.utc)
                window.current_stage = next_stage_num
                window.window_expires_at = now + timedelta(minutes=time_window)
            else:
                async with _correlation_lock:
                    _correlation_windows.pop(rid, None)

                if not _within_cooldown(rule):
                    async with AsyncSessionLocal() as fresh_db:
                        result = await fresh_db.execute(
                            select(AlertRule).where(AlertRule.id == rule.id)
                        )
                        fresh_rule = result.scalar_one_or_none()
                        if fresh_rule and not _within_cooldown(fresh_rule):
                            await _create_and_deliver(
                                fresh_db,
                                fresh_rule,
                                window.accumulated_severity,
                                f"Correlation alert: {fresh_rule.name}",
                                f"Multi-stage correlation rule matched ({len(stages)} stages)",
                                matched_entities=window.matched_entities,
                                context={"stages_matched": len(stages)},
                            )


async def evaluate_silence_rules(db: AsyncSession) -> None:
    """Run every 5 minutes. Check if expected entities/sources have gone quiet."""
    try:
        rules = await _get_cached_rules(db)
        silence_rules = [r for r in rules if r.rule_type == "silence"]

        if not silence_rules:
            return

        for rule in silence_rules:
            try:
                await _eval_silence_rule(rule, db)
            except Exception:
                logger.exception("Error evaluating silence rule %s", rule.name)
    except Exception:
        logger.exception("Error in evaluate_silence_rules")


async def _eval_silence_rule(rule: AlertRule, db: AsyncSession) -> None:
    """Check whether an entity or source_type has gone silent."""
    if _within_cooldown(rule):
        return

    if not rule.silence_expected_interval_minutes:
        return
    if not rule.silence_entity and not rule.silence_source_type:
        return

    from app.models.post import Post

    now = datetime.now(timezone.utc)
    expected_interval = timedelta(minutes=rule.silence_expected_interval_minutes)
    silence_cutoff = now - expected_interval

    # Find the most recent post matching the entity or source_type
    last_seen_dt: Optional[datetime] = None

    if rule.silence_entity:
        # Query most recent EntityMention for the entity
        result = await db.execute(
            select(EntityMention.extracted_at)
            .join(Entity, EntityMention.entity_id == Entity.id)
            .where(Entity.name.ilike(rule.silence_entity))
            .order_by(EntityMention.extracted_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            last_seen_dt = row if row.tzinfo else row.replace(tzinfo=timezone.utc)

    elif rule.silence_source_type:
        # Query most recent post for this source_type
        result = await db.execute(
            select(Post.ingested_at)
            .where(Post.source_type == rule.silence_source_type)
            .order_by(Post.ingested_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            last_seen_dt = row if row.tzinfo else row.replace(tzinfo=timezone.utc)

    # Update silence_last_seen if we found a newer timestamp
    if last_seen_dt is not None:
        if rule.silence_last_seen is None or last_seen_dt > rule.silence_last_seen:
            rule.silence_last_seen = last_seen_dt
            await db.commit()

    # Determine effective last-seen (use silence_last_seen if available)
    effective_last_seen = rule.silence_last_seen or last_seen_dt

    # If we've never seen this entity/source at all, that itself is silence — but
    # only fire if the rule has been around longer than one interval to avoid
    # false positives on brand-new rules.
    if effective_last_seen is None:
        rule_age = now - (rule.created_at if rule.created_at.tzinfo else rule.created_at.replace(tzinfo=timezone.utc))
        if rule_age < expected_interval:
            return  # Too new — don't fire yet
        # Never seen — fire
        entity_label = rule.silence_entity or rule.silence_source_type or "unknown"
        hours = rule.silence_expected_interval_minutes / 60
        await _create_and_deliver(
            db,
            rule,
            rule.severity,
            f"Silence alert: {entity_label}",
            f"No activity detected for '{entity_label}' — expected every {hours:.1f}h but never seen.",
            matched_entities=[rule.silence_entity] if rule.silence_entity else None,
        )
        return

    # Check if last seen is older than the expected interval
    if effective_last_seen < silence_cutoff:
        entity_label = rule.silence_entity or rule.silence_source_type or "unknown"
        elapsed_minutes = int((now - effective_last_seen).total_seconds() / 60)
        hours_elapsed = elapsed_minutes / 60
        hours_expected = rule.silence_expected_interval_minutes / 60
        await _create_and_deliver(
            db,
            rule,
            rule.severity,
            f"Silence alert: {entity_label}",
            (
                f"No activity detected for '{entity_label}' in {hours_elapsed:.1f}h "
                f"(expected at least every {hours_expected:.1f}h). "
                f"Last seen: {effective_last_seen.strftime('%Y-%m-%d %H:%M UTC')}"
            ),
            matched_entities=[rule.silence_entity] if rule.silence_entity else None,
            context={
                "last_seen": effective_last_seen.isoformat(),
                "elapsed_minutes": elapsed_minutes,
                "expected_interval_minutes": rule.silence_expected_interval_minutes,
            },
        )


async def _check_velocity_condition(condition: dict, db: AsyncSession) -> tuple[bool, list[str]]:
    """Check entity_velocity condition. Returns (matched, matched_entity_names)."""
    entities = condition.get("entities", [])
    threshold = condition.get("threshold", 2.0)
    window_minutes = condition.get("window_minutes", 60)

    matched_entities = []

    for entity_name in entities:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=window_minutes)
        baseline_start = now - timedelta(days=7)

        result_w = await db.execute(
            select(func.count(EntityMention.id))
            .join(Entity, EntityMention.entity_id == Entity.id)
            .where(
                Entity.name.ilike(entity_name),
                EntityMention.extracted_at >= window_start,
            )
        )
        count_w = result_w.scalar_one_or_none() or 0

        result_b = await db.execute(
            select(func.count(EntityMention.id))
            .join(Entity, EntityMention.entity_id == Entity.id)
            .where(
                Entity.name.ilike(entity_name),
                EntityMention.extracted_at >= baseline_start,
                EntityMention.extracted_at < window_start,
            )
        )
        count_b_total = result_b.scalar_one_or_none() or 0
        num_windows = (7 * 24 * 60) / max(window_minutes, 1)
        baseline_per_window = count_b_total / max(num_windows, 1)
        spike_ratio = count_w / max(baseline_per_window, 0.5)

        if spike_ratio >= threshold and count_w >= 2:
            matched_entities.append(entity_name)

    return len(matched_entities) > 0, matched_entities


# ---------------------------------------------------------------------------
# Test/dry-run a rule
# ---------------------------------------------------------------------------

async def dry_run_rule(rule: AlertRule, db: AsyncSession) -> dict[str, Any]:
    """Dry-run a rule against the last 1 hour of data."""
    from app.models.post import Post
    from datetime import timedelta

    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    result = await db.execute(
        select(Post)
        .where(Post.ingested_at >= one_hour_ago)
        .order_by(Post.ingested_at.desc())
        .limit(200)
    )
    posts = result.scalars().all()

    matched = []
    for post in posts:
        content = post.content or ""
        if rule.rule_type == "keyword" and rule.keywords:
            if _post_matches_source(
                {"source_type": post.source_type}, rule.source_types
            ) and _matches_keywords(content, rule.keywords, rule.keyword_mode or "any"):
                matched.append(
                    {"post_id": str(post.id), "content_preview": content[:200]}
                )
        elif rule.rule_type == "velocity":
            # Can't test velocity with individual posts
            pass
        elif rule.rule_type == "geo_proximity":
            if rule.geo_lat is not None and rule.geo_lng is not None and rule.geo_radius_km:
                for field_name in ("event", "location"):
                    sub = {"source_type": post.source_type}
                    _ = sub  # no geo on posts in dry run normally
                # Report config info
                matched.append({
                    "note": f"Geo-proximity: center ({rule.geo_lat}, {rule.geo_lng}), radius {rule.geo_radius_km} km",
                })
        elif rule.rule_type == "silence":
            matched.append({
                "note": f"Silence rule: monitors '{rule.silence_entity or rule.silence_source_type}' every {rule.silence_expected_interval_minutes} min",
            })
        elif rule.rule_type == "correlation":
            stages = (rule.directives or {}).get("stages", [])
            stage1 = next((s for s in stages if s.get("stage") == 1), None)
            if stage1 and _stage_matches_post(stage1, {"source_type": post.source_type}, content):
                matched.append(
                    {"post_id": str(post.id), "content_preview": content[:200], "stage": 1}
                )

    return {
        "rule_id": str(rule.id),
        "rule_type": rule.rule_type,
        "posts_checked": len(posts),
        "matches": matched[:20],
        "match_count": len(matched),
    }


# Singleton-like module-level interface
__all__ = [
    "evaluate_post",
    "evaluate_velocity_rules",
    "evaluate_silence_rules",
    "dry_run_rule",
    "invalidate_rule_cache",
]
