"""
Scheduled Delivery Service — Sprint 31 Checkpoint 2.

Provides channel delivery primitives for scheduled outputs (briefs, digests, etc.).
Supports Telegram and webhook POST at minimum.

Design goals:
  - Returns structured DeliveryResult objects; never raises on channel failure.
  - Easy to call from brief_scheduler or any future scheduled runner.
  - Additive: does not modify existing alert delivery in correlation_engine.py.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger("orthanc.scheduled_delivery")

# ---------------------------------------------------------------------------
# Structured result type
# ---------------------------------------------------------------------------


@dataclass
class DeliveryResult:
    """Outcome of a single channel delivery attempt."""

    channel: str                    # e.g. "telegram", "webhook"
    success: bool
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status_code: int | None = None  # HTTP status if applicable
    error: str | None = None        # error message on failure
    detail: str | None = None       # optional extra context (truncated response, etc.)

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "success": self.success,
            "timestamp": self.timestamp.isoformat(),
            "status_code": self.status_code,
            "error": self.error,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# Low-level channel primitives
# ---------------------------------------------------------------------------


async def deliver_telegram(
    chat_id: str | int,
    text: str,
    *,
    bot_token: str | None = None,
    parse_mode: str = "HTML",
    timeout: float = 15.0,
) -> DeliveryResult:
    """Send a message to a Telegram chat via Bot API.

    Args:
        chat_id:    Telegram chat / user ID to deliver to.
        text:       Message text (HTML by default).
        bot_token:  Override token; falls back to TELEGRAM_BOT_TOKEN env var.
        parse_mode: Telegram parse mode ("HTML" or "Markdown").
        timeout:    HTTP request timeout in seconds.

    Returns:
        DeliveryResult with success/failure information.
    """
    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return DeliveryResult(
            channel="telegram",
            success=False,
            error="TELEGRAM_BOT_TOKEN not configured",
        )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)

        if resp.status_code == 200:
            logger.info("Telegram delivery OK → chat_id=%s", chat_id)
            return DeliveryResult(
                channel="telegram",
                success=True,
                status_code=resp.status_code,
            )
        else:
            body_snippet = resp.text[:300]
            logger.warning(
                "Telegram delivery failed → chat_id=%s status=%d body=%s",
                chat_id,
                resp.status_code,
                body_snippet,
            )
            return DeliveryResult(
                channel="telegram",
                success=False,
                status_code=resp.status_code,
                error=f"HTTP {resp.status_code}",
                detail=body_snippet,
            )

    except Exception as exc:  # noqa: BLE001
        logger.error("Telegram delivery exception → chat_id=%s: %s", chat_id, exc)
        return DeliveryResult(
            channel="telegram",
            success=False,
            error=str(exc),
        )


async def deliver_webhook(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> DeliveryResult:
    """POST a JSON payload to a webhook URL.

    Args:
        url:     Destination URL.
        payload: JSON-serialisable dict to POST.
        headers: Optional extra HTTP headers (e.g. Authorization).
        timeout: HTTP request timeout in seconds.

    Returns:
        DeliveryResult with success/failure information.
    """
    if not url:
        return DeliveryResult(
            channel="webhook",
            success=False,
            error="No webhook URL configured",
        )

    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=request_headers)

        if resp.status_code < 400:
            logger.info("Webhook delivery OK → url=%s status=%d", url, resp.status_code)
            return DeliveryResult(
                channel="webhook",
                success=True,
                status_code=resp.status_code,
            )
        else:
            body_snippet = resp.text[:300]
            logger.warning(
                "Webhook delivery failed → url=%s status=%d body=%s",
                url,
                resp.status_code,
                body_snippet,
            )
            return DeliveryResult(
                channel="webhook",
                success=False,
                status_code=resp.status_code,
                error=f"HTTP {resp.status_code}",
                detail=body_snippet,
            )

    except Exception as exc:  # noqa: BLE001
        logger.error("Webhook delivery exception → url=%s: %s", url, exc)
        return DeliveryResult(
            channel="webhook",
            success=False,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# High-level: deliver a scheduled brief to all configured channels
# ---------------------------------------------------------------------------


def _format_brief_telegram(brief: dict) -> str:
    """Render a brief dict as Telegram HTML text."""
    title = brief.get("title") or "Intelligence Brief"
    summary = brief.get("summary") or ""
    generated_at = brief.get("generated_at") or ""
    model = brief.get("model_name") or brief.get("model") or "AI"
    post_count = brief.get("post_count")

    lines = [
        "📋 <b>ORTHANC SCHEDULED BRIEF</b>",
        f"<b>{title}</b>",
        "",
        summary[:3000] if summary else "<i>(no summary)</i>",
    ]

    meta_parts = []
    if generated_at:
        meta_parts.append(f"Generated: {generated_at}")
    if post_count is not None:
        meta_parts.append(f"Posts analysed: {post_count}")
    if model:
        meta_parts.append(f"Model: {model}")

    if meta_parts:
        lines.append("")
        lines.append(f"<i>{' | '.join(meta_parts)}</i>")

    return "\n".join(lines)


async def deliver_brief(
    brief: dict,
    *,
    telegram_chat_id: str | int | None = None,
    telegram_bot_token: str | None = None,
    webhook_url: str | None = None,
    webhook_headers: dict[str, str] | None = None,
    user_id: str | None = None,
) -> list[DeliveryResult]:
    """Deliver a generated brief to all configured channels.

    This is the primary entry point for the brief scheduler to call after
    brief generation completes.

    Args:
        brief:              Dict from brief_generator.generate_brief() or Brief ORM fields.
        telegram_chat_id:   Telegram chat ID to deliver to (optional).
        telegram_bot_token: Override bot token (optional; falls back to env var).
        webhook_url:        Webhook URL to POST to (optional).
        webhook_headers:    Extra headers for webhook (e.g. auth token).
        user_id:            User ID for logging context.

    Returns:
        List of DeliveryResult — one per channel attempted.
        Empty list if no channels are configured.
    """
    results: list[DeliveryResult] = []
    label = f"user={user_id}" if user_id else "unknown user"

    if not telegram_chat_id and not webhook_url:
        logger.debug("deliver_brief: no channels configured for %s — nothing to send", label)
        return results

    # ── Telegram ─────────────────────────────────────────────────────────
    if telegram_chat_id:
        text = _format_brief_telegram(brief)
        result = await deliver_telegram(
            chat_id=telegram_chat_id,
            text=text,
            bot_token=telegram_bot_token,
        )
        results.append(result)
        if not result.success:
            logger.warning(
                "Brief Telegram delivery failed for %s: %s", label, result.error
            )

    # ── Webhook ───────────────────────────────────────────────────────────
    if webhook_url:
        webhook_payload: dict[str, Any] = {
            "event": "scheduled_brief",
            "user_id": user_id,
            "brief": {
                "id": brief.get("id"),
                "title": brief.get("title"),
                "summary": brief.get("summary"),
                "model": brief.get("model"),
                "model_name": brief.get("model_name"),
                "hours": brief.get("hours"),
                "post_count": brief.get("post_count"),
                "generated_at": brief.get("generated_at"),
                "confidence_score": brief.get("confidence_score"),
                "confidence_label": brief.get("confidence_label"),
            },
        }
        result = await deliver_webhook(
            url=webhook_url,
            payload=webhook_payload,
            headers=webhook_headers,
        )
        results.append(result)
        if not result.success:
            logger.warning(
                "Brief webhook delivery failed for %s: %s", label, result.error
            )

    # Summary log
    successes = sum(1 for r in results if r.success)
    logger.info(
        "Brief delivery complete for %s: %d/%d channels succeeded",
        label,
        successes,
        len(results),
    )
    return results
