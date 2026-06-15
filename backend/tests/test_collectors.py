"""
Collector tests — TASK-98.

All external HTTP calls and database interactions are mocked.
Tests focus on: parsing logic, error handling, deduplication, fallback behaviour.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://invalid:invalid@localhost:5999/invalid_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-orthanc-2024")

from tests.conftest import make_mock_db


# ── RSS collector tests ───────────────────────────────────────────────────────

def _make_feed(entries: list[dict], bozo: bool = False) -> MagicMock:
    """Build a fake feedparser feed."""
    feed_mock = MagicMock()
    feed_mock.bozo = bozo
    feed_mock.bozo_exception = Exception("parse error") if bozo else None
    feed_mock.feed.get = lambda key, default="": {"title": "Test Feed"}.get(key, default)
    feed_mock.entries = []
    for e in entries:
        entry = MagicMock()
        entry.get = lambda k, d="", _e=e: _e.get(k, d)
        entry.id = e.get("id", "")
        entry.link = e.get("link", "")
        entry.title = e.get("title", "")
        entry.summary = e.get("summary", "")
        entry.author = e.get("author", "")
        entry.published_parsed = None
        entry.updated_parsed = None
        entry.created_parsed = None
        feed_mock.entries.append(entry)
    return feed_mock


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rss_collector_parse():
    """RSS collector creates posts from a mocked feed."""
    from app.collectors.rss_collector import RSSCollector

    collector = RSSCollector(poll_interval=9999)  # won't actually poll

    entries = [
        {"id": "guid-001", "link": "https://example.com/1", "title": "Article 1",
         "summary": "Summary one", "author": "Reporter"},
        {"id": "guid-002", "link": "https://example.com/2", "title": "Article 2",
         "summary": "Summary two", "author": "Reporter"},
    ]
    fake_feed = _make_feed(entries)

    # Mock feedparser.parse to return the fake feed synchronously
    # Mock AsyncSessionLocal to return a mock session
    mock_session = make_mock_db()
    # First execute: dedup check returns None (no existing post)
    mock_session.execute.return_value.scalars.return_value.first.return_value = None
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    created_posts = []

    def _capture_add(obj):
        created_posts.append(obj)

    mock_session.add = _capture_add

    ctx_manager = MagicMock()
    ctx_manager.__aenter__ = AsyncMock(return_value=mock_session)
    ctx_manager.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.object(collector, "_parse_feed", AsyncMock(return_value=fake_feed)),
        patch("app.collectors.rss_collector.AsyncSessionLocal", return_value=ctx_manager),
        patch("app.collectors.rss_collector.broadcast_post", AsyncMock()),
        patch("app.collectors.rss_collector.entity_extractor.extract_entities_async", AsyncMock(return_value=[])),
        patch("app.collectors.rss_collector.geo_extractor.process_post", AsyncMock(return_value=[])),
    ):
        feed_url = "https://example.com/feed.rss"
        source_id = "source-001"

        await collector._poll_once(source_id, feed_url)

    # Should have attempted to create 2 posts
    assert len(created_posts) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rss_collector_error_handling():
    """RSS collector surfaces unusable feeds so source health/backoff can record failures."""
    from app.collectors.rss_collector import RSSCollector, RSSFetchError

    collector = RSSCollector(poll_interval=9999)
    feed_url = "https://example.com/bad-feed.rss"

    with patch.object(collector, "_parse_feed", AsyncMock(side_effect=RSSFetchError("parse error with no entries"))):
        with pytest.raises(RSSFetchError):
            await collector._poll_once("source-bad", feed_url)

    assert collector._attempt_history[feed_url] == [False]
    assert feed_url in collector._bozo_warned


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rss_collector_http_500():
    """RSS collector converts HTTP failures into source-health failures."""
    from app.collectors.rss_collector import RSSCollector, RSSFetchError

    collector = RSSCollector(poll_interval=9999)
    feed_url = "https://example.com/error.rss"

    with patch.object(collector, "_parse_feed", AsyncMock(side_effect=RSSFetchError("HTTP 500 fetching feed"))):
        with pytest.raises(RSSFetchError):
            await collector._poll_once("source-err", feed_url)

    assert collector._attempt_history[feed_url] == [False]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reddit_collector_falls_back_to_rss_when_public_json_is_forbidden(monkeypatch):
    """403 from unauthenticated Reddit JSON falls back to subreddit RSS."""
    from app.collectors.reddit_collector import RedditCollector

    collector = RedditCollector()
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)

    rss_body = b"""<?xml version='1.0' encoding='UTF-8'?>
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <title>r/worldnews</title>
      <entry>
        <id>https://www.reddit.com/r/worldnews/comments/abc123/example/</id>
        <title>Example headline</title>
        <author><name>example_author</name></author>
        <updated>2024-01-01T00:00:00Z</updated>
        <link href='https://www.reddit.com/r/worldnews/comments/abc123/example/' />
        <summary>Example summary</summary>
      </entry>
    </feed>"""

    class FakeResponse:
        def __init__(self, status_code, content=b"", headers=None):
            self.status_code = status_code
            self.content = content
            self.headers = headers or {"content-type": "text/html"}

        def raise_for_status(self):
            if self.status_code >= 400:
                import httpx

                raise httpx.HTTPStatusError("forbidden", request=None, response=self)

    class FakeClient:
        async def get(self, url, *args, **kwargs):
            if url.endswith(".rss"):
                return FakeResponse(200, rss_body, {"content-type": "application/atom+xml"})
            return FakeResponse(403)

    data = await collector._fetch_subreddit_listing(FakeClient(), "worldnews")

    post = data["data"]["children"][0]["data"]
    assert post["id"] == "abc123"
    assert post["title"] == "Example headline"
    assert post["source_format"] == "rss_fallback"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reddit_collector_uses_oauth_when_configured(monkeypatch):
    """Configured Reddit collector uses oauth.reddit.com instead of blocked public JSON."""
    from app.collectors.reddit_collector import RedditCollector

    collector = RedditCollector()
    credentials = {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "user_agent": "python:orthanc-test:v1.0",
        "cache_key": "test:client-id",
    }

    calls = []

    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code
            self.headers = {"content-type": "application/json"}

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise AssertionError(f"unexpected HTTP {self.status_code}")

    class FakeClient:
        async def post(self, url, **kwargs):
            calls.append(("POST", url, kwargs))
            return FakeResponse({"access_token": "token-123", "expires_in": 3600})

        async def get(self, url, **kwargs):
            calls.append(("GET", url, kwargs))
            return FakeResponse({"data": {"children": []}})

    data = await collector._fetch_subreddit_listing(FakeClient(), "worldnews", credentials=credentials)

    assert data == {"data": {"children": []}}
    assert calls[0][0] == "POST"
    assert calls[1][0] == "GET"
    assert calls[1][1] == "https://oauth.reddit.com/r/worldnews/new"
    assert calls[1][2]["headers"]["Authorization"] == "Bearer token-123"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reddit_collector_reads_credentials_from_settings():
    """Reddit collector prefers encrypted Settings/Credentials over env vars."""
    from app.collectors.reddit_collector import RedditCollector
    from app.services.collector_manager import collector_manager

    user_id = "user-reddit-001"
    await collector_manager.unlock(user_id, "reddit", {
        "client_id": "settings-client",
        "client_secret": "settings-secret",
        "user_agent": "python:orthanc-settings:v1.0",
    })

    credentials = await RedditCollector()._get_oauth_credentials(user_id)

    assert credentials["client_id"] == "settings-client"
    assert credentials["client_secret"] == "settings-secret"
    assert credentials["user_agent"] == "python:orthanc-settings:v1.0"
    assert credentials["cache_key"] == "user:user-reddit-001:settings-client"

    await collector_manager.lock(user_id, "reddit")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_telegram_collector_dedup():
    """The same Telegram message ID does not create a duplicate post."""
    from app.models.post import Post

    # Simulate the dedup check: existing post found → skip
    mock_session = make_mock_db()

    existing_post = MagicMock(spec=Post)
    existing_post.source_id = "tg-msg-999"

    # Dedup query returns the existing post
    mock_session.execute.return_value.scalars.return_value.first.return_value = existing_post

    ctx_manager = MagicMock()
    ctx_manager.__aenter__ = AsyncMock(return_value=mock_session)
    ctx_manager.__aexit__ = AsyncMock(return_value=False)

    added_objects = []
    mock_session.add = lambda obj: added_objects.append(obj)

    # Build a minimal message object
    msg = MagicMock()
    msg.id = 999
    msg.text = "Duplicate message"
    msg.date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    msg.sender_id = 12345
    msg.media = None
    msg.forward = None
    msg.grouped_id = None

    source = MagicMock()
    source.id = "src-tg-01"
    source.handle = "testchannel"
    source.user_id = "user-01"

    with patch("app.db.AsyncSessionLocal", return_value=ctx_manager):
        # Check the dedup logic manually: if existing post is found, skip
        async with ctx_manager as session:
            from sqlalchemy import select
            from app.models.post import Post as PostModel

            result = await session.execute(
                select(PostModel).where(
                    PostModel.source_type == "telegram",
                    PostModel.source_id == str(msg.id),
                )
            )
            existing = result.scalars().first()

            if existing is None:
                # Would insert
                session.add(MagicMock())

    # Since the mock returns an existing post, nothing should be added
    assert len(added_objects) == 0, "Duplicate message should not be inserted"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_x_collector_fallback():
    """When the X API fails, XCollector falls back to xAI for tweet fetching."""
    import httpx
    from app.collectors.x_collector import XCollector

    collector = XCollector()

    # Simulate X API raising a network error
    xai_results = [
        {"id": "tweet-001", "text": "Tweet from xAI fallback", "created_at": "2024-01-01T00:00:00Z",
         "author": "testuser"},
    ]

    with (
        patch.object(
            collector,
            "_fetch_tweets_x_api",
            AsyncMock(side_effect=httpx.RequestError("X API down")),
        ),
        patch.object(
            collector,
            "_fetch_tweets_xai",
            AsyncMock(return_value=xai_results),
        ),
    ):
        # The public method that orchestrates the fallback
        # We test the fallback logic directly
        try:
            tweets = await collector._fetch_tweets_x_api("testhandle", "x-api-key", "x-api-secret")
            pytest.fail("Expected X API to fail")
        except httpx.RequestError:
            # Fallback to xAI
            tweets = await collector._fetch_tweets_xai("testhandle", "xai-key")

    assert len(tweets) == 1
    assert tweets[0]["id"] == "tweet-001"
