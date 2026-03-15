"""Official Sources Collector — diplomatic press releases and web sources.

Collects from:
  1. OFAC Recent Actions    — https://ofac.treasury.gov/recent-actions
  2. US State Dept RSS      — https://www.state.gov/rss-feed/press-releases/feed/
  3. China MFA Spokesperon  — https://www.fmprc.gov.cn/eng/xw/fyrbt/
  4. OPEC Press Releases    — https://www.opec.org/press-releases.html

All posts are stored in the posts table with source-specific source_type values.
Errors in any single source never crash the overall collection loop.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.post import Post
from app.routers.feed import broadcast_post
from app.services.entity_extractor import entity_extractor
from app.services.geo_extractor import geo_extractor
from app.models.entity import Entity, EntityMention
from app.models.event import Event

logger = logging.getLogger("orthanc.collectors.official_sources")

# ── Source definitions ────────────────────────────────────────────────────────

SOURCES = {
    "state_dept_rss": {
        "display_name": "US State Department Press Releases",
        "url": "https://www.state.gov/rss-feed/press-releases/feed/",
        "source_class": "official",
        "default_reliability_prior": "high",
        "ecosystem": "diplomacy",
        "language": "English",
        "poll_interval": 600,  # 10 min
        "collector": "rss",
    },
    "ofac_recent_actions": {
        "display_name": "OFAC Recent Actions",
        "url": "https://ofac.treasury.gov/recent-actions",
        "source_class": "official",
        "default_reliability_prior": "high",
        "ecosystem": "sanctions",
        "language": "English",
        "poll_interval": 3600,  # 1 hour
        "collector": "scraper",
    },
    "china_mfa": {
        "display_name": "China MFA Spokesperson Remarks",
        "url": "https://www.fmprc.gov.cn/eng/xw/fyrbt/",
        "source_class": "official",
        "default_reliability_prior": "high",
        "ecosystem": "diplomacy",
        "language": "English",
        "poll_interval": 3600,
        "collector": "scraper",
    },
    "opec_press": {
        "display_name": "OPEC Press Releases",
        "url": "https://www.opec.org/press-releases.html",
        "source_class": "official",
        "default_reliability_prior": "high",
        "ecosystem": "energy",
        "language": "English",
        "poll_interval": 3600,
        "collector": "scraper",
    },
}

# ── Utility ───────────────────────────────────────────────────────────────────

def _stable_id(source_type: str, url_or_text: str) -> str:
    """Generate a stable dedup ID from source_type + URL/text."""
    digest = hashlib.sha256(url_or_text.encode("utf-8")).hexdigest()[:16]
    return f"{source_type}:{digest}"


def _strip_html(text: str) -> str:
    """Very light HTML strip — remove tags and decode common entities."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def _parse_rss_timestamp(entry) -> Optional[datetime]:
    """Extract timezone-aware datetime from a feedparser entry."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        val = getattr(entry, attr, None)
        if val and isinstance(val, time.struct_time):
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


async def _persist_post(
    source_type: str,
    source_id: str,
    author: str,
    content: str,
    raw_json: dict,
    timestamp: Optional[datetime],
) -> None:
    """Dedup-check and persist a Post, then broadcast and run enrichment."""
    async with AsyncSessionLocal() as session:
        # Dedup check
        existing = await session.execute(
            select(Post).where(
                Post.source_type == source_type,
                Post.source_id == source_id,
            )
        )
        if existing.scalars().first():
            return

        post = Post(
            source_type=source_type,
            source_id=source_id,
            author=author,
            content=content,
            raw_json=raw_json,
            timestamp=timestamp,
        )
        session.add(post)
        await session.flush()

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
            geo_events = await geo_extractor.process_post(str(post.id), post.content or "")
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
            logger.warning("Geo extraction failed for post %s: %s", post.id, geo_exc)

        # Entity extraction
        try:
            extracted_ents = await entity_extractor.extract_entities_async(post.content or "")
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
                    entity.last_seen = datetime.now(tz=timezone.utc)
                else:
                    entity = Entity(
                        name=ent["name"],
                        type=ent["type"],
                        canonical_name=canonical,
                        mention_count=1,
                    )
                    session.add(entity)
                    await session.flush()
                mention = EntityMention(
                    entity_id=entity.id,
                    post_id=post.id,
                    context_snippet=ent["context_snippet"],
                )
                session.add(mention)
        except Exception as ent_exc:
            logger.warning("Entity extraction failed for post %s: %s", post.id, ent_exc)

        await session.commit()


# ── Individual source collectors ──────────────────────────────────────────────

async def _collect_state_dept_rss() -> int:
    """Collect US State Department press releases via RSS."""
    source_cfg = SOURCES["state_dept_rss"]
    url = source_cfg["url"]

    loop = asyncio.get_event_loop()
    try:
        parsed = await loop.run_in_executor(None, feedparser.parse, url)
    except Exception as exc:
        logger.error("State Dept RSS fetch error: %s", exc)
        return 0

    if parsed.get("bozo") and not parsed.entries:
        logger.warning("State Dept RSS parse error: %s", parsed.get("bozo_exception"))
        return 0

    new_count = 0
    for entry in parsed.entries:
        try:
            guid = entry.get("id") or entry.get("link", "")
            if not guid:
                continue

            title = entry.get("title", "")
            summary = entry.get("summary", entry.get("description", ""))
            content = f"{title}\n\n{_strip_html(summary)}".strip()
            ts = _parse_rss_timestamp(entry)

            raw = {
                "title": title,
                "link": entry.get("link", ""),
                "summary": summary,
                **{k: v for k, v in source_cfg.items() if k not in ("url", "collector", "poll_interval")},
            }

            await _persist_post(
                source_type="state_dept_rss",
                source_id=guid,
                author="US State Department",
                content=content,
                raw_json=raw,
                timestamp=ts,
            )
            new_count += 1
        except Exception as exc:
            logger.warning("State Dept RSS entry error: %s", exc)

    if new_count:
        logger.info("State Dept RSS: %d new posts", new_count)
    return new_count


async def _collect_ofac_recent_actions() -> int:
    """Scrape OFAC Recent Actions page for new entries."""
    source_cfg = SOURCES["ofac_recent_actions"]
    url = source_cfg["url"]

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Orthanc/1.0; +https://orthanc.io)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except httpx.HTTPError as exc:
        logger.error("OFAC Recent Actions fetch error: %s", exc)
        return 0

    # Extract action entries — OFAC page uses table rows or list items
    new_count = 0
    entries = _parse_ofac_recent_actions_html(html)

    for entry in entries:
        try:
            content = entry.get("text", "").strip()
            if not content:
                continue

            link = entry.get("link", "")
            source_id = _stable_id("ofac_recent_actions", link or content[:200])

            raw = {
                "link": link,
                "date_str": entry.get("date", ""),
                **{k: v for k, v in source_cfg.items() if k not in ("url", "collector", "poll_interval")},
            }

            # Parse date if available
            ts: Optional[datetime] = None
            date_str = entry.get("date", "")
            if date_str:
                for fmt in ("%m/%d/%Y", "%B %d, %Y", "%Y-%m-%d"):
                    try:
                        ts = datetime.strptime(date_str.strip(), fmt).replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        pass

            await _persist_post(
                source_type="ofac_recent_actions",
                source_id=source_id,
                author="OFAC",
                content=content,
                raw_json=raw,
                timestamp=ts,
            )
            new_count += 1
        except Exception as exc:
            logger.warning("OFAC Recent Actions entry error: %s", exc)

    if new_count:
        logger.info("OFAC Recent Actions: %d new entries", new_count)
    return new_count


def _parse_ofac_recent_actions_html(html: str) -> list[dict]:
    """Parse OFAC recent actions page — handles multiple table/list layouts."""
    entries: list[dict] = []
    try:
        from html.parser import HTMLParser

        class OFACParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self._in_row = False
                self._in_cell = False
                self._cells: list[str] = []
                self._current_cell = ""
                self._links: list[str] = []
                self._current_link: str = ""
                self._results: list[dict] = []

            def handle_starttag(self, tag, attrs):
                attrs_dict = dict(attrs)
                if tag == "tr":
                    self._in_row = True
                    self._cells = []
                    self._links = []
                elif tag in ("td", "th") and self._in_row:
                    self._in_cell = True
                    self._current_cell = ""
                elif tag == "a" and self._in_cell:
                    href = attrs_dict.get("href", "")
                    if href:
                        self._current_link = href

            def handle_endtag(self, tag):
                if tag in ("td", "th") and self._in_cell:
                    self._cells.append(self._current_cell.strip())
                    if self._current_link:
                        self._links.append(self._current_link)
                        self._current_link = ""
                    self._in_cell = False
                elif tag == "tr" and self._in_row:
                    if len(self._cells) >= 2:
                        date_part = self._cells[0]
                        text_part = " | ".join(self._cells[1:])
                        # Skip header rows
                        if text_part and not text_part.lower().startswith("action"):
                            self._results.append({
                                "date": date_part,
                                "text": _strip_html(text_part),
                                "link": self._links[0] if self._links else "",
                            })
                    self._in_row = False

            def handle_data(self, data):
                if self._in_cell:
                    self._current_cell += data

        parser = OFACParser()
        parser.feed(html)
        entries = parser._results

        # If table parsing found nothing, try extracting paragraphs with date patterns
        if not entries:
            date_pattern = re.compile(
                r"(\d{1,2}/\d{1,2}/\d{4}|\w+ \d{1,2}, \d{4})"
            )
            paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", html, re.DOTALL | re.IGNORECASE)
            for p in paragraphs:
                text = _strip_html(p).strip()
                if len(text) < 20:
                    continue
                date_match = date_pattern.search(text)
                date_str = date_match.group(0) if date_match else ""
                link_match = re.search(r'href="([^"]+)"', p)
                link = link_match.group(1) if link_match else ""
                entries.append({"date": date_str, "text": text, "link": link})

    except Exception as exc:
        logger.warning("OFAC HTML parse error: %s", exc)

    return entries[:100]  # cap at 100 entries per poll


async def _collect_china_mfa() -> int:
    """Scrape China MFA spokesperson briefings page."""
    source_cfg = SOURCES["china_mfa"]
    url = source_cfg["url"]

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Orthanc/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except httpx.HTTPError as exc:
        logger.error("China MFA fetch error: %s", exc)
        return 0

    entries = _parse_china_mfa_html(html)
    new_count = 0

    for entry in entries:
        try:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            date_str = entry.get("date", "")

            if not title and not link:
                continue

            content = title
            source_id = _stable_id("china_mfa", link or title)

            # Make absolute URL
            if link and not link.startswith("http"):
                link = "https://www.fmprc.gov.cn" + link

            raw = {
                "title": title,
                "link": link,
                "date_str": date_str,
                **{k: v for k, v in source_cfg.items() if k not in ("url", "collector", "poll_interval")},
            }

            ts: Optional[datetime] = None
            if date_str:
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%B %d, %Y"):
                    try:
                        ts = datetime.strptime(date_str.strip(), fmt).replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        pass

            await _persist_post(
                source_type="china_mfa",
                source_id=source_id,
                author="China MFA Spokesperson",
                content=content,
                raw_json=raw,
                timestamp=ts,
            )
            new_count += 1
        except Exception as exc:
            logger.warning("China MFA entry error: %s", exc)

    if new_count:
        logger.info("China MFA: %d new briefings", new_count)
    return new_count


def _parse_china_mfa_html(html: str) -> list[dict]:
    """Parse China MFA briefings list page."""
    entries: list[dict] = []
    try:
        # Extract article links from the briefings list
        # Pattern: <a href="/eng/xw/fyrbt/...">Title</a>
        link_pattern = re.compile(
            r'<a[^>]+href="(/eng/xw/fyrbt/[^"]+)"[^>]*>\s*(.*?)\s*</a>',
            re.DOTALL | re.IGNORECASE,
        )
        date_pattern = re.compile(r"(\d{4}-\d{2}-\d{2}|\d{4}/\d{2}/\d{2})")

        for m in link_pattern.finditer(html):
            href = m.group(1)
            title = _strip_html(m.group(2)).strip()
            if not title or len(title) < 5:
                continue
            # Try to find date near this link
            pos = m.start()
            nearby = html[max(0, pos - 200):pos + 200]
            date_m = date_pattern.search(nearby)
            date_str = date_m.group(0).replace("/", "-") if date_m else ""

            entries.append({"title": title, "link": href, "date": date_str})
            if len(entries) >= 50:
                break

        # Also try generic list items
        if not entries:
            li_pattern = re.compile(
                r'<li[^>]*>.*?<a[^>]+href="([^"]*fyrbt[^"]*)"[^>]*>(.*?)</a>.*?</li>',
                re.DOTALL | re.IGNORECASE,
            )
            for m in li_pattern.finditer(html):
                href = m.group(1)
                title = _strip_html(m.group(2)).strip()
                if title and len(title) >= 5:
                    entries.append({"title": title, "link": href, "date": ""})
                if len(entries) >= 50:
                    break

    except Exception as exc:
        logger.warning("China MFA HTML parse error: %s", exc)

    return entries


async def _collect_opec_press() -> int:
    """Scrape OPEC press releases page."""
    source_cfg = SOURCES["opec_press"]
    url = source_cfg["url"]

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Orthanc/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except httpx.HTTPError as exc:
        logger.error("OPEC press releases fetch error: %s", exc)
        return 0

    entries = _parse_opec_html(html)
    new_count = 0

    for entry in entries:
        try:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            date_str = entry.get("date", "")

            if not title:
                continue

            if link and not link.startswith("http"):
                link = "https://www.opec.org" + link

            source_id = _stable_id("opec_press", link or title)
            content = title

            raw = {
                "title": title,
                "link": link,
                "date_str": date_str,
                **{k: v for k, v in source_cfg.items() if k not in ("url", "collector", "poll_interval")},
            }

            ts: Optional[datetime] = None
            if date_str:
                for fmt in ("%d %B %Y", "%B %d, %Y", "%Y-%m-%d", "%d/%m/%Y"):
                    try:
                        ts = datetime.strptime(date_str.strip(), fmt).replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        pass

            await _persist_post(
                source_type="opec_press",
                source_id=source_id,
                author="OPEC",
                content=content,
                raw_json=raw,
                timestamp=ts,
            )
            new_count += 1
        except Exception as exc:
            logger.warning("OPEC entry error: %s", exc)

    if new_count:
        logger.info("OPEC: %d new press releases", new_count)
    return new_count


def _parse_opec_html(html: str) -> list[dict]:
    """Parse OPEC press releases listing page."""
    entries: list[dict] = []
    try:
        # OPEC typically uses article or list-item structures
        # Try to extract links with dates
        article_pattern = re.compile(
            r'<(?:article|li|div)[^>]*class="[^"]*(?:press|release|item|news)[^"]*"[^>]*>(.*?)</(?:article|li|div)>',
            re.DOTALL | re.IGNORECASE,
        )

        link_pat = re.compile(r'href="(/[^"]*press[^"]*)"', re.IGNORECASE)
        title_pat = re.compile(r'<(?:h\d|a)[^>]*>(.*?)</(?:h\d|a)>', re.DOTALL | re.IGNORECASE)
        date_pat = re.compile(
            r"(\d{1,2}\s+\w+\s+\d{4}|\d{4}-\d{2}-\d{2}|\w+\s+\d{1,2},\s+\d{4})"
        )

        # First try article blocks
        for block_match in article_pattern.finditer(html):
            block = block_match.group(1)
            link_m = link_pat.search(block)
            title_m = title_pat.search(block)
            date_m = date_pat.search(block)

            link = link_m.group(1) if link_m else ""
            title = _strip_html(title_m.group(1)).strip() if title_m else ""
            date = date_m.group(0) if date_m else ""

            if title and len(title) >= 10:
                entries.append({"title": title, "link": link, "date": date})
            if len(entries) >= 50:
                break

        # Fallback: scan all links containing /press
        if not entries:
            generic_link = re.compile(
                r'<a[^>]+href="(/[^"]*(?:press-release|press_release)[^"]*)"[^>]*>(.*?)</a>',
                re.DOTALL | re.IGNORECASE,
            )
            for m in generic_link.finditer(html):
                href = m.group(1)
                title = _strip_html(m.group(2)).strip()
                if title and len(title) >= 10:
                    pos = m.start()
                    nearby = html[max(0, pos - 200):pos + 200]
                    date_m = date_pat.search(nearby)
                    entries.append({
                        "title": title,
                        "link": href,
                        "date": date_m.group(0) if date_m else "",
                    })
                if len(entries) >= 50:
                    break

    except Exception as exc:
        logger.warning("OPEC HTML parse error: %s", exc)

    return entries


# ── Collector class ───────────────────────────────────────────────────────────

class OfficialSourcesCollector:
    """Manages all official sources collection tasks."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False

    async def start(self) -> None:
        """Start all official source collection loops."""
        if self._running:
            return
        self._running = True
        logger.info("Starting official sources collector")

        self._tasks["state_dept_rss"] = asyncio.create_task(
            self._loop("state_dept_rss", _collect_state_dept_rss, SOURCES["state_dept_rss"]["poll_interval"]),
            name="official_state_dept",
        )
        self._tasks["ofac_recent_actions"] = asyncio.create_task(
            self._loop("ofac_recent_actions", _collect_ofac_recent_actions, SOURCES["ofac_recent_actions"]["poll_interval"]),
            name="official_ofac_actions",
        )
        self._tasks["china_mfa"] = asyncio.create_task(
            self._loop("china_mfa", _collect_china_mfa, SOURCES["china_mfa"]["poll_interval"]),
            name="official_china_mfa",
        )
        self._tasks["opec_press"] = asyncio.create_task(
            self._loop("opec_press", _collect_opec_press, SOURCES["opec_press"]["poll_interval"]),
            name="official_opec",
        )

    async def stop(self) -> None:
        """Cancel all collection tasks."""
        self._running = False
        for name, task in self._tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("Official sources collector stopped")

    async def _loop(self, name: str, collector_fn, poll_interval: int) -> None:
        """Generic poll loop for a single source."""
        logger.info("Official sources: starting %s (interval=%ds)", name, poll_interval)
        while self._running:
            try:
                await collector_fn()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Official sources [%s] error: %s", name, exc)
            try:
                await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                raise

    @property
    def active_sources(self) -> list[str]:
        return [name for name, task in self._tasks.items() if not task.done()]


# Module-level singleton
official_sources_collector = OfficialSourcesCollector()
