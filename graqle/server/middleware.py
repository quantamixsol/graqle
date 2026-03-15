"""Server middleware — authentication, rate limiting, request validation."""

# ── graqle:intelligence ──
# module: graqle.server.middleware
# risk: HIGH (impact radius: 34 modules)
# consumers: sdk_self_audit, adaptive, reformulator, relevance, benchmark_runner +29 more
# dependencies: __future__, logging, os, time, collections +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from collections.abc import Callable

logger = logging.getLogger("graqle.server.middleware")

# ---------------------------------------------------------------------------
# T61: API Key Authentication
# ---------------------------------------------------------------------------

API_KEY_HEADER = "X-API-Key"
AUTH_BEARER_PREFIX = "Bearer "


def get_configured_api_keys() -> set[str]:
    """Load valid API keys from environment.

    Supports:
        COGNIGRAPH_API_KEY — single key
        COGNIGRAPH_API_KEYS — comma-separated list
    """
    keys: set[str] = set()
    single = os.environ.get("COGNIGRAPH_API_KEY", "")
    if single:
        keys.add(single)
    multi = os.environ.get("COGNIGRAPH_API_KEYS", "")
    if multi:
        keys.update(k.strip() for k in multi.split(",") if k.strip())
    return keys


def setup_auth_middleware(app) -> None:
    """Add API key authentication middleware to FastAPI app.

    Checks X-API-Key header or Authorization: Bearer <key>.
    Skips auth for /health and /docs endpoints.
    Disabled when no API keys are configured (development mode).
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    valid_keys = get_configured_api_keys()

    if not valid_keys:
        logger.info("No API keys configured — auth disabled (dev mode)")
        return

    logger.info(f"API key auth enabled ({len(valid_keys)} key(s) configured)")

    class AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Callable):
            # Skip auth for health/docs
            path = request.url.path
            if path in ("/health", "/docs", "/openapi.json", "/redoc"):
                return await call_next(request)

            # Check X-API-Key header
            api_key = request.headers.get(API_KEY_HEADER, "")

            # Fallback: Authorization: Bearer <key>
            if not api_key:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith(AUTH_BEARER_PREFIX):
                    api_key = auth_header[len(AUTH_BEARER_PREFIX):]

            if api_key not in valid_keys:
                logger.warning(f"Auth failed from {request.client.host}: invalid key")
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or missing API key"},
                )

            return await call_next(request)

    app.add_middleware(AuthMiddleware)


# ---------------------------------------------------------------------------
# T62: Rate Limiting (Token Bucket)
# ---------------------------------------------------------------------------

class TokenBucket:
    """Simple token bucket rate limiter.

    Args:
        rate: Tokens added per second
        capacity: Maximum tokens in bucket
    """

    def __init__(self, rate: float = 10.0, capacity: float = 20.0) -> None:
        self.rate = rate
        self.capacity = capacity
        self._tokens = capacity
        self._last_refill = time.monotonic()

    def consume(self, tokens: float = 1.0) -> bool:
        """Try to consume tokens. Returns True if allowed."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False


class RateLimiter:
    """Per-client rate limiter using token buckets.

    Args:
        rate: Requests per second per client
        capacity: Burst capacity per client
    """

    def __init__(self, rate: float = 10.0, capacity: float = 20.0) -> None:
        self.rate = rate
        self.capacity = capacity
        self._buckets: dict[str, TokenBucket] = defaultdict(
            lambda: TokenBucket(rate=self.rate, capacity=self.capacity)
        )

    def allow(self, client_key: str) -> bool:
        return self._buckets[client_key].consume()


def setup_rate_limit_middleware(
    app,
    rate: float = 10.0,
    capacity: float = 20.0,
) -> None:
    """Add rate limiting middleware to FastAPI app.

    Configurable via env vars:
        COGNIGRAPH_RATE_LIMIT — requests/second (default: 10)
        COGNIGRAPH_RATE_BURST — burst capacity (default: 20)
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    env_rate = os.environ.get("COGNIGRAPH_RATE_LIMIT")
    env_burst = os.environ.get("COGNIGRAPH_RATE_BURST")
    if env_rate:
        rate = float(env_rate)
    if env_burst:
        capacity = float(env_burst)

    limiter = RateLimiter(rate=rate, capacity=capacity)

    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Callable):
            # Use API key or IP as client identifier
            client_key = (
                request.headers.get(API_KEY_HEADER, "")
                or request.client.host
            )

            if not limiter.allow(client_key):
                logger.warning(f"Rate limited: {client_key}")
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Try again later."},
                    headers={"Retry-After": "1"},
                )

            return await call_next(request)

    app.add_middleware(RateLimitMiddleware)


# ---------------------------------------------------------------------------
# T63: Request Validation Constants
# ---------------------------------------------------------------------------

MAX_QUERY_LENGTH = 10_000  # 10K chars
MAX_ROUNDS = 20
MAX_BATCH_SIZE = 50
