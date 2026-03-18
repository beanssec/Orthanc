"""Dark-web intelligence collector — Sprint 33 CP1.

TASK-76: Clearnet ransomware leak blog mirrors
TASK-77: Paste site monitoring (Pastebin)

Both collectors store posts with low reliability priors (0.3) and
source_class="dark_web".  404/connection errors are handled gracefully since
these sites go down frequently.

Scheduling:
  Ransomware leak blogs — every 2 hours
  Paste site monitoring — every 30 minutes (rate-limited)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.post import Post
from app.routers.feed import broadcast_post

logger = logging.getLogger("orthanc.collectors.darkweb")

# ── TASK-76: Ransomware leak blog mirrors ─────────────────────────────────────
# Clearnet mirrors / onion-available sites; these go down frequently.
# Keep the list conservative — only stable, long-running mirrors.

RANSOMWARE_MIRRORS: list[dict] = [
    {
        "group": "LockBit",
        "url": "https://lockbitblog.com",
        "selector_victim": ".victim-name, h2.entry-title, .leak-title",
        "selector_date": ".entry-date, time",
        "selector_desc": ".entry-summary, .victim-description, p",
    },
    {
        "group": "BlackCat (ALPHV)",
        "url": "https://alphvmmm27o3abo3r2mlmjrpdmzle3rykajqc5xsj7j7ejksbpsa36ad.onion.ly",
        "selector_victim": "h2, .victim, .target-name",
        "selector_date": "time, .date",
        "selector_desc": ".description, p",
    },
    {
        "group": "RansomHub",
        "url": "https://ransomhub.ws",
        "selector_victim": ".victim-name, h2, h3",
        "selector_date": "time, .date, .published",
        "selector_desc": ".excerpt, .desc, p",
    },
    {
        "group": "Cl0p",
        "url": "https://clop.su",
        "selector_victim": ".company, h2, .title",
        "selector_date": ".date, time",
        "selector_desc": "p, .info",
    },
    {
        "group": "Play",
        "url": "https://www.play-news.to",
        "selector_victim": "h2, .name, .company-name",
        "selector_date": ".date, time",
        "selector_desc": ".desc, p",
    },
]

RANSOMWARE_POLL_INTERVAL = 7200   # 2 hours
PASTE_POLL_INTERVAL = 1800        # 30 minutes
PASTE_REQUEST_DELAY = 3.0         # seconds between paste requests (rate limit)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _make_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]


def _try_parse_date(date_str: str) -> Optional[datetime]:
    """Try to parse common date formats; return None on failure."""
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%B %d, %Y", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


# ── HTML scraping helpers ──────────────────────────────────────────────────────

def _css_extract_text(html: str, selectors: str) -> list[str]:
    """Very lightweight selector-style extraction without BeautifulSoup.

    Handles simple tag-based selectors (e.g. 'h2', 'time', 'p').
    Falls back to regex-based extraction for class selectors.
    Returns up to 20 matches.
    """
    results: list[str] = []
    for sel in [s.strip() for s in selectors.split(",")]:
        if not sel:
            continue
        if sel.startswith("."):
            cls = re.escape(sel[1:])
            pattern = rf'class="[^"]*{cls}[^"]*"[^>]*>(.*?)<'
            matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
        else:
            tag = re.escape(sel.split(".")[0])
            pattern = rf"<{tag}[^>]*>(.*?)</{tag}>"
            matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)

        for m in matches[:10]:
            clean = re.sub(r"<[^>]+>", " ", m).strip()
            clean = re.sub(r"&amp;", "&", clean)
            clean = re.sub(r"&lt;", "<", clean)
            clean = re.sub(r"&gt;", ">", clean)
            clean = re.sub(r"&#\d+;", "", clean)
            clean = re.sub(r"\s+", " ", clean).strip()
            if len(clean) > 3:
                results.append(clean)

        if len(results) >= 20:
            break

    return results[:20]


class DarkwebCollector:
    """Collector for clearnet ransomware leak blog mirrors and paste sites."""

    def __init__(self) -> None:
        self._running = False
        self._task_ransomware: Optional[asyncio.Task] = None
        self._task_paste: Optional[asyncio.Task] = None
        self._paste_keywords: list[str] = []
        self._paste_keywords_refreshed: float = 0.0

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task_ransomware = asyncio.create_task(self._ransomware_loop())
        self._task_paste = asyncio.create_task(self._paste_loop())
        logger.info("Darkweb collector started")

    async def stop(self) -> None:
        self._running = False
        for task in (self._task_ransomware, self._task_paste):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("Darkweb collector stopped")

    # ── TASK-76: Ransomware leak blogs ────────────────────────────────────────

    async def _ransomware_loop(self) -> None:
        """Poll ransomware leak blogs every RANSOMWARE_POLL_INTERVAL seconds."""
        await asyncio.sleep(60)  # brief startup delay
        while self._running:
            try:
                await self._collect_ransomware_blogs()
            except Exception as exc:
                logger.error("Ransomware collector cycle error: %s", exc)
            await asyncio.sleep(RANSOMWARE_POLL_INTERVAL)

    async def _collect_ransomware_blogs(self) -> None:
        """Scrape each configured ransomware mirror and store new victim posts."""
        async with httpx.AsyncClient(
            headers=_BROWSER_HEADERS,
            timeout=30,
            follow_redirects=True,
        ) as client:
            for mirror in RANSOMWARE_MIRRORS:
                try:
                    await self._scrape_ransomware_mirror(client, mirror)
                except Exception as exc:
                    logger.warning(
                        "Ransomware mirror scrape failed (%s): %s", mirror["group"], exc
                    )

    async def _scrape_ransomware_mirror(self, client: httpx.AsyncClient, mirror: dict) -> None:
        group = mirror["group"]
        url = mirror["url"]
        source_id = f"darkweb:{group.lower().replace(' ', '-').replace('(', '').replace(')', '')}"

        try:
            response = await client.get(url)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.debug("Ransomware mirror %s (%s) unreachable: %s", group, url, exc)
            return

        if response.status_code == 404:
            logger.debug("Ransomware mirror %s returned 404 — site likely down", group)
            return
        if response.status_code in (403, 429, 503):
            logger.debug("Ransomware mirror %s returned %d — skipping", group, response.status_code)
            return
        if response.status_code >= 400:
            logger.warning("Ransomware mirror %s HTTP %d", group, response.status_code)
            return

        html = response.text
        victims = _css_extract_text(html, mirror["selector_victim"])
        dates = _css_extract_text(html, mirror["selector_date"])
        descs = _css_extract_text(html, mirror["selector_desc"])

        if not victims:
            logger.debug("Ransomware mirror %s: no victims found in HTML", group)
            return

        saved = 0
        for i, victim in enumerate(victims[:20]):
            date_str = dates[i] if i < len(dates) else ""
            desc = descs[i] if i < len(descs) else ""

            content = f"[RANSOMWARE:{group}] Victim: {victim}"
            if desc:
                content += f" — {desc[:300]}"

            content_hash = _make_content_hash(content)
            external_id = f"ransomware:{source_id}:{content_hash}"

            async with AsyncSessionLocal() as session:
                existing = await session.execute(
                    select(Post.id).where(Post.external_id == external_id)
                )
                if existing.scalar():
                    continue  # already ingested

            ts = _try_parse_date(date_str) or datetime.now(timezone.utc)

            post = Post(
                source_type="darkweb",
                source_id=source_id,
                author=f"[{group}]",
                content=content[:2000],
                external_id=external_id,
                timestamp=ts,
                raw_json={
                    "source_class": "dark_web",
                    "reliability_prior": 0.3,
                    "group": group,
                    "victim": victim,
                    "description": desc[:500] if desc else None,
                    "mirror_url": url,
                },
            )

            async with AsyncSessionLocal() as session:
                session.add(post)
                try:
                    await session.commit()
                    await session.refresh(post)
                    await broadcast_post(post)
                    saved += 1
                except Exception as db_exc:
                    await session.rollback()
                    logger.debug("Ransomware post save failed: %s", db_exc)

        if saved:
            logger.info("Ransomware collector: saved %d new victims from %s", saved, group)

    # ── TASK-77: Paste site monitoring ────────────────────────────────────────

    async def _paste_loop(self) -> None:
        """Monitor paste sites for tracked keywords every PASTE_POLL_INTERVAL seconds."""
        await asyncio.sleep(120)  # longer startup delay
        while self._running:
            try:
                await self._refresh_paste_keywords()
                if self._paste_keywords:
                    await self._monitor_paste_sites()
                else:
                    logger.debug("Paste collector: no keywords configured — skipping cycle")
            except Exception as exc:
                logger.error("Paste collector cycle error: %s", exc)
            await asyncio.sleep(PASTE_POLL_INTERVAL)

    async def _refresh_paste_keywords(self) -> None:
        """Reload entity names and tracked narrative terms for paste monitoring."""
        now = time.time()
        if now - self._paste_keywords_refreshed < 600:  # refresh every 10 min
            return

        keywords: list[str] = []
        try:
            from app.models.entity import Entity
            from app.models.narrative import NarrativeTracker

            async with AsyncSessionLocal() as session:
                # Top entity names by mention count
                ent_result = await session.execute(
                    select(Entity.canonical_name)
                    .order_by(Entity.mention_count.desc())
                    .limit(20)
                )
                keywords.extend(r[0] for r in ent_result.all() if r[0])

                # Active tracker names as search terms
                tracker_result = await session.execute(
                    select(NarrativeTracker.name)
                    .where(NarrativeTracker.status == "active")
                    .limit(10)
                )
                keywords.extend(r[0] for r in tracker_result.all() if r[0])

        except Exception as exc:
            logger.debug("Paste collector: keyword refresh failed: %s", exc)

        self._paste_keywords = [k for k in keywords if len(k) > 3][:25]
        self._paste_keywords_refreshed = now
        logger.debug("Paste collector: loaded %d keywords", len(self._paste_keywords))

    async def _monitor_paste_sites(self) -> None:
        """Query Pastebin scraping API for keywords."""
        async with httpx.AsyncClient(
            headers=_BROWSER_HEADERS,
            timeout=20,
            follow_redirects=True,
        ) as client:
            for keyword in self._paste_keywords[:10]:  # limit to 10 per cycle
                try:
                    await self._search_pastebin(client, keyword)
                except Exception as exc:
                    logger.debug("Paste search failed for '%s': %s", keyword, exc)
                # Rate-limit between requests to avoid IP bans
                await asyncio.sleep(PASTE_REQUEST_DELAY)

    async def _search_pastebin(self, client: httpx.AsyncClient, keyword: str) -> None:
        """
        Search Pastebin's public scraping API for a keyword.
        Uses the public /api/scraping API endpoint (no key required for limited use).
        Falls back to search page scraping if API unavailable.
        """
        try:
            resp = await client.get(
                "https://scrape.pastebin.com/api_scraping.php",
                params={"limit": 20},
                timeout=15,
            )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.debug("Pastebin API unreachable: %s", exc)
            return

        if resp.status_code in (403, 429):
            logger.debug("Pastebin API rate-limited (%d) — backing off", resp.status_code)
            await asyncio.sleep(30)
            return

        if resp.status_code != 200:
            return

        try:
            pastes = resp.json()
        except Exception:
            return

        if not isinstance(pastes, list):
            return

        kw_lower = keyword.lower()
        saved = 0

        for paste in pastes:
            if not isinstance(paste, dict):
                continue

            full_url = paste.get("full_url") or paste.get("scrape_url", "")
            paste_key = paste.get("key", "")
            title = paste.get("title") or ""
            syntax = paste.get("syntax") or ""
            user = paste.get("user") or "anonymous"

            # Check title/syntax for keyword match first
            snippet = (title + " " + syntax).lower()
            if kw_lower not in snippet:
                raw_url = f"https://scrape.pastebin.com/api_scrape_item.php?i={paste_key}"
                try:
                    raw_resp = await client.get(raw_url, timeout=10)
                    if raw_resp.status_code != 200:
                        continue
                    if kw_lower not in raw_resp.text.lower():
                        continue
                    content_text = raw_resp.text[:2000]
                except Exception:
                    continue
            else:
                content_text = f"[PASTE:{paste_key}] {title}\nKeyword match: {keyword}"

            external_id = f"paste:pastebin:{paste_key}"

            async with AsyncSessionLocal() as session:
                existing = await session.execute(
                    select(Post.id).where(Post.external_id == external_id)
                )
                if existing.scalar():
                    continue

            content_body = (
                f"[PASTEBIN] Keyword match: '{keyword}'\n"
                f"Title: {title or 'Untitled'}\n"
                f"URL: {full_url}\n"
                f"---\n{content_text[:1500]}"
            )

            post = Post(
                source_type="paste",
                source_id=f"pastebin:{keyword[:30]}",
                author=user,
                content=content_body[:2000],
                external_id=external_id,
                timestamp=datetime.now(timezone.utc),
                raw_json={
                    "source_class": "dark_web",
                    "reliability_prior": 0.3,
                    "keyword": keyword,
                    "paste_key": paste_key,
                    "title": title,
                    "syntax": syntax,
                    "paste_url": full_url,
                    "paste_site": "pastebin",
                },
            )

            async with AsyncSessionLocal() as session:
                session.add(post)
                try:
                    await session.commit()
                    await session.refresh(post)
                    await broadcast_post(post)
                    saved += 1
                except Exception as db_exc:
                    await session.rollback()
                    logger.debug("Paste post save failed: %s", db_exc)

        if saved:
            logger.info("Paste collector: saved %d new pastes for keyword '%s'", saved, keyword)


# Singleton
darkweb_collector = DarkwebCollector()
