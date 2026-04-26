"""
Sliding-window rate limiter middleware with pluggable backend.

Responsibilities:
- Limit auth endpoints (POST /auth/token) to 10 req/min per IP (brute-force).
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
- Optional: redis (for production Redis-backed rate limiting).

Configuration:
- RATE_LIMIT_BACKEND: "memory" (default) or "redis".
- REDIS_URL: Redis connection URL (required when backend=redis).
- RATE_LIMIT_AUTH: Auth endpoint limit per minute (default: 10).
- RATE_LIMIT_GOVERNANCE: Governance endpoint limit per minute (default: 20).
- RATE_LIMIT_DEFAULT: Default endpoint limit per minute (default: 100).

Example:
    app.add_middleware(RateLimitMiddleware)
    # 10 POST /auth/token per minute per IP → 11th returns 429.
    # 20 POST /overrides/request per minute per IP → 21st returns 429.
    # 100 GET /runs per minute per IP → 101st returns 429.
"""

from __future__ import annotations

import abc
import os
import threading
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
_AUTH_PREFIXES = ("/auth/token",)

_GOVERNANCE_LIMIT = int(os.environ.get("RATE_LIMIT_GOVERNANCE", "20"))  # per minute
_AUTH_LIMIT = int(os.environ.get("RATE_LIMIT_AUTH", "10"))  # per minute
_DEFAULT_LIMIT = int(os.environ.get("RATE_LIMIT_DEFAULT", "100"))  # per minute
_WINDOW_SECONDS = 60


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------


class RateLimitBackend(abc.ABC):
    """
    Abstract rate limit backend.

    Implementations track request counts per key within a sliding window
    and report whether a new request is allowed.

    Responsibilities:
    - Count requests per key within the configured window.
    - Return whether a new request is allowed and the retry-after delay.

    Does NOT:
    - Classify requests (that is the middleware's job).
    - Log or raise errors.
    """

    @abc.abstractmethod
    def is_allowed(self, key: str, limit: int) -> tuple[bool, int]:
        """
        Check if a request is within the rate limit.

        Args:
            key: Rate limit key (e.g. "192.168.1.1:auth").
            limit: Maximum requests allowed per window.

        Returns:
            Tuple of (allowed, retry_after_seconds).
            retry_after is 0 if allowed.
        """


# ---------------------------------------------------------------------------
# In-memory backend (single-worker, development, tests)
# ---------------------------------------------------------------------------


class InMemoryRateLimitBackend(RateLimitBackend):
    """
    Thread-safe in-memory sliding window counter.

    Uses a threading.Lock to guard read-modify-write of the timestamp
    lists so concurrent ASGI requests (served from a thread pool) cannot
    corrupt the window state.

    Suitable for single-worker deployments and tests. Multi-worker
    production deployments should use RedisRateLimitBackend.

    Attributes:
        _store: Dict mapping key -> list of timestamps.
        _lock: Threading lock for thread safety.

    Example:
        backend = InMemoryRateLimitBackend()
        allowed, retry = backend.is_allowed("192.168.1.1:default", limit=100)
    """

    def __init__(self) -> None:
        """Initialize the in-memory store and its lock."""
        self._store: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, key: str, limit: int) -> tuple[bool, int]:
        """
        Check if a request is within the rate limit (in-memory).

        Thread-safe: acquires the internal lock for the duration of the
        check-and-append operation.

        Args:
            key: Rate limit key.
            limit: Maximum requests per window.

        Returns:
            Tuple of (allowed, retry_after_seconds).

        Example:
            allowed, retry = backend.is_allowed("10.0.0.1:auth", 10)
        """
        now = time.monotonic()
        cutoff = now - _WINDOW_SECONDS

        with self._lock:
            calls = [t for t in self._store[key] if t > cutoff]
            self._store[key] = calls

            if len(calls) >= limit:
                oldest = calls[0]
                retry_after = int(_WINDOW_SECONDS - (now - oldest)) + 1
                return False, retry_after

            self._store[key].append(now)
            return True, 0


# ---------------------------------------------------------------------------
# Redis backend (multi-worker production)
# ---------------------------------------------------------------------------


