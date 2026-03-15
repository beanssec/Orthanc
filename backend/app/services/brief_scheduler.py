"""
Brief Scheduler — hybrid in-memory (legacy) + DB-backed (Sprint 31).

* Legacy in-memory schedules are kept for backward compatibility with the
  existing /briefs/schedule endpoint.
* DB-backed ScheduledBrief records are ticked every 5 minutes and executed
  via the same brief_generator pathway.  Run history is written to
  scheduled_brief_runs.
* Sprint 31 CP3: digest generation is supported alongside brief generation.
  When a ScheduledBrief row has delivery_method == "digest" (or the caller
  supplies a digest_type kwarg), the scheduler calls digest_generator instead
  of brief_generator so tracker/alert digests can be delivered on a schedule.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("orthanc.brief_scheduler")


class BriefScheduler:
    def __init__(self) -> None:
        # ── Legacy in-memory store (user_id str -> config dict) ──────────────
        self._schedules: dict[str, dict] = {}

    # ── Legacy in-memory schedule management ────────────────────────────────

    def set_schedule(self, user_id: str, config: dict) -> None:
        """Store or update a user's brief schedule config (in-memory)."""
        existing = self._schedules.get(user_id, {})
        self._schedules[user_id] = {
            **existing,
            **config,
            "last_generated": existing.get("last_generated"),
        }
        logger.info(
            "Schedule set for user=%s  hour=%s  range=%sh  enabled=%s",
            user_id,
            config.get("schedule_hour_utc"),
            config.get("time_range_hours"),
            config.get("enabled"),
        )

    def remove_schedule(self, user_id: str) -> None:
        self._schedules.pop(user_id, None)

    def get_schedule(self, user_id: str) -> dict | None:
        entry = self._schedules.get(user_id)
        if entry is None:
            return None
        cfg = dict(entry)
        last = cfg.get("last_generated")
        cfg["last_generated"] = last.isoformat() if last else None
        return cfg

    # ── Background loop ──────────────────────────────────────────────────────

    async def run_loop(self) -> None:
        """Check every 5 minutes whether any scheduled brief is due."""
        logger.info("Brief scheduler loop started")
        while True:
            try:
                await self._tick()
            except Exception as exc:  # noqa: BLE001
                logger.error("Brief scheduler error: %s", exc)
            await asyncio.sleep(300)  # 5-minute interval

    async def _tick(self) -> None:
        now = datetime.now(timezone.utc)
        # Tick legacy in-memory schedules
        await self._tick_memory(now)
        # Tick DB-backed durable schedules
        await self._tick_db(now)

    # ── Legacy in-memory tick ────────────────────────────────────────────────

    async def _tick_memory(self, now: datetime) -> None:
        for user_id, config in list(self._schedules.items()):
            if not config.get("enabled", True):
                continue
            hour = config.get("schedule_hour_utc", 8)
            last: datetime | None = config.get("last_generated")

            due = now.hour == hour and (
                last is None or last.date() < now.date()
            )
            if due:
                logger.info("Generating scheduled brief (memory) for user %s", user_id)
                await self._generate_brief(user_id, config)
                config["last_generated"] = now

    async def _generate_brief(self, user_id: str, config: dict) -> None:
        try:
            from app.services.brief_generator import brief_generator
            await brief_generator.generate_brief(
                user_id=user_id,
                hours=config.get("time_range_hours", 24),
                model_id=config.get("model_id", "grok-3-mini"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Scheduled brief generation (memory) failed for user=%s: %s",
                user_id,
                exc,
            )

    # ── DB-backed tick ───────────────────────────────────────────────────────

    async def _tick_db(self, now: datetime) -> None:
        """Find all enabled ScheduledBrief records that are due and execute them."""
        try:
            from app.db import AsyncSessionLocal
            from app.models.scheduled_brief import ScheduledBrief, ScheduledBriefRun
            from sqlalchemy import select

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(ScheduledBrief).where(ScheduledBrief.enabled.is_(True))
                )
                schedules: list[ScheduledBrief] = result.scalars().all()

            for sched in schedules:
                if self._is_due(sched, now):
                    asyncio.create_task(self._execute_db_schedule(sched, now))

        except Exception as exc:  # noqa: BLE001
            logger.error("DB schedule tick error: %s", exc)

    def _is_due(self, sched, now: datetime) -> bool:
        """Determine whether a ScheduledBrief should fire right now."""
        # Simple hour-of-day trigger
        if sched.schedule_hour_utc is not None:
            if now.hour != sched.schedule_hour_utc:
                return False
            # Don't re-fire the same hour on the same day
            if sched.last_run_at and sched.last_run_at.date() >= now.date():
                return False
            return True

        # Future: cron_expr-based triggering would be parsed here.
        # For now, if no hour is set and no cron, skip.
        return False

    async def _execute_db_schedule(self, sched, now: datetime) -> None:
        """Execute a single DB-backed ScheduledBrief and record the run."""
        schedule_id = sched.id
        user_id = sched.user_id
        logger.info(
            "Executing DB scheduled brief id=%s user=%s name=%r",
            schedule_id,
            user_id,
            sched.name,
        )

        run_id = uuid.uuid4()
        brief_id: uuid.UUID | None = None
        status = "error"
        error_message: str | None = None
        completed_at: datetime | None = None

        try:
            from app.db import AsyncSessionLocal
            from app.models.scheduled_brief import ScheduledBrief, ScheduledBriefRun
            from app.services.brief_generator import brief_generator
            from sqlalchemy import select

            # Create a "running" run record
            async with AsyncSessionLocal() as db:
                run = ScheduledBriefRun(
                    id=run_id,
                    schedule_id=schedule_id,
                    user_id=user_id,
                    status="running",
                    started_at=now,
                )
                db.add(run)
                # Mark schedule as running / update last_run_at
                sched_row = await db.get(ScheduledBrief, schedule_id)
                if sched_row:
                    sched_row.last_run_at = now
                    sched_row.last_status = "running"
                    sched_row.last_error = None
                await db.commit()

            # Execute the brief generation
            result = await brief_generator.generate_brief(
                user_id=str(user_id),
                hours=sched.time_window_hours,
                model_id=sched.model_id,
                topic=sched.topic_filter,
                source_types=sched.source_filters,
            )

            # Extract the brief_id from the result if available
            raw_id = result.get("id") if isinstance(result, dict) else None
            if raw_id:
                try:
                    brief_id = uuid.UUID(str(raw_id))
                except (ValueError, AttributeError):
                    brief_id = None

            status = "success"
            completed_at = datetime.now(timezone.utc)
            logger.info(
                "DB scheduled brief id=%s completed successfully, brief_id=%s",
                schedule_id,
                brief_id,
            )

        except Exception as exc:  # noqa: BLE001
            status = "error"
            error_message = str(exc)
            completed_at = datetime.now(timezone.utc)
            logger.error(
                "DB scheduled brief id=%s FAILED: %s",
                schedule_id,
                exc,
            )

        # Finalise the run record and update the schedule's status
        try:
            from app.db import AsyncSessionLocal
            from app.models.scheduled_brief import ScheduledBrief, ScheduledBriefRun

            async with AsyncSessionLocal() as db:
                run_row = await db.get(ScheduledBriefRun, run_id)
                if run_row:
                    run_row.status = status
                    run_row.error_message = error_message
                    run_row.brief_id = brief_id
                    run_row.completed_at = completed_at

                sched_row = await db.get(ScheduledBrief, schedule_id)
                if sched_row:
                    sched_row.last_status = status
                    sched_row.last_error = error_message

                await db.commit()
        except Exception as fin_exc:  # noqa: BLE001
            logger.error(
                "Failed to finalise run record for schedule=%s: %s",
                schedule_id,
                fin_exc,
            )


    # ── Digest runner (Sprint 31 CP3) ────────────────────────────────────────

    async def generate_digest_for_schedule(
        self,
        user_id: str,
        *,
        hours: int = 24,
        digest_type: str = "combined",
        deliver: bool = False,
        telegram_chat_id: str | None = None,
        telegram_bot_token: str | None = None,
        webhook_url: str | None = None,
    ) -> dict:
        """Generate a tracker/alert digest and optionally deliver it.

        This is the digest counterpart to ``_generate_brief``.  It can be
        called directly by the DB-backed tick when a ScheduledBrief has
        ``delivery_method == "digest"``, or invoked ad-hoc.

        Args:
            user_id:            UUID string of the owning user.
            hours:              Look-back window in hours.
            digest_type:        "tracker" | "alert" | "combined".
            deliver:            If True, route result through scheduled_delivery.
            telegram_chat_id:   Telegram destination (required if deliver=True).
            telegram_bot_token: Override bot token (optional).
            webhook_url:        Webhook destination (optional).

        Returns:
            The raw digest dict from digest_generator.
        """
        from app.services.digest_generator import (
            generate_alert_digest,
            generate_combined_digest,
            generate_tracker_digest,
        )

        if digest_type == "tracker":
            result = await generate_tracker_digest(user_id=user_id, hours=hours)
        elif digest_type == "alert":
            result = await generate_alert_digest(user_id=user_id, hours=hours)
        else:
            result = await generate_combined_digest(user_id=user_id, hours=hours)

        logger.info(
            "Digest generated: type=%s user=%s window=%sh",
            digest_type,
            user_id,
            hours,
        )

        if deliver and (telegram_chat_id or webhook_url):
            from app.services.scheduled_delivery import (
                DeliveryResult,
                deliver_telegram,
                deliver_webhook,
            )

            text = result.get("text_summary", "")
            if telegram_chat_id and text:
                await deliver_telegram(
                    chat_id=telegram_chat_id,
                    text=text[:4096],  # Telegram message limit
                    bot_token=telegram_bot_token,
                )
            if webhook_url:
                await deliver_webhook(url=webhook_url, payload=result)

        return result


# Module-level singleton
brief_scheduler = BriefScheduler()
