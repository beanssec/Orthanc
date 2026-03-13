"""Simple in-memory rate limiter middleware."""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse


class RateLimiter:
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> bool:
        now = time.time()
        # Evict timestamps outside the rolling window
        self._requests[key] = [t for t in self._requests[key] if now - t < self.window]
        if len(self._requests[key]) >= self.max_requests:
            return False
        self._requests[key].append(now)
        return True


rate_limiter = RateLimiter()


async def rate_limit_middleware(request: Request, call_next):
    """Reject clients that exceed 100 req/min. Health paths are exempt."""
    # Exempt health probes so Docker/K8s checks are never blocked
    if request.url.path.startswith("/health"):
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.check(client_ip):
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests"},
        )

    return await call_next(request)
