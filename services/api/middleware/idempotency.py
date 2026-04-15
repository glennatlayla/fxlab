"""
Idempotency middleware — prevent duplicate write operations on fintech trading platform.

Responsibilities:
- Intercept POST/PUT/PATCH requests with Idempotency-Key header.
- Store response for each key and replay on duplicate requests.
- Keys expire after 1 hour (3600 seconds, configurable via IDEMPOTENCY_WINDOW).
- Return 409 Conflict if request with same key is currently being processed.
- Use in-memory store by default (same pattern as rate_limit.py).
- Thread-safe with threading.Lock.
- Exclude health paths and auth endpoints (tokens must be unique per request).

Does NOT:
- Perform business logic.
- Inspect or modify request/response bodies beyond caching.
- Log sensitive data.

Dependencies:
- Starlette middleware base classes.
- structlog: Structured logging.

Configuration:
- IDEMPOTENCY_WINDOW: Key expiration window in seconds (default: 3600 = 1 hour).

Example:
    app.add_middleware(IdempotencyMiddleware)
    # POST /api/trades with Idempotency-Key: idem-1234
    # -> Response stored under key "idem-1234"
    # POST /api/trades with Idempotency-Key: idem-1234
    # -> Returns cached response with Idempotency-Key-Status: replayed
    # POST /api/trades with Idempotency-Key: idem-1234 (concurrent)
    # -> Returns 409 Conflict
"""

from __future__ import annotations

import os
import threading
import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger(__name__)

# Excluded paths that should not participate in idempotency
_EXCLUDED_PATHS = {"/health", "/", "/docs", "/openapi.json", "/redoc", "/auth/token"}

# Methods subject to idempotency (write operations)
_IDEMPOTENT_METHODS = {"POST", "PUT", "PATCH"}

# Default window for storing responses: 1 hour (was 24 hours prior to
# enterprise hardening H2.8).  Shorter window bounds memory usage and
# reduces the risk of stale idempotency collisions on retried requests
# that legitimately differ.  The window is configurable via env var.
_WINDOW_SECONDS = int(os.environ.get("IDEMPOTENCY_WINDOW", "3600"))


# ---------------------------------------------------------------------------
# In-memory idempotency store
# ---------------------------------------------------------------------------


