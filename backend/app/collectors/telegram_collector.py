"""
Telegram collector using Telethon.

Listens to Telegram channels defined in `sources` and inserts new posts
into the DB, broadcasting via WebSocket.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from telethon import TelegramClient, events
from telethon.errors import (
    ChannelPrivateError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.tl.types import Channel, Chat, User as TLUser

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.entity import Entity, EntityMention
from app.models.event import Event
from app.models.post import Post
from app.routers.feed import broadcast_post
from app.services.collector_manager import collector_manager
from app.services.entity_extractor import entity_extractor
from app.services.geo_extractor import geo_extractor
from app.services.media_service import media_service
from app.services.authenticity_analyzer import authenticity_analyzer

logger = logging.getLogger("orthanc.collectors.telegram")

SESSION_DIR = "/app/data/telegram_sessions"


def _make_json_serializable(obj: Any) -> Any:
    """Recursively convert non-serializable types to JSON-safe equivalents."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_serializable(i) for i in obj]
    # Handle Telethon TLObject types — they have a .to_dict() method
    if hasattr(obj, "to_dict"):
        return _make_json_serializable(obj.to_dict())
    return obj


class TelegramCollector:
    def __init__(self) -> None:
        self._client: Optional[TelegramClient] = None
        self._running: bool = False
        self._user_id: Optional[str] = None
        # Maps str(entity_id) -> config dict (download_images, etc.)
        self._source_configs: dict[str, dict] = {}

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self, user_id: str, sources: list) -> None:
        """Start listening to Telegram channels from `sources`."""
        if self._running:
            logger.warning("TelegramCollector already running for user %s", user_id)
            return

        keys = await collector_manager.get_keys(user_id, "telegram")
        if not keys:
            logger.error("No Telegram API keys found for user %s — cannot start collector", user_id)
            return

        api_id: int = int(keys["api_id"])
        api_hash: str = keys["api_hash"]

        os.makedirs(SESSION_DIR, exist_ok=True)
        session_path = os.path.join(SESSION_DIR, user_id)

        self._user_id = user_id
        self._client = TelegramClient(session_path, api_id, api_hash)

        await self._client.connect()

        if not await self._client.is_user_authorized():
            logger.error(
                "Telegram session for user %s is not authorised. "
                "Complete authentication via /telegram/auth/ endpoints first.",
                user_id,
            )
            await self._client.disconnect()
            self._client = None
            return

        # Build the list of channel handles/IDs to subscribe to
        telegram_sources = [
            s for s in sources
            if (s.type if hasattr(s, "type") else "telegram") == "telegram"
        ]
        channel_handles = [
            s.handle if hasattr(s, "handle") else str(s)
            for s in telegram_sources
        ]

        # Resolve each handle to a Telegram entity, skipping failures
        chat_entities: list = []
        self._source_configs = {}

        for source in telegram_sources:
            handle = source.handle if hasattr(source, "handle") else str(source)
            try:
                entity = await self._client.get_entity(handle)
                chat_entities.append(entity)
                # Store per-source media download config keyed by Telegram entity ID
                self._source_configs[str(entity.id)] = {
                    "download_images": getattr(source, "download_images", False),
                    "download_videos": getattr(source, "download_videos", False),
                    "max_image_size_mb": getattr(source, "max_image_size_mb", 10.0),
                    "max_video_size_mb": getattr(source, "max_video_size_mb", 100.0),
                }
                logger.info(
                    "Resolved Telegram entity: %s → %s (images=%s videos=%s)",
                    handle, entity.id,
                    self._source_configs[str(entity.id)]["download_images"],
                    self._source_configs[str(entity.id)]["download_videos"],
                )
            except (ChannelPrivateError, UsernameInvalidError, UsernameNotOccupiedError) as exc:
                logger.warning("Cannot resolve Telegram channel '%s': %s", handle, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Unexpected error resolving '%s': %s", handle, exc)

        if not chat_entities:
            logger.warning(
                "No valid Telegram channels resolved for user %s — collector idle but connected",
                user_id,
            )

        chat_ids = [e.id for e in chat_entities]

        @self._client.on(events.NewMessage(chats=chat_ids if chat_ids else None))
        async def _on_new_message(event: events.NewMessage.Event) -> None:
            await self._handle_message(event)

        self._running = True
        logger.info(
            "TelegramCollector started for user %s, watching %d channel(s)",
            user_id,
            len(chat_entities),
        )

        # Backfill recent messages from each channel
        for entity in chat_entities:
            try:
                await self._backfill_channel(entity, limit=50)
            except Exception as exc:
                logger.warning("Backfill failed for %s: %s", entity.id, exc)

        # Schedule run_until_disconnected as a background task so we don't block the caller.
        asyncio.ensure_future(self._client.run_until_disconnected())

    async def stop(self) -> None:
        """Disconnect the Telethon client and mark as stopped."""
        self._running = False
        if self._client and self._client.is_connected():
            await self._client.disconnect()
            logger.info("TelegramCollector stopped for user %s", self._user_id)
        self._client = None
        self._user_id = None
        self._source_configs = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _download_and_attach_media(
        self,
        message: Any,
        post: Post,
        channel_id: Any,
        source_config: dict,
    ) -> None:
        """
        Download media from a Telethon message and attach it to the Post object.
        Updates post.media_* fields in-place. Does NOT commit the session.
        Queues authenticity check for images.
        """
        max_image_bytes = source_config.get("max_image_size_mb", 10.0) * 1024 * 1024
        max_video_bytes = source_config.get("max_video_size_mb", 100.0) * 1024 * 1024

        try:
            if message.photo and source_config.get("download_images"):
                file_bytes: bytes = await self._client.download_media(message, bytes)
                if file_bytes and len(file_bytes) <= max_image_bytes:
                    relative_path = media_service.save_media(
                        file_bytes, str(channel_id), message.id, "jpg"
                    )
                    thumb_relative = media_service.generate_thumbnail(relative_path, message.id)
                    metadata = media_service.extract_image_metadata(relative_path)

                    post.media_type = "image"
                    post.media_path = relative_path
                    post.media_size_bytes = len(file_bytes)
                    post.media_mime = "image/jpeg"
                    post.media_thumbnail_path = thumb_relative
                    post.media_metadata = metadata

                    logger.debug(
                        "Downloaded image for message %s/%s (%d bytes)",
                        channel_id, message.id, len(file_bytes)
                    )
                elif file_bytes:
                    logger.debug(
                        "Image skipped (too large: %d > %d bytes) for message %s/%s",
                        len(file_bytes), max_image_bytes, channel_id, message.id
                    )

            elif message.video and source_config.get("download_videos"):
                file_bytes = await self._client.download_media(message, bytes)
                if file_bytes and len(file_bytes) <= max_video_bytes:
                    relative_path = media_service.save_media(
                        file_bytes, str(channel_id), message.id, "mp4"
                    )
                    metadata = media_service.extract_video_metadata(relative_path)

                    post.media_type = "video"
                    post.media_path = relative_path
                    post.media_size_bytes = len(file_bytes)
                    post.media_mime = "video/mp4"
                    post.media_metadata = metadata

                    logger.debug(
                        "Downloaded video for message %s/%s (%d bytes)",
                        channel_id, message.id, len(file_bytes)
                    )
                elif file_bytes:
                    logger.debug(
                        "Video skipped (too large: %d > %d bytes) for message %s/%s",
                        len(file_bytes), max_video_bytes, channel_id, message.id
                    )

        except Exception as exc:
            logger.warning(
                "Media download failed for message %s/%s: %s",
                channel_id, message.id, exc
            )

    async def _check_authenticity(self, post_id: Any, relative_path: str, metadata: dict) -> None:
        """Async fire-and-forget task: run vision model authenticity check and update post."""
        try:
            # Try OpenRouter first (GPT-4o vision), fall back to xAI (needs vision tier)
            keys = await collector_manager.get_keys(self._user_id, "openrouter")
            provider = "openrouter"
            api_key: Optional[str] = keys.get("api_key") if keys else None

            if not api_key:
                keys = await collector_manager.get_keys(self._user_id, "x")
                if keys:
                    api_key = keys.get("api_key")
                    provider = "xai"

            if not api_key:
                logger.debug(
                    "No xAI or OpenRouter key available — skipping authenticity check for post %s",
                    post_id
                )
                return

            result = await authenticity_analyzer.analyze_image(
                relative_path, metadata, api_key, provider
            )

            if result:
                async with AsyncSessionLocal() as session:
                    post = await session.get(Post, post_id)
                    if post:
                        post.authenticity_score = result.get("score")
                        post.authenticity_analysis = json.dumps(result)
                        post.authenticity_checked_at = datetime.now(timezone.utc)
                        await session.commit()
                        logger.debug(
                            "Authenticity check complete for post %s: score=%.2f verdict=%s",
                            post_id, result.get("score", 0), result.get("verdict", "?")
                        )

            if not result:
                # Mark as checked even on failure so UI doesn't show "Analyzing" forever
                async with AsyncSessionLocal() as session:
                    post = await session.get(Post, post_id)
                    if post:
                        post.authenticity_checked_at = datetime.now(timezone.utc)
                        await session.commit()

        except Exception as exc:
            logger.warning("Authenticity check failed for post %s: %s", post_id, exc)
            try:
                async with AsyncSessionLocal() as session:
                    post = await session.get(Post, post_id)
                    if post:
                        post.authenticity_checked_at = datetime.now(timezone.utc)
                        await session.commit()
            except Exception:
                pass

    async def _backfill_channel(self, entity, limit: int = 50) -> None:
        """Pull the latest `limit` messages from a channel and ingest any we haven't seen."""
        channel_name = getattr(entity, "title", str(entity.id))
        source_config = self._source_configs.get(str(entity.id), {})
        logger.info("Backfilling up to %d messages from %s (id=%s)", limit, channel_name, entity.id)

        ingested = 0
        async for message in self._client.iter_messages(entity, limit=limit):
            has_text = bool(message.text or message.message)
            has_media = bool(message.photo or message.video or message.document)

            # Skip truly empty messages
            if not has_text and not has_media:
                continue

            channel_id = entity.id
            message_id = message.id
            source_id = f"{channel_id}_{message_id}"

            # Check if we already have this message
            async with AsyncSessionLocal() as session:
                existing = await session.execute(
                    select(Post.id).where(
                        Post.source_type == "telegram",
                        Post.source_id == source_id,
                    )
                )
                if existing.scalars().first():
                    continue

            # Build the post
            content = message.text or message.message
            if not content:
                caption = getattr(message, "message", "") or ""
                content = f"[Media] {caption}".strip() if caption else "[Media]"

            timestamp = message.date if message.date else datetime.now(timezone.utc)

            # Derive author
            if isinstance(entity, Channel):
                author = entity.title or str(entity.id)
            elif isinstance(entity, Chat):
                author = entity.title or str(entity.id)
            else:
                author = str(entity.id)

            try:
                raw_dict = _make_json_serializable(message.to_dict())
            except Exception:
                raw_dict = {"message_id": message_id}

            post = Post(
                source_type="telegram",
                source_id=source_id,
                author=author,
                content=content,
                raw_json=raw_dict,
                timestamp=timestamp,
            )

            # Download media (before session.add so fields are set before flush)
            if has_media and source_config:
                await self._download_and_attach_media(message, post, channel_id, source_config)

            async with AsyncSessionLocal() as session:
                session.add(post)
                await session.flush()

                # Geo extraction
                try:
                    geo_events = await geo_extractor.process_post(str(post.id), content or "")
                    for evt in geo_events:
                        event_obj = Event(
                            post_id=post.id,
                            lat=evt["lat"],
                            lng=evt["lng"],
                            place_name=evt["place_name"],
                            confidence=evt["confidence"],
                        )
                        session.add(event_obj)
                except Exception as exc:
                    logger.debug("Geo extraction failed for backfill post: %s", exc)

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
                except Exception as exc:
                    logger.debug("Entity extraction failed for backfill post: %s", exc)

                await session.commit()
                await session.refresh(post)

            # Queue async authenticity check for downloaded images (fire-and-forget)
            if post.media_type == "image" and post.media_path:
                asyncio.ensure_future(
                    self._check_authenticity(post.id, post.media_path, post.media_metadata or {})
                )

            # Broadcast
            await broadcast_post({
                "id": str(post.id),
                "source_type": post.source_type,
                "source_id": post.source_id,
                "author": post.author,
                "content": post.content,
                "timestamp": post.timestamp.isoformat() if post.timestamp else None,
                "ingested_at": post.ingested_at.isoformat() if post.ingested_at else None,
                "event": None,
                "media_type": post.media_type,
                "media_thumbnail_path": post.media_thumbnail_path,
                "authenticity_score": post.authenticity_score,
            })
            ingested += 1

        logger.info("Backfilled %d new messages from %s", ingested, channel_name)

    async def _handle_message(self, event: events.NewMessage.Event) -> None:
        """Persist an incoming Telegram message to the DB and broadcast it."""
        try:
            message = event.message
            chat = await event.get_chat()

            # Derive a human-readable author / channel name
            if isinstance(chat, Channel):
                author = chat.title or str(chat.id)
            elif isinstance(chat, Chat):
                author = chat.title or str(chat.id)
            elif isinstance(chat, TLUser):
                parts = filter(None, [chat.first_name, chat.last_name])
                author = " ".join(parts) or str(chat.id)
            else:
                author = str(chat.id) if chat else "unknown"

            channel_id = chat.id if chat else "unknown"
            message_id = message.id
            source_id = f"{channel_id}_{message_id}"

            # Content — prefer text, fall back to media caption or placeholder
            content: Optional[str] = message.text or message.message
            if not content:
                caption = getattr(message, "message", "") or ""
                content = f"[Media] {caption}".strip() if caption else "[Media]"

            # Timestamp — use message.date (UTC-aware) or now
            timestamp: datetime = message.date if message.date else datetime.now(timezone.utc)

            # raw_json — make it serialisable
            try:
                raw_dict = _make_json_serializable(message.to_dict())
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not serialise message to dict: %s", exc)
                raw_dict = {"error": str(exc)}

            post = Post(
                source_type="telegram",
                source_id=source_id,
                author=author,
                content=content,
                raw_json=raw_dict,
                timestamp=timestamp,
            )

            # Download media if source is configured for it
            source_config = self._source_configs.get(str(channel_id), {})
            has_media = bool(message.photo or message.video or message.document)
            if has_media and source_config:
                await self._download_and_attach_media(message, post, channel_id, source_config)

            async with AsyncSessionLocal() as session:
                session.add(post)
                await session.flush()  # assign post.id

                # Run geo extraction (non-blocking — failures must not abort ingest)
                try:
                    geo_events = await geo_extractor.process_post(str(post.id), post.content or "")
                    for evt in geo_events:
                        event_obj = Event(
                            post_id=post.id,
                            lat=evt["lat"],
                            lng=evt["lng"],
                            place_name=evt["place_name"],
                            confidence=evt["confidence"],
                        )
                        session.add(event_obj)
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
                            context_snippet=ent["context_snippet"],
                        )
                        session.add(mention)
                except Exception as ent_exc:
                    logger.warning("Entity extraction failed for post %s: %s", post.id, ent_exc)

                await session.commit()
                await session.refresh(post)

            # Queue authenticity check for downloaded images (fire-and-forget, never blocks ingest)
            if post.media_type == "image" and post.media_path:
                asyncio.ensure_future(
                    self._check_authenticity(post.id, post.media_path, post.media_metadata or {})
                )

            # Broadcast over WebSocket
            await broadcast_post(
                {
                    "id": str(post.id),
                    "source_type": post.source_type,
                    "source_id": post.source_id,
                    "author": post.author,
                    "content": post.content,
                    "timestamp": post.timestamp.isoformat() if post.timestamp else None,
                    "ingested_at": post.ingested_at.isoformat() if post.ingested_at else None,
                    "event": None,
                    "media_type": post.media_type,
                    "media_thumbnail_path": post.media_thumbnail_path,
                    "authenticity_score": post.authenticity_score,
                }
            )

            logger.debug("Ingested Telegram message %s from %s", source_id, author)

        except Exception as exc:  # noqa: BLE001
            logger.error("Error handling Telegram message: %s", exc, exc_info=True)
