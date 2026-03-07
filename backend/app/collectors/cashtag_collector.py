"""Cashtag collector — monitors $TICKER mentions on X via xAI Grok live search."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.db import AsyncSessionLocal
from app.models.post import Post
from app.services.collector_manager import collector_manager
from sqlalchemy import select

logger = logging.getLogger("orthanc.collectors.cashtag")

XAI_ENDPOINT = "https://api.x.ai/v1/chat/completions"
XAI_MODEL = "grok-3-mini"
POLL_INTERVAL = 300  # 5 minutes
BATCH_SIZE = 5       # tickers per Grok call

SYSTEM_PROMPT = (
    "You are a financial social media analyst. Return ONLY a JSON array of tweets. "
    "Each tweet object must have: id (string), text (string), author (string), "
    "created_at (ISO 8601 string), sentiment (one of: bullish, bearish, neutral). "
    "No commentary, no markdown, just the JSON array."
)


def _parse_ts(created_at: Optional[str]) -> Optional[datetime]:
    if not created_at:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(created_at, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except Exception:
        return None


class CashtagCollector:
    """Monitors X/Twitter cashtag mentions ($TICKER) via xAI Grok."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}  # user_id -> task

    async def start(self, user_id: str, tickers: list[str]) -> None:
        """Start monitoring cashtags for a user's portfolio tickers."""
        if not tickers:
            logger.debug("CashtagCollector: no tickers for user %s", user_id)
            return

        keys = await collector_manager.get_keys(user_id, "x")
        if not keys:
            logger.info("CashtagCollector: no xAI keys for user %s — skipping", user_id)
            return

        api_key: str = keys.get("api_key", "")
        if not api_key:
            logger.warning("CashtagCollector: xAI keys missing 'api_key' for user %s", user_id)
            return

        # Stop any existing task for this user
        await self.stop_user(user_id)

        logger.info("CashtagCollector: starting for user %s, tickers=%s", user_id, tickers)
        task = asyncio.create_task(
            self._poll_loop(user_id, tickers, api_key),
            name=f"cashtag_{user_id}",
        )
        self._tasks[user_id] = task

    async def stop_user(self, user_id: str) -> None:
        """Cancel the cashtag task for a specific user."""
        task = self._tasks.pop(user_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def stop(self) -> None:
        """Cancel all cashtag polling tasks."""
        logger.info("CashtagCollector: stopping %d tasks", len(self._tasks))
        for user_id in list(self._tasks.keys()):
            await self.stop_user(user_id)

    async def _poll_loop(self, user_id: str, tickers: list[str], api_key: str) -> None:
        while True:
            try:
                await self._poll_once(user_id, tickers, api_key)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("CashtagCollector: poll error for user %s", user_id)

            try:
                await asyncio.sleep(POLL_INTERVAL)
            except asyncio.CancelledError:
                raise

    async def _poll_once(self, user_id: str, tickers: list[str], api_key: str) -> None:
        """Fetch cashtag mentions for all tickers in batches."""
        logger.debug("CashtagCollector: polling %d tickers for user %s", len(tickers), user_id)

        # Process in batches of BATCH_SIZE
        for i in range(0, len(tickers), BATCH_SIZE):
            batch = tickers[i : i + BATCH_SIZE]
            cashtags = " ".join(f"${t}" for t in batch)

            try:
                tweets = await self._fetch_cashtag_tweets(cashtags, api_key)
            except Exception:
                logger.exception("CashtagCollector: Grok fetch failed for %s", cashtags)
                continue

            if not tweets:
                continue

            new_count = 0
            async with AsyncSessionLocal() as session:
                for tweet in tweets:
                    tweet_id = str(tweet.get("id", ""))
                    if not tweet_id:
                        continue

                    source_id = f"cashtag_{tweet_id}"

                    existing = await session.execute(
                        select(Post).where(
                            Post.source_type == "cashtag",
                            Post.source_id == source_id,
                        )
                    )
                    if existing.scalars().first():
                        continue

                    # Enrich raw_json with cashtags and sentiment
                    raw = dict(tweet)
                    raw["cashtags"] = batch
                    raw["sentiment"] = tweet.get("sentiment", "neutral")

                    post = Post(
                        source_type="cashtag",
                        source_id=source_id,
                        author=tweet.get("author", "unknown"),
                        content=tweet.get("text", ""),
                        raw_json=raw,
                        timestamp=_parse_ts(tweet.get("created_at")),
                    )
                    session.add(post)
                    new_count += 1

                await session.commit()

            if new_count:
                logger.info("CashtagCollector: %d new posts for %s", new_count, cashtags)

    async def _fetch_cashtag_tweets(self, cashtags: str, api_key: str) -> list[dict]:
        """Call xAI Grok to retrieve recent cashtag tweets."""
        payload = {
            "model": XAI_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Get the 10 most recent tweets mentioning {cashtags}. "
                        "Include tweet text, author, date, and sentiment (bullish/bearish/neutral)."
                    ),
                },
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
            logger.warning("CashtagCollector: rate limited — backing off %ds", retry_after)
            await asyncio.sleep(retry_after)
            return []

        resp.raise_for_status()
        data = resp.json()

        raw_content: str = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "[]")
        )

        # Strip markdown code fences
        raw_content = re.sub(r"```(?:json)?\s*", "", raw_content).strip()

        try:
            tweets = json.loads(raw_content)
            if isinstance(tweets, list):
                return tweets
        except json.JSONDecodeError as e:
            logger.warning("CashtagCollector: JSON parse error: %s", e)

        return []


# Module-level singleton
cashtag_collector = CashtagCollector()
