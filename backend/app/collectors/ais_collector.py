"""AIS ship tracking collector — aisstream.io WebSocket (requires free API key)."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

try:
    import websockets
    _WS_AVAILABLE = True
except ImportError:
    _WS_AVAILABLE = False

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.event import Event
from app.models.post import Post
from app.routers.feed import broadcast_post

logger = logging.getLogger("orthanc.collectors.ais")

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"

# Key waterways to monitor
MONITORING_BBOXES = [
    # Black Sea
    [[40.9, 27.5], [46.6, 41.0]],
    # Strait of Hormuz / Persian Gulf
    [[22.0, 56.0], [27.0, 60.0]],
    # Red Sea
    [[12.0, 32.0], [30.0, 45.0]],
    # Eastern Mediterranean
    [[30.0, 25.0], [42.0, 37.0]],
]

# Ship types of intelligence interest (AIS type codes)
INTEL_SHIP_TYPES = {
    35: "Military",
    36: "Sailing",
    37: "Pleasure Craft",
    50: "Pilot Vessel",
    51: "Search and Rescue",
    55: "Law Enforcement",
    58: "Medical Transport",
    59: "Noncombatant",
}


class AISCollector:
    """
    Streams AIS data from aisstream.io WebSocket API.

    Requires a free API key from https://aisstream.io
    Configure via credentials provider "ais" → field "api_key".

    When no API key is available, the collector stays inactive but the
    /layers/ships endpoint returns demo data so the map layer still works.
    """

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False
        self._current_ships: dict[str, dict] = {}

    async def start(self, api_key: str) -> None:
        if self._task and not self._task.done():
            logger.info("AIS collector already running")
            return
        if not _WS_AVAILABLE:
            logger.warning("websockets package not available — AIS collector disabled")
            return
        logger.info("Starting AIS collector (aisstream.io)")
        self._running = True
        self._task = asyncio.create_task(
            self._stream_loop(api_key), name="ais_stream"
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("AIS collector stopped")

    def get_current_ships(self) -> list[dict]:
        return list(self._current_ships.values())

    async def _stream_loop(self, api_key: str) -> None:
        while self._running:
            try:
                await self._connect_and_stream(api_key)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("AIS stream error: %s — reconnecting in 30s", exc)
                await asyncio.sleep(30)

    async def _connect_and_stream(self, api_key: str) -> None:
        import websockets

        subscribe_msg = json.dumps({
            "APIKey": api_key,
            "BoundingBoxes": MONITORING_BBOXES,
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
        })

        async with websockets.connect(AISSTREAM_URL, ping_interval=20) as ws:
            logger.info("AIS WebSocket connected")
            await ws.send(subscribe_msg)

            async for raw in ws:
                if not self._running:
                    break
                try:
                    msg = json.loads(raw)
                    await self._handle_message(msg)
                except Exception as exc:
                    logger.warning("AIS message parse error: %s", exc)

    async def _handle_message(self, msg: dict) -> None:
        msg_type = msg.get("MessageType")

        if msg_type == "PositionReport":
            meta = msg.get("MetaData", {})
            payload = msg.get("Message", {}).get("PositionReport", {})
            mmsi = str(meta.get("MMSI", ""))
            lat = meta.get("latitude")
            lng = meta.get("longitude")
            if not (mmsi and lat is not None and lng is not None):
                return

            ship_name = meta.get("ShipName", "Unknown").strip()
            speed = payload.get("Sog", 0)
            heading = payload.get("TrueHeading", 0)
            nav_status = payload.get("NavigationalStatus", 0)

            ship_data = self._current_ships.get(mmsi, {})
            ship_data.update({
                "mmsi": mmsi,
                "vessel_name": ship_name,
                "lat": lat,
                "lng": lng,
                "speed": speed,
                "heading": heading,
                "nav_status": nav_status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            self._current_ships[mmsi] = ship_data

            # Store track point for maritime intelligence
            try:
                from app.services.maritime_intel_service import maritime_intel_service
                cog = payload.get("Cog")
                asyncio.create_task(maritime_intel_service.store_track_point(
                    mmsi=mmsi,
                    vessel_name=ship_name,
                    lat=lat,
                    lng=lng,
                    speed=speed,
                    heading=heading,
                    course=cog,
                    destination=ship_data.get("destination"),
                    vessel_type=ship_data.get("ship_type"),
                    flag=None,
                    timestamp=datetime.now(timezone.utc),
                ))
            except Exception as exc:
                logger.debug("Maritime track store error: %s", exc)

        elif msg_type == "ShipStaticData":
            meta = msg.get("MetaData", {})
            payload = msg.get("Message", {}).get("ShipStaticData", {})
            mmsi = str(meta.get("MMSI", ""))
            if not mmsi:
                return

            ship_type_code = payload.get("Type", 0)
            ship_type = INTEL_SHIP_TYPES.get(ship_type_code, f"Type {ship_type_code}")
            destination = payload.get("Destination", "").strip()
            call_sign = payload.get("CallSign", "").strip()
            dim = payload.get("Dimension", {})

            ship_data = self._current_ships.get(mmsi, {"mmsi": mmsi})
            ship_data.update({
                "ship_type": ship_type,
                "ship_type_code": ship_type_code,
                "destination": destination,
                "call_sign": call_sign,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            self._current_ships[mmsi] = ship_data

            # Persist military/intelligence ships to DB
            if ship_type_code in INTEL_SHIP_TYPES and ship_type_code != 0:
                await self._persist_ship(mmsi, ship_data)

    async def _persist_ship(self, mmsi: str, data: dict) -> None:
        vessel_name = data.get("vessel_name", "Unknown")
        ship_type = data.get("ship_type", "Unknown")
        lat = data.get("lat")
        lng = data.get("lng")
        content = (
            f"[Ship] {vessel_name} (MMSI: {mmsi}) — Type: {ship_type}, "
            f"Dest: {data.get('destination', 'Unknown')}, "
            f"Speed: {data.get('speed', 0)}kt"
        )

        try:
            async with AsyncSessionLocal() as session:
                existing = await session.execute(
                    select(Post).where(
                        Post.source_type == "ship",
                        Post.source_id == mmsi,
                    )
                )
                existing_post = existing.scalar_one_or_none()
                if existing_post:
                    existing_post.content = content
                    existing_post.raw_json = data
                    existing_post.timestamp = datetime.now(timezone.utc)
                    await session.commit()
                else:
                    post = Post(
                        source_type="ship",
                        source_id=mmsi,
                        author=vessel_name,
                        content=content,
                        raw_json=data,
                        timestamp=datetime.now(timezone.utc),
                    )
                    session.add(post)
                    await session.flush()
                    if lat and lng:
                        event = Event(
                            post_id=post.id,
                            lat=lat,
                            lng=lng,
                            place_name=f"Ship {vessel_name}",
                            confidence=0.8,
                        )
                        session.add(event)
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
                    await session.commit()
        except Exception as exc:
            logger.warning("AIS DB persist error for MMSI %s: %s", mmsi, exc)


# Singleton — shared by orchestrator and layers router
ais_collector = AISCollector()
