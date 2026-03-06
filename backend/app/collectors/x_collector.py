from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.entity import Entity, EntityMention
from app.models.event import Event
from app.models.post import Post
from app.models.source import Source
from app.routers.feed import broadcast_post
from app.services.collector_manager import collector_manager
from app.services.entity_extractor import entity_extractor
from app.services.geo_extractor import geo_extractor

logger = logging.getLogger("orthanc.collectors.x")

DEFAULT_POLL_INTERVAL = 60  # 1 minute
XAI_ENDPOINT = "https://api.x.ai/v1/chat/completions"
XAI_MODEL = "grok-3-mini"

SYSTEM_PROMPT = (
    "You are a tweet retrieval assistant. Return ONLY a JSON array of the most recent tweets "
    "from the specified account. Each tweet should have: id, text, author, created_at. "
    "No commentary."
)


def _parse_tweet_timestamp(created_at: Optional[str]) -> Optional[datetime]:
    """Parse various ISO-8601 / Twitter date formats into a tz-aware datetime."""
    if not created_at:
        return None
    # Try ISO 8601 with Z or offset
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%a %b %d %H:%M:%S +0000 %Y",  # legacy Twitter format
    ):
        try:
            dt = datetime.strptime(created_at, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    # Fallback: strip trailing Z and parse
    try:
        return datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except Exception:
        return None


class XCollector:
    """Polls X (Twitter) accounts via xAI/Grok and persists tweets as Posts."""

    def __init__(self, poll_interval: int = DEFAULT_POLL_INTERVAL):
        self._poll_interval = poll_interval
        self._tasks: dict[str, asyncio.Task] = {}  # source.id -> task

    async def start(self, user_id: str, sources: list[Source]) -> None:
        """Begin polling X accounts for a user (uses their stored xAI API key)."""
        keys = await collector_manager.get_keys(user_id, "x")
        if not keys:
            logger.warning("No X/xAI keys found for user %s — skipping X collector", user_id)
            return

        api_key: str = keys.get("api_key", "")
        if not api_key:
            logger.warning("X keys for user %s missing 'api_key' field", user_id)
            return

        for source in sources:
            source_id = str(source.id)
            if source_id in self._tasks:
                continue
            logger.info("Starting X poller for %s (source %s)", source.handle, source_id)
            task = asyncio.create_task(
                self._poll_loop(user_id, source_id, source.handle, api_key),
                name=f"x_poll_{source_id}",
            )
            self._tasks[source_id] = task

    async def stop(self) -> None:
        """Cancel all polling tasks."""
        logger.info("Stopping X collector (%d tasks)", len(self._tasks))
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def _poll_loop(
        self, user_id: str, source_id: str, handle: str, api_key: str
    ) -> None:
        """Continuous polling loop for a single X account."""
        backoff = self._poll_interval
        while True:
            try:
                await self._poll_once(user_id, source_id, handle, api_key)
                backoff = self._poll_interval  # reset backoff on success
            except asyncio.CancelledError:
                logger.info("X poller cancelled for @%s", handle)
                raise
            except _RateLimitError as e:
                logger.warning("X rate limit for @%s — backing off %ds", handle, e.retry_after)
                backoff = e.retry_after
            except Exception as exc:
                logger.exception("X poll error for @%s: %s", handle, exc)

            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                logger.info("X poller cancelled during sleep for @%s", handle)
                raise

    async def _poll_once(
        self, user_id: str, source_id: str, handle: str, api_key: str
    ) -> None:
        """Fetch and persist new tweets for one account."""
        logger.debug("Polling X account @%s", handle)

        tweets = await self._fetch_tweets(handle, api_key)
        if not tweets:
            logger.debug("No tweets returned for @%s", handle)
            return

        new_count = 0
        async with AsyncSessionLocal() as session:
            for tweet in tweets:
                tweet_id = str(tweet.get("id", ""))
                if not tweet_id:
                    continue

                # Deduplicate
                existing = await session.execute(
                    select(Post).where(
                        Post.source_type == "x",
                        Post.source_id == tweet_id,
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                author = tweet.get("author", handle)
                text = tweet.get("text", "")
                ts = _parse_tweet_timestamp(tweet.get("created_at"))

                post = Post(
                    source_type="x",
                    source_id=tweet_id,
                    author=author,
                    content=text,
                    raw_json=tweet,
                    timestamp=ts,
                )
                session.add(post)
                await session.flush()

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
                    extracted_ents = entity_extractor.extract_entities(post.content or "")
                    for ent in extracted_ents:
                        canonical = entity_extractor.canonical_name(ent["name"])
                        existing_ent = await session.execute(
                            select(Entity).where(
                                Entity.canonical_name == canonical,
                                Entity.type == ent["type"],
                            )
                        )
                        entity_obj = existing_ent.scalar_one_or_none()
                        if entity_obj:
                            entity_obj.mention_count += 1
                            entity_obj.last_seen = datetime.now(tz=timezone.utc)
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
                            post_id=post.id,
                            context_snippet=ent["context_snippet"],
                        )
                        session.add(mention)
                except Exception as ent_exc:
                    logger.warning("Entity extraction failed for post %s: %s", post.id, ent_exc)

                new_count += 1

            # Update last_polled
            source_result = await session.execute(
                select(Source).where(Source.id == source_id)
            )
            source = source_result.scalar_one_or_none()
            if source:
                source.last_polled = datetime.now(tz=timezone.utc)

            await session.commit()

        if new_count:
            logger.info("X @%s: inserted %d new posts", handle, new_count)
        else:
            logger.debug("X @%s: no new tweets", handle)

    async def _fetch_tweets(self, handle: str, api_key: str) -> list[dict]:
        """Call xAI Grok to retrieve recent tweets for a handle."""
        handle = handle.lstrip("@")  # normalize — avoid @@handle
        payload = {
            "model": XAI_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Get the 10 most recent tweets from @{handle}"},
            ],
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(XAI_ENDPOINT, json=payload, headers=headers)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            raise _RateLimitError(retry_after)

        resp.raise_for_status()
        data = resp.json()

        raw_content: str = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "[]")
        )

        # Strip markdown code fences if present
        raw_content = re.sub(r"```(?:json)?\s*", "", raw_content).strip()

        try:
            tweets = json.loads(raw_content)
            if isinstance(tweets, list):
                return tweets
            logger.warning("Unexpected xAI response structure for @%s", handle)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse xAI JSON for @%s: %s", handle, e)

        return []


class _RateLimitError(Exception):
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Rate limited — retry after {retry_after}s")
