"""X API v2 async client for Overwatch.

Provides direct access to the X (Twitter) API v2 using Bearer Token auth.
This replaces/complements the xAI/Grok approach with real structured data.

Rate limits (free tier):
  - 1,500 tweet reads per 15-minute window
  - 500,000 tweets/month
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger("orthanc.services.x_api_client")

BASE_URL = "https://api.x.com/2"

# Rate limit tracking: 1,500 requests per 15-min window (free tier)
_RATE_LIMIT_WINDOW_SECONDS = 15 * 60  # 900 seconds
_RATE_LIMIT_MAX_REQUESTS = 1_500
_RATE_LIMIT_WARN_THRESHOLD = 1_200  # warn at 80% usage


class XApiError(Exception):
    """Base error for X API client."""


class XApiAuthError(XApiError):
    """401/403 — invalid or expired Bearer Token."""


class XApiRateLimitError(XApiError):
    """429 — rate limit hit."""

    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"X API rate limit — retry after {retry_after}s")


class XApiNotFoundError(XApiError):
    """404 — user not found."""


class _RateLimitTracker:
    """Simple in-process rate limit tracker (per-token granularity not needed for OSINT scale)."""

    def __init__(self) -> None:
        self._window_start: float = time.monotonic()
        self._request_count: int = 0

    def record_request(self) -> None:
        now = time.monotonic()
        if now - self._window_start >= _RATE_LIMIT_WINDOW_SECONDS:
            # Reset window
            self._window_start = now
            self._request_count = 0
        self._request_count += 1

        if self._request_count >= _RATE_LIMIT_WARN_THRESHOLD:
            logger.warning(
                "X API v2: approaching rate limit — %d/%d requests in current 15-min window",
                self._request_count,
                _RATE_LIMIT_MAX_REQUESTS,
            )

    def is_exhausted(self) -> bool:
        now = time.monotonic()
        if now - self._window_start >= _RATE_LIMIT_WINDOW_SECONDS:
            return False  # window has reset
        return self._request_count >= _RATE_LIMIT_MAX_REQUESTS

    def seconds_until_reset(self) -> int:
        elapsed = time.monotonic() - self._window_start
        remaining = _RATE_LIMIT_WINDOW_SECONDS - elapsed
        return max(0, int(remaining))


# Module-level tracker shared across all XApiClient instances
_rate_tracker = _RateLimitTracker()


class XApiClient:
    """Async client for X API v2.

    Usage:
        client = XApiClient(bearer_token="AAAAAA...")
        user_id = await client.get_user_id("elonmusk")
        tweets = await client.get_user_tweets(user_id, max_results=10)
    """

    def __init__(self, bearer_token: str) -> None:
        self._bearer_token = bearer_token
        self._headers = {
            "Authorization": f"Bearer {bearer_token}",
            "User-Agent": "OverwatchOSINT/1.0",
        }

    async def get_user_id(self, username: str) -> str:
        """Resolve a Twitter username to its numeric user ID.

        Args:
            username: Twitter handle (with or without leading @)

        Returns:
            Numeric user ID string

        Raises:
            XApiAuthError: Invalid/expired token
            XApiNotFoundError: User not found
            XApiRateLimitError: Rate limit hit
            XApiError: Other API errors
        """
        username = username.lstrip("@")
        url = f"{BASE_URL}/users/by/username/{username}"

        if _rate_tracker.is_exhausted():
            wait = _rate_tracker.seconds_until_reset()
            logger.warning("X API v2: local rate limit exhausted, backing off %ds", wait)
            raise XApiRateLimitError(retry_after=wait)

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers=self._headers)

        _rate_tracker.record_request()
        self._handle_error(resp, context=f"get_user_id({username})")

        data = resp.json()
        user_data = data.get("data", {})
        user_id = user_data.get("id")
        if not user_id:
            raise XApiNotFoundError(f"No user ID in response for @{username}: {data}")

        logger.debug("X API: resolved @%s → user_id=%s", username, user_id)
        return str(user_id)

    async def get_user_tweets(
        self, user_id: str, max_results: int = 10
    ) -> list[dict]:
        """Fetch recent tweets for a user by numeric user ID.

        Args:
            user_id: Numeric user ID (from get_user_id)
            max_results: Number of tweets to return (5–100, API min is 5)

        Returns:
            List of tweet dicts with keys: id, text, author_id, created_at

        Raises:
            XApiAuthError: Invalid/expired token
            XApiRateLimitError: Rate limit hit
            XApiError: Other API errors
        """
        # X API v2 enforces min 5, max 100 for timeline
        max_results = max(5, min(100, max_results))

        url = f"{BASE_URL}/users/{user_id}/tweets"
        params = {
            "tweet.fields": "created_at,author_id,text,id",
            "max_results": str(max_results),
            "exclude": "retweets,replies",  # OSINT focus: original tweets only
        }

        if _rate_tracker.is_exhausted():
            wait = _rate_tracker.seconds_until_reset()
            logger.warning("X API v2: local rate limit exhausted, backing off %ds", wait)
            raise XApiRateLimitError(retry_after=wait)

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers=self._headers, params=params)

        _rate_tracker.record_request()
        self._handle_error(resp, context=f"get_user_tweets({user_id})")

        data = resp.json()
        tweets_raw = data.get("data", [])
        if not tweets_raw:
            logger.debug("X API: no tweets returned for user_id=%s", user_id)
            return []

        # Normalise to a consistent schema
        tweets = []
        for t in tweets_raw:
            tweets.append(
                {
                    "id": str(t.get("id", "")),
                    "text": t.get("text", ""),
                    "author_id": str(t.get("author_id", "")),
                    "created_at": t.get("created_at"),
                    # author field filled in by caller from handle context
                    "author": None,
                }
            )

        logger.debug("X API: fetched %d tweets for user_id=%s", len(tweets), user_id)
        return tweets

    @staticmethod
    def _handle_error(resp: httpx.Response, context: str = "") -> None:
        """Raise typed exceptions for known X API v2 error codes."""
        if resp.status_code == 200:
            return

        ctx = f" [{context}]" if context else ""

        if resp.status_code == 401:
            raise XApiAuthError(
                f"X API v2 401 Unauthorised{ctx}: Bearer Token is invalid or revoked. "
                "Check your X API credentials."
            )
        if resp.status_code == 403:
            raise XApiAuthError(
                f"X API v2 403 Forbidden{ctx}: Token lacks required permissions. "
                "Ensure your app has 'Read' access in the X Developer Portal."
            )
        if resp.status_code == 404:
            raise XApiNotFoundError(f"X API v2 404 Not Found{ctx}: {resp.text}")
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("x-rate-limit-reset", "60"))
            # x-rate-limit-reset is an epoch timestamp; convert to seconds-from-now
            wait = max(0, retry_after - int(time.time()))
            raise XApiRateLimitError(retry_after=wait or 60)

        # Generic error
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        raise XApiError(
            f"X API v2 {resp.status_code}{ctx}: {body}"
        )

    async def resolve_and_fetch(
        self, username: str, max_results: int = 10
    ) -> list[dict]:
        """Convenience: resolve username → user_id → tweets in one call.

        Returns tweets with `author` field populated from the username.
        """
        user_id = await self.get_user_id(username)
        tweets = await self.get_user_tweets(user_id, max_results=max_results)
        # Populate author field
        for t in tweets:
            t["author"] = username.lstrip("@")
        return tweets
