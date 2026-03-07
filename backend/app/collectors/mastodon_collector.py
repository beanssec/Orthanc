"""Mastodon (ActivityPub) collector — polls public account statuses via instance REST API."""
from __future__ import annotations

import asyncio
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
from app.services.entity_extractor import entity_extractor
from app.services.geo_extractor import geo_extractor

logger = logging.getLogger("orthanc.collectors.mastodon")

POLL_INTERVAL = 300    # 5 minutes between full cycles
INTER_ACCOUNT_DELAY = 2  # seconds between accounts


def _strip_html(html: str) -> str:
    """Convert Mastodon HTML status content to plain text."""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class MastodonCollector:
    """Polls Mastodon accounts using each instance's public REST API (no auth required)."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        # Cache: "user@instance" -> account_id str
        self._account_id_cache: dict[str, str] = {}

    async def start(self, sources: list) -> None:
        """Start polling all provided Mastodon sources."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(sources))
        logger.info("MastodonCollector started with %d sources", len(sources))

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
                    logger.error("Mastodon error for %s: %s", source.handle, exc)
                try:
                    await asyncio.sleep(INTER_ACCOUNT_DELAY)
                except asyncio.CancelledError:
                    raise

            try:
                await asyncio.sleep(POLL_INTERVAL)
            except asyncio.CancelledError:
                raise

    def _parse_handle(self, handle: str) -> tuple[str, str]:
        """
        Parse 'user@instance.social' into (username, instance).
        Falls back gracefully if '@' is absent.
        """
        if "@" in handle:
            parts = handle.split("@", 1)
            return parts[0].lstrip("@"), parts[1]
        # Treat bare string as instance domain — can't resolve without user
        raise ValueError(f"Mastodon handle must be 'user@instance' format, got: {handle!r}")

    async def _resolve_account_id(self, username: str, instance: str) -> str | None:
        """
        Lookup a Mastodon account_id via the /api/v1/accounts/lookup endpoint.
        Results are cached to avoid repeated lookups.
        """
        cache_key = f"{username}@{instance}"
        if cache_key in self._account_id_cache:
            return self._account_id_cache[cache_key]

        url = f"https://{instance}/api/v1/accounts/lookup"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params={"acct": username})
            if resp.status_code == 200:
                data = resp.json()
                account_id = data.get("id")
                if account_id:
                    self._account_id_cache[cache_key] = str(account_id)
                    logger.debug("Mastodon resolved %s@%s → id=%s", username, instance, account_id)
                    return str(account_id)
            else:
                logger.warning(
                    "Mastodon lookup returned %d for %s@%s", resp.status_code, username, instance
                )
        except Exception as exc:
            logger.error("Mastodon lookup error for %s@%s: %s", username, instance, exc)
        return None

    async def _poll_account(self, source: Source) -> None:
        """Fetch recent statuses from a single Mastodon account and persist new ones."""
        try:
            username, instance = self._parse_handle(source.handle)
        except ValueError as exc:
            logger.error("Invalid Mastodon handle for source %s: %s", source.id, exc)
            return

        account_id = await self._resolve_account_id(username, instance)
        if not account_id:
            logger.warning("Could not resolve Mastodon account for %s@%s", username, instance)
            return

        url = f"https://{instance}/api/v1/accounts/{account_id}/statuses"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params={"limit": 10, "exclude_reblogs": "true"})

        if resp.status_code != 200:
            logger.warning("Mastodon API returned %d for %s@%s", resp.status_code, username, instance)
            return

        statuses = resp.json()
        new_count = 0

        for status in statuses:
            status_id = status.get("id", "")
            if not status_id:
                continue

            # Sanitise instance domain for use in external_id
            instance_slug = instance.replace(".", "_")
            external_id = f"mastodon_{instance_slug}_{status_id}"

            # Deduplicate
            async with AsyncSessionLocal() as session:
                existing = await session.execute(
                    select(Post).where(Post.external_id == external_id)
                )
                if existing.scalars().first():
                    continue

            # Content — Mastodon returns HTML
            raw_html = status.get("content", "")
            text = _strip_html(raw_html)

            # Skip empty statuses (e.g. media-only with no text)
            if not text:
                text = "[media post]"

            # CW / subject line
            spoiler_text = status.get("spoiler_text", "")
            if spoiler_text:
                text = f"[CW: {spoiler_text}]\n\n{text}"

            # Author
            account = status.get("account", {})
            author_display = account.get("display_name") or account.get("username") or username
            author_acct = account.get("acct", f"{username}@{instance}")

            # Timestamp
            created_at = status.get("created_at", "")
            timestamp = datetime.now(timezone.utc)
            if created_at:
                try:
                    timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                except ValueError:
                    pass

            # Engagement metrics
            faves = status.get("favourites_count", 0)
            boosts = status.get("reblogs_count", 0)
            replies = status.get("replies_count", 0)
            if faves or boosts or replies:
                text += f"\n\n[★ {faves} | ↻ {boosts} | 💬 {replies}]"

            # Media attachments — surface descriptions
            for att in status.get("media_attachments", []):
                att_type = att.get("type", "")
                desc = att.get("description") or ""
                if desc:
                    text += f"\n[{att_type.capitalize()}: {desc}]"
                else:
                    text += f"\n[{att_type.capitalize()} attachment]"

            # Persist
            async with AsyncSessionLocal() as session:
                post = Post(
                    source_type="mastodon",
                    source_id=str(source.id),
                    external_id=external_id,
                    author=f"{author_display} (@{author_acct})",
                    content=text,
                    timestamp=timestamp,
                    ingested_at=datetime.now(timezone.utc),
                )
                session.add(post)
                await session.flush()

                # Update source.last_polled
                src_result = await session.execute(select(Source).where(Source.id == source.id))
                src_obj = src_result.scalars().first()
                if src_obj:
                    src_obj.last_polled = datetime.now(timezone.utc)

                await session.commit()
                logger.info("Mastodon [%s@%s]: %s", username, instance, text[:80])

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
                geo_events = await geo_extractor.process_post(str(post.id), text)
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
                logger.warning("Mastodon geo extraction failed for post %s: %s", post.id, geo_exc)

            # Entity extraction
            try:
                extracted_ents = await entity_extractor.extract_entities_async(text)
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
                            entity = existing_ent.scalars().first()
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
                logger.warning("Mastodon entity extraction failed for post %s: %s", post.id, ent_exc)

            new_count += 1

        if new_count:
            logger.info("Mastodon [%s@%s]: inserted %d new posts", username, instance, new_count)
        else:
            logger.debug("Mastodon [%s@%s]: no new posts", username, instance)


mastodon_collector = MastodonCollector()
