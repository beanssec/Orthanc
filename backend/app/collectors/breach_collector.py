"""Have I Been Pwned breach collector — Sprint 33 CP1c (TASK-78).

Fetches the public HIBP breach list (no API key required) and stores
government/military/intelligence-relevant breaches as posts.

Endpoint: GET https://haveibeenpwned.com/api/v3/breaches
Poll interval: daily
Source type: "breach" / source class stored in raw_json as "official_data"
"""
from __future__ import annotations

import asyncio
import hashlib
import html as html_module
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.post import Post
from app.routers.feed import broadcast_post

logger = logging.getLogger("orthanc.collectors.breach")

HIBP_BREACHES_URL = "https://haveibeenpwned.com/api/v3/breaches"
POLL_INTERVAL_SECONDS = 86400  # daily
REQUEST_TIMEOUT = 30

_BROWSER_HEADERS = {
    "User-Agent": "orthanc-osint/1.0 (breach monitoring)",
    "Accept": "application/json",
}

# Categories of interest for OSINT / national security context
_RELEVANT_GOV_SIGNALS = (
    ".gov",
    ".mil",
    ".edu",
    "government",
    "military",
    "defense",
    "ministry",
    "federal",
    "police",
    "intelligence",
)

_SENSITIVE_DATA_CLASSES = frozenset({
    "Passwords",
    "Government issued IDs",
    "Social security numbers",
    "Financial data",
    "Health records",
    "Military personnel",
})


def _clean_html(raw: str) -> str:
    """Strip HTML tags and decode HTML entities."""
    clean = re.sub(r"<[^>]+>", " ", raw or "")
    clean = html_module.unescape(clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:1000]


def _make_external_id(breach_name: str) -> str:
    return f"breach:hibp:{breach_name.lower().replace(' ', '-')}"


def _is_relevant(breach: dict) -> bool:
    """Check if a breach is relevant for OSINT interest."""
    categories = set(breach.get("DataClasses") or [])
    domain = (breach.get("Domain") or "").lower()
    name = (breach.get("Name") or "").lower()

    # Domain/name heuristics for government/military
    for signal in _RELEVANT_GOV_SIGNALS:
        if signal in domain or signal in name:
            return True

    # DataClasses fallback — include if sensitive PII exposed
    if _SENSITIVE_DATA_CLASSES & categories:
        return True

    return False


class BreachCollector:
    """Polls the HIBP public breach list daily and ingests relevant entries."""

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Breach collector started")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Breach collector stopped")

    async def _loop(self) -> None:
        await asyncio.sleep(180)  # startup delay
        while self._running:
            try:
                await self._collect()
            except Exception as exc:
                logger.error("Breach collector cycle error: %s", exc)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _collect(self) -> None:
        """Fetch HIBP breach list and store relevant entries."""
        breaches = await self._fetch_breaches()
        if breaches is None:
            return

        relevant = [b for b in breaches if _is_relevant(b)]
        logger.info(
            "Breach collector: %d total breaches, %d relevant",
            len(breaches), len(relevant),
        )

        saved = 0
        for breach in relevant:
            try:
                stored = await self._store_breach(breach)
                if stored:
                    saved += 1
            except Exception as exc:
                logger.warning(
                    "Failed to store breach %s: %s",
                    breach.get("Name", "?"), exc,
                )

        if saved:
            logger.info("Breach collector: stored %d new breach records", saved)

    async def _fetch_breaches(self) -> Optional[list[dict]]:
        """Fetch the full HIBP breach list."""
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                resp = await client.get(
                    HIBP_BREACHES_URL,
                    headers=_BROWSER_HEADERS,
                    params={"truncateResponse": "false"},
                )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.warning("HIBP API unreachable: %s", exc)
            return None

        if resp.status_code == 429:
            logger.warning("HIBP API rate-limited — will retry next cycle")
            return None

        if resp.status_code != 200:
            logger.warning("HIBP API returned HTTP %d", resp.status_code)
            return None

        try:
            return resp.json()
        except Exception as exc:
            logger.error("HIBP API: JSON parse failed: %s", exc)
            return None

    async def _store_breach(self, breach: dict) -> bool:
        """Persist a breach as a post. Returns True if newly inserted."""
        name = breach.get("Name") or "Unknown"
        external_id = _make_external_id(name)

        async with AsyncSessionLocal() as session:
            existing = await session.execute(
                select(Post.id).where(Post.external_id == external_id)
            )
            if existing.scalar():
                return False

        domain = breach.get("Domain") or ""
        breach_date = breach.get("BreachDate") or ""
        added_date = breach.get("AddedDate") or ""
        pwn_count = breach.get("PwnCount") or 0
        data_classes = breach.get("DataClasses") or []
        description_raw = breach.get("Description") or ""
        description = _clean_html(description_raw)

        # Parse breach date for the post timestamp
        ts = datetime.now(timezone.utc)
        for fmt in ("%Y-%m-%d", "%Y-%m"):
            try:
                ts = datetime.strptime(breach_date, fmt).replace(tzinfo=timezone.utc)
                break
            except (ValueError, TypeError):
                pass

        content = (
            f"[BREACH] {name}"
            + (f" ({domain})" if domain else "")
            + f" — {pwn_count:,} accounts compromised"
            + (f" — Breach date: {breach_date}" if breach_date else "")
            + f"\nData types: {', '.join(data_classes[:10])}"
            + (f"\n{description}" if description else "")
        )

        post = Post(
            source_type="breach",
            source_id="hibp",
            author="HIBP",
            content=content[:2000],
            external_id=external_id,
            timestamp=ts,
            raw_json={
                "source_class": "official_data",
                "reliability_prior": 0.85,  # HIBP is a curated data source
                "breach_name": name,
                "domain": domain,
                "breach_date": breach_date,
                "added_date": added_date,
                "pwn_count": pwn_count,
                "data_classes": data_classes,
                "is_verified": breach.get("IsVerified", False),
                "is_sensitive": breach.get("IsSensitive", False),
                "is_fabricated": breach.get("IsFabricated", False),
                "source": "hibp",
                "hibp_url": f"https://haveibeenpwned.com/PwnedWebsites#{name}",
            },
        )

        async with AsyncSessionLocal() as session:
            session.add(post)
            try:
                await session.commit()
                await session.refresh(post)
                await broadcast_post(post)
                return True
            except Exception as exc:
                await session.rollback()
                logger.debug("Breach post save conflict (likely duplicate): %s", exc)
                return False


# Singleton
breach_collector = BreachCollector()
