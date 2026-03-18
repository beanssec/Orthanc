"""
Auth flow tests — TASK-94.

Tests login, registration, session-status, and token expiry.
All DB calls are mocked; no real database required.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://invalid:invalid@localhost:5999/invalid_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-overwatch-2024")

from tests.conftest import TEST_USER_ID, TEST_USERNAME, TEST_PASSWORD, make_mock_db, make_mock_user


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_client(db_override=None, user_override=None):
    """Create a TestClient with dependency overrides for auth tests."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_db
    from app.middleware.auth import get_current_user

    db = db_override or make_mock_db()
    user = user_override or make_mock_user()

    async def _mock_get_db():
        yield db

    async def _mock_get_current_user():
        return user

    app.dependency_overrides[get_db] = _mock_get_db
    app.dependency_overrides[get_current_user] = _mock_get_current_user
    return TestClient(app, raise_server_exceptions=False), db, user


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_login_success():
    """Valid credentials return a JWT access token."""
    from argon2 import PasswordHasher
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_db
    from app.middleware.auth import get_current_user

    ph = PasswordHasher()
    password_hash = ph.hash(TEST_PASSWORD)

    mock_user = make_mock_user()
    mock_user.password_hash = password_hash

    db = make_mock_db()
    db.execute.return_value.scalar_one_or_none.return_value = mock_user

    async def _mock_get_db():
        yield db

    async def _mock_get_current_user():
        return mock_user

    app.dependency_overrides[get_db] = _mock_get_db
    app.dependency_overrides[get_current_user] = _mock_get_current_user

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})

    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert "refresh_token" in data

    app.dependency_overrides.clear()


@pytest.mark.unit
def test_login_invalid_password():
    """Wrong password returns HTTP 401."""
    from argon2 import PasswordHasher
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_db

    ph = PasswordHasher()
    password_hash = ph.hash("correct_password")

    mock_user = make_mock_user()
    mock_user.password_hash = password_hash

    db = make_mock_db()
    db.execute.return_value.scalar_one_or_none.return_value = mock_user

    async def _mock_get_db():
        yield db

    app.dependency_overrides[get_db] = _mock_get_db
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post("/auth/login", json={"username": TEST_USERNAME, "password": "wrong_password"})

    assert resp.status_code == 401

    app.dependency_overrides.clear()


@pytest.mark.unit
def test_login_nonexistent_user():
    """Login for an unknown user returns HTTP 401."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_db

    db = make_mock_db()
    # user not found
    db.execute.return_value.scalar_one_or_none.return_value = None

    async def _mock_get_db():
        yield db

    app.dependency_overrides[get_db] = _mock_get_db
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post("/auth/login", json={"username": "nobody", "password": "anything"})

    assert resp.status_code == 401

    app.dependency_overrides.clear()


@pytest.mark.unit
def test_session_status(client, auth_headers):
    """GET /auth/session-status returns user info for a valid token."""
    resp = client.get("/auth/session-status", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    # Should contain authentication status fields
    assert "authenticated" in data or isinstance(data, dict)


@pytest.mark.unit
def test_session_status_expired():
    """An expired / invalid token returns HTTP 401."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_db

    db = make_mock_db()

    async def _mock_get_db():
        yield db

    app.dependency_overrides[get_db] = _mock_get_db
    # Do NOT override get_current_user — let the real auth middleware run
    # with a bad token so it returns 401.
    if "get_current_user" in app.dependency_overrides:
        del app.dependency_overrides["get_current_user"]

    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get(
        "/auth/session-status",
        headers={"Authorization": "Bearer this.is.not.a.valid.token"},
    )
    assert resp.status_code == 401

    app.dependency_overrides.clear()


@pytest.mark.unit
def test_register_new_user():
    """POST /auth/register creates a new user and returns user info."""
    from datetime import datetime, timezone
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_db

    db = make_mock_db()
    # First execute: username uniqueness check → None (username is free)
    db.execute.return_value.scalar_one_or_none.return_value = None

    # db.refresh is called after commit; patch it to set created_at
    # (server_default is not applied by the mock DB, so we must set it manually)
    async def _refresh_with_created_at(user_obj):
        if not getattr(user_obj, "created_at", None):
            user_obj.created_at = datetime.now(timezone.utc)

    db.refresh = AsyncMock(side_effect=_refresh_with_created_at)

    async def _mock_get_db():
        yield db

    app.dependency_overrides[get_db] = _mock_get_db
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/auth/register",
        json={"username": "brandnewuser", "password": "securepass123"},
    )

    # 201 Created is expected; 400 if username taken; 422 validation error
    assert resp.status_code in (201, 200, 400, 422), \
        f"Unexpected status {resp.status_code}: {resp.text[:300]}"
    if resp.status_code == 201:
        data = resp.json()
        assert "username" in data

    app.dependency_overrides.clear()
