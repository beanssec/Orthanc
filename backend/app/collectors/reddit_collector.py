"""Reddit collector — polls public subreddits for new posts."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import feedparser
import httpx
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.event import Event
from app.models.post import Post
from app.models.source import Source
from app.routers.feed import broadcast_post
from app.services.entity_persistence import persist_entities
from app.services.geo_extractor import geo_extractor

logger = logging.getLogger("orthanc.collectors.reddit")

DEFAULT_POLL_INTERVAL = 300  # 5 minutes
REDDIT_USER_AGENT = os.getenv(
    "REDDIT_USER_AGENT",
    "python:orthanc-osint:v1.0 (contact: ops@orthanc.local)",
)
REDDIT_AUTH_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_OAUTH_BASE_URL = "https://oauth.reddit.com"
REDDIT_PUBLIC_BASE_URLS = (
    "https://www.reddit.com",
    "https://old.reddit.com",
)


class RedditAuthError(RuntimeError):
    """Raised when Reddit cannot be queried reliably with current credentials."""


class RedditCollector:
    """Polls public subreddits via Reddit's API.

    Reddit's unauthenticated JSON endpoints are increasingly blocked from server
    networks and often return HTML 403 pages even with a user-agent.  The
    production path is therefore app-only OAuth when REDDIT_CLIENT_ID and
    REDDIT_CLIENT_SECRET are configured.  Anonymous JSON remains as a best-effort
    fallback for dev/local environments only.
    """

    def __init__(self, poll_interval: int = DEFAULT_POLL_INTERVAL):
        self._poll_interval = poll_interval
        self._tasks: dict[str, asyncio.Task] = {}  # source_id -> task
        # cache_key -> (access_token, expires_at).  The collector is process-wide,
        # so never use a single token slot across users/providers.
        self._token_cache: dict[str, tuple[str, datetime]] = {}

    async def start(self, sources: list) -> None:
        """Begin polling configured subreddits."""
        for source in sources:
            source_id = str(source.id)
            if source_id in self._tasks:
                continue
            subreddit = source.handle.lstrip("r/").lstrip("/")
            user_id = str(source.user_id)
            per_source_interval = source.poll_interval_seconds or self._poll_interval
            logger.info("Starting Reddit poller for r/%s (source %s, interval=%ds)", subreddit, source_id, per_source_interval)
            task = asyncio.create_task(
                self._poll_loop(source_id, subreddit, per_source_interval, user_id),
                name=f"reddit_poll_{source_id}",
            )
            self._tasks[source_id] = task

    async def stop(self) -> None:
        """Cancel all polling tasks."""
        logger.info("Stopping Reddit collector (%d tasks)", len(self._tasks))
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def _poll_loop(self, source_id: str, subreddit: str, poll_interval: int, user_id: str | None = None) -> None:
        """Continuous polling loop for a single subreddit."""
        from app.services.collector_manager import collector_manager

        backoff = poll_interval
        max_backoff = poll_interval * 16
        while True:
            try:
                await self._poll_once(source_id, subreddit, user_id=user_id)
                backoff = poll_interval
                await collector_manager.record_source_success(source_id)
            except asyncio.CancelledError:
                logger.info("Reddit poller cancelled for r/%s", subreddit)
                raise
            except Exception as exc:
                logger.warning("Reddit poll error for r/%s: %s", subreddit, exc)
                auto_disabled = await collector_manager.record_source_error(source_id, str(exc))
                if auto_disabled:
                    logger.warning("Reddit poller stopping for auto-disabled source %s", source_id)
                    self._tasks.pop(source_id, None)
                    return
                backoff = min(max(backoff * 2, 60), max_backoff)

            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                logger.info("Reddit poller cancelled during sleep for r/%s", subreddit)
                raise

    async def _get_oauth_credentials(self, user_id: str | None = None) -> Optional[dict[str, str]]:
        """Return Reddit OAuth credentials from encrypted settings, falling back to env.

        Settings/Credentials stores user-scoped keys as client_id/client_secret/user_agent.
        Environment variables remain supported for server-level deployments.
        """
        if user_id:
            from app.services.collector_manager import collector_manager

            keys = await collector_manager.get_keys(user_id, "reddit")
            if keys and keys.get("client_id") and keys.get("client_secret"):
                return {
                    "client_id": keys["client_id"],
                    "client_secret": keys["client_secret"],
                    "user_agent": keys.get("user_agent") or REDDIT_USER_AGENT,
                    "cache_key": f"user:{user_id}:{keys['client_id']}",
                }

        client_id = os.getenv("REDDIT_CLIENT_ID")
        client_secret = os.getenv("REDDIT_CLIENT_SECRET")
        if client_id and client_secret:
            return {
                "client_id": client_id,
                "client_secret": client_secret,
                "user_agent": os.getenv("REDDIT_USER_AGENT") or REDDIT_USER_AGENT,
                "cache_key": f"env:{client_id}",
            }
        return None

    async def _get_access_token(self, client: httpx.AsyncClient, credentials: dict[str, str]) -> str:
        """Return a cached Reddit app-only OAuth token for one credential set."""
        now = datetime.now(tz=timezone.utc)
        cache_key = credentials["cache_key"]
        cached = self._token_cache.get(cache_key)
        if cached:
            token, expires_at = cached
            if expires_at > now + timedelta(seconds=60):
                return token

        response = await client.post(
            REDDIT_AUTH_URL,
            auth=(credentials["client_id"], credentials["client_secret"]),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": credentials.get("user_agent") or REDDIT_USER_AGENT},
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise RedditAuthError("Reddit OAuth response did not include an access_token")

        expires_in = int(payload.get("expires_in") or 3600)
        self._token_cache[cache_key] = (
            token,
            now + timedelta(seconds=max(expires_in - 30, 60)),
        )
        return token

    async def _fetch_subreddit_rss_listing(self, client: httpx.AsyncClient, subreddit: str) -> dict:
        """Fetch subreddit RSS and normalize it to the Reddit listing shape.

        This is a deliberately narrow fallback for environments where Reddit
        blocks unauthenticated JSON with 403 but still serves public subreddit
        RSS.  OAuth remains the preferred production path because RSS is less
        complete, but RSS keeps public sources ingesting instead of failing hard.
        """
        response = None
        last_error: Exception | None = None
        for base_url in ("https://www.reddit.com", "https://old.reddit.com"):
            try:
                response = await client.get(
                    f"{base_url}/r/{subreddit}/.rss",
                    headers={
                        "User-Agent": "Orthanc-OSINT/1.0 (+https://orthanc.local; reddit rss fallback)",
                        "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml, */*;q=0.8",
                    },
                )
                response.raise_for_status()
                break
            except Exception as exc:
                last_error = exc
                response = None
        if response is None:
            raise RedditAuthError(f"Reddit RSS fallback failed for r/{subreddit}: {last_error}")

        parsed = feedparser.parse(response.content)
        if parsed.get("bozo") and not parsed.entries:
            raise RedditAuthError(f"Reddit RSS parse failed for r/{subreddit}: {parsed.get('bozo_exception')}")

        children = []
        for entry in parsed.entries:
            guid = entry.get("id") or entry.get("link") or ""
            post_id = ""
            if guid:
                match = re.search(r"/comments/([^/]+)", guid)
                post_id = match.group(1) if match else guid.rstrip("/").split("/")[-1]
            if not post_id:
                continue
            published = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
            created_utc = None
            if published:
                try:
                    import calendar

                    created_utc = calendar.timegm(published)
                except Exception:
                    created_utc = None
            children.append({
                "kind": "t3",
                "data": {
                    "id": post_id,
                    "name": f"t3_{post_id}",
                    "title": entry.get("title", ""),
                    "selftext": entry.get("summary", ""),
                    "author": entry.get("author", f"r/{subreddit}"),
                    "created_utc": created_utc,
                    "permalink": entry.get("link", ""),
                    "url": entry.get("link", ""),
                    "source_format": "rss_fallback",
                },
            })
        return {"data": {"children": children}}

    async def _fetch_subreddit_listing(
        self,
        client: httpx.AsyncClient,
        subreddit: str,
        credentials: Optional[dict[str, str]] = None,
    ) -> dict:
        """Fetch subreddit listing via OAuth, with RSS fallback for blocked public JSON."""
        params = {"limit": 25, "raw_json": 1}

        if credentials:
            token = await self._get_access_token(client, credentials)
            response = await client.get(
                f"{REDDIT_OAUTH_BASE_URL}/r/{subreddit}/new",
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": credentials.get("user_agent") or REDDIT_USER_AGENT,
                    "Accept": "application/json",
                },
            )
            if response.status_code == 401:
                # Token may have been revoked before expiry; refresh once.
                self._token_cache.pop(credentials["cache_key"], None)
                token = await self._get_access_token(client, credentials)
                response = await client.get(
                    f"{REDDIT_OAUTH_BASE_URL}/r/{subreddit}/new",
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "User-Agent": credentials.get("user_agent") or REDDIT_USER_AGENT,
                        "Accept": "application/json",
                    },
                )
            response.raise_for_status()
            return response.json()

        last_403: str | None = None
        for base_url in REDDIT_PUBLIC_BASE_URLS:
            response = await client.get(
                f"{base_url}/r/{subreddit}/new.json",
                params=params,
                headers={"User-Agent": REDDIT_USER_AGENT, "Accept": "application/json"},
            )
            if response.status_code == 403:
                content_type = response.headers.get("content-type", "")
                last_403 = f"{base_url} returned 403 ({content_type})"
                continue
            response.raise_for_status()
            return response.json()

        logger.warning(
            "Reddit public JSON returned 403 for r/%s; trying RSS fallback. "
            "Configure REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET for the preferred OAuth API path.",
            subreddit,
        )
        try:
            return await self._fetch_subreddit_rss_listing(client, subreddit)
        except Exception as exc:
            raise RedditAuthError(
                "Reddit returned 403 for unauthenticated JSON endpoints and RSS fallback failed. "
                "Configure REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET for app-only OAuth. "
                f"Last JSON response: {last_403 or '403'}; RSS error: {exc}"
            ) from exc

    async def _poll_once(self, source_id: str, subreddit: str, user_id: str | None = None) -> None:
        """Fetch new posts from a subreddit."""
        logger.debug("Polling Reddit r/%s", subreddit)

        try:
            timeout = httpx.Timeout(20.0, connect=10.0, read=20.0, write=10.0, pool=5.0)
            credentials = await self._get_oauth_credentials(user_id)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                data = await self._fetch_subreddit_listing(client, subreddit, credentials=credentials)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise RedditAuthError(f"subreddit r/{subreddit} not found (404)") from e
            if e.response.status_code == 429:
                retry_after = e.response.headers.get("retry-after")
                logger.warning("Reddit rate limited for r/%s (retry-after=%s)", subreddit, retry_after)
            raise
        except Exception as e:
            logger.warning("Reddit request failed for r/%s: %s", subreddit, e)
            raise

        posts_data = data.get("data", {}).get("children", [])
        if not posts_data:
            logger.debug("Reddit r/%s: no posts", subreddit)
            return

        new_count = 0
        async with AsyncSessionLocal() as session:
            for item in posts_data:
                post_data = item.get("data", {})
                post_id_str = post_data.get("id", "")
                if not post_id_str:
                    continue

                source_id_key = f"reddit_{subreddit}_{post_id_str}"

                # Deduplicate
                existing = await session.execute(
                    select(Post).where(
                        Post.source_type == "reddit",
                        Post.source_id == source_id_key,
                    )
                )
                if existing.scalars().first():
                    continue

                title = post_data.get("title", "")
                selftext = post_data.get("selftext", "")
                author = post_data.get("author", f"r/{subreddit}")
                content = f"{title}\n\n{selftext}".strip() if selftext else title

                created_utc = post_data.get("created_utc")
                if created_utc:
                    ts = datetime.fromtimestamp(float(created_utc), tz=timezone.utc)
                else:
                    ts = datetime.now(tz=timezone.utc)

                post = Post(
                    source_type="reddit",
                    source_id=source_id_key,
                    author=author,
                    content=content,
                    raw_json=post_data,
                    timestamp=ts,
                )
                session.add(post)
                await session.flush()

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
                    logger.warning("Geo extraction failed for Reddit post %s: %s", post.id, geo_exc)

                # Entity extraction
                await persist_entities(session, post.id, content or "", log_label="reddit")

                new_count += 1

            # Update last_polled for this source
            src_result = await session.execute(select(Source).where(Source.id == source_id))
            src = src_result.scalars().first()
            if src:
                src.last_polled = datetime.now(tz=timezone.utc)

            await session.commit()

        if new_count:
            logger.info("Reddit r/%s: inserted %d new posts", subreddit, new_count)
        else:
            logger.debug("Reddit r/%s: no new posts", subreddit)
