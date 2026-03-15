"""Telegram Wave 1 channel seeder — Sprint 32 Checkpoint 2.

Seeds 12 Telegram channel Source records for all existing users.
Metadata (source_class, ecosystem, language) is stored in config_json.
This seeder is fully idempotent: it skips any channel already present
for a given user (matched on type="telegram" + handle).

Called once on startup from main.py lifespan (after source group seeder).
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.source import Source
from app.models.user import User

logger = logging.getLogger("orthanc.telegram.wave1_seeder")

# ---------------------------------------------------------------------------
# Wave 1 channel definitions
# ---------------------------------------------------------------------------

WAVE1_CHANNELS: list[dict] = [
    {
        "handle": "idfofficial",
        "display_name": "IDF Official",
        "source_class": "official",
        "reliability": "high",
        "ecosystem": "israel/military",
        "language": "en",
    },
    {
        "handle": "Irna_en",
        "display_name": "IRNA English",
        "source_class": "state_media",
        "reliability": "medium",
        "ecosystem": "iran",
        "language": "en",
    },
    {
        "handle": "manniefabian",
        "display_name": "Mannie's War Room",
        "source_class": "journalist",
        "reliability": "high",
        "ecosystem": "israel",
        "language": "en",
    },
    {
        "handle": "rybar",
        "display_name": "Rybar",
        "source_class": "propaganda_risk",
        "reliability": "low",
        "ecosystem": "russia/ukraine",
        "language": "ru",
    },
    {
        "handle": "rybar_in_english",
        "display_name": "Rybar English",
        "source_class": "propaganda_risk",
        "reliability": "low",
        "ecosystem": "russia/ukraine",
        "language": "en",
    },
    {
        "handle": "QudsNen",
        "display_name": "Quds News Network",
        "source_class": "militia_adjacent",
        "reliability": "low",
        "ecosystem": "gaza/palestine",
        "language": "en",
    },
    {
        "handle": "gazaalanpa",
        "display_name": "Gaza Now English",
        "source_class": "militia_adjacent",
        "reliability": "low",
        "ecosystem": "gaza",
        "language": "en",
    },
    {
        "handle": "PalestineResist",
        "display_name": "Resistance News Network",
        "source_class": "militia_adjacent",
        "reliability": "low",
        "ecosystem": "palestine",
        "language": "en",
    },
    {
        "handle": "sepah_pasdaran",
        "display_name": "Akhbar Sepah Pasdaran",
        "source_class": "propaganda_risk",
        "reliability": "low",
        "ecosystem": "iran/irgc",
        "language": "fa",
    },
    {
        "handle": "Electrohizbullah",
        "display_name": "Hezbollah Military Media",
        "source_class": "militia_adjacent",
        "reliability": "low",
        "ecosystem": "lebanon/hezbollah",
        "language": "ar",
    },
    {
        "handle": "Eng_ahed",
        "display_name": "Al-Ahed English",
        "source_class": "state_media",
        "reliability": "low",
        "ecosystem": "lebanon/hezbollah",
        "language": "en",
    },
    {
        "handle": "militarysummary",
        "display_name": "Military Summary",
        "source_class": "propaganda_risk",
        "reliability": "low",
        "ecosystem": "russia/ukraine",
        "language": "en",
    },
]


async def seed_telegram_wave1() -> None:
    """Seed Wave 1 Telegram channels for all users. Idempotent."""
    async with AsyncSessionLocal() as session:
        # Get all users
        all_users_result = await session.execute(select(User))
        users = all_users_result.scalars().all()

        if not users:
            logger.info("No users found — Telegram Wave 1 seeder will re-run on next startup")
            return

        total_added = 0

        for user in users:
            user_added = 0
            for channel in WAVE1_CHANNELS:
                handle = channel["handle"]

                # Check if this channel already exists for this user (case-insensitive handle match)
                existing = await session.execute(
                    select(Source).where(
                        Source.user_id == user.id,
                        Source.type == "telegram",
                        Source.handle == handle,
                    )
                )
                if existing.scalars().first():
                    continue  # Already seeded for this user

                source = Source(
                    user_id=user.id,
                    type="telegram",
                    handle=handle,
                    display_name=channel["display_name"],
                    enabled=True,
                    source_class=channel["source_class"],
                    default_reliability_prior=channel["reliability"],
                    ecosystem=channel["ecosystem"],
                    config_json={
                        "source_class": channel["source_class"],
                        "reliability": channel["reliability"],
                        "ecosystem": channel["ecosystem"],
                        "language": channel["language"],
                        "seeded_by": "telegram_wave1",
                    },
                )
                session.add(source)
                user_added += 1

            if user_added:
                logger.info(
                    "Telegram Wave 1: seeded %d channels for user %s",
                    user_added, str(user.id)
                )
                total_added += user_added

        await session.commit()

    if total_added:
        logger.info("Telegram Wave 1 seeder: added %d source records total", total_added)
    else:
        logger.info("Telegram Wave 1 seeder: all channels already seeded (no-op)")
