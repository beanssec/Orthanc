"""
Brief Scheduler — in-memory, checks every 5 minutes if a scheduled brief is due.
State is lost on restart (MVP — user re-enables on the Schedule tab).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger("orthanc.brief_scheduler")


class BriefScheduler:
    def __init__(self) -> None:
        # user_id (str) -> config dict
        self._schedules: dict[str, dict] = {}

    # ── Schedule management ─────────────────────────────────────────────

    def set_schedule(self, user_id: str, config: dict) -> None:
        """Store or update a user's brief schedule config."""
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
        # Serialize last_generated for API responses
        last = cfg.get("last_generated")
        cfg["last_generated"] = last.isoformat() if last else None
        return cfg

    # ── Background loop ─────────────────────────────────────────────────

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
        for user_id, config in list(self._schedules.items()):
            if not config.get("enabled", True):
                continue
            hour = config.get("schedule_hour_utc", 8)
            last: datetime | None = config.get("last_generated")

            due = now.hour == hour and (
                last is None or last.date() < now.date()
            )
            if due:
                logger.info("Generating scheduled brief for user %s", user_id)
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
            logger.error("Scheduled brief generation failed for user=%s: %s", user_id, exc)


# Module-level singleton
brief_scheduler = BriefScheduler()