class IdempotencyStore:
    """
    Thread-safe in-memory store for idempotent request responses.

    Stores successful responses indexed by Idempotency-Key.
    Each entry includes: (status_code, body_bytes, headers_dict, timestamp).

    Attributes:
        _store: Dict mapping idempotency key -> (status, body, headers, timestamp).
        _in_flight: Set of keys currently being processed (to detect concurrent
                    duplicates).
        _lock: Threading lock for thread-safe access.

    Responsibilities:
    - Store and retrieve cached responses.
    - Track in-flight requests to detect concurrency.
    - Clean up expired entries on each request.
    - Provide thread-safe operations.

    Does NOT:
    - Perform business logic.
    - Log sensitive request data.

    Example:
        store = IdempotencyStore()
        # Mark key as in-flight
        in_flight = store.start_request("idem-123")
        if in_flight:
            return Response(..., status_code=409)  # Concurrent duplicate
        # After response ready:
        store.store_response("idem-123", 201, b"...", {...})
        store.finish_request("idem-123")
    """

    def __init__(self, window_seconds: int = _WINDOW_SECONDS) -> None:
        """
        Initialize the idempotency store.

        Args:
            window_seconds: How long to keep responses (default: 3600 = 1h).
        """
        self._store: dict[str, tuple[int, bytes, dict[str, str], float]] = {}
        self._in_flight: set[str] = set()
        self._lock = threading.Lock()
        self._window_seconds = window_seconds

    def start_request(self, key: str) -> bool:
        """
        Mark a request as in-flight.

        Thread-safe. Also performs cleanup of expired entries.

        Args:
            key: Idempotency key for the request.

        Returns:
            True if the key is already being processed (concurrent duplicate),
            False if we successfully marked it as in-flight.

        Raises:
            None. Errors are logged and permissive (allow the request).

        Example:
            if store.start_request("idem-123"):
                return Response(..., status_code=409)  # Concurrent dup
        """
        now = time.time()

        with self._lock:
            # Cleanup expired entries
            self._cleanup_expired(now)

            # Check for concurrent duplicate (already in-flight)
            if key in self._in_flight:
                logger.warning(
                    "idempotency.concurrent_duplicate_detected",
                    key=key,
                    component="idempotency_middleware",
                )
                return True

            # Mark as in-flight
            self._in_flight.add(key)
            logger.debug(
                "idempotency.request_started",
                key=key,
                component="idempotency_middleware",
            )
            return False

    def store_response(
        self,
        key: str,
        status_code: int,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        """
        Store a response for later replay.

        Thread-safe.

        Args:
            key: Idempotency key.
            status_code: HTTP status code (e.g., 201, 200).
            body: Response body as bytes.
            headers: Response headers dict (only non-sensitive headers).

        Returns:
            None.

        Example:
            store.store_response("idem-123", 201, b'{"id": "t123"}', {...})
        """
        now = time.time()

        with self._lock:
            self._store[key] = (status_code, body, headers, now)
            logger.debug(
                "idempotency.response_stored",
                key=key,
                status_code=status_code,
                component="idempotency_middleware",
            )

    def get_cached_response(self, key: str) -> tuple[int, bytes, dict[str, str]] | None:
        """
        Retrieve a cached response if it exists and is not expired.

        Thread-safe.

        Args:
            key: Idempotency key.

        Returns:
            Tuple of (status_code, body_bytes, headers_dict) if found and fresh,
            None if not found or expired.

        Example:
            result = store.get_cached_response("idem-123")
            if result:
                status, body, headers = result
        """
        now = time.time()

        with self._lock:
            if key not in self._store:
                return None

            status, body, headers, timestamp = self._store[key]

            # Check if expired
            if now - timestamp > self._window_seconds:
                del self._store[key]
                logger.debug(
                    "idempotency.cached_response_expired",
                    key=key,
                    age_seconds=int(now - timestamp),
                    component="idempotency_middleware",
                )
                return None

            logger.debug(
                "idempotency.cached_response_retrieved",
                key=key,
                status_code=status,
                age_seconds=int(now - timestamp),
                component="idempotency_middleware",
            )
            return (status, body, headers)

    def finish_request(self, key: str) -> None:
        """
        Mark a request as no longer in-flight.

        Thread-safe. Called after response has been stored.

        Args:
            key: Idempotency key.

        Returns:
            None.

        Example:
            store.finish_request("idem-123")
        """
        with self._lock:
            self._in_flight.discard(key)
            logger.debug(
                "idempotency.request_finished",
                key=key,
                component="idempotency_middleware",
            )

    def _cleanup_expired(self, now: float) -> None:
        """
        Remove all expired entries from the store (must be called with lock held).

        Args:
            now: Current timestamp.

        Returns:
            None.
        """
        expired_keys = [
            key
            for key, (_, _, _, timestamp) in self._store.items()
            if now - timestamp > self._window_seconds
        ]

        for key in expired_keys:
            del self._store[key]

        if expired_keys:
            logger.debug(
                "idempotency.cleanup_completed",
                expired_count=len(expired_keys),
                component="idempotency_middleware",
            )


# ---------------------------------------------------------------------------
# Redis-backed idempotency store (for multi-worker deployments)
# ---------------------------------------------------------------------------


class RedisIdempotencyStore:
    """
    Redis-backed idempotency store for cross-worker duplicate detection.

    Uses Redis SET NX (set-if-not-exists) for atomic in-flight tracking
    and SETEX for cached responses with automatic TTL expiry.

    Fail-open on Redis errors: if Redis is unavailable, requests are
    allowed through (preferring availability over strict dedup). This is
    the correct trade-off because idempotency is a convenience guarantee,
    not a security boundary — the database layer should enforce uniqueness
    constraints on financial transactions.

    Attributes:
        _redis: Redis client instance.
        _window_seconds: TTL for cached responses.

    Example:
        import redis
        r = redis.Redis.from_url("redis://localhost:6379/0")
        store = RedisIdempotencyStore(r, window_seconds=3600)
    """

    # Key prefixes to namespace idempotency data in Redis
    _PREFIX_FLIGHT = "idem:flight:"
    _PREFIX_RESPONSE = "idem:resp:"

    def __init__(self, redis_client: object, window_seconds: int = _WINDOW_SECONDS) -> None:
        """
        Initialize the Redis idempotency store.

        Args:
            redis_client: A redis.Redis client instance.
            window_seconds: TTL for cached responses (default: 3600 = 1h).
        """
        self._redis = redis_client
        self._window_seconds = window_seconds

    def start_request(self, key: str) -> bool:
        """
        Atomically mark a request as in-flight via SET NX.

        Args:
            key: Idempotency key.

        Returns:
            True if the key is already in-flight (concurrent duplicate).
            False if we successfully marked it as in-flight.
        """
        try:
            flight_key = f"{self._PREFIX_FLIGHT}{key}"
            # SET NX with TTL — returns True if the key was set (new request)
            was_set = self._redis.set(  # type: ignore[attr-defined]
                flight_key,
                b"in-flight",
                nx=True,
                ex=60,
            )
            if not was_set:
                # Key already exists — check if it's in-flight or has a cached response
                resp_key = f"{self._PREFIX_RESPONSE}{key}"
                if self._redis.exists(resp_key):  # type: ignore[attr-defined]
                    # Has a cached response — not truly in-flight, just a replay
                    return False
                logger.warning(
                    "idempotency.redis.concurrent_duplicate",
                    key=key,
                    component="idempotency_middleware",
                )
                return True
            return False
        except Exception as exc:
            # Fail-open: allow the request through on Redis error
            logger.warning(
                "idempotency.redis.start_request_error",
                key=key,
                error=str(exc),
                action="allowed",
                component="idempotency_middleware",
            )
            return False

    def store_response(
        self,
        key: str,
        status_code: int,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        """
        Cache a response in Redis with TTL.

        Args:
            key: Idempotency key.
            status_code: HTTP status code.
            body: Response body bytes.
            headers: Response headers dict.
        """
        import base64
        import json

        try:
            resp_key = f"{self._PREFIX_RESPONSE}{key}"
            data = json.dumps(
                {
                    "status_code": status_code,
                    "body": base64.b64encode(body).decode("ascii"),
                    "headers": headers,
                }
            )
            self._redis.setex(  # type: ignore[attr-defined]
                resp_key,
                self._window_seconds,
                data.encode("utf-8"),
            )
            logger.debug(
                "idempotency.redis.response_stored",
                key=key,
                status_code=status_code,
                component="idempotency_middleware",
            )
        except Exception as exc:
            logger.warning(
                "idempotency.redis.store_error",
                key=key,
                error=str(exc),
                component="idempotency_middleware",
            )

    def get_cached_response(self, key: str) -> tuple[int, bytes, dict[str, str]] | None:
        """
        Retrieve a cached response from Redis.

        Args:
            key: Idempotency key.

        Returns:
            Tuple of (status_code, body, headers) if found, None otherwise.
        """
        import base64
        import json

        try:
            resp_key = f"{self._PREFIX_RESPONSE}{key}"
            raw = self._redis.get(resp_key)  # type: ignore[attr-defined]
            if raw is None:
                return None
            data = json.loads(raw)
            return (
                data["status_code"],
                base64.b64decode(data["body"]),
                data["headers"],
            )
        except Exception as exc:
            logger.warning(
                "idempotency.redis.get_cached_error",
                key=key,
                error=str(exc),
                component="idempotency_middleware",
            )
            return None

    def finish_request(self, key: str) -> None:
        """
        Remove the in-flight marker for a request.

        Args:
            key: Idempotency key.
        """
        try:
            flight_key = f"{self._PREFIX_FLIGHT}{key}"
            self._redis.delete(flight_key)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning(
                "idempotency.redis.finish_error",
                key=key,
                error=str(exc),
                component="idempotency_middleware",
            )


def _create_idempotency_store() -> IdempotencyStore | RedisIdempotencyStore:
    """
    Create the appropriate idempotency store based on IDEMPOTENCY_BACKEND env var.

    Returns:
        RedisIdempotencyStore when IDEMPOTENCY_BACKEND=redis and Redis is reachable.
        IdempotencyStore (in-memory) otherwise.

    Example:
        store = _create_idempotency_store()
    """
    backend = os.environ.get("IDEMPOTENCY_BACKEND", "memory").lower()

    if backend == "redis":
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        try:
            import redis as redis_lib

            client = redis_lib.Redis.from_url(redis_url, decode_responses=False)
            client.ping()  # type: ignore[attr-defined]
            logger.info(
                "idempotency.redis_backend_initialized",
                redis_url=redis_url.split("@")[-1] if "@" in redis_url else redis_url,
                component="idempotency_middleware",
            )
            return RedisIdempotencyStore(client, window_seconds=_WINDOW_SECONDS)
        except Exception as exc:
            logger.warning(
                "idempotency.redis_fallback_to_memory",
                error=str(exc),
                component="idempotency_middleware",
            )
            return IdempotencyStore()

    if backend != "memory":
        logger.warning(
            "idempotency.unknown_backend",
            backend=backend,
            action="falling_back_to_memory",
            component="idempotency_middleware",
        )

    return IdempotencyStore()


# Global idempotency store — configured via IDEMPOTENCY_BACKEND env var
_store = _create_idempotency_store()


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Middleware that prevents duplicate write operations using idempotency keys.

    Behavior:
    - Only applies to POST, PUT, PATCH methods.
    - Excludes specific paths (/health, /auth/token, etc).
    - On first request with Idempotency-Key: processes normally, stores response,
      adds "Idempotency-Key-Status: stored" header.
    - On duplicate request with same key: returns cached response with
      "Idempotency-Key-Status: replayed" header.
    - On concurrent request with same key: returns 409 Conflict.
    - Keys expire after 1 hour (configurable via IDEMPOTENCY_WINDOW env var).
    - All operations are thread-safe.

    Attributes:
        _store: The global IdempotencyStore instance.

    Raises:
        409 Conflict: If duplicate request detected while original is being processed.

    Example:
        app.add_middleware(IdempotencyMiddleware)
        # POST /api/trades with Idempotency-Key: my-key
        # -> Response stored, returns "Idempotency-Key-Status: stored"
        # POST /api/trades with Idempotency-Key: my-key
        # -> Returns cached response, "Idempotency-Key-Status: replayed"
    """

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        """
        Process the request and enforce idempotency if applicable.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or handler in the stack.

        Returns:
            JSONResponse with 409 if concurrent duplicate detected,
            cached response if duplicate request,
            original response with "stored" header if new request,
            or original response if idempotency doesn't apply.

        Raises:
            None. Errors are logged; processing continues permissively.
        """
        # Skip idempotency for non-idempotent methods
        if request.method not in _IDEMPOTENT_METHODS:
            logger.debug(
                "idempotency.method_not_idempotent",
                method=request.method,
                path=request.url.path,
                component="idempotency_middleware",
            )
            return await call_next(request)

        # Skip idempotency for excluded paths
        if request.url.path in _EXCLUDED_PATHS:
            logger.debug(
                "idempotency.path_excluded",
                path=request.url.path,
                component="idempotency_middleware",
            )
            return await call_next(request)

        # Extract Idempotency-Key header
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            logger.debug(
                "idempotency.no_key_provided",
                path=request.url.path,
                method=request.method,
                component="idempotency_middleware",
            )
            return await call_next(request)

        # Check if this key is already being processed (concurrent duplicate)
        if _store.start_request(idempotency_key):
            logger.warning(
                "idempotency.concurrent_request_rejected",
                key=idempotency_key,
                path=request.url.path,
                method=request.method,
                component="idempotency_middleware",
            )
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "Duplicate request currently being processed. Please wait and retry."
                },
            )

        # Check if we have a cached response
        cached = _store.get_cached_response(idempotency_key)
        if cached is not None:
            status_code, body, headers = cached
            logger.info(
                "idempotency.cached_response_replayed",
                key=idempotency_key,
                path=request.url.path,
                method=request.method,
                status_code=status_code,
                component="idempotency_middleware",
            )
            # Return cached response with replay header
            response = Response(
                content=body,
                status_code=status_code,
                headers={**headers, "Idempotency-Key-Status": "replayed"},
            )
            _store.finish_request(idempotency_key)
            return response

        # Process the request normally
        try:
            response = await call_next(request)

            # Only cache successful responses (2xx, 3xx, 4xx with specific status codes)
            # Don't cache 5xx server errors or redirects
            if response.status_code < 500:
                # Read response body for caching
                body = b""
                async for chunk in response.body_iterator:
                    body += chunk

                # Extract headers (excluding hop-by-hop headers)
                cached_headers = {
                    k: v
                    for k, v in response.headers.items()
                    if k.lower()
                    not in {
                        "connection",
                        "content-length",
                        "content-encoding",
                        "transfer-encoding",
                        "vary",
                        "pragma",
                        "cache-control",
                        "expires",
                        "set-cookie",
                    }
                }

                # Store the response
                _store.store_response(idempotency_key, response.status_code, body, cached_headers)

                # Return response with "stored" header
                response = Response(
                    content=body,
                    status_code=response.status_code,
                    headers={
                        **cached_headers,
                        "Idempotency-Key-Status": "stored",
                    },
                    media_type=response.media_type,
                )
                logger.info(
                    "idempotency.new_response_stored",
                    key=idempotency_key,
                    path=request.url.path,
                    method=request.method,
                    status_code=response.status_code,
                    component="idempotency_middleware",
                )
            else:
                logger.warning(
                    "idempotency.server_error_not_cached",
                    key=idempotency_key,
                    path=request.url.path,
                    method=request.method,
                    status_code=response.status_code,
                    component="idempotency_middleware",
                )

            return response

        finally:
            # Always mark request as no longer in-flight
            _store.finish_request(idempotency_key)