class RedisRateLimitBackend(RateLimitBackend):
    """
    Redis-backed sliding window rate limiter using sorted sets.

    Each key is a Redis sorted set where members are unique request IDs
    (timestamps with random suffix) and scores are Unix timestamps.
    The window is enforced by removing members older than (now - window_seconds).

    Thread-safe: Redis operations are atomic or pipelined within a single
    MULTI/EXEC transaction.

    Attributes:
        _redis: Redis client instance.
        _window_seconds: Sliding window duration.

    Dependencies:
        - redis: Python Redis client library.

    Error conditions:
        - Redis connection failure: DENIES the request with retry_after=5s
          (fail-closed to prevent unlimited access during Redis outages).
          This is critical for financial platforms where /auth/token
          brute-force must remain rate-limited even when Redis is down.

    Example:
        import redis
        r = redis.Redis.from_url("redis://localhost:6379/0")
        backend = RedisRateLimitBackend(r)
        allowed, retry = backend.is_allowed("10.0.0.1:auth", 10)
    """

    def __init__(self, redis_client: object, window_seconds: int = _WINDOW_SECONDS) -> None:
        """
        Initialize the Redis-backed rate limit backend.

        Args:
            redis_client: A ``redis.Redis`` (or compatible) client instance.
            window_seconds: Sliding window duration in seconds (default: 60).

        Example:
            backend = RedisRateLimitBackend(redis.Redis.from_url(url))
        """
        self._redis = redis_client
        self._window_seconds = window_seconds

    def is_allowed(self, key: str, limit: int) -> tuple[bool, int]:
        """
        Check if a request is within the rate limit (Redis-backed).

        Uses a Redis sorted set with scores as Unix timestamps. Atomically:
        1. Remove expired entries (score < now - window).
        2. Count remaining entries.
        3. If under limit, add the new request.
        4. Set TTL on the key for automatic cleanup.

        Falls back to allowing the request if Redis is unavailable (permissive).

        Args:
            key: Rate limit key.
            limit: Maximum requests per window.

        Returns:
            Tuple of (allowed, retry_after_seconds).

        Example:
            allowed, retry = backend.is_allowed("10.0.0.1:default", 100)
        """
        import secrets

        redis_key = f"ratelimit:{key}"
        now = time.time()
        cutoff = now - self._window_seconds

        try:
            pipe = self._redis.pipeline(transaction=True)  # type: ignore[attr-defined]
            # Remove expired entries
            pipe.zremrangebyscore(redis_key, "-inf", cutoff)
            # Count current entries
            pipe.zcard(redis_key)
            results = pipe.execute()
            current_count = results[1]

            if current_count >= limit:
                # Find the oldest entry to compute retry_after
                oldest = self._redis.zrange(redis_key, 0, 0, withscores=True)  # type: ignore[attr-defined]
                if oldest:
                    oldest_score = oldest[0][1]
                    retry_after = int(self._window_seconds - (now - oldest_score)) + 1
                    return False, max(1, retry_after)
                return False, 1

            # Add this request with a unique member and current timestamp as score
            member = f"{now}:{secrets.token_hex(4)}"
            pipe2 = self._redis.pipeline(transaction=True)  # type: ignore[attr-defined]
            pipe2.zadd(redis_key, {member: now})
            pipe2.expire(redis_key, self._window_seconds + 10)
            pipe2.execute()

            return True, 0

        except Exception as exc:
            # Fail-closed on Redis failure — DENY the request to prevent
            # unlimited access (especially to /auth/token brute-force).
            # For a financial trading platform, fail-open would allow an
            # attacker unlimited requests during any Redis outage.
            logger.warning(
                "rate_limit.redis_error",
                key=key,
                error=str(exc),
                component="rate_limit",
                action="denied",
            )
            return False, 5


# ---------------------------------------------------------------------------
# Backend factory
# ---------------------------------------------------------------------------


def _create_backend() -> RateLimitBackend:
    """
    Create the appropriate rate limit backend based on RATE_LIMIT_BACKEND env var.

    Returns:
        InMemoryRateLimitBackend (default) or RedisRateLimitBackend.

    Raises:
        ValueError: If RATE_LIMIT_BACKEND is set to an unknown value.

    Example:
        backend = _create_backend()
    """
    backend_type = os.environ.get("RATE_LIMIT_BACKEND", "memory").lower()

    if backend_type == "memory":
        logger.info(
            "rate_limit.backend_initialized",
            backend="memory",
            component="rate_limit",
        )
        return InMemoryRateLimitBackend()

    if backend_type == "redis":
        redis_url = os.environ.get("REDIS_URL")
        environment = os.environ.get("ENVIRONMENT", "").lower()

        if not redis_url:
            if environment == "production":
                raise RuntimeError(
                    "REDIS_URL is required in production when RATE_LIMIT_BACKEND=redis. "
                    "Set REDIS_URL to your Redis cluster endpoint "
                    "(e.g. redis://redis:6379/0). Falling back to localhost is not "
                    "permitted in production deployments."
                )
            # Development/test: allow localhost fallback for developer ergonomics
            redis_url = "redis://localhost:6379/0"
            logger.warning(
                "rate_limit.localhost_fallback",
                component="rate_limit",
                detail="REDIS_URL not set — falling back to localhost. "
                "This is acceptable for development but not production.",
            )

        try:
            import redis

            client = redis.Redis.from_url(redis_url, decode_responses=True)
            # Test connectivity
            client.ping()  # type: ignore[attr-defined]  # redis.Redis.from_url stub returns None-typed in some versions
            logger.info(
                "rate_limit.backend_initialized",
                backend="redis",
                redis_url=redis_url.split("@")[-1],  # Strip credentials
                component="rate_limit",
            )
            return RedisRateLimitBackend(client)
        except ImportError:
            logger.warning(
                "rate_limit.redis_import_failed",
                component="rate_limit",
            )
            return InMemoryRateLimitBackend()
        except Exception as exc:
            logger.warning(
                "rate_limit.redis_connect_failed",
                error=str(exc),
                component="rate_limit",
            )
            return InMemoryRateLimitBackend()

    raise ValueError(f"Unknown RATE_LIMIT_BACKEND: '{backend_type}'. Supported: 'memory', 'redis'.")


