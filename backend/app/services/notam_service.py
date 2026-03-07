"""NOTAM (Notice to Airmen) service — tracks military-relevant airspace restrictions."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.event import Event
from app.models.post import Post

logger = logging.getLogger("orthanc.services.notam")

POLL_INTERVAL = 900  # 15 minutes

# --------------------------------------------------------------------------
# Flight Information Regions to monitor for military activity
# --------------------------------------------------------------------------

WATCH_FIRS: list[str] = [
    "OIIX",  # Tehran FIR (Iran)
    "OSTT",  # Damascus FIR (Syria)
    "ORBB",  # Baghdad FIR (Iraq)
    "UKBV",  # Kyiv FIR (Ukraine)
    "UKLV",  # Lviv FIR (Ukraine)
    "UMKK",  # Kaliningrad FIR (Russia)
    "ULLL",  # St Petersburg FIR
    "LLLL",  # Tel Aviv FIR (Israel)
    "OLBB",  # Beirut FIR (Lebanon)
    "OYSC",  # Sanaa FIR (Yemen)
    "OEJD",  # Jeddah FIR (Saudi Arabia)
    "OKAC",  # Kuwait FIR
    "OBBB",  # Bahrain FIR
    "OMAE",  # UAE FIR
    "UTTR",  # Tashkent FIR
    "OPLR",  # Lahore FIR (Pakistan)
    "VOMF",  # Chennai FIR (India)
    "ZGZU",  # Guangzhou FIR (China, SCS)
    "RPHI",  # Manila FIR (Philippines, SCS)
    "RKRR",  # Incheon FIR (South Korea)
    "RJJJ",  # Tokyo FIR (Japan)
    "ZKKP",  # Pyongyang FIR (N. Korea)
]

MILITARY_KEYWORDS: list[str] = [
    "MILITARY", "MIL EXERCISE", "LIVE FIRING", "MISSILE", "ROCKET",
    "DANGER AREA", "RESTRICTED AREA", "PROHIBITED AREA", "TFR",
    "GPS INTERFERENCE", "GPS JAMMING", "GNSS", "UNMANNED",
    "DRONE", "UAS", "UAV", "NO FLY", "AIR DEFENSE",
    "NAVAL EXERCISE", "BOMBING", "GUNNERY", "PARATROOP",
    "AEROBATICS MILITARY", "AERIAL REFUELING", "SPECIAL OPERATIONS",
    "EXERCISE", "LASER", "WEAPONS FIRING", "FIREWORKS",  # broader net
]

GPS_KEYWORDS: list[str] = [
    "GPS INTERFERENCE", "GPS JAMMING", "GNSS", "GPS OUTAGE",
    "NAVIGATION UNRELIABLE", "SIGNAL INTERFERENCE",
]

# Q-line format: Q)FIR/QRPCA/IV/NBO/AW/000/999/DDMMN0DDDE999
# The coordinate part is the 8th element (index 7): "DDMMN0DDDE"
Q_LINE_COORD_RE = re.compile(
    r"Q\)[^/]*/[^/]*/[^/]*/[^/]*/[^/]*/[^/]*/[^/]*/([^/]+)/",
    re.IGNORECASE,
)

# Standalone ICAO coordinate pattern in NOTAM body
COORD_RE = re.compile(
    r"(\d{2})(\d{2})(\d{2})?([NS])(\d{3})(\d{2})(\d{2})?([EW])",
    re.IGNORECASE,
)

# NOTAM time format: YYMMDDhhmm (UTC)
NOTAM_TIME_RE = re.compile(r"(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})")

# Pilotweb NOTAM fetch endpoint (free, no auth)
PILOTWEB_URL = (
    "https://notams.aim.faa.gov/notamSearch/"
    "?method=displayByICAOs&formatType=ICAO&actionType=notamRetrievalByICAOs&retrieveLocId={icao}"
)

# FAA external API v2 (requires API key)
FAA_API_URL = "https://external-api.faa.gov/notamapi/v1/notams"


# ---------------------------------------------------------------------------
# Coordinate parsing helpers
# ---------------------------------------------------------------------------

def parse_icao_coord(coord_str: str) -> tuple[float, float] | None:
    """Parse ICAO coordinate string to (lat, lng).

    Handles formats:
    - DDMM[N/S]DDDMM[E/W]   e.g. 3245N05137E
    - DDMMSS[N/S]DDDMMSS[E/W] e.g. 324530N0513700E
    """
    coord_str = coord_str.strip().upper()
    m = COORD_RE.match(coord_str)
    if not m:
        return None
    try:
        lat = int(m.group(1)) + int(m.group(2)) / 60 + int(m.group(3) or 0) / 3600
        if m.group(4) == "S":
            lat = -lat
        lng = int(m.group(5)) + int(m.group(6)) / 60 + int(m.group(7) or 0) / 3600
        if m.group(8) == "W":
            lng = -lng
        # Sanity check
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return None
        return (round(lat, 5), round(lng, 5))
    except (ValueError, TypeError):
        return None


def _parse_notam_time(time_str: str) -> datetime | None:
    """Parse a NOTAM time string (YYMMDDhhmm) to a UTC datetime."""
    time_str = time_str.strip()
    if len(time_str) < 10:
        return None
    m = NOTAM_TIME_RE.match(time_str[:10])
    if not m:
        return None
    try:
        yy, mo, dd, hh, mn = (int(x) for x in m.groups())
        year = 2000 + yy if yy < 80 else 1900 + yy
        return datetime(year, mo, dd, hh, mn, tzinfo=timezone.utc)
    except (ValueError, OverflowError):
        return None


# ---------------------------------------------------------------------------
# Parser — extract structured fields from raw NOTAM text
# ---------------------------------------------------------------------------

def parse_notam_text(notam_text: str) -> dict:
    """Extract fields from a raw ICAO NOTAM string.

    Returns a dict with keys: notam_id, fir, q_code, start_time, end_time,
    lat, lng, radius_nm, lower_fl, upper_fl, body, type.
    """
    result: dict = {
        "notam_id": None,
        "fir": None,
        "q_code": None,
        "start_time": None,
        "end_time": None,
        "lat": None,
        "lng": None,
        "radius_nm": None,
        "lower_fl": None,
        "upper_fl": None,
        "body": notam_text.strip(),
        "type": "standard",
        "raw_text": notam_text.strip(),
    }

    lines = notam_text.strip().split("\n")
    full_text = " ".join(lines)

    # Extract NOTAM ID from first line: A1234/24 NOTAMN
    id_m = re.search(r"\b([A-Z]\d{4}/\d{2})\b", full_text)
    if id_m:
        result["notam_id"] = id_m.group(1)

    # Parse Q-line
    q_m = re.search(r"Q\)([^\n]+)", notam_text, re.IGNORECASE)
    if q_m:
        q_parts = q_m.group(1).strip().split("/")
        if len(q_parts) >= 1:
            result["fir"] = q_parts[0].strip()
        if len(q_parts) >= 2:
            result["q_code"] = q_parts[1].strip()
        # Q-line lower/upper flight levels
        if len(q_parts) >= 7:
            try:
                result["lower_fl"] = int(q_parts[5].strip())
                result["upper_fl"] = int(q_parts[6].strip())
            except (ValueError, IndexError):
                pass
        # Q-line coordinates: format DDMMN DDDMME or DDMM[N/S]DDDMM[E/W]
        if len(q_parts) >= 9:
            raw_coord = q_parts[7].strip() + q_parts[8].strip()
            coords = parse_icao_coord(raw_coord)
            if coords:
                result["lat"], result["lng"] = coords
        if len(q_parts) >= 10:
            try:
                result["radius_nm"] = int(q_parts[9].strip())
            except (ValueError, IndexError):
                pass

    # Parse B) (start time)
    b_m = re.search(r"B\)\s*(\d{10})", notam_text, re.IGNORECASE)
    if b_m:
        result["start_time"] = _parse_notam_time(b_m.group(1))

    # Parse C) (end time) — may be "PERM" or have EST suffix
    c_m = re.search(r"C\)\s*(\d{10}|PERM)", notam_text, re.IGNORECASE)
    if c_m:
        val = c_m.group(1).strip().upper()
        if val == "PERM":
            result["end_time"] = datetime(2099, 12, 31, tzinfo=timezone.utc)
        else:
            result["end_time"] = _parse_notam_time(val)

    # If no coords from Q-line, scan body for coordinates
    if result["lat"] is None:
        e_m = re.search(r"E\)\s*(.+?)(?:\nF\)|\nG\)|\Z)", notam_text, re.IGNORECASE | re.DOTALL)
        body_text = e_m.group(1) if e_m else notam_text
        # Find first coordinate pair in body
        for cm in COORD_RE.finditer(body_text.upper()):
            coord_raw = cm.group(0)
            coords = parse_icao_coord(coord_raw)
            if coords:
                result["lat"], result["lng"] = coords
                break

    # Extract body (E-line)
    e_m = re.search(r"E\)\s*(.+?)(?:\nF\)|\nG\)|\Z)", notam_text, re.IGNORECASE | re.DOTALL)
    if e_m:
        result["body"] = e_m.group(1).strip()

    # Classify type
    body_upper = (result["body"] or "").upper()
    if any(kw in body_upper for kw in GPS_KEYWORDS):
        result["type"] = "gps_jamming"
    elif "TFR" in body_upper or re.search(r"Q\)[A-Z]*/Q[RT][LR]", notam_text or "", re.IGNORECASE):
        result["type"] = "tfr"
    elif any(kw in body_upper for kw in ["MILITARY", "MIL EXERCISE", "EXERCISE", "LIVE FIRING",
                                          "BOMBING", "GUNNERY", "MISSILE", "NAVAL EXERCISE"]):
        result["type"] = "military"

    return result


# ---------------------------------------------------------------------------
# Main service class
# ---------------------------------------------------------------------------

class NOTAMService:
    """Polls multiple FIRs for military-relevant NOTAMs."""

    def __init__(self, poll_interval: int = POLL_INTERVAL) -> None:
        self._poll_interval = poll_interval
        self._task: asyncio.Task | None = None
        self._running = False

    # ---- Public API -------------------------------------------------------

    async def start_polling(self) -> None:
        """Start the background polling loop."""
        if self._running:
            logger.info("NOTAM service already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="notam_poll")
        logger.info("NOTAM service started — polling %d FIRs every %ds", len(WATCH_FIRS), self._poll_interval)

    async def stop(self) -> None:
        """Cancel the polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("NOTAM service stopped")

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ---- Polling logic ----------------------------------------------------

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("NOTAM poll error: %s", exc)
            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                raise

    async def _poll_once(self) -> None:
        logger.info("Polling NOTAMs for %d FIRs", len(WATCH_FIRS))
        all_notams = await self.poll_all_watched()
        if all_notams:
            await self._store_notams(all_notams)

    async def poll_all_watched(self) -> list[dict]:
        """Poll all watched FIRs, return list of military-relevant NOTAM dicts."""
        results: list[dict] = []

        # Check if FAA API key is configured
        faa_key = await self._get_faa_api_key()

        for fir in WATCH_FIRS:
            try:
                if faa_key:
                    notams = await self._fetch_via_faa_api(fir, faa_key)
                else:
                    notams = await self._fetch_via_pilotweb(fir)

                for n in notams:
                    body = (n.get("body") or n.get("raw_text") or "").upper()
                    if self.is_military_relevant(body):
                        n["fir"] = n.get("fir") or fir
                        results.append(n)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Failed to fetch NOTAMs for FIR %s: %s", fir, exc)

            # Small delay between FIR requests to be polite
            await asyncio.sleep(0.5)

        logger.info("NOTAM poll complete: %d military-relevant NOTAMs found", len(results))
        return results

    async def fetch_notams(self, fir: str) -> list[dict]:
        """Fetch and parse NOTAMs for a single FIR."""
        faa_key = await self._get_faa_api_key()
        if faa_key:
            return await self._fetch_via_faa_api(fir, faa_key)
        return await self._fetch_via_pilotweb(fir)

    # ---- Data source adapters --------------------------------------------

    async def _fetch_via_pilotweb(self, fir: str) -> list[dict]:
        """Fetch NOTAMs from FAA PilotWeb (free, no auth)."""
        url = PILOTWEB_URL.format(icao=fir)
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(
                    url,
                    headers={"Accept": "text/html,application/xhtml+xml"},
                )
                if resp.status_code == 404:
                    logger.debug("PilotWeb 404 for FIR %s (non-FAA FIR, skipping)", fir)
                    return []
                resp.raise_for_status()
                return self._parse_pilotweb_response(resp.text, fir)
        except httpx.TimeoutException:
            logger.debug("PilotWeb timeout for FIR %s", fir)
            return []
        except httpx.HTTPStatusError as exc:
            logger.debug("PilotWeb HTTP %d for FIR %s", exc.response.status_code, fir)
            return []

    def _parse_pilotweb_response(self, html: str, fir: str) -> list[dict]:
        """Parse PilotWeb HTML to extract NOTAM text blocks."""
        notams: list[dict] = []

        # PilotWeb wraps each NOTAM in <pre> tags or as plain text blocks
        pre_blocks = re.findall(r"<pre[^>]*>(.*?)</pre>", html, re.DOTALL | re.IGNORECASE)
        if not pre_blocks:
            # Fallback: try to extract NOTAM text blocks (A####/## format)
            pre_blocks = re.findall(
                r"([A-Z]\d{4}/\d{2}\s+NOTAM[NRC].*?)(?=[A-Z]\d{4}/\d{2}\s+NOTAM|\Z)",
                html,
                re.DOTALL,
            )

        for block in pre_blocks:
            # Strip HTML tags
            text = re.sub(r"<[^>]+>", "", block).strip()
            if not text or len(text) < 20:
                continue
            try:
                parsed = parse_notam_text(text)
                if not parsed.get("notam_id"):
                    continue
                if not parsed.get("fir"):
                    parsed["fir"] = fir
                notams.append(parsed)
            except Exception as exc:
                logger.debug("NOTAM parse error: %s", exc)

        return notams

    async def _fetch_via_faa_api(self, fir: str, api_key: str) -> list[dict]:
        """Fetch NOTAMs using the FAA NOTAM API v2."""
        params = {
            "icaoLocation": fir,
            "pageSize": "1000",
            "pageNum": "1",
        }
        headers = {
            "client_id": api_key,
            "client_secret": "",  # Some implementations use key-only
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(FAA_API_URL, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return self._parse_faa_api_response(data, fir)
        except httpx.HTTPStatusError as exc:
            logger.warning("FAA API HTTP %d for FIR %s", exc.response.status_code, fir)
            return []

    def _parse_faa_api_response(self, data: dict, fir: str) -> list[dict]:
        """Parse FAA API v2 JSON response."""
        notams: list[dict] = []
        items = data.get("items", [])
        for item in items:
            try:
                props = item.get("properties", {})
                notam_text = props.get("icaoMessage") or props.get("traditionalMessage") or ""
                if not notam_text:
                    continue
                parsed = parse_notam_text(notam_text)

                # Override with structured API fields where available
                if props.get("notamNumber"):
                    parsed["notam_id"] = props["notamNumber"]
                if props.get("location"):
                    parsed["fir"] = parsed.get("fir") or props["location"]
                if props.get("effectiveStart"):
                    try:
                        parsed["start_time"] = datetime.fromisoformat(
                            props["effectiveStart"].replace("Z", "+00:00")
                        )
                    except (ValueError, AttributeError):
                        pass
                if props.get("effectiveEnd"):
                    try:
                        parsed["end_time"] = datetime.fromisoformat(
                            props["effectiveEnd"].replace("Z", "+00:00")
                        )
                    except (ValueError, AttributeError):
                        pass

                # Lat/lng from API geometry
                geom = item.get("geometry", {})
                if geom.get("type") == "Point":
                    coords = geom.get("coordinates", [])
                    if len(coords) >= 2:
                        parsed["lng"] = coords[0]
                        parsed["lat"] = coords[1]

                parsed.setdefault("fir", fir)
                notams.append(parsed)
            except Exception as exc:
                logger.debug("FAA API parse error for item: %s", exc)

        return notams

    # ---- Keyword helpers -------------------------------------------------

    def is_military_relevant(self, notam_text: str) -> bool:
        """Return True if the NOTAM text contains military-relevant keywords."""
        upper = notam_text.upper()
        return any(kw in upper for kw in MILITARY_KEYWORDS)

    # ---- Credential lookup -----------------------------------------------

    async def _get_faa_api_key(self) -> Optional[str]:
        """Check if any user has configured a NOTAM/FAA API key."""
        try:
            from app.services.collector_manager import collector_manager
            # collector_manager is per-user; we look for any user with 'notam' creds
            # For simplicity: iterate over cached keys
            if hasattr(collector_manager, "_cache"):
                for user_keys in collector_manager._cache.values():
                    notam_keys = user_keys.get("notam", {})
                    if notam_keys:
                        return notam_keys.get("api_key") or notam_keys.get("client_id")
        except Exception:
            pass
        return None

    # ---- Database storage ------------------------------------------------

    async def _store_notams(self, notams: list[dict]) -> None:
        """Persist parsed NOTAMs as Post + Event records."""
        new_count = 0
        now = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as session:
            for notam in notams:
                notam_id = notam.get("notam_id")
                if not notam_id:
                    # Generate deterministic ID from text hash
                    notam_id = "AUTO-" + hashlib.md5(
                        (notam.get("raw_text") or "")[:200].encode()
                    ).hexdigest()[:8].upper()

                fir = notam.get("fir", "UNKN")
                external_id = f"notam:{fir}:{notam_id}"

                # Dedup check
                existing = await session.execute(
                    select(Post).where(Post.external_id == external_id)
                )
                if existing.scalar_one_or_none():
                    continue

                start_time: datetime | None = notam.get("start_time")
                end_time: datetime | None = notam.get("end_time")
                notam_type: str = notam.get("type", "standard")

                # Build content summary
                body = (notam.get("body") or notam.get("raw_text") or "")[:500]
                content_parts = [
                    f"NOTAM {notam_id} [{fir}]",
                    f"Type: {notam_type.upper()}",
                ]
                if start_time:
                    content_parts.append(f"Valid: {start_time.strftime('%Y-%m-%d %H:%MZ')}")
                if end_time and end_time.year < 2090:
                    content_parts.append(f"Until: {end_time.strftime('%Y-%m-%d %H:%MZ')}")
                content_parts.append(body)
                content = "\n".join(content_parts)

                raw_meta = {
                    "notam_id": notam_id,
                    "fir": fir,
                    "q_code": notam.get("q_code"),
                    "type": notam_type,
                    "start_time": start_time.isoformat() if start_time else None,
                    "end_time": end_time.isoformat() if end_time else None,
                    "lower_fl": notam.get("lower_fl"),
                    "upper_fl": notam.get("upper_fl"),
                    "radius_nm": notam.get("radius_nm"),
                    "lat": notam.get("lat"),
                    "lng": notam.get("lng"),
                }

                post = Post(
                    source_type="notam",
                    source_id=notam_id,
                    author=f"FAA/ICAO NOTAM — {fir}",
                    content=content,
                    raw_json=raw_meta,
                    timestamp=start_time or now,
                    external_id=external_id,
                )
                session.add(post)
                await session.flush()

                # Create geo event if we have coordinates
                lat = notam.get("lat")
                lng = notam.get("lng")
                if lat is not None and lng is not None:
                    geo_event = Event(
                        post_id=post.id,
                        lat=lat,
                        lng=lng,
                        place_name=f"NOTAM {notam_id} — {fir}",
                        confidence=0.9,
                        precision="exact",
                    )
                    session.add(geo_event)

                new_count += 1

            await session.commit()

        if new_count:
            logger.info("NOTAM service: stored %d new NOTAMs", new_count)


# Module-level singleton
notam_service = NOTAMService()
