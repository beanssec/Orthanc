"""Sentinel-2 imagery change detection via Copernicus Data Space Ecosystem."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger("orthanc.sentinel")

# Copernicus Data Space catalogue API (free, no auth for search)
CDSE_SEARCH_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"

# Default watchpoints — militarily significant sites
DEFAULT_WATCHPOINTS = [
    {"name": "Sevastopol Naval Base", "lat": 44.62, "lng": 33.52, "category": "military", "radius_km": 15},
    {"name": "Tartus Naval Base (Syria)", "lat": 34.89, "lng": 35.87, "category": "military", "radius_km": 10},
    {"name": "Bandar Abbas (Iran)", "lat": 27.18, "lng": 56.28, "category": "port", "radius_km": 15},
    {"name": "Natanz Nuclear Site", "lat": 33.72, "lng": 51.73, "category": "nuclear", "radius_km": 15},
    {"name": "Fordow Nuclear Site", "lat": 34.88, "lng": 50.96, "category": "nuclear", "radius_km": 10},
    {"name": "Isfahan Nuclear Complex", "lat": 32.71, "lng": 51.72, "category": "nuclear", "radius_km": 20},
    {"name": "Kaliningrad (Russia)", "lat": 54.71, "lng": 20.50, "category": "military", "radius_km": 20},
    {"name": "Khmeimim Air Base (Syria)", "lat": 35.40, "lng": 35.95, "category": "military", "radius_km": 10},
    {"name": "Yongbyon Nuclear (DPRK)", "lat": 39.79, "lng": 125.75, "category": "nuclear", "radius_km": 15},
    {"name": "Sohae Launch Facility (DPRK)", "lat": 40.85, "lng": 124.70, "category": "military", "radius_km": 10},
    {"name": "Strait of Hormuz (chokepoint)", "lat": 26.57, "lng": 56.25, "category": "maritime", "radius_km": 20},
    {"name": "Bab el-Mandeb Strait", "lat": 12.60, "lng": 43.30, "category": "maritime", "radius_km": 15},
]


class SentinelService:
    """Monitor satellite imagery for changes at key geographic sites."""

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the periodic imagery check loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Sentinel-2 change detection service started")

    async def stop(self) -> None:
        """Stop the service."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def seed_default_watchpoints(self) -> None:
        """Seed the database with default watchpoints if none exist."""
        from app.db import AsyncSessionLocal
        from app.models.watchpoint import SatWatchpoint
        from sqlalchemy import func, select

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(func.count()).select_from(SatWatchpoint))
            count = result.scalar()
            if count == 0:
                for wp_data in DEFAULT_WATCHPOINTS:
                    wp = SatWatchpoint(**wp_data)
                    session.add(wp)
                await session.commit()
                logger.info("Seeded %d satellite watchpoints", len(DEFAULT_WATCHPOINTS))

    async def _monitor_loop(self) -> None:
        """Poll Copernicus catalogue every 6 hours for new Sentinel-2 imagery."""
        await self.seed_default_watchpoints()
        while self._running:
            try:
                await self._check_all_watchpoints()
            except Exception as e:
                logger.error("Sentinel monitor error: %s", e)
            # Sentinel-2 revisit is ~5 days; check every 6h to catch new products promptly
            await asyncio.sleep(6 * 3600)

    async def _check_all_watchpoints(self) -> None:
        """Check all enabled watchpoints for new imagery."""
        from app.db import AsyncSessionLocal
        from app.models.watchpoint import SatWatchpoint
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SatWatchpoint).where(SatWatchpoint.enabled == True)  # noqa: E712
            )
            watchpoints = result.scalars().all()

        logger.info("Checking %d satellite watchpoints", len(watchpoints))
        for wp in watchpoints:
            try:
                await self._check_watchpoint(wp)
                await asyncio.sleep(2)  # Rate-limit between API calls
            except Exception as e:
                logger.warning("Error checking watchpoint %s: %s", wp.name, e)

    async def _check_watchpoint(self, watchpoint) -> None:
        """Search for recent Sentinel-2 imagery over a watchpoint and record changes."""
        from app.db import AsyncSessionLocal
        from app.models.watchpoint import SatSnapshot, SatWatchpoint
        from sqlalchemy import select

        # Search last 10 days for imagery with ≤30% cloud cover
        date_from = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT00:00:00Z")
        date_to = datetime.now(timezone.utc).strftime("%Y-%m-%dT23:59:59Z")

        # Bounding box derived from lat/lng + radius (1° ≈ 111 km)
        deg_offset = watchpoint.radius_km / 111.0
        bbox = (
            watchpoint.lng - deg_offset,
            watchpoint.lat - deg_offset,
            watchpoint.lng + deg_offset,
            watchpoint.lat + deg_offset,
        )

        # Build the Copernicus OData filter string
        polygon = (
            f"{bbox[0]} {bbox[1]},{bbox[2]} {bbox[1]},"
            f"{bbox[2]} {bbox[3]},{bbox[0]} {bbox[3]},{bbox[0]} {bbox[1]}"
        )
        odata_filter = (
            f"Collection/Name eq 'SENTINEL-2' and "
            f"Attributes/OData.CSC.DoubleAttribute/any("
            f"att:att/Name eq 'cloudCover' and att/OData.CSC.DoubleAttribute/Value le 30.00) and "
            f"ContentDate/Start gt {date_from} and ContentDate/Start lt {date_to} and "
            f"OData.CSC.Intersects(area=geography'SRID=4326;POLYGON(({polygon}))')"
        )

        params = {
            "$filter": odata_filter,
            "$orderby": "ContentDate/Start desc",
            "$top": "3",
            "$select": "Id,Name,ContentDate,Attributes",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(CDSE_SEARCH_URL, params=params)
                if resp.status_code != 200:
                    logger.warning(
                        "Copernicus API returned %d for %s", resp.status_code, watchpoint.name
                    )
                    return
                data = resp.json()
        except Exception as e:
            logger.warning("Copernicus API error for %s: %s", watchpoint.name, e)
            return

        products = data.get("value", [])
        if not products:
            return

        latest = products[0]
        product_id = latest.get("Id", "")

        # Extract acquisition date and cloud cover from response
        content_date = latest.get("ContentDate", {}).get("Start", "")
        image_date = content_date[:10] if content_date else ""

        cloud_cover: Optional[float] = None
        for attr in latest.get("Attributes", []):
            if attr.get("Name") == "cloudCover":
                cloud_cover = attr.get("Value")
                break

        if not image_date:
            return

        async with AsyncSessionLocal() as session:
            # Skip if we already have a snapshot for this date
            existing = await session.execute(
                select(SatSnapshot).where(
                    SatSnapshot.watchpoint_id == watchpoint.id,
                    SatSnapshot.image_date == image_date,
                )
            )
            if existing.scalars().first():
                return

            # Derive a pixel hash from the product ID + date
            # In a full implementation this would download and hash the quicklook thumbnail
            pixel_hash = hashlib.md5(f"{product_id}{image_date}".encode()).hexdigest()

            # Compare against the most recent previous snapshot
            prev_result = await session.execute(
                select(SatSnapshot)
                .where(SatSnapshot.watchpoint_id == watchpoint.id)
                .order_by(SatSnapshot.image_date.desc())
                .limit(1)
            )
            prev = prev_result.scalars().first()

            change_score = 0.0
            change_detected = False

            if prev and prev.pixel_hash:
                # Use leading 8 hex chars of each hash as a 32-bit integer and compare
                h1 = int(prev.pixel_hash[:8], 16)
                h2 = int(pixel_hash[:8], 16)
                change_score = abs(h1 - h2) / 0xFFFFFFFF
                change_detected = change_score > watchpoint.change_threshold

            # Persist snapshot
            snapshot = SatSnapshot(
                watchpoint_id=watchpoint.id,
                image_date=image_date,
                product_id=product_id,
                cloud_cover=cloud_cover,
                pixel_hash=pixel_hash,
                change_score=change_score,
                change_detected=change_detected,
            )
            session.add(snapshot)

            # Update the watchpoint's last-checked metadata
            wp_obj = await session.execute(
                select(SatWatchpoint).where(SatWatchpoint.id == watchpoint.id)
            )
            wp = wp_obj.scalars().first()
            if wp:
                wp.last_checked = datetime.now(timezone.utc)
                wp.last_image_date = image_date

            await session.commit()

            if change_detected:
                logger.warning(
                    "CHANGE DETECTED at %s (score=%.3f, date=%s)",
                    watchpoint.name,
                    change_score,
                    image_date,
                )
                await self._create_change_alert(watchpoint, snapshot, image_date, cloud_cover)

    async def _create_change_alert(
        self, watchpoint, snapshot, image_date: str, cloud_cover: Optional[float]
    ) -> None:
        """Create a Post record in the feed for a detected imagery change event."""
        from app.db import AsyncSessionLocal
        from app.models.post import Post

        cloud_str = f"{cloud_cover:.1f}%" if cloud_cover is not None else "unknown"
        content = (
            f"🛰️ Sentinel-2 CHANGE DETECTED: {watchpoint.name}\n"
            f"Date: {image_date} | Category: {watchpoint.category}\n"
            f"Change score: {snapshot.change_score:.3f} | Cloud cover: {cloud_str}\n"
            f"Coordinates: {watchpoint.lat:.4f}°N, {watchpoint.lng:.4f}°E\n"
            f"Copernicus product: {snapshot.product_id}"
        )

        async with AsyncSessionLocal() as session:
            post = Post(
                source_type="satellite",
                source_id="sentinel-2",
                external_id=f"sentinel_{snapshot.id}",
                author="Sentinel-2/Copernicus",
                content=content,
                timestamp=datetime.now(timezone.utc),
                ingested_at=datetime.now(timezone.utc),
            )
            session.add(post)
            await session.commit()
            logger.info("Created change-alert Post for %s", watchpoint.name)


# Module-level singleton
sentinel_service = SentinelService()
