from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.event import Event
from app.models.post import Post
from app.models.source import Source
from app.routers.feed import broadcast_post
from app.services.collector_manager import collector_manager
from app.services.entity_persistence import persist_entities
from app.services.geo_extractor import geo_extractor
from app.services.x_api_client import (
    XApiAuthError,
    XApiClient,
    XApiError,
    XApiNotFoundError,
    XApiRateLimitError,
)

logger = logging.getLogger("orthanc.collectors.x")

DEFAULT_POLL_INTERVAL = 60  # 1 minute
XAI_ENDPOINT = "https://api.x.ai/v1/chat/completions"
XAI_MODEL = "grok-3-mini"

SYSTEM_PROMPT = (
    "You are a tweet retrieval assistant. Return ONLY a JSON array of the most recent tweets "
    "from the specified account. Each tweet should have: id, text, author, created_at. "
    "No commentary."
)

# Source-of-truth tag stored in Post.raw_json["_source_method"]
SOURCE_METHOD_X_API = "x_api"
SOURCE_METHOD_XAI = "xai"
SOURCE_METHOD_XAI_OPENROUTER = "xai_openrouter"

OPENROUTER_XAI_MODEL = "x-ai/grok-3-mini"


def _parse_tweet_timestamp(created_at: Optional[str]) -> Optional[datetime]:
    """Parse various ISO-8601 / Twitter date formats into a tz-aware datetime."""
    if not created_at:
        return None
    # Try ISO 8601 with Z or offset
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%a %b %d %H:%M:%S +0000 %Y",  # legacy Twitter format
    ):
        try:
            dt = datetime.strptime(created_at, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    # Fallback: strip trailing Z and parse
    try:
        return datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except Exception:
        return None


class XCollector:
    """Polls X (Twitter) accounts and persists tweets as Posts.

    Preferred path: X API v2 (real structured data, no hallucinations).
    Fallback path:  xAI/Grok chat completion (legacy).

    Key selection logic:
      - If ``x_api_bearer_token`` is present in the stored "x" keys → use X API v2
      - Else if ``api_key`` (xAI key) is present → fall back to Grok approach
    """

    def __init__(self, poll_interval: int = DEFAULT_POLL_INTERVAL):
        self._poll_interval = poll_interval
        self._tasks: dict[str, asyncio.Task] = {}  # source.id -> task
        # Track sources that had an unrecoverable auth error on X API v2
        # to avoid spamming error logs on every poll cycle.
        self._x_api_disabled_sources: set[str] = set()

    async def start(self, user_id: str, sources: list[Source]) -> None:
        """Begin polling X accounts for a user."""
        keys = await collector_manager.get_keys(user_id, "x")
        if not keys:
            logger.warning("No X keys found for user %s — skipping X collector", user_id)
            return

        x_api_bearer_token: str = keys.get("x_api_bearer_token", "")
        xai_api_key: str = keys.get("api_key", "")

        if not x_api_bearer_token and not xai_api_key:
            logger.warning(
                "X keys for user %s have neither 'x_api_bearer_token' nor 'api_key' — "
                "skipping X collector",
                user_id,
            )
            return

        method = SOURCE_METHOD_X_API if x_api_bearer_token else "xai_openrouter/xai"
        logger.info(
            "Starting X collector for user %s using method=%s (%d sources)",
            user_id,
            method,
            len(sources),
        )

        for source in sources:
            source_id = str(source.id)
            if source_id in self._tasks:
                continue
            per_source_interval = source.poll_interval_seconds or self._poll_interval

            # Calculate initial delay — skip sources polled recently to avoid
            # burning API credits on every restart
            initial_delay = 0
            if source.last_polled:
                elapsed = (datetime.now(tz=timezone.utc) - source.last_polled).total_seconds()
                if elapsed < per_source_interval:
                    initial_delay = int(per_source_interval - elapsed)
                    logger.info(
                        "X @%s polled %ds ago (interval=%ds) — deferring first poll by %ds",
                        source.handle, int(elapsed), per_source_interval, initial_delay,
                    )

            logger.info("Starting X poller for %s (source %s, interval=%ds, initial_delay=%ds)",
                        source.handle, source_id, per_source_interval, initial_delay)
            task = asyncio.create_task(
                self._poll_loop(
                    user_id,
                    source_id,
                    source.handle,
                    x_api_bearer_token=x_api_bearer_token,
                    xai_api_key=xai_api_key,
                    poll_interval=per_source_interval,
                    initial_delay=initial_delay,
                ),
                name=f"x_poll_{source_id}",
            )
            self._tasks[source_id] = task

    async def stop(self) -> None:
        """Cancel all polling tasks."""
        logger.info("Stopping X collector (%d tasks)", len(self._tasks))
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def _poll_loop(
        self,
        user_id: str,
        source_id: str,
        handle: str,
        *,
        x_api_bearer_token: str,
        xai_api_key: str,
        poll_interval: int,
        initial_delay: int = 0,
    ) -> None:
        """Continuous polling loop for a single X account."""
        if initial_delay > 0:
            logger.info("X @%s: waiting %ds before first poll (recently polled)", handle, initial_delay)
            try:
                await asyncio.sleep(initial_delay)
            except asyncio.CancelledError:
                logger.info("X poller cancelled during initial delay for @%s", handle)
                raise
        backoff = poll_interval
        while True:
            try:
                await self._poll_once(
                    user_id,
                    source_id,
                    handle,
                    x_api_bearer_token=x_api_bearer_token,
                    xai_api_key=xai_api_key,
                )
                backoff = poll_interval  # reset on success
            except asyncio.CancelledError:
                logger.info("X poller cancelled for @%s", handle)
                raise
            except _RateLimitError as e:
                logger.warning("X rate limit for @%s — backing off %ds", handle, e.retry_after)
                backoff = e.retry_after
            except _SourceDisabledError:
                logger.error(
                    "X poller permanently disabled for @%s (source %s) due to auth error",
                    handle,
                    source_id,
                )
                return  # exit loop — don't retry invalid credentials
            except Exception as exc:
                logger.exception("X poll error for @%s: %s", handle, exc)

            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                logger.info("X poller cancelled during sleep for @%s", handle)
                raise

    async def _poll_once(
        self,
        user_id: str,
        source_id: str,
        handle: str,
        *,
        x_api_bearer_token: str,
        xai_api_key: str,
    ) -> None:
        """Fetch and persist new tweets for one account."""
        logger.debug("Polling X account @%s", handle)

        if x_api_bearer_token and source_id not in self._x_api_disabled_sources:
            tweets, source_method = await self._fetch_tweets_x_api(
                handle, x_api_bearer_token, source_id
            )
        else:
            # Try OpenRouter first (has working X Search via :online plugin), fall back to direct xAI
            tweets, source_method = await self._fetch_tweets_openrouter(handle)
            if not tweets and xai_api_key:
                tweets = await self._fetch_tweets_xai(handle, xai_api_key)
                source_method = SOURCE_METHOD_XAI

        if not tweets:
            logger.debug("No tweets returned for @%s", handle)
            return

        new_count = 0
        async with AsyncSessionLocal() as session:
            for tweet in tweets:
                tweet_id = str(tweet.get("id", ""))
                if not tweet_id:
                    continue

                # Deduplicate
                existing = await session.execute(
                    select(Post).where(
                        Post.source_type == "x",
                        Post.source_id == tweet_id,
                    )
                )
                if existing.scalars().first():
                    continue

                author = tweet.get("author", handle)
                text = tweet.get("text", "")
                ts = _parse_tweet_timestamp(tweet.get("created_at"))

                # Annotate raw JSON with which method produced this tweet
                raw = dict(tweet)
                raw["_source_method"] = source_method

                post = Post(
                    source_type="x",
                    source_id=tweet_id,
                    author=author,
                    content=text,
                    raw_json=raw,
                    timestamp=ts,
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

                # Run geo extraction (non-blocking — failures must not abort ingest)
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
                except Exception as geo_exc:  # noqa: BLE001
                    logger.warning("Geo extraction failed for post %s: %s", post.id, geo_exc)

                # Run entity extraction
                await persist_entities(session, post.id, post.content or "", log_label="x")

                new_count += 1

            # Update last_polled
            source_result = await session.execute(
                select(Source).where(Source.id == source_id)
            )
            source_obj = source_result.scalars().first()
            if source_obj:
                source_obj.last_polled = datetime.now(tz=timezone.utc)

            await session.commit()

        if new_count:
            logger.info(
                "X @%s [%s]: inserted %d new posts", handle, source_method, new_count
            )
        else:
            logger.debug("X @%s: no new tweets", handle)

    # -------------------------------------------------------------------------
    # X API v2 path
    # -------------------------------------------------------------------------

    async def _fetch_tweets_x_api(
        self, handle: str, bearer_token: str, source_id: str
    ) -> tuple[list[dict], str]:
        """Fetch tweets via X API v2.  Returns (tweets, source_method)."""
        client = XApiClient(bearer_token)
        try:
            tweets = await client.resolve_and_fetch(handle, max_results=10)
            return tweets, SOURCE_METHOD_X_API
        except XApiAuthError as exc:
            # Unrecoverable — bad token. Disable this source from X API v2.
            logger.error(
                "X API v2 auth error for @%s (source %s): %s. "
                "Disabling X API v2 for this source.",
                handle,
                source_id,
                exc,
            )
            self._x_api_disabled_sources.add(source_id)
            raise _SourceDisabledError(str(exc)) from exc
        except XApiNotFoundError as exc:
            logger.warning("X API v2: @%s not found — skipping: %s", handle, exc)
            return [], SOURCE_METHOD_X_API
        except XApiRateLimitError as exc:
            logger.warning(
                "X API v2 rate limit for @%s — retry after %ds", handle, exc.retry_after
            )
            raise _RateLimitError(exc.retry_after) from exc
        except XApiError as exc:
            logger.error("X API v2 error for @%s: %s", handle, exc)
            return [], SOURCE_METHOD_X_API
        except httpx.RequestError as exc:
            logger.warning("X API v2 network error for @%s: %s — will retry", handle, exc)
            return [], SOURCE_METHOD_X_API

    # -------------------------------------------------------------------------
    # OpenRouter / Grok + X Search plugin path
    # -------------------------------------------------------------------------

    async def _fetch_tweets_openrouter(self, handle: str) -> tuple[list[dict], str]:
        """Fetch tweets via OpenRouter's Grok + X Search plugin."""
        from app.services.model_router import model_router

        handle = handle.lstrip("@")

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Get the 10 most recent tweets from @{handle}"},
        ]

        try:
            result = await model_router.chat(
                "x_collection",  # task name for logging
                messages,
                model=OPENROUTER_XAI_MODEL,
                temperature=0,
            )

            raw_content = result.get("content", "[]")
            # Strip markdown code fences if present
            raw_content = re.sub(r"```(?:json)?\s*", "", raw_content).strip()

            try:
                tweets = json.loads(raw_content)
                if isinstance(tweets, list):
                    # Attach any citations from the response annotations
                    citations = result.get("annotations", [])
                    if citations:
                        for tweet in tweets:
                            tweet["_citations"] = citations
                    return tweets, SOURCE_METHOD_XAI_OPENROUTER
                logger.warning("Unexpected OpenRouter/Grok response structure for @%s", handle)
            except json.JSONDecodeError as e:
                logger.warning("Failed to parse OpenRouter/Grok JSON for @%s: %s", handle, e)

            return [], SOURCE_METHOD_XAI_OPENROUTER

        except Exception as exc:
            logger.warning("OpenRouter X collection failed for @%s: %s", handle, exc)
            return [], SOURCE_METHOD_XAI_OPENROUTER

    # -------------------------------------------------------------------------
    # xAI / Grok fallback path (unchanged from original implementation)
    # -------------------------------------------------------------------------

    async def _fetch_tweets_xai(self, handle: str, api_key: str) -> list[dict]:
        """Call xAI Grok to retrieve recent tweets for a handle (legacy fallback)."""
        handle = handle.lstrip("@")  # normalize — avoid @@handle
        payload = {
            "model": XAI_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Get the 10 most recent tweets from @{handle}"},
            ],
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(XAI_ENDPOINT, json=payload, headers=headers)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            raise _RateLimitError(retry_after)

        resp.raise_for_status()
        data = resp.json()

        raw_content: str = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "[]")
        )

        # Strip markdown code fences if present
        raw_content = re.sub(r"```(?:json)?\s*", "", raw_content).strip()

        try:
            tweets = json.loads(raw_content)
            if isinstance(tweets, list):
                return tweets
            logger.warning("Unexpected xAI response structure for @%s", handle)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse xAI JSON for @%s: %s", handle, e)

        return []


class _RateLimitError(Exception):
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Rate limited — retry after {retry_after}s")


class _SourceDisabledError(Exception):
    """Raised when a source should be permanently disabled due to auth failure."""
