"""Shodan collector — polls Shodan search API for host/device intelligence."""
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
from app.services.collector_manager import collector_manager
from app.services.entity_extractor import entity_extractor

logger = logging.getLogger("orthanc.collectors.shodan")

DEFAULT_POLL_INTERVAL = 3600  # 1 hour — Shodan is rate-limited
SHODAN_SEARCH_URL = "https://api.shodan.io/shodan/host/search"


def _parse_shodan_timestamp(ts_str: Optional[str]) -> Optional[datetime]:
    """Parse Shodan timestamp string to tz-aware datetime."""
    if not ts_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(ts_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


class ShodanCollector:
    """Polls Shodan for results matching configured search queries."""

    def __init__(self, poll_interval: int = DEFAULT_POLL_INTERVAL):
        self._poll_interval = poll_interval
        self._tasks: dict[str, asyncio.Task] = {}  # source_id -> task

    async def start(self, user_id: str, sources: list) -> None:
        """Begin polling Shodan for each source query."""
        keys = await collector_manager.get_keys(user_id, "shodan")
        if not keys:
            logger.warning("No Shodan keys found for user %s — skipping Shodan collector", user_id)
            return

        api_key: str = keys.get("api_key", "")
        if not api_key:
            logger.warning("Shodan keys for user %s missing 'api_key' field", user_id)
            return

        for source in sources:
            source_id = str(source.id)
            if source_id in self._tasks:
                continue
            query = source.handle
            logger.info("Starting Shodan poller for query %r (source %s)", query, source_id)
            task = asyncio.create_task(
                self._poll_loop(user_id, source_id, query, api_key),
                name=f"shodan_poll_{source_id}",
            )
            self._tasks[source_id] = task

    async def stop(self) -> None:
        """Cancel all polling tasks."""
        logger.info("Stopping Shodan collector (%d tasks)", len(self._tasks))
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def _poll_loop(
        self, user_id: str, source_id: str, query: str, api_key: str
    ) -> None:
        """Continuous polling loop for a single Shodan query."""
        while True:
            try:
                await self._poll_once(user_id, source_id, query, api_key)
            except asyncio.CancelledError:
                logger.info("Shodan poller cancelled for query %r", query)
                raise
            except Exception as exc:
                logger.exception("Shodan poll error for query %r: %s", query, exc)

            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                logger.info("Shodan poller cancelled during sleep for query %r", query)
                raise

    async def _poll_once(
        self, user_id: str, source_id: str, query: str, api_key: str
    ) -> None:
        """Fetch one page of Shodan results and persist new matches."""
        logger.debug("Polling Shodan for query %r", query)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    SHODAN_SEARCH_URL,
                    params={"key": api_key, "query": query, "page": 1},
                )
                if resp.status_code == 401:
                    logger.error("Shodan API key invalid for user query %r", query)
                    return
                if resp.status_code == 403:
                    logger.error("Shodan API access forbidden (plan restriction?) for query %r", query)
                    return
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("Shodan HTTP error for query %r: %s", query, e)
            return
        except Exception as e:
            logger.warning("Shodan request failed for query %r: %s", query, e)
            return

        matches = data.get("matches", [])
        if not matches:
            logger.debug("Shodan query %r: no matches", query)
            return

        new_count = 0
        async with AsyncSessionLocal() as session:
            for match in matches:
                ip_str = match.get("ip_str", "")
                port = match.get("port", 0)
                if not ip_str:
                    continue

                source_id_key = f"{ip_str}:{port}"

                # Deduplicate
                existing = await session.execute(
                    select(Post).where(
                        Post.source_type == "shodan",
                        Post.source_id == source_id_key,
                    )
                )
                if existing.scalars().first():
                    continue

                # Build content
                org = match.get("org") or match.get("isp") or "Unknown"
                product = match.get("product") or match.get("module") or "Unknown Service"
                banner = match.get("data", "")
                banner_excerpt = banner[:500] if banner else "(no banner)"
                author = org
                content = (
                    f"[Shodan] {ip_str}:{port} ({org})\n"
                    f"Service: {product}\n"
                    f"Banner: {banner_excerpt}"
                )

                ts = _parse_shodan_timestamp(match.get("timestamp")) or datetime.now(tz=timezone.utc)

                post = Post(
                    source_type="shodan",
                    source_id=source_id_key,
                    author=author,
                    content=content,
                    raw_json=match,
                    timestamp=ts,
                )
                session.add(post)
                await session.flush()

                # Broadcast
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

                # Create event from location if available
                location = match.get("location", {})
                lat = location.get("latitude")
                lng = location.get("longitude")
                if lat is not None and lng is not None:
                    try:
                        event = Event(
                            post_id=post.id,
                            lat=float(lat),
                            lng=float(lng),
                            place_name=f"{location.get('city', '')} {location.get('country_name', '')}".strip(),
                            confidence=0.9,
                        )
                        session.add(event)
                    except Exception as evt_exc:
                        logger.warning("Failed to create event for Shodan match %s: %s", source_id_key, evt_exc)

                # Entity extraction
                try:
                    extracted_ents = await entity_extractor.extract_entities_async(content or "")
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
                    logger.warning("Entity extraction failed for shodan post %s: %s", post.id, ent_exc)

                new_count += 1

            # Update last_polled for this source
            src_result = await session.execute(select(Source).where(Source.id == source_id))
            src = src_result.scalars().first()
            if src:
                src.last_polled = datetime.now(tz=timezone.utc)

            await session.commit()

        if new_count:
            logger.info("Shodan query %r: inserted %d new posts", query, new_count)
        else:
            logger.debug("Shodan query %r: no new matches", query)
