#!/usr/bin/env python3
"""One-time cleanup script for junk entities in the Orthanc database.

Deletes entities (and their entity_mentions) matching known junk patterns:
- name contains t.me/, https://, or http:// (URL debris)
- name starts with @ (usernames)
- name contains POV (Reddit/Telegram POV labels)
- name starts with "Original msg" (Telegram boilerplate)
- name is only emoji (no alphanumeric characters)
- name length <= 2 (too short to be meaningful)
- canonical_name is empty string

Usage:
    cd backend
    python cleanup_entities.py
"""
from __future__ import annotations

import asyncio
import logging
import re
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("cleanup_entities")

# Pattern to detect emoji-only names (no alphanumeric characters)
_HAS_ALNUM_RE = re.compile(r"[a-zA-Z0-9]")


async def run_cleanup() -> None:
    from sqlalchemy import delete, select, func, or_, and_
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker

    from app.config import settings
    from app.models.entity import Entity, EntityMention

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as session:
        # Helper: delete entities matching a condition, return count
        async def delete_matching(label: str, condition) -> int:
            # Get IDs first so we can delete mentions
            result = await session.execute(
                select(Entity.id).where(condition)
            )
            ids = [row[0] for row in result.fetchall()]
            if not ids:
                logger.info("  %s: 0 entities matched", label)
                return 0

            # Delete mentions first (FK constraint)
            await session.execute(
                delete(EntityMention).where(EntityMention.entity_id.in_(ids))
            )
            # Delete entities
            await session.execute(
                delete(Entity).where(Entity.id.in_(ids))
            )
            await session.flush()
            logger.info("  %s: deleted %d entities (+ their mentions)", label, len(ids))
            return len(ids)

        total = 0

        logger.info("Starting entity cleanup...")

        # 1. URLs in name
        count = await delete_matching(
            "name contains URL (t.me/, https://, http://)",
            or_(
                Entity.name.contains("t.me/"),
                Entity.name.contains("https://"),
                Entity.name.contains("http://"),
            ),
        )
        total += count

        # 2. @handles
        count = await delete_matching(
            "name starts with @",
            Entity.name.like("@%"),
        )
        total += count

        # 3. POV labels
        count = await delete_matching(
            "name contains 'POV'",
            Entity.name.contains("POV"),
        )
        total += count

        # 4. "Original msg" boilerplate
        count = await delete_matching(
            "name starts with 'Original msg'",
            Entity.name.like("Original msg%"),
        )
        total += count

        # 5. Name length <= 2
        count = await delete_matching(
            "name length <= 2",
            func.length(Entity.name) <= 2,
        )
        total += count

        # 6. Empty canonical_name
        count = await delete_matching(
            "canonical_name is empty string",
            Entity.canonical_name == "",
        )
        total += count

        # 7. Emoji-only names (no alphanumeric characters) — must do in Python
        result = await session.execute(select(Entity.id, Entity.name))
        rows = result.fetchall()
        emoji_ids = [
            row[0] for row in rows
            if row[1] and not _HAS_ALNUM_RE.search(row[1])
        ]
        if emoji_ids:
            await session.execute(
                delete(EntityMention).where(EntityMention.entity_id.in_(emoji_ids))
            )
            await session.execute(
                delete(Entity).where(Entity.id.in_(emoji_ids))
            )
            await session.flush()
            logger.info("  emoji-only names: deleted %d entities (+ their mentions)", len(emoji_ids))
            total += len(emoji_ids)
        else:
            logger.info("  emoji-only names: 0 entities matched")

        await session.commit()
        logger.info("Cleanup complete. Total entities deleted: %d", total)

    await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(run_cleanup())
    except KeyboardInterrupt:
        logger.info("Interrupted.")
        sys.exit(0)
    except Exception as exc:
        logger.error("Cleanup failed: %s", exc, exc_info=True)
        sys.exit(1)
