"""Shared entity persistence helper — deadlock-safe entity extraction + DB write.

All collectors should use `persist_entities()` instead of inline entity
extraction logic.  This centralises the no_autoflush / rollback handling
that prevents deadlocks when multiple collectors write entities concurrently.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import Entity, EntityMention
from app.services.entity_extractor import entity_extractor

logger = logging.getLogger("orthanc.entity_persistence")


async def persist_entities(
    session: AsyncSession,
    post_id: UUID,
    text: str,
    *,
    translated_text: str | None = None,
    log_label: str = "post",
) -> int:
    """Extract entities from *text* (or *translated_text* if provided) and persist them.

    If *translated_text* is provided and non-empty, it is used for extraction
    instead of the raw *text*. This improves extraction quality for non-English
    posts since the LLM receives already-translated content.

    Uses ``session.no_autoflush`` to avoid query-triggered flushes that
    cause deadlocks when multiple async tasks write to the Entity table
    concurrently.

    Returns the number of entity mentions created.

    On failure the session is rolled back so the caller can continue
    with a clean transaction state (the post itself will need to be
    re-added if the caller wants to keep it).
    """
    extraction_text = translated_text if (translated_text and translated_text.strip()) else text
    if not extraction_text or len(extraction_text.strip()) < 2:
        return 0

    try:
        extracted = await entity_extractor.extract_entities_async(extraction_text)
        if not extracted:
            return 0

        count = 0
        with session.no_autoflush:
            for ent in extracted:
                canonical = entity_extractor.canonical_name(ent["name"])
                result = await session.execute(
                    select(Entity).where(
                        Entity.canonical_name == canonical,
                        Entity.type == ent["type"],
                    )
                )
                entity_obj = result.scalars().first()
                if entity_obj:
                    entity_obj.mention_count += 1
                    entity_obj.last_seen = datetime.now(timezone.utc)
                else:
                    entity_obj = Entity(
                        name=ent["name"],
                        type=ent["type"],
                        canonical_name=canonical,
                        mention_count=1,
                    )
                    session.add(entity_obj)
                    await session.flush()

                mention = EntityMention(
                    entity_id=entity_obj.id,
                    post_id=post_id,
                    context_snippet=ent.get("context_snippet"),
                )
                session.add(mention)
                count += 1

        return count

    except Exception as exc:
        logger.warning(
            "Entity extraction/persistence failed for %s %s: %s",
            log_label, post_id, exc,
        )
        try:
            await session.rollback()
        except Exception:
            pass
        return 0
