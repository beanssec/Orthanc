"""
Pytest configuration and shared fixtures for the Orthanc backend test suite.

Strategy: uses AsyncMock for DB sessions to avoid PostgreSQL-dialect
incompatibilities in the test environment.  A real JWT is generated so
auth-specific tests can exercise the token validation path.

Do NOT import from `app.*` at module level here — conftest is executed before
any monkeypatching; imports are deferred into fixture bodies or helper
functions so they happen after `os.environ` is set up.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Environment must be set before any app import ────────────────────────────
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://invalid:invalid@localhost:5999/invalid_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-orthanc-2024")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key-orthanc-24")
os.environ.setdefault("ORTHANC_MEDIA_DIR", "/tmp/orthanc-test-media")


# ── Constants shared across tests ─────────────────────────────────────────────
TEST_USER_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
TEST_USERNAME = "testuser"
TEST_PASSWORD = "testpassword123"


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_mock_user():
    """Return a MagicMock that quacks like a User ORM object."""
    from app.models.user import User
    user = MagicMock(spec=User)
    user.id = uuid.UUID(TEST_USER_ID)
    user.username = TEST_USERNAME
    user.password_hash = "$argon2id$v=19$m=65536,t=3,p=4$mockhash"
    user.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return user


def make_mock_db():
    """Return a fully-wired AsyncMock for AsyncSession."""
    db = AsyncMock()

    # Default scalar result (covers most SELECT … WHERE patterns)
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    result.scalar_one.return_value = None
    result.scalar.return_value = 0
    scalars = MagicMock()
    scalars.all.return_value = []
    scalars.first.return_value = None
    scalars.one_or_none.return_value = None
    result.scalars.return_value = scalars
    result.fetchall.return_value = []
    result.all.return_value = []
    result.mappings.return_value.all.return_value = []

    db.execute.return_value = result
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.close = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    return db


# ── Core fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def test_user():
    """Mock User ORM object."""
    return make_mock_user()


@pytest.fixture
def db_session():
    """Async SQLAlchemy session mock — no real DB required."""
    return make_mock_db()


@pytest.fixture
def auth_headers():
    """Valid JWT Bearer token for authenticated endpoint tests."""
    from jose import jwt
    from app.config import settings

    payload = {
        "sub": TEST_USER_ID,
        "username": TEST_USERNAME,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(hours=8),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(test_user, db_session):
    """
    FastAPI TestClient with:
      - get_db overridden to return the mock db_session
      - get_current_user overridden to return the mock test_user

    The lifespan startup will attempt to connect to the (non-existent) test DB
    but all collector/service start-up calls are wrapped in try/except and fail
    gracefully.  Actual test requests use the mock DB.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_db
    from app.middleware.auth import get_current_user

    async def _mock_get_db():
        yield db_session

    async def _mock_get_current_user():
        return test_user

    app.dependency_overrides[get_db] = _mock_get_db
    app.dependency_overrides[get_current_user] = _mock_get_current_user

    # Do NOT use the context manager here — entering it runs the lifespan which
    # tries to install signal handlers and fails in non-main threads.
    # raise_server_exceptions=False suppresses startup errors on first request.
    tc = TestClient(app, raise_server_exceptions=False)
    yield tc

    app.dependency_overrides.clear()


# ── Pytest markers / asyncio config ───────────────────────────────────────────

def pytest_configure(config):
    config.addinivalue_line("markers", "unit: Fast unit tests — no I/O")
    config.addinivalue_line("markers", "integration: Integration tests — may use mock I/O")
