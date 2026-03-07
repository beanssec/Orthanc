from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import feedparser
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.entity import Entity, EntityMention
from app.models.event import Event
from app.models.post import Post
from app.models.source import Source
from app.routers.feed import broadcast_post
from app.services.entity_extractor import entity_extractor
from app.services.geo_extractor import geo_extractor

logger = logging.getLogger("orthanc.collectors.rss")

DEFAULT_POLL_INTERVAL = 300  # 5 minutes


def _sanitize_value(v):
    """Recursively convert feedparser special objects to JSON-safe types."""
    if isinstance(v, time.struct_time):
        try:
            return datetime(*v[:6], tzinfo=timezone.utc).isoformat()
        except Exception:
            return str(v)
    elif isinstance(v, dict):
        return {k: _sanitize_value(val) for k, val in v.items()}
    elif isinstance(v, (list, tuple)):
        return [_sanitize_value(i) for i in v]
    elif isinstance(v, (str, int, float, bool)) or v is None:
        return v
    else:
        return str(v)


def _entry_to_dict(entry) -> dict:
    """Convert a feedparser entry to a JSON-serializable dict."""
    return {k: _sanitize_value(v) for k, v in dict(entry).items()}


def _parse_entry_timestamp(entry) -> Optional[datetime]:
    """Extract a timezone-aware datetime from a feedparser entry."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        val = getattr(entry, attr, None)
        if val and isinstance(val, time.struct_time):
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


class RSSCollector:
    """Polls RSS feeds and persists entries as Posts."""

    def __init__(self, poll_interval: int = DEFAULT_POLL_INTERVAL):
        self._poll_interval = poll_interval
        self._tasks: dict[str, asyncio.Task] = {}  # source.id -> task

    async def start(self, sources: list[Source]) -> None:
        """Begin polling all provided RSS sources."""
        for source in sources:
            source_id = str(source.id)
            if source_id in self._tasks:
                continue  # already running
            logger.info("Starting RSS poller for source %s (%s)", source_id, source.handle)
            task = asyncio.create_task(
                self._poll_loop(source_id, source.handle),
                name=f"rss_poll_{source_id}",
            )
            self._tasks[source_id] = task

    async def stop(self) -> None:
        """Cancel all polling tasks."""
        logger.info("Stopping RSS collector (%d tasks)", len(self._tasks))
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def _poll_loop(self, source_id: str, feed_url: str) -> None:
        """Continuous polling loop for a single RSS feed."""
        while True:
            try:
                await self._poll_once(source_id, feed_url)
            except asyncio.CancelledError:
                logger.info("RSS poller cancelled for source %s", source_id)
                raise
            except Exception as exc:
                logger.exception("RSS poll error for source %s: %s", source_id, exc)

            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                logger.info("RSS poller cancelled during sleep for source %s", source_id)
                raise

    async def _poll_once(self, source_id: str, feed_url: str) -> None:
        """Fetch and process one round of a feed."""
        logger.debug("Polling RSS feed %s", feed_url)

        # feedparser is synchronous — run in thread pool
        loop = asyncio.get_event_loop()
        parsed = await loop.run_in_executor(None, feedparser.parse, feed_url)

        if parsed.get("bozo") and not parsed.entries:
            logger.warning("RSS parse error for %s: %s", feed_url, parsed.get("bozo_exception"))
            return

        feed_title = parsed.feed.get("title", feed_url)
        new_count = 0

        async with AsyncSessionLocal() as session:
            for entry in parsed.entries:
                guid = entry.get("id") or entry.get("link", "")
                if not guid:
                    logger.debug("Skipping entry without id/link in %s", feed_url)
                    continue

                # Deduplicate
                existing = await session.execute(
                    select(Post).where(
                        Post.source_type == "rss",
                        Post.source_id == guid,
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                title = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
                author = entry.get("author", feed_title)
                content = f"{title}\n\n{summary}".strip()
                ts = _parse_entry_timestamp(entry)
                raw = _entry_to_dict(entry)

                post = Post(
                    source_type="rss",
                    source_id=guid,
                    author=author,
                    content=content,
                    raw_json=raw,
                    timestamp=ts,
                )
                session.add(post)
                await session.flush()  # assign post.id before broadcast

                post_dict = {
                    "id": str(post.id),
                    "source_type": post.source_type,
                    "source_id": post.source_id,
                    "author": post.author,
                    "content": post.content,
                    "timestamp": post.timestamp.isoformat() if post.timestamp else None,
                    "ingested_at": post.ingested_at.isoformat() if post.ingested_at else None,
                    "event": None,
                }
                await broadcast_post(post_dict)

                # Run geo extraction (non-blocking — failures must not abort ingest)
                try:
                    geo_events = await geo_extractor.process_post(str(post.id), post.content or "")
                    for evt in geo_events:
                        event = Event(
                            post_id=post.id,
                            lat=evt["lat"],
                            lng=evt["lng"],
                            place_name=evt["place_name"],
                            confidence=evt["confidence"],
                        )
                        session.add(event)
                except Exception as geo_exc:  # noqa: BLE001
                    logger.warning("Geo extraction failed for post %s: %s", post.id, geo_exc)

                # Run entity extraction
                try:
                    extracted_ents = await entity_extractor.extract_entities_async(post.content or "")
                    for ent in extracted_ents:
                        canonical = entity_extractor.canonical_name(ent["name"])
                        existing_ent = await session.execute(
                            select(Entity).where(
                                Entity.canonical_name == canonical,
                                Entity.type == ent["type"],
                            )
                        )
                        entity = existing_ent.scalar_one_or_none()
                        if entity:
                            entity.mention_count += 1
                            entity.last_seen = datetime.now(tz=timezone.utc)
                        else:
                            entity = Entity(
                                name=ent["name"],
                                type=ent["type"],
                                canonical_name=canonical,
                                mention_count=1,
                            )
                            session.add(entity)
                            await session.flush()
                        mention = EntityMention(
                            entity_id=entity.id,
                            post_id=post.id,
                            context_snippet=ent["context_snippet"],
                        )
                        session.add(mention)
                except Exception as ent_exc:
                    logger.warning("Entity extraction failed for post %s: %s", post.id, ent_exc)

                new_count += 1

            # Update last_polled on the source
            source_result = await session.execute(
                select(Source).where(Source.id == source_id)
            )
            source = source_result.scalar_one_or_none()
            if source:
                source.last_polled = datetime.now(tz=timezone.utc)

            await session.commit()

        if new_count:
            logger.info("RSS %s: inserted %d new posts", feed_url, new_count)
        else:
            logger.debug("RSS %s: no new entries", feed_url)
