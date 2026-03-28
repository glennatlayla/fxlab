"""
In-memory sliding-window rate limiter middleware.

Responsibilities:
- Limit governance operations (POST/PUT/PATCH to /overrides, /approvals, /promotions)
  to 20 req/min per IP.
- Limit all other non-health endpoints to 100 req/min per IP.
- Return 429 Too Many Requests with Retry-After header when exceeded.
- Exclude health paths, OPTIONS, and GET /health.

Does NOT:
- Perform business logic.
- Access databases.
- Log sensitive request data.

Dependencies:
- Starlette middleware base classes.
- collections.defaultdict, time.

Future:
- In production, swap _store for a Redis-backed counter by setting
  RATE_LIMIT_BACKEND=redis and REDIS_URL=redis://... (future milestone).

Example:
    app.add_middleware(RateLimitMiddleware)
    # 20 POST /overrides/request per minute per IP → 21st returns 429.
    # 100 GET /runs per minute per IP → 101st returns 429.
"""

import os
import time
from collections import defaultdict

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = structlog.get_logger(__name__)

_EXCLUDED_PATHS = {"/health", "/", "/docs", "/openapi.json", "/redoc"}
_GOVERNANCE_PREFIXES = ("/overrides", "/approvals", "/promotions")
_GOVERNANCE_METHODS = {"POST", "PUT", "PATCH"}

_GOVERNANCE_LIMIT = int(os.environ.get("RATE_LIMIT_GOVERNANCE", "20"))  # per minute
_DEFAULT_LIMIT = int(os.environ.get("RATE_LIMIT_DEFAULT", "100"))  # per minute
_WINDOW_SECONDS = 60


class _SlidingWindow:
    """
    Thread-unsafe in-memory sliding window counter.

    Sufficient for single-worker dev. In production (multi-worker),
    swap for Redis-backed implementation.

    Attributes:
        _store: Dict mapping key -> list of timestamps when requests occurred.
    """

    def __init__(self):
        """Initialize the sliding window store."""
        self._store: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str, limit: int) -> tuple[bool, int]:
        """
        Check if a request is within the rate limit.

        Args:
            key: Rate limit key (e.g. "ip:default" or "ip:path" for governance).
            limit: Maximum number of requests allowed in the window.

        Returns:
            Tuple of (allowed: bool, retry_after_seconds: int).
            retry_after is 0 if allowed, or seconds until the oldest request expires if not.

        Example:
            allowed, retry_after = window.is_allowed("192.168.1.1:default", limit=100)
            if not allowed:
                response.headers["Retry-After"] = str(retry_after)
        """
        now = time.monotonic()
        cutoff = now - _WINDOW_SECONDS
        calls = [t for t in self._store[key] if t > cutoff]
        self._store[key] = calls

        if len(calls) >= limit:
            oldest = calls[0]
            retry_after = int(_WINDOW_SECONDS - (now - oldest)) + 1
            return False, retry_after

        self._store[key].append(now)
        return True, 0


_window = _SlidingWindow()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    In-memory sliding-window rate limiter.

    Limits:
    - Governance endpoints (POST/PUT/PATCH /overrides, /approvals, /promotions):
      20 req/min per IP.
    - All other non-health endpoints: 100 req/min per IP.

    Raises:
        429 Too Many Requests if limit is exceeded.
    """

    async def dispatch(self, request: Request, call_next):
        """
        Process the request and enforce rate limits.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or handler in the stack.

        Returns:
            JSONResponse with 429 if rate limited, otherwise the next handler's response.
        """
        # Exclude OPTIONS and health paths from rate limiting
        if request.method == "OPTIONS" or request.url.path in _EXCLUDED_PATHS:
            return await call_next(request)

        # Extract client IP
        client_ip = request.client.host if request.client else "unknown"

        # Determine if this is a governance operation
        path = request.url.path
        method = request.method
        is_governance = method in _GOVERNANCE_METHODS and any(
            path.startswith(p) for p in _GOVERNANCE_PREFIXES
        )

        # Determine limit and rate limit key
        if is_governance:
            limit = _GOVERNANCE_LIMIT
            key = f"{client_ip}:{path}"
        else:
            limit = _DEFAULT_LIMIT
            key = f"{client_ip}:default"

        # Check rate limit
        allowed, retry_after = _window.is_allowed(key, limit)
        if not allowed:
            logger.warning(
                "rate_limit.exceeded",
                client_ip=client_ip,
                path=path,
                method=method,
                is_governance=is_governance,
                limit=limit,
                retry_after=retry_after,
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please slow down."},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
