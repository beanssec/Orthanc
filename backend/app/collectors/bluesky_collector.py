"""Bluesky (AT Protocol) collector — polls public account feeds via the AppView API."""
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
from app.models.source import Source
from app.routers.feed import broadcast_post
from app.services.entity_extractor import entity_extractor
from app.services.geo_extractor import geo_extractor

logger = logging.getLogger("orthanc.collectors.bluesky")

BLUESKY_API = "https://public.api.bsky.app/xrpc"
POLL_INTERVAL = 300   # 5 minutes between full cycles
INTER_ACCOUNT_DELAY = 2  # seconds between accounts


class BlueskyCollector:
    """Polls Bluesky accounts using the public AT Protocol AppView API (no auth required)."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self, sources: list) -> None:
        """Start polling all provided Bluesky sources."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(sources))
        logger.info("BlueskyCollector started with %d sources", len(sources))

    async def stop(self) -> None:
        """Cancel the polling task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self, sources: list) -> None:
        """Continuous loop — polls every account then sleeps."""
        while self._running:
            for source in sources:
                if not self._running:
                    return
                try:
                    await self._poll_account(source)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("Bluesky error for %s: %s", source.handle, exc)
                try:
                    await asyncio.sleep(INTER_ACCOUNT_DELAY)
                except asyncio.CancelledError:
                    raise

            try:
                await asyncio.sleep(POLL_INTERVAL)
            except asyncio.CancelledError:
                raise

    async def _poll_account(self, source: Source) -> None:
        """Fetch recent posts from a single Bluesky account and persist new ones."""
        handle = source.handle  # e.g. "bellingcat.bsky.social"
        url = f"{BLUESKY_API}/app.bsky.feed.getAuthorFeed"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params={"actor": handle, "limit": 10})

        if resp.status_code != 200:
            logger.warning("Bluesky API returned %d for %s", resp.status_code, handle)
            return

        data = resp.json()
        feed = data.get("feed", [])
        new_count = 0

        for item in feed:
            post_data = item.get("post", {})
            record = post_data.get("record", {})

            # Skip reposts — only ingest original posts
            if item.get("reason", {}).get("$type") == "app.bsky.feed.defs#reasonRepost":
                continue

            uri = post_data.get("uri", "")  # at://did:plc:xxx/app.bsky.feed.post/rkey
            if not uri:
                continue
            rkey = uri.split("/")[-1]
            external_id = f"bsky_{rkey}"

            # Deduplicate
            async with AsyncSessionLocal() as session:
                existing = await session.execute(
                    select(Post).where(Post.external_id == external_id)
                )
                if existing.scalar_one_or_none():
                    continue

            # Parse text
            text = record.get("text", "")
            created_at = record.get("createdAt", "")
            author = post_data.get("author", {})
            author_handle = author.get("handle", handle)
            author_name = author.get("displayName") or author_handle

            # Parse timestamp
            timestamp = datetime.now(timezone.utc)
            if created_at:
                try:
                    timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                except ValueError:
                    pass

            # Engagement metrics
            like_count = post_data.get("likeCount", 0)
            repost_count = post_data.get("repostCount", 0)
            reply_count = post_data.get("replyCount", 0)

            # Build rich content string
            content = text
            if like_count or repost_count or reply_count:
                content += f"\n\n[♥ {like_count} | ↻ {repost_count} | 💬 {reply_count}]"

            # Embedded image alt-text
            embed = post_data.get("embed", {})
            if embed.get("$type") == "app.bsky.embed.images#view":
                for img in embed.get("images", []):
                    alt = img.get("alt", "")
                    if alt:
                        content += f"\n[Image: {alt}]"

            # External link card
            if embed.get("$type") == "app.bsky.embed.external#view":
                ext = embed.get("external", {})
                ext_uri = ext.get("uri", "")
                ext_title = ext.get("title", "")
                if ext_uri:
                    content += f"\n[Link: {ext_title or ext_uri}]"

            # Persist
            async with AsyncSessionLocal() as session:
                post = Post(
                    source_type="bluesky",
                    source_id=str(source.id),
                    external_id=external_id,
                    author=author_name,
                    content=content,
                    timestamp=timestamp,
                    ingested_at=datetime.now(timezone.utc),
                )
                session.add(post)
                await session.flush()  # get post.id before broadcast

                # Update source.last_polled
                src_result = await session.execute(select(Source).where(Source.id == source.id))
                src_obj = src_result.scalar_one_or_none()
                if src_obj:
                    src_obj.last_polled = datetime.now(timezone.utc)

                await session.commit()
                logger.info("Bluesky [%s]: %s", author_handle, text[:80])

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

            # Geo extraction
            try:
                geo_events = await geo_extractor.process_post(str(post.id), content)
                if geo_events:
                    async with AsyncSessionLocal() as session:
                        for evt in geo_events:
                            session.add(Event(
                                post_id=post.id,
                                lat=evt["lat"],
                                lng=evt["lng"],
                                place_name=evt["place_name"],
                                confidence=evt["confidence"],
                            ))
                        await session.commit()
            except Exception as geo_exc:
                logger.warning("Bluesky geo extraction failed for post %s: %s", post.id, geo_exc)

            # Entity extraction
            try:
                extracted_ents = entity_extractor.extract_entities(content)
                if extracted_ents:
                    async with AsyncSessionLocal() as session:
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
                                entity.last_seen = datetime.now(timezone.utc)
                            else:
                                entity = Entity(
                                    name=ent["name"],
                                    type=ent["type"],
                                    canonical_name=canonical,
                                    mention_count=1,
                                )
                                session.add(entity)
                                await session.flush()
                            session.add(EntityMention(
                                entity_id=entity.id,
                                post_id=post.id,
                                context_snippet=ent.get("context_snippet", ""),
                            ))
                        await session.commit()
            except Exception as ent_exc:
                logger.warning("Bluesky entity extraction failed for post %s: %s", post.id, ent_exc)

            new_count += 1

        if new_count:
            logger.info("Bluesky [%s]: inserted %d new posts", handle, new_count)
        else:
            logger.debug("Bluesky [%s]: no new posts", handle)


bluesky_collector = BlueskyCollector()
