"""Discord collector — connects to Discord Gateway via bot token to ingest messages."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.entity import Entity, EntityMention
from app.models.event import Event
from app.models.post import Post
from app.routers.feed import broadcast_post
from app.services.collector_manager import collector_manager
from app.services.entity_extractor import entity_extractor
from app.services.geo_extractor import geo_extractor

logger = logging.getLogger("orthanc.collectors.discord")

DISCORD_GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"
DISCORD_API_BASE = "https://discord.com/api/v10"

# Discord Gateway opcodes
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_HEARTBEAT_ACK = 11


class DiscordCollector:
    """Connects to Discord Gateway and ingests messages from configured channels."""

    def __init__(self):
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._running: bool = False
        self._user_id: Optional[str] = None
        self._token: Optional[str] = None
        self._channel_ids: set[str] = set()
        self._heartbeat_interval: Optional[float] = None
        self._sequence: Optional[int] = None
        self._task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

    async def start(self, user_id: str, sources: list) -> None:
        """Start listening to Discord channels from sources."""
        if self._running:
            logger.warning("DiscordCollector already running for user %s", user_id)
            return

        keys = await collector_manager.get_keys(user_id, "discord")
        if not keys:
            logger.warning("No Discord keys for user %s — skipping Discord collector", user_id)
            return

        token = keys.get("bot_token", "")
        if not token:
            logger.warning("Discord keys for user %s missing 'bot_token' field", user_id)
            return

        self._user_id = user_id
        self._token = token

        # Extract channel IDs from sources (handle = channel_id or channel_id:guild_id)
        self._channel_ids = set()
        for source in sources:
            handle = source.handle if hasattr(source, "handle") else str(source)
            # Handle "channel_id:guild_id" format or just channel_id
            channel_id = handle.split(":")[0].strip()
            if channel_id:
                self._channel_ids.add(channel_id)

        if not self._channel_ids:
            logger.warning("No Discord channel IDs configured for user %s", user_id)
            return

        logger.info(
            "Starting Discord collector for user %s, watching %d channel(s)",
            user_id,
            len(self._channel_ids),
        )
        self._running = True
        self._task = asyncio.create_task(
            self._gateway_loop(),
            name=f"discord_gateway_{user_id}",
        )

    async def stop(self) -> None:
        """Stop the Discord collector."""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        self._ws = None
        self._session = None
        logger.info("Discord collector stopped for user %s", self._user_id)

    async def _gateway_loop(self) -> None:
        """Main WebSocket gateway connection loop with reconnect."""
        backoff = 5
        while self._running:
            try:
                await self._connect_and_listen()
                backoff = 5  # reset on clean exit
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Discord gateway error: %s — reconnecting in %ds", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 120)

    async def _connect_and_listen(self) -> None:
        """Connect to Discord Gateway and process events."""
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = aiohttp.ClientSession()

        async with self._session.ws_connect(DISCORD_GATEWAY_URL) as ws:
            self._ws = ws
            async for msg in ws:
                if not self._running:
                    break
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_event(json.loads(msg.data))
                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                    logger.warning("Discord WS closed/error: %s", msg)
                    break

    async def _handle_event(self, payload: dict) -> None:
        """Process a Discord Gateway payload."""
        op = payload.get("op")
        self._sequence = payload.get("s") or self._sequence

        if op == OP_DISPATCH:
            event_type = payload.get("t")
            data = payload.get("d", {})
            if event_type == "MESSAGE_CREATE":
                await self._handle_message(data)

        elif op == 10:  # Hello
            self._heartbeat_interval = payload["d"]["heartbeat_interval"] / 1000.0
            # Start heartbeat
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            # Send Identify
            await self._identify()

        elif op == OP_HEARTBEAT_ACK:
            logger.debug("Discord heartbeat acknowledged")

        elif op == OP_HEARTBEAT:
            await self._send_heartbeat()

    async def _identify(self) -> None:
        """Send IDENTIFY payload to Discord Gateway."""
        if not self._ws:
            return
        await self._ws.send_json({
            "op": OP_IDENTIFY,
            "d": {
                "token": self._token,
                "intents": 512,  # GUILD_MESSAGES intent
                "properties": {
                    "os": "linux",
                    "browser": "orthanc",
                    "device": "orthanc",
                },
            },
        })

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats."""
        while self._running and self._heartbeat_interval:
            await asyncio.sleep(self._heartbeat_interval)
            await self._send_heartbeat()

    async def _send_heartbeat(self) -> None:
        """Send a heartbeat to keep the connection alive."""
        if self._ws and not self._ws.closed:
            await self._ws.send_json({"op": OP_HEARTBEAT, "d": self._sequence})

    async def _handle_message(self, data: dict) -> None:
        """Persist a Discord message to the DB."""
        try:
            channel_id = str(data.get("channel_id", ""))
            if channel_id not in self._channel_ids:
                return

            message_id = str(data.get("id", ""))
            if not message_id:
                return

            source_id = f"{channel_id}_{message_id}"
            author_data = data.get("author", {})
            author = author_data.get("username", "unknown")
            content = data.get("content", "")
            if not content:
                return  # Skip empty messages (embeds, etc.)

            timestamp_str = data.get("timestamp")
            ts: datetime
            if timestamp_str:
                try:
                    ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                except Exception:
                    ts = datetime.now(tz=timezone.utc)
            else:
                ts = datetime.now(tz=timezone.utc)

            async with AsyncSessionLocal() as session:
                existing = await session.execute(
                    select(Post).where(
                        Post.source_type == "discord",
                        Post.source_id == source_id,
                    )
                )
                if existing.scalars().first():
                    return

                post = Post(
                    source_type="discord",
                    source_id=source_id,
                    author=author,
                    content=content,
                    raw_json=data,
                    timestamp=ts,
                )
                session.add(post)
                await session.flush()

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
                    logger.warning("Geo extraction failed for Discord post %s: %s", post.id, geo_exc)

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
                    logger.warning("Entity extraction failed for discord post %s: %s", post.id, ent_exc)

                await session.commit()

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
            logger.debug("Ingested Discord message %s from %s", source_id, author)

        except Exception as exc:
            logger.error("Error handling Discord message: %s", exc, exc_info=True)