_window: RateLimitBackend = _create_backend()


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window rate limiter with pluggable backend.

    Limits:
    - Auth endpoints (POST /auth/token): 10 req/min per IP.
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

        # Classify the request and apply the appropriate rate limit bucket
        path = request.url.path
        method = request.method
        is_governance = method in _GOVERNANCE_METHODS and any(
            path.startswith(p) for p in _GOVERNANCE_PREFIXES
        )
        is_auth = method == "POST" and any(path.startswith(p) for p in _AUTH_PREFIXES)

        # Determine limit and rate limit key — auth is tightest, then
        # governance, then the general default bucket.
        if is_auth:
            limit = _AUTH_LIMIT
            key = f"{client_ip}:auth"
        elif is_governance:
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


# ---------------------------------------------------------------------------
# FastAPI dependency decorator for endpoint-specific rate limiting
# ---------------------------------------------------------------------------


def rate_limit(
    max_requests: int,
    window_seconds: int,
    scope: str = "",
):
    """
    FastAPI dependency factory for endpoint-specific rate limiting.

    Returns a callable that can be wrapped with Depends() to enforce
    per-user, per-scope rate limits. Extracts user ID from JWT token
    in Authorization header and checks rate limit against the configured
    max_requests within window_seconds.

    Raises:
        RateLimitExceededError: When the user exceeds the configured limit.

    Args:
        max_requests: Maximum requests allowed in the window.
        window_seconds: Time window in seconds.
        scope: Rate limit scope identifier for logging/tracking
               (e.g., "run_submission", "kill_switch", "risk_setting").

    Returns:
        A callable that performs the rate limit check (to be wrapped with Depends).

    Raises:
        RateLimitExceededError: If limit exceeded; caught by controller
                                and returned as 429 HTTP response.

    Example:
        @router.post("/research/runs")
        async def submit_run(
            run: RunRequest,
            _rate_check = Depends(
                rate_limit(max_requests=5, window_seconds=60, scope="run_submission")
            ),
            request: Request,
        ) -> RunResponse:
            # Rate limit already checked by dependency
            # Process the run request
            pass
    """
    import jwt

    from libs.contracts.rate_limit import RateLimitExceededError

    async def _check_rate_limit(request: Request) -> None:
        """
        Check rate limit for the current user and scope.

        Extracts user ID from JWT token in Authorization header. Constructs
        a rate limit key as "user_id:scope" and checks against the configured
        limit and window. Logs the check and raises RateLimitExceededError
        if exceeded.

        Args:
            request: FastAPI request context.

        Raises:
            RateLimitExceededError: If the user has exceeded the limit.
        """
        # Extract user ID from JWT token in Authorization header
        auth_header = request.headers.get("Authorization", "")
        user_id = "unknown"

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                # Decode JWT without verification (we assume upstream auth middleware
                # already verified it). We only care about the 'sub' claim.
                decoded = jwt.decode(token, options={"verify_signature": False})
                user_id = decoded.get("sub", "unknown")
            except Exception:
                # If JWT is malformed, use "unknown" user ID
                user_id = "unknown"

        # Construct rate limit key
        rate_limit_key = f"{user_id}:{scope}" if scope else f"{user_id}:default"

        # Check rate limit
        allowed, retry_after = _window.is_allowed(rate_limit_key, max_requests)

        if not allowed:
            # Log the rate limit violation
            logger.warning(
                "rate_limit.dependency_exceeded",
                user_id=user_id,
                scope=scope,
                limit=max_requests,
                window_seconds=window_seconds,
                retry_after=retry_after,
                path=request.url.path,
                method=request.method,
                component="rate_limit_dependency",
            )

            # Raise exception for controller to catch and convert to 429
            raise RateLimitExceededError(
                detail="Rate limit exceeded. Please slow down.",
                retry_after_seconds=retry_after,
                scope=scope,
                limit=max_requests,
                window_seconds=window_seconds,
            )

        # Log successful check (at DEBUG level to avoid noise)
        logger.debug(
            "rate_limit.dependency_allowed",
            user_id=user_id,
            scope=scope,
            limit=max_requests,
            path=request.url.path,
            component="rate_limit_dependency",
        )

    # Return the check function (caller wraps with Depends)
    return _check_rate_limit
