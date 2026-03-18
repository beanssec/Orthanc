"""Per-user API rate limiting middleware.

Limits are applied per authenticated user (JWT sub claim) with fallback to
client IP for unauthenticated requests.

Endpoint groups with separate limits:
  auth   - /auth/** and /token/**          → 5 req/min   (brute-force protection)
  write  - POST/PUT/PATCH/DELETE           → 30 req/min
  read   - everything else                 → 100 req/min

Responses:
  429 Too Many Requests with Retry-After header (seconds until window resets).

Health and metrics paths are exempt from all rate limiting.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from typing import Dict, List

from fastapi import Request
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Exempt prefixes (never rate-limited)
# ---------------------------------------------------------------------------
_EXEMPT_PREFIXES = ("/health", "/metrics")

# ---------------------------------------------------------------------------
# Limit config: (max_requests, window_seconds)
# ---------------------------------------------------------------------------
_GROUP_LIMITS: Dict[str, tuple[int, int]] = {
    "auth":  (5,   60),   # 5 requests per minute
    "write": (30,  60),   # 30 requests per minute
    "read":  (100, 60),   # 100 requests per minute
}


def _classify_request(method: str, path: str) -> str:
    """Return the endpoint group for rate-limiting purposes."""
    if path.startswith(("/auth", "/token", "/login", "/register", "/telegram-auth")):
        return "auth"
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        return "write"
    return "read"


def _extract_user_key(request: Request) -> str:
    """Extract a stable identity key from the request.

    Priority:
      1. JWT sub claim from Authorization Bearer token (user-level limit)
      2. API key prefix (first 8 chars of X-API-Key header)
      3. Client IP (fallback for unauthenticated requests)
    """
    # Try JWT sub claim (decode without verification — we only need the sub)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            import base64, json
            # Decode JWT payload (middle segment) — no signature check needed here
            payload_b64 = token.split(".")[1]
            # Add padding if needed
            padded = payload_b64 + "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded))
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:
            pass

    # Try API key prefix
    api_key = request.headers.get("X-API-Key", "")
    if api_key:
        return f"apikey:{api_key[:12]}"

    # Fallback: client IP
    client_ip = request.client.host if request.client else "unknown"
    return f"ip:{client_ip}"


class PerGroupRateLimiter:
    """Sliding-window rate limiter with per-user, per-group limits."""

    def __init__(self) -> None:
        # Keyed by (identity_key, group) → list of request timestamps
        self._windows: Dict[tuple[str, str], List[float]] = defaultdict(list)

    def check(self, identity: str, group: str) -> tuple[bool, int]:
        """Check if the request is allowed.

        Returns:
            (allowed: bool, retry_after_seconds: int)
            retry_after_seconds is 0 when allowed, else seconds until oldest entry expires.
        """
        max_req, window = _GROUP_LIMITS[group]
        now = time.time()
        key = (identity, group)
        # Evict entries outside the rolling window
        self._windows[key] = [t for t in self._windows[key] if now - t < window]

        if len(self._windows[key]) >= max_req:
            # How long until the oldest entry falls out of the window
            oldest = self._windows[key][0]
            retry_after = math.ceil(window - (now - oldest))
            return False, max(1, retry_after)

        self._windows[key].append(now)
        return True, 0


# Module-level singleton
_limiter = PerGroupRateLimiter()


async def rate_limit_middleware(request: Request, call_next):
    """Rate limit middleware — per-user, per-group, with Retry-After header."""
    path = request.url.path

    # Exempt health + metrics paths
    for prefix in _EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return await call_next(request)

    identity = _extract_user_key(request)
    group = _classify_request(request.method, path)

    allowed, retry_after = _limiter.check(identity, group)

    if not allowed:
        max_req, window = _GROUP_LIMITS[group]
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={
                "detail": "Too many requests",
                "group": group,
                "limit": max_req,
                "window_seconds": window,
                "retry_after_seconds": retry_after,
            },
        )

    return await call_next(request)


# Legacy alias (backwards compat if anything imported the old singleton)
rate_limiter = _limiter
