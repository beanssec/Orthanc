"""
Digest Generator — Sprint 31, Checkpoint 3.

Provides scheduled-delivery-ready digest generation for two distinct signals:

  1. TrackerDigest   — summarises active narrative trackers and their recent
                       matched narratives, annotated with confidence signals.
  2. AlertDigest     — summarises recent AlertEvent firings grouped by severity,
                       surfacing the highest-priority events first.

Both generators return structured dicts that are JSON-serialisable and suitable
for delivery via scheduled_delivery.deliver_telegram / deliver_webhook.

Design principles
-----------------
- Additive & safe: no existing models or services are modified.
- Confidence-aware: where Narrative.evidence_score / divergence_score /
  label_confidence / confirmation_status are available they inform the
  phrasing so a recipient can gauge signal quality at a glance.
- Reusable: top-level async functions that the brief_scheduler (or any future
  cron runner) can call directly.
- Graceful degradation: DB or import errors return structured "empty" dicts
  rather than raising.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("orthanc.digest_generator")

# ---------------------------------------------------------------------------
# Confidence annotation helpers
# ---------------------------------------------------------------------------

_EVIDENCE_HIGH = 0.65
_EVIDENCE_LOW  = 0.35
_DIVERG_HIGH   = 0.60  # high divergence → contested narrative

# Narrative confirmation status → human label
_CONFIRMATION_LABELS: dict[str, str] = {
    "confirmed":   "confirmed",
    "denied":      "denied",
    "contested":   "contested",
    "unverified":  "unverified",
    "emerging":    "emerging",
}


def _narrative_confidence_note(narrative) -> str:
    """Return a short confidence annotation for a single Narrative ORM object."""
    parts: list[str] = []

    evidence = getattr(narrative, "evidence_score", None)
    divergence = getattr(narrative, "divergence_score", None)
    label_conf = getattr(narrative, "label_confidence", None)
    confirmation = getattr(narrative, "confirmation_status", None)

    # Evidence quality
    if evidence is not None:
        if evidence >= _EVIDENCE_HIGH:
            parts.append("strong evidence")
        elif evidence <= _EVIDENCE_LOW:
            parts.append("thin evidence")
        # else medium — no annotation

    # Divergence
    if divergence is not None and divergence >= _DIVERG_HIGH:
        parts.append("contested reporting")

    # Label confidence (from clustering / LLM tagging)
    if label_conf is not None:
        if label_conf < 0.50:
            parts.append(f"low label confidence ({label_conf:.0%})")

    # Confirmation status
    if confirmation:
        status_label = _CONFIRMATION_LABELS.get(confirmation, confirmation)
        if status_label not in ("unverified",):
            parts.append(status_label)

    return ", ".join(parts) if parts else "unverified"


def _format_narrative_line(narrative, match_score: float | None = None) -> str:
    """One-line digest entry for a narrative."""
    title = getattr(narrative, "canonical_title", None) or getattr(narrative, "title", "Untitled")
    post_count = getattr(narrative, "post_count", 0)
    source_count = getattr(narrative, "source_count", 0)
    note = _narrative_confidence_note(narrative)
    score_str = f"  match={match_score:.2f}" if match_score is not None else ""

    return (
        f"• {title} "
        f"[{post_count}p/{source_count}s | {note}]"
        f"{score_str}"
    )


# ---------------------------------------------------------------------------
# Tracker Digest
# ---------------------------------------------------------------------------


async def generate_tracker_digest(
    user_id: str,
    *,
    hours: int = 24,
    max_trackers: int = 10,
    max_narratives_per_tracker: int = 5,
) -> dict[str, Any]:
    """Generate a digest of active narrative trackers for a user.

    Queries the DB for active NarrativeTracker rows owned by the user, then
    fetches recent NarrativeTrackerMatch rows (within ``hours``) and the
    underlying Narrative details.

    Args:
        user_id:                    UUID string of the owning user.
        hours:                      Look-back window for matches.
        max_trackers:               Cap on trackers included.
        max_narratives_per_tracker: Cap on narrative lines per tracker.

    Returns:
        Structured dict:
        {
            "digest_type":    "tracker",
            "user_id":        str,
            "generated_at":   ISO-8601 str,
            "window_hours":   int,
            "tracker_count":  int,
            "trackers": [
                {
                    "tracker_id":       str,
                    "name":             str,
                    "objective":        str | None,
                    "narrative_count":  int,
                    "narratives": [
                        {
                            "narrative_id":   str,
                            "title":          str,
                            "post_count":     int,
                            "source_count":   int,
                            "match_score":    float | None,
                            "confidence_note": str,
                        }, ...
                    ],
                }, ...
            ],
            "text_summary":  str,   # human-readable for direct delivery
        }
    """
    generated_at = datetime.now(timezone.utc)
    cutoff = generated_at - timedelta(hours=hours)

    _empty = {
        "digest_type": "tracker",
        "user_id": user_id,
        "generated_at": generated_at.isoformat(),
        "window_hours": hours,
        "tracker_count": 0,
        "trackers": [],
        "text_summary": f"No active tracker data found for the past {hours}h.",
    }

    try:
        from sqlalchemy import select
        from app.db import AsyncSessionLocal
        from app.models.narrative import (
            Narrative,
            NarrativeTracker,
            NarrativeTrackerMatch,
        )

        try:
            owner_uuid = uuid.UUID(str(user_id))
        except (ValueError, AttributeError):
            logger.warning("generate_tracker_digest: invalid user_id=%r", user_id)
            return _empty

        async with AsyncSessionLocal() as db:
            # Fetch active trackers for this user
            tracker_rows = (
                await db.execute(
                    select(NarrativeTracker)
                    .where(
                        NarrativeTracker.owner_user_id == owner_uuid,
                        NarrativeTracker.status == "active",
                    )
                    .limit(max_trackers)
                )
            ).scalars().all()

            if not tracker_rows:
                return _empty

            tracker_ids = [t.id for t in tracker_rows]

            # Fetch recent matches for those trackers
            match_rows = (
                await db.execute(
                    select(NarrativeTrackerMatch)
                    .where(
                        NarrativeTrackerMatch.tracker_id.in_(tracker_ids),
                        NarrativeTrackerMatch.matched_at >= cutoff,
                    )
                    .order_by(NarrativeTrackerMatch.match_score.desc())
                )
            ).scalars().all()

            # Group matches by tracker_id
            from collections import defaultdict
            matches_by_tracker: dict[uuid.UUID, list] = defaultdict(list)
            for m in match_rows:
                matches_by_tracker[m.tracker_id].append(m)

            # Fetch all relevant narratives in one query
            narrative_ids = list({m.narrative_id for m in match_rows})
            if narrative_ids:
                narrative_map: dict[uuid.UUID, Narrative] = {
                    n.id: n
                    for n in (
                        await db.execute(
                            select(Narrative).where(Narrative.id.in_(narrative_ids))
                        )
                    ).scalars().all()
                }
            else:
                narrative_map = {}

        # Build structured output
        trackers_out: list[dict] = []
        for tracker in tracker_rows:
            tracker_matches = matches_by_tracker.get(tracker.id, [])
            # Top N matches by match_score
            tracker_matches_top = sorted(
                tracker_matches, key=lambda m: m.match_score, reverse=True
            )[:max_narratives_per_tracker]

            narrative_lines: list[dict] = []
            for m in tracker_matches_top:
                nar = narrative_map.get(m.narrative_id)
                if nar is None:
                    continue
                narrative_lines.append(
                    {
                        "narrative_id": str(nar.id),
                        "title": (
                            getattr(nar, "canonical_title", None)
                            or getattr(nar, "title", "Untitled")
                        ),
                        "post_count": getattr(nar, "post_count", 0),
                        "source_count": getattr(nar, "source_count", 0),
                        "match_score": round(m.match_score, 4),
                        "confidence_note": _narrative_confidence_note(nar),
                    }
                )

            trackers_out.append(
                {
                    "tracker_id": str(tracker.id),
                    "name": tracker.name,
                    "objective": tracker.objective,
                    "narrative_count": len(narrative_lines),
                    "narratives": narrative_lines,
                }
            )

        text_summary = _build_tracker_text(trackers_out, hours, generated_at)

        return {
            "digest_type": "tracker",
            "user_id": user_id,
            "generated_at": generated_at.isoformat(),
            "window_hours": hours,
            "tracker_count": len(trackers_out),
            "trackers": trackers_out,
            "text_summary": text_summary,
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("generate_tracker_digest failed for user=%s: %s", user_id, exc)
        return _empty


def _build_tracker_text(trackers: list[dict], hours: int, ts: datetime) -> str:
    """Render the tracker digest as human-readable text (Telegram-ready)."""
    ts_str = ts.strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"🔭 <b>TRACKER DIGEST</b>  |  {ts_str}",
        f"<i>Active trackers with narrative activity in the past {hours}h</i>",
        "",
    ]
    if not trackers:
        lines.append("No active tracker data for this window.")
        return "\n".join(lines)

    for t in trackers:
        lines.append(f"<b>{t['name']}</b>")
        if t.get("objective"):
            lines.append(f"  <i>{t['objective'][:120]}</i>")
        if not t["narratives"]:
            lines.append("  No new narrative matches in window.")
        else:
            for n in t["narratives"]:
                score_str = f"  score={n['match_score']:.2f}" if n.get("match_score") else ""
                lines.append(
                    f"  • {n['title']} "
                    f"[{n['post_count']}p/{n['source_count']}s | {n['confidence_note']}]"
                    f"{score_str}"
                )
        lines.append("")

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Alert Digest
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {"flash": 0, "urgent": 1, "routine": 2}
_SEVERITY_EMOJI = {"flash": "🔴", "urgent": "🟠", "routine": "🟡"}


async def generate_alert_digest(
    user_id: str,
    *,
    hours: int = 24,
    max_events: int = 20,
) -> dict[str, Any]:
    """Generate a digest of recent AlertEvent firings for a user.

    Groups events by severity (flash → urgent → routine) and attaches the
    rule name and event summary so the recipient can triage quickly.

    Args:
        user_id:    UUID string of the owning user.
        hours:      Look-back window for alert events.
        max_events: Total cap on events returned (highest severity first).

    Returns:
        Structured dict:
        {
            "digest_type":   "alert",
            "user_id":       str,
            "generated_at":  ISO-8601 str,
            "window_hours":  int,
            "total_events":  int,
            "flash_count":   int,
            "urgent_count":  int,
            "routine_count": int,
            "events": [
                {
                    "event_id":   str,
                    "rule_id":    str,
                    "rule_name":  str | None,
                    "severity":   str,
                    "title":      str,
                    "summary":    str | None,
                    "fired_at":   ISO-8601 str,
                    "acknowledged": bool,
                }, ...
            ],
            "text_summary": str,
        }
    """
    generated_at = datetime.now(timezone.utc)
    cutoff = generated_at - timedelta(hours=hours)

    _empty: dict[str, Any] = {
        "digest_type": "alert",
        "user_id": user_id,
        "generated_at": generated_at.isoformat(),
        "window_hours": hours,
        "total_events": 0,
        "flash_count": 0,
        "urgent_count": 0,
        "routine_count": 0,
        "events": [],
        "text_summary": f"No alert events found in the past {hours}h.",
    }

    try:
        from sqlalchemy import select
        from app.db import AsyncSessionLocal
        from app.models.alert_rule import AlertEvent, AlertRule

        try:
            owner_uuid = uuid.UUID(str(user_id))
        except (ValueError, AttributeError):
            logger.warning("generate_alert_digest: invalid user_id=%r", user_id)
            return _empty

        async with AsyncSessionLocal() as db:
            # Fetch recent events for this user, ordered by severity then time
            event_rows = (
                await db.execute(
                    select(AlertEvent)
                    .where(
                        AlertEvent.user_id == owner_uuid,
                        AlertEvent.fired_at >= cutoff,
                    )
                    .order_by(AlertEvent.fired_at.desc())
                    .limit(max_events * 3)  # over-fetch; we'll re-sort below
                )
            ).scalars().all()

            if not event_rows:
                return _empty

            # Fetch associated rule names in one query
            rule_ids = list({e.rule_id for e in event_rows})
            rule_map: dict[uuid.UUID, str] = {}
            if rule_ids:
                rule_rows = (
                    await db.execute(
                        select(AlertRule.id, AlertRule.name).where(
                            AlertRule.id.in_(rule_ids)
                        )
                    )
                ).all()
                for rid, rname in rule_rows:
                    rule_map[rid] = rname

        # Sort: flash first, then urgent, then routine; newest within each tier
        sorted_events = sorted(
            event_rows,
            key=lambda e: (
                _SEVERITY_ORDER.get(e.severity, 99),
                -(e.fired_at.timestamp() if e.fired_at else 0),
            ),
        )[:max_events]

        events_out: list[dict] = []
        flash_count = urgent_count = routine_count = 0

        for ev in sorted_events:
            sev = ev.severity
            if sev == "flash":
                flash_count += 1
            elif sev == "urgent":
                urgent_count += 1
            else:
                routine_count += 1

            events_out.append(
                {
                    "event_id": str(ev.id),
                    "rule_id": str(ev.rule_id),
                    "rule_name": rule_map.get(ev.rule_id),
                    "severity": sev,
                    "title": ev.title,
                    "summary": ev.summary,
                    "fired_at": ev.fired_at.isoformat() if ev.fired_at else None,
                    "acknowledged": bool(ev.acknowledged),
                }
            )

        text_summary = _build_alert_text(
            events_out,
            flash_count,
            urgent_count,
            routine_count,
            hours,
            generated_at,
        )

        return {
            "digest_type": "alert",
            "user_id": user_id,
            "generated_at": generated_at.isoformat(),
            "window_hours": hours,
            "total_events": len(events_out),
            "flash_count": flash_count,
            "urgent_count": urgent_count,
            "routine_count": routine_count,
            "events": events_out,
            "text_summary": text_summary,
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("generate_alert_digest failed for user=%s: %s", user_id, exc)
        return _empty


def _build_alert_text(
    events: list[dict],
    flash_count: int,
    urgent_count: int,
    routine_count: int,
    hours: int,
    ts: datetime,
) -> str:
    """Render the alert digest as human-readable text (Telegram-ready)."""
    ts_str = ts.strftime("%Y-%m-%d %H:%M UTC")
    total = len(events)
    lines = [
        f"🚨 <b>ALERT DIGEST</b>  |  {ts_str}",
        f"<i>{total} events in the past {hours}h"
        f"  |  🔴 {flash_count} flash  🟠 {urgent_count} urgent  🟡 {routine_count} routine</i>",
        "",
    ]

    if not events:
        lines.append("No alert events in this window. ✓")
        return "\n".join(lines)

    current_sev: str | None = None
    for ev in events:
        sev = ev.get("severity", "routine")
        if sev != current_sev:
            current_sev = sev
            emoji = _SEVERITY_EMOJI.get(sev, "•")
            lines.append(f"{emoji} <b>{sev.upper()}</b>")

        title = ev.get("title", "Untitled event")
        rule_name = ev.get("rule_name") or "unknown rule"
        fired_str = ""
        if ev.get("fired_at"):
            try:
                fired_dt = datetime.fromisoformat(ev["fired_at"])
                fired_str = f"  {fired_dt.strftime('%H:%M')}"
            except ValueError:
                fired_str = ""

        ack_flag = "  ✓ ack" if ev.get("acknowledged") else ""
        summary_snippet = ""
        if ev.get("summary"):
            summary_snippet = f"\n    <i>{ev['summary'][:100]}</i>"

        lines.append(
            f"  • {title} [{rule_name}]{fired_str}{ack_flag}{summary_snippet}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Combined digest (convenience wrapper)
# ---------------------------------------------------------------------------


async def generate_combined_digest(
    user_id: str,
    *,
    hours: int = 24,
    include_trackers: bool = True,
    include_alerts: bool = True,
) -> dict[str, Any]:
    """Generate a combined tracker + alert digest for scheduled delivery.

    Returns a single structured dict with both sub-digests and a merged
    text_summary suitable for a single Telegram message.

    Args:
        user_id:          UUID string of the owning user.
        hours:            Shared look-back window for both digest types.
        include_trackers: Whether to include tracker data.
        include_alerts:   Whether to include alert data.

    Returns:
        {
            "digest_type":    "combined",
            "user_id":        str,
            "generated_at":   ISO-8601 str,
            "window_hours":   int,
            "tracker_digest": dict | None,
            "alert_digest":   dict | None,
            "text_summary":   str,
        }
    """
    import asyncio as _asyncio

    generated_at = datetime.now(timezone.utc)

    tracker_digest: dict | None = None
    alert_digest: dict | None = None

    tasks = []
    if include_trackers:
        tasks.append(generate_tracker_digest(user_id, hours=hours))
    else:
        tasks.append(_noop())

    if include_alerts:
        tasks.append(generate_alert_digest(user_id, hours=hours))
    else:
        tasks.append(_noop())

    results = await _asyncio.gather(*tasks, return_exceptions=True)

    if include_trackers and not isinstance(results[0], BaseException):
        tracker_digest = results[0]
    if include_alerts and not isinstance(results[1], BaseException):
        alert_digest = results[1]

    # Merge text sections
    sections: list[str] = []
    if tracker_digest and tracker_digest.get("tracker_count", 0) > 0:
        sections.append(tracker_digest.get("text_summary", ""))
    if alert_digest and alert_digest.get("total_events", 0) > 0:
        sections.append(alert_digest.get("text_summary", ""))

    if sections:
        text_summary = "\n\n".join(sections)
    else:
        text_summary = f"Nothing to report for the past {hours}h."

    return {
        "digest_type": "combined",
        "user_id": user_id,
        "generated_at": generated_at.isoformat(),
        "window_hours": hours,
        "tracker_digest": tracker_digest,
        "alert_digest": alert_digest,
        "text_summary": text_summary,
    }


async def _noop() -> None:
    return None
