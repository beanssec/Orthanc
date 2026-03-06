"""Reddit collector — polls public subreddits for new posts."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.entity import Entity, EntityMention
from app.models.event import Event
from app.models.post import Post
from app.routers.feed import broadcast_post
from app.services.entity_extractor import entity_extractor
from app.services.geo_extractor import geo_extractor

logger = logging.getLogger("orthanc.collectors.reddit")

DEFAULT_POLL_INTERVAL = 300  # 5 minutes
REDDIT_USER_AGENT = "Orthanc-OSINT/1.0 (by /u/orthanc_bot)"


class RedditCollector:
    """Polls public subreddits via Reddit JSON API (no auth required)."""

    def __init__(self, poll_interval: int = DEFAULT_POLL_INTERVAL):
        self._poll_interval = poll_interval
        self._tasks: dict[str, asyncio.Task] = {}  # source_id -> task

    async def start(self, sources: list) -> None:
        """Begin polling configured subreddits."""
        for source in sources:
            source_id = str(source.id)
            if source_id in self._tasks:
                continue
            subreddit = source.handle.lstrip("r/").lstrip("/")
            logger.info("Starting Reddit poller for r/%s (source %s)", subreddit, source_id)
            task = asyncio.create_task(
                self._poll_loop(source_id, subreddit),
                name=f"reddit_poll_{source_id}",
            )
            self._tasks[source_id] = task

    async def stop(self) -> None:
        """Cancel all polling tasks."""
        logger.info("Stopping Reddit collector (%d tasks)", len(self._tasks))
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def _poll_loop(self, source_id: str, subreddit: str) -> None:
        """Continuous polling loop for a single subreddit."""
        while True:
            try:
                await self._poll_once(source_id, subreddit)
            except asyncio.CancelledError:
                logger.info("Reddit poller cancelled for r/%s", subreddit)
                raise
            except Exception as exc:
                logger.exception("Reddit poll error for r/%s: %s", subreddit, exc)

            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                logger.info("Reddit poller cancelled during sleep for r/%s", subreddit)
                raise

    async def _poll_once(self, source_id: str, subreddit: str) -> None:
        """Fetch new posts from a subreddit."""
        url = f"https://www.reddit.com/r/{subreddit}/new.json"
        logger.debug("Polling Reddit r/%s", subreddit)

        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                headers={"User-Agent": REDDIT_USER_AGENT},
                follow_redirects=True,
            ) as client:
                resp = await client.get(url, params={"limit": 25})
                if resp.status_code == 429:
                    logger.warning("Reddit rate limited for r/%s, backing off", subreddit)
                    await asyncio.sleep(60)
                    return
                if resp.status_code == 404:
                    logger.warning("Subreddit r/%s not found (404)", subreddit)
                    return
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("Reddit HTTP error for r/%s: %s", subreddit, e)
            return
        except Exception as e:
            logger.warning("Reddit request failed for r/%s: %s", subreddit, e)
            return

        posts_data = data.get("data", {}).get("children", [])
        if not posts_data:
            logger.debug("Reddit r/%s: no posts", subreddit)
            return

        new_count = 0
        async with AsyncSessionLocal() as session:
            for item in posts_data:
                post_data = item.get("data", {})
                post_id_str = post_data.get("id", "")
                if not post_id_str:
                    continue

                source_id_key = f"reddit_{subreddit}_{post_id_str}"

                # Deduplicate
                existing = await session.execute(
                    select(Post).where(
                        Post.source_type == "reddit",
                        Post.source_id == source_id_key,
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                title = post_data.get("title", "")
                selftext = post_data.get("selftext", "")
                author = post_data.get("author", f"r/{subreddit}")
                content = f"{title}\n\n{selftext}".strip() if selftext else title

                created_utc = post_data.get("created_utc")
                if created_utc:
                    ts = datetime.fromtimestamp(float(created_utc), tz=timezone.utc)
                else:
                    ts = datetime.now(tz=timezone.utc)

                post = Post(
                    source_type="reddit",
                    source_id=source_id_key,
                    author=author,
                    content=content,
                    raw_json=post_data,
                    timestamp=ts,
                )
                session.add(post)
                await session.flush()

                await broadcast_post({
                    "id": str(post.id),
                    "source_type": post.source_type,
                    "source_id": post.source_id,
                    "author": post.author,
                    "content": post.content,
                    "timestamp": post.timestamp.isoformat() if post.timestamp else None,
                    "ingested_at": post.ingested_at.isoformat() if post.ingested_at else None,
                    "event": None,
                })

                # Geo extraction
                try:
                    geo_events = await geo_extractor.process_post(str(post.id), content)
                    for evt in geo_events:
                        event = Event(
                            post_id=post.id,
                            lat=evt["lat"],
                            lng=evt["lng"],
                            place_name=evt["place_name"],
                            confidence=evt["confidence"],
                        )
                        session.add(event)
                except Exception as geo_exc:
                    logger.warning("Geo extraction failed for Reddit post %s: %s", post.id, geo_exc)

                # Entity extraction
                try:
                    extracted_ents = entity_extractor.extract_entities(content or "")
                    for ent in extracted_ents:
                        canonical = entity_extractor.canonical_name(ent["name"])
                        existing_ent = await session.execute(
                            select(Entity).where(
                                Entity.canonical_name == canonical,
                                Entity.type == ent["type"],
                            )
                        )
                        entity_obj = existing_ent.scalars().first()
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
                            post_id=post.id,
                            context_snippet=ent.get("context_snippet"),
                        )
                        session.add(mention)
                except Exception as ent_exc:
                    logger.warning("Entity extraction failed for reddit post %s: %s", post.id, ent_exc)

                new_count += 1

            await session.commit()

        if new_count:
            logger.info("Reddit r/%s: inserted %d new posts", subreddit, new_count)
        else:
            logger.debug("Reddit r/%s: no new posts", subreddit)
