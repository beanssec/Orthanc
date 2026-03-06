"""Satellite tracker using CelesTrak TLE data + sgp4 propagation."""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger("orthanc.collectors.satellite")

CELESTRAK_URLS: dict[str, str] = {
    "stations": "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle",
    "military": "https://celestrak.org/NORAD/elements/gp.php?GROUP=military&FORMAT=tle",
    "weather": "https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle",
}

# Only track these groups (avoid 5000+ Starlink sats)
TRACKED_GROUPS = ["stations", "military", "weather"]

# Per-group max satellites (curate to interesting ones)
GROUP_MAX = {
    "stations": 20,    # ISS, CSS, etc.
    "military": 80,    # US/RU/CN recon, SIGINT, early warning
    "weather": 30,     # NOAA, GOES, Meteosat
}


def _eci_to_geodetic(r: list[float], jd_full: float) -> tuple[float, float, float]:
    """Convert ECI (km) position vector to (lat_deg, lon_deg, alt_km).
    
    Uses the sgp4 WGS-72 model approach — manual conversion from TEME to geodetic.
    """
    # Earth rotation: GMST from Julian date
    # jd_full = JD + fraction
    t_ut1 = (jd_full - 2451545.0) / 36525.0
    # GMST in radians (IAU 1982 formula)
    gmst = (
        67310.54841
        + (876600.0 * 3600.0 + 8640184.812866) * t_ut1
        + 0.093104 * t_ut1**2
        - 6.2e-6 * t_ut1**3
    )
    # Convert to radians, normalize
    gmst_rad = math.radians(gmst / 240.0 % 360.0)

    x, y, z = r  # km

    # ECI → ECEF (rotate by GMST)
    lon_ecef = math.atan2(y, x) - gmst_rad
    r_xy = math.sqrt(x**2 + y**2)

    # WGS-84 constants
    a = 6378.137  # km
    f = 1.0 / 298.257223563
    e2 = 2 * f - f**2

    # Iterative geodetic latitude
    lat = math.atan2(z, r_xy * (1 - e2))
    for _ in range(10):
        N = a / math.sqrt(1 - e2 * math.sin(lat)**2)
        lat_new = math.atan2(z + e2 * N * math.sin(lat), r_xy)
        if abs(lat_new - lat) < 1e-9:
            break
        lat = lat_new

    N = a / math.sqrt(1 - e2 * math.sin(lat)**2)
    alt = r_xy / math.cos(lat) - N if abs(math.cos(lat)) > 1e-10 else abs(z) / math.sin(lat) - N * (1 - e2)

    # Normalize longitude to [-180, 180]
    lon = math.degrees(lon_ecef)
    lon = ((lon + 180) % 360) - 180
    lat_deg = math.degrees(lat)

    return lat_deg, lon, alt


class SatelliteCollector:
    """Tracks satellite positions using TLE data from CelesTrak."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._tle_refresh_task: asyncio.Task | None = None
        self._tle_cache: dict[str, list[tuple[str, Any]]] = {}  # group → [(name, satrec)]
        self._current_positions: list[dict] = []
        self._poll_interval = 30    # Update positions every 30s
        self._tle_refresh_interval = 3600  # Refresh TLE every hour
        self._running = False

    @property
    def current_positions(self) -> list[dict]:
        return self._current_positions

    async def start(self) -> None:
        """Start satellite tracking."""
        if self._running:
            return
        self._running = True
        logger.info("SatelliteCollector starting…")
        try:
            await self._refresh_tles()
            # Compute initial positions immediately
            self._current_positions = self._compute_positions()
        except Exception as exc:
            logger.warning("Initial TLE refresh failed: %s", exc)
        self._task = asyncio.create_task(self._track_loop())
        self._tle_refresh_task = asyncio.create_task(self._tle_refresh_loop())
        logger.info(
            "SatelliteCollector started — tracking %d satellites",
            sum(len(v) for v in self._tle_cache.values()),
        )

    async def stop(self) -> None:
        """Stop satellite tracking."""
        self._running = False
        for task in (self._task, self._tle_refresh_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def _refresh_tles(self) -> None:
        """Download TLE data from CelesTrak."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            for group in TRACKED_GROUPS:
                url = CELESTRAK_URLS.get(group)
                if not url:
                    continue
                try:
                    resp = await client.get(url, headers={"User-Agent": "Orthanc-OSINT/1.0"})
                    resp.raise_for_status()
                    lines = [l.strip() for l in resp.text.strip().split("\n") if l.strip()]
                    max_sats = GROUP_MAX.get(group, 50)
                    sats: list[tuple[str, Any]] = []

                    for i in range(0, len(lines) - 2, 3):
                        if len(sats) >= max_sats:
                            break
                        name = lines[i]
                        line1 = lines[i + 1]
                        line2 = lines[i + 2]
                        if not (line1.startswith("1 ") and line2.startswith("2 ")):
                            continue
                        try:
                            from sgp4.api import Satrec
                            sat = Satrec.twoline2rv(line1, line2)
                            sats.append((name, sat))
                        except Exception as exc:
                            logger.debug("Failed to parse TLE for %s: %s", name, exc)

                    self._tle_cache[group] = sats
                    logger.info("TLE refresh: %s → %d satellites", group, len(sats))
                except Exception as exc:
                    logger.warning("TLE download failed for %s: %s", group, exc)

    async def _tle_refresh_loop(self) -> None:
        """Refresh TLE data hourly."""
        while self._running:
            await asyncio.sleep(self._tle_refresh_interval)
            try:
                await self._refresh_tles()
            except Exception as exc:
                logger.warning("TLE refresh failed: %s", exc)

    async def _track_loop(self) -> None:
        """Compute satellite positions on a regular interval."""
        while self._running:
            try:
                self._current_positions = self._compute_positions()
            except Exception as exc:
                logger.warning("Position compute failed: %s", exc)
            await asyncio.sleep(self._poll_interval)

    def _compute_positions(self) -> list[dict]:
        """Compute current lat/lng/alt for all tracked satellites."""
        try:
            from sgp4.api import jday
        except ImportError:
            logger.warning("sgp4 not installed — satellite tracking disabled")
            return []

        now = datetime.now(timezone.utc)
        jd, fr = jday(
            now.year, now.month, now.day,
            now.hour, now.minute,
            now.second + now.microsecond / 1e6,
        )

        positions: list[dict] = []
        for group, sats in self._tle_cache.items():
            for name, sat in sats:
                try:
                    e, r, v = sat.sgp4(jd, fr)
                    if e != 0:
                        continue
                    lat, lng, alt = _eci_to_geodetic(r, jd + fr)
                    # Sanity check
                    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
                        continue
                    velocity = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
                    positions.append({
                        "name": name,
                        "group": group,
                        "lat": round(lat, 4),
                        "lng": round(lng, 4),
                        "altitude_km": round(alt, 1),
                        "velocity_kms": round(velocity, 2),
                    })
                except Exception:
                    continue

        return positions


# Module-level singleton
satellite_collector = SatelliteCollector()
