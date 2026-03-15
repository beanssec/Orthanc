"""Maritime Advisory Collector — Sprint 32 Checkpoint 2.

Scrapes:
  - US MARAD Maritime Safety Communications with Industry (MSCI) advisories
    https://www.maritime.dot.gov/msci-advisories
  - UKMTO Warnings & Advisories
    https://www.ukmto.org/ukmto-products/warnings

Posts are stored as source_type="maritime_advisory" and are fully idempotent
(duplicate source_ids are silently skipped). All errors are caught and logged;
failures never crash the existing ingestion pipeline.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.db import AsyncSessionLocal
from app.models.event import Event
from app.models.post import Post
from app.services.geo_extractor import geo_extractor

try:
    from lxml import html as lxml_html  # type: ignore
    _LXML = True
except ImportError:
    _LXML = False
    import html as _html_mod  # stdlib

logger = logging.getLogger("orthanc.collectors.maritime_advisory")

POLL_INTERVAL = 1800  # 30 minutes

MARAD_URL = "https://www.maritime.dot.gov/msci-advisories"
UKMTO_URL = "https://www.ukmto.org/ukmto-products/warnings"

# Shared HTTP headers to look like a real browser
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _stable_id(prefix: str, text: str) -> str:
    """Derive a stable de-dup key from prefix + text hash."""
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _clean_text(s: str) -> str:
    """Collapse whitespace and strip."""
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# lxml-based HTML helpers (falls back to regex if lxml unavailable)
# ---------------------------------------------------------------------------

def _extract_text_lxml(page_bytes: bytes) -> list[dict]:
    """
    Parse the raw HTML bytes with lxml and return a list of
    {"title": ..., "body": ..., "url": ...} dicts for each advisory item.
    This is a best-effort extraction that handles a wide variety of page layouts.
    """
    try:
        doc = lxml_html.fromstring(page_bytes)
        items: list[dict] = []

        # Strategy 1: look for <article>, <li>, <tr> elements that contain link + text
        for tag in ("article", "li", "tr", "div"):
            nodes = doc.cssselect(tag) if hasattr(doc, "cssselect") else doc.findall(f".//{tag}")
            for node in nodes:
                # Require at least 30 chars of text content
                node_text = _clean_text(node.text_content() if hasattr(node, "text_content") else "")
                if len(node_text) < 30:
                    continue

                # Grab the first link inside the node as the item URL
                links = node.findall(".//a")
                link_href = ""
                link_text = ""
                if links:
                    link_href = links[0].get("href", "")
                    link_text = _clean_text(links[0].text_content() if hasattr(links[0], "text_content") else "")

                # Skip navigation / header noise
                lower = node_text.lower()
                if any(kw in lower for kw in ("skip to", "home", "sitemap", "contact us", "javascript")):
                    continue

                items.append({
                    "title": link_text or node_text[:120],
                    "body": node_text,
                    "url": link_href,
                })

                # Limit to first 50 candidates to avoid runaway
                if len(items) >= 50:
                    break
            if items:
                break

        # Deduplicate by (title,body) pairs
        seen: set[str] = set()
        unique: list[dict] = []
        for item in items:
            key = item["title"] + item["body"][:80]
            if key not in seen:
                seen.add(key)
                unique.append(item)

        return unique

    except Exception as exc:
        logger.debug("lxml parse error: %s", exc)
        return []


def _extract_text_regex(page_text: str) -> list[dict]:
    """Fallback: pull visible text paragraphs from HTML via regex."""
    # Strip tags
    no_tags = re.sub(r"<[^>]+>", " ", page_text)
    # Collapse whitespace
    clean = re.sub(r"\s+", " ", no_tags).strip()
    # Split on sentence-like boundaries, take chunks >= 60 chars
    chunks = [c.strip() for c in re.split(r"(?<=[.!?])\s+", clean) if len(c.strip()) >= 60]
    return [{"title": c[:120], "body": c, "url": ""} for c in chunks[:40]]


def _parse_advisory_page(page_bytes: bytes, source_name: str, base_url: str) -> list[dict]:
    """
    Top-level parser: try lxml then regex fallback.
    Returns list of {"source_id", "title", "content", "url"} dicts.
    """
    items: list[dict] = []

    if _LXML:
        raw_items = _extract_text_lxml(page_bytes)
    else:
        raw_items = _extract_text_regex(page_bytes.decode("utf-8", errors="replace"))

    for item in raw_items:
        body = item.get("body", "") or item.get("title", "")
        if len(body) < 30:
            continue
        title = item.get("title", body[:100])
        link_href = item.get("url", "")
        # Absolutise relative URLs
        if link_href and not link_href.startswith("http"):
            from urllib.parse import urljoin
            link_href = urljoin(base_url, link_href)

        content = f"[{source_name}] {title}"
        if body and body != title:
            content += f"\n\n{body}"
        if link_href:
            content += f"\n\nSource: {link_href}"

        source_id = _stable_id(source_name.lower().replace(" ", "_"), body)

        items.append({
            "source_id": source_id,
            "title": title,
            "content": content,
            "url": link_href,
        })

    return items


# ---------------------------------------------------------------------------
# Main collector class
# ---------------------------------------------------------------------------

class MaritimeAdvisoryCollector:
    """Polls MARAD and UKMTO advisory pages and persists new advisories as Posts."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the background polling loop."""
        if self.is_running:
            logger.debug("MaritimeAdvisoryCollector already running")
            return
        logger.info("Starting Maritime Advisory Collector (MARAD + UKMTO)")
        self._task = asyncio.create_task(self._run_loop(), name="maritime_advisory_loop")

    async def stop(self) -> None:
        """Cancel the polling loop."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Maritime Advisory Collector stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Poll both sources on startup then every POLL_INTERVAL seconds."""
        while True:
            try:
                await self._poll_all()
            except asyncio.CancelledError:
                logger.info("Maritime advisory loop cancelled")
                raise
            except Exception as exc:
                # Never crash the loop — log and sleep
                logger.error("Maritime advisory poll error (will retry): %s", exc)
            try:
                await asyncio.sleep(POLL_INTERVAL)
            except asyncio.CancelledError:
                raise

    async def _poll_all(self) -> None:
        """Fetch both advisory pages and ingest new items."""
        sources = [
            {
                "name": "MARAD Maritime Advisories",
                "url": MARAD_URL,
                "short": "marad",
            },
            {
                "name": "UKMTO Warnings & Advisories",
                "url": UKMTO_URL,
                "short": "ukmto",
            },
        ]
        for src in sources:
            try:
                await self._poll_source(src["name"], src["url"], src["short"])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # One source failing must not block the other
                logger.warning("Advisory poll failed for %s: %s", src["name"], exc)

    async def _poll_source(self, source_name: str, url: str, short: str) -> None:
        """Fetch one advisory page and ingest any new items."""
        logger.debug("Polling maritime advisory source: %s", url)

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers=_HEADERS,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                page_bytes = resp.content
        except httpx.TimeoutException:
            logger.warning("Timeout fetching %s", url)
            return
        except httpx.HTTPStatusError as exc:
            logger.warning("HTTP %s fetching %s: %s", exc.response.status_code, url, exc)
            return
        except Exception as exc:
            logger.warning("Error fetching %s: %s", url, exc)
            return

        items = _parse_advisory_page(page_bytes, source_name, url)
        logger.debug("Parsed %d candidate items from %s", len(items), source_name)

        new_count = 0
        for item in items:
            try:
                ingested = await self._ingest_item(item, source_name)
                if ingested:
                    new_count += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Failed to ingest advisory item from %s: %s", source_name, exc)

        if new_count:
            logger.info("Maritime advisory %s: ingested %d new items", source_name, new_count)
        else:
            logger.debug("Maritime advisory %s: no new items", source_name)

    async def _ingest_item(self, item: dict, source_name: str) -> bool:
        """
        Insert one advisory item as a Post. Returns True if newly inserted,
        False if it was a duplicate (already exists).
        """
        source_id = item["source_id"]
        content = item["content"]

        async with AsyncSessionLocal() as session:
            from sqlalchemy import select as sa_select
            existing = await session.execute(
                sa_select(Post.id).where(
                    Post.source_type == "maritime_advisory",
                    Post.source_id == source_id,
                )
            )
            if existing.scalars().first():
                return False

            post = Post(
                source_type="maritime_advisory",
                source_id=source_id,
                author=source_name,
                content=content,
                raw_json={
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "source_name": source_name,
                },
                timestamp=datetime.now(timezone.utc),
            )
            session.add(post)
            await session.flush()  # assign post.id

            # Geo extraction (non-blocking — failure must not abort ingest)
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
            except Exception as geo_exc:
                logger.debug("Geo extraction failed for maritime advisory %s: %s", source_id, geo_exc)

            await session.commit()
            logger.debug("Ingested maritime advisory: %s (%s)", item.get("title", source_id)[:80], source_name)

        # Broadcast (non-blocking — never fails ingest on WS error)
        try:
            from app.routers.feed import broadcast_post
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
        except Exception as broadcast_exc:
            logger.debug("Broadcast failed for maritime advisory %s: %s", source_id, broadcast_exc)

        return True


# Module-level singleton
maritime_advisory_collector = MaritimeAdvisoryCollector()
