"""
Per-account login attempt tracker for brute-force protection (AUTH-4).

Purpose:
    Track failed login attempts per email address and temporarily lock
    accounts that exceed the maximum allowed failures within a sliding
    time window.

Responsibilities:
    - Record failed login attempts per email.
    - Check if an email is currently locked out.
    - Clear failure history on successful login.
    - Report retry_after seconds for locked accounts.
    - Thread-safe: safe for use in multi-threaded ASGI workers.

Does NOT:
    - Authenticate users or verify passwords.
    - Block at the network/IP level (that is the rate limiter's job).

Backends:
    - LoginAttemptTracker: In-memory, per-worker only. Suitable for
      single-worker dev and tests.
    - RedisLoginAttemptTracker: Redis sorted-set backed. Cross-worker
      brute-force protection. Fail-closed on Redis errors.

Dependencies:
    - threading: Thread safety via Lock.
    - time: Monotonic clock for window expiry.
    - structlog: Structured logging.

Error conditions:
    - None raised; all methods are safe to call and return sensible defaults.

Example:
    tracker = LoginAttemptTracker(max_attempts=5, window_seconds=900)
    if tracker.is_locked("user@example.com"):
        retry = tracker.retry_after("user@example.com")
        raise HTTPException(429, f"Too many attempts. Retry after {retry}s.")
    # ... attempt login ...
    if login_failed:
        tracker.record_failure("user@example.com")
    else:
        tracker.record_success("user@example.com")
"""

from __future__ import annotations

import os
import threading
import time

import redis
import structlog

logger = structlog.get_logger(__name__)

# Default configuration — overridable via environment variables.
_DEFAULT_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5"))
_DEFAULT_WINDOW_SECONDS = int(os.environ.get("LOGIN_LOCKOUT_WINDOW", "900"))


class LoginAttemptTracker:
    """
    In-memory sliding-window tracker for failed login attempts.

    Tracks per-email failure timestamps and locks out accounts that exceed
    ``max_attempts`` failures within ``window_seconds``. Thread-safe via
    a threading.Lock protecting all state mutations.

    Attributes:
        _max_attempts: Maximum allowed failures before lockout.
        _window_seconds: Sliding window duration in seconds.
        _store: Dict mapping email -> list of failure timestamps (monotonic).
        _lock: Threading lock for concurrent access safety.

    Example:
        tracker = LoginAttemptTracker(max_attempts=5, window_seconds=900)
        tracker.record_failure("user@example.com")
        if tracker.is_locked("user@example.com"):
            retry = tracker.retry_after("user@example.com")
    """

    def __init__(
        self,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        window_seconds: int = _DEFAULT_WINDOW_SECONDS,
    ) -> None:
        """
        Initialize the login attempt tracker.

        Args:
            max_attempts: Number of failures before account lockout (default: 5).
            window_seconds: Sliding window in seconds (default: 900 = 15 min).

        Example:
            tracker = LoginAttemptTracker(max_attempts=5, window_seconds=900)
        """
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._store: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, email: str) -> list[float]:
        """
        Remove expired timestamps for a given email.

        Must be called while holding self._lock.

        Args:
            email: The email to prune timestamps for.

        Returns:
            List of non-expired timestamps still within the window.
        """
        cutoff = time.monotonic() - self._window_seconds
        timestamps = self._store.get(email, [])
        valid = [t for t in timestamps if t > cutoff]
        if valid:
            self._store[email] = valid
        elif email in self._store:
            del self._store[email]
        return valid

    def record_failure(self, email: str) -> None:
        """
        Record a failed login attempt for the given email.

        Appends the current monotonic timestamp to the email's failure list.
        Thread-safe.

        Args:
            email: The email address that failed authentication.

        Example:
            tracker.record_failure("user@example.com")
        """
        with self._lock:
            self._prune(email)
            if email not in self._store:
                self._store[email] = []
            self._store[email].append(time.monotonic())

        logger.debug(
            "login_attempt.failure_recorded",
            email=email,
            component="login_attempt_tracker",
        )

    def record_success(self, email: str) -> None:
        """
        Clear all failure history for the given email after a successful login.

        Thread-safe.

        Args:
            email: The email address that successfully authenticated.

        Example:
            tracker.record_success("user@example.com")
        """
        with self._lock:
            if email in self._store:
                del self._store[email]

        logger.debug(
            "login_attempt.success_cleared",
            email=email,
            component="login_attempt_tracker",
        )

    def is_locked(self, email: str) -> bool:
        """
        Check if the given email is currently locked out.

        An email is locked if it has >= max_attempts failures within the
        sliding window.

        Args:
            email: The email address to check.

        Returns:
            True if the account is locked out, False otherwise.

        Example:
            if tracker.is_locked("user@example.com"):
                raise HTTPException(429, "Too many attempts.")
        """
        with self._lock:
            valid = self._prune(email)
            return len(valid) >= self._max_attempts

    def retry_after(self, email: str) -> int:
        """
        Return seconds until the account lockout expires.

        If the account is not locked, returns 0. Otherwise returns the
        number of seconds until the oldest failure in the window expires,
        which will drop the count below the threshold.

        Args:
            email: The email address to check.

        Returns:
            Seconds until the account is unlocked (0 if not locked).

        Example:
            retry = tracker.retry_after("user@example.com")
            if retry > 0:
                response.headers["Retry-After"] = str(retry)
        """
        with self._lock:
            valid = self._prune(email)
            if len(valid) < self._max_attempts:
                return 0
            # Oldest failure determines when the lock expires
            oldest = valid[0]
            now = time.monotonic()
            remaining = self._window_seconds - (now - oldest)
            return max(1, int(remaining) + 1)


# ---------------------------------------------------------------------------
# Redis-backed tracker for multi-worker production deployments (H-CRIT-3)
# ---------------------------------------------------------------------------


class RedisLoginAttemptTracker:
    """
    Redis-backed sliding-window tracker for failed login attempts.

    Uses Redis sorted sets (ZADD/ZCARD/ZRANGEBYSCORE) to track per-email
    failure timestamps across all ASGI worker processes. This ensures that
    the 5-attempt brute-force limit is enforced globally, not per-worker.

    Fail-closed policy:
        If Redis is unreachable, all methods that check lockout status
        return the SAFE default (locked=True, retry_after=window_seconds).
        This prevents brute-force bypass during Redis outages.

    Attributes:
        _redis: Redis client instance.
        _max_attempts: Maximum allowed failures before lockout.
        _window_seconds: Sliding window duration in seconds.
        _prefix: Redis key prefix for namespacing.

    Dependencies:
        - Redis client (injected via constructor).

    Example:
        import redis
        r = redis.Redis.from_url("redis://localhost:6379/0")
        tracker = RedisLoginAttemptTracker(r, max_attempts=5, window_seconds=900)
        tracker.record_failure("user@example.com")
        if tracker.is_locked("user@example.com"):
            retry = tracker.retry_after("user@example.com")
    """

    _PREFIX = "login:attempts:"

    def __init__(
        self,
        redis_client: redis.Redis,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        window_seconds: int = _DEFAULT_WINDOW_SECONDS,
    ) -> None:
        """
        Initialize the Redis-backed login attempt tracker.

        Args:
            redis_client: A Redis client instance (e.g. redis.Redis).
            max_attempts: Number of failures before account lockout (default: 5).
            window_seconds: Sliding window in seconds (default: 900 = 15 min).

        Example:
            tracker = RedisLoginAttemptTracker(redis_client, max_attempts=5)
        """
        self._redis = redis_client
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds

    def _key(self, email: str) -> str:
        """
        Build the Redis key for a given email.

        Args:
            email: The email address to build a key for.

        Returns:
            Namespaced Redis key string.
        """
        return f"{self._PREFIX}{email}"

    def record_failure(self, email: str) -> None:
        """
        Record a failed login attempt for the given email in Redis.

        Uses a pipeline to atomically:
        1. ZADD the current timestamp to the sorted set.
        2. ZREMRANGEBYSCORE to prune expired entries.
        3. EXPIRE to set TTL on the key (auto-cleanup).

        On Redis error, logs a warning but does NOT raise — the in-memory
        fallback will still be available per-worker.

        Args:
            email: The email address that failed authentication.

        Example:
            tracker.record_failure("user@example.com")
        """
        key = self._key(email)
        now = time.time()
        cutoff = now - self._window_seconds

        try:
            pipe = self._redis.pipeline()
            pipe.zadd(key, {str(now): now})
            pipe.zremrangebyscore(key, "-inf", cutoff)
            # Set key expiry slightly longer than the window to auto-cleanup
            pipe.expire(key, self._window_seconds + 60)
            pipe.execute()

            logger.debug(
                "login_attempt.redis_failure_recorded",
                email=email,
                component="redis_login_tracker",
            )
        except Exception:
            logger.warning(
                "login_attempt.redis_record_failure_error",
                email=email,
                component="redis_login_tracker",
                exc_info=True,
            )

    def record_success(self, email: str) -> None:
        """
        Clear all failure history for the given email after a successful login.

        Deletes the entire sorted set key from Redis.

        On Redis error, logs a warning. The key will expire naturally
        via TTL even if this DELETE fails.

        Args:
            email: The email address that successfully authenticated.

        Example:
            tracker.record_success("user@example.com")
        """
        key = self._key(email)
        try:
            self._redis.delete(key)
            logger.debug(
                "login_attempt.redis_success_cleared",
                email=email,
                component="redis_login_tracker",
            )
        except Exception:
            logger.warning(
                "login_attempt.redis_record_success_error",
                email=email,
                component="redis_login_tracker",
                exc_info=True,
            )

    def is_locked(self, email: str) -> bool:
        """
        Check if the given email is currently locked out.

        Prunes expired entries via ZREMRANGEBYSCORE, then checks ZCARD
        against max_attempts.

        Fail-closed: returns True (locked) on any Redis error. This
        prevents brute-force bypass during Redis outages — a legitimate
        user can retry after a short wait, but an attacker cannot
        exploit the outage window.

        Args:
            email: The email address to check.

        Returns:
            True if the account is locked out or Redis is unreachable.
            False if the account is under the failure threshold.

        Example:
            if tracker.is_locked("user@example.com"):
                raise HTTPException(429, "Too many attempts.")
        """
        key = self._key(email)
        cutoff = time.time() - self._window_seconds

        try:
            # Prune expired entries before counting
            self._redis.zremrangebyscore(key, "-inf", cutoff)
            count = self._redis.zcard(key)
            return count >= self._max_attempts  # type: ignore[operator]  # redis sync stubs partial-typed: zcard returns Awaitable|Any
        except Exception:
            # Fail-closed: deny login attempts when Redis is down
            logger.warning(
                "login_attempt.redis_is_locked_error",
                email=email,
                component="redis_login_tracker",
                detail="Redis unreachable — fail-closed, returning locked=True",
                exc_info=True,
            )
            return True

    def retry_after(self, email: str) -> int:
        """
        Return seconds until the account lockout expires.

        If the account is not locked, returns 0. Otherwise returns the
        number of seconds until the oldest failure in the window expires.

        Fail-closed: returns window_seconds on Redis error.

        Args:
            email: The email address to check.

        Returns:
            Seconds until the account is unlocked (0 if not locked).

        Example:
            retry = tracker.retry_after("user@example.com")
            if retry > 0:
                response.headers["Retry-After"] = str(retry)
        """
        key = self._key(email)
        cutoff = time.time() - self._window_seconds

        try:
            self._redis.zremrangebyscore(key, "-inf", cutoff)
            count = self._redis.zcard(key)
            if count < self._max_attempts:  # type: ignore[operator]  # redis sync stubs partial-typed: zcard returns Awaitable|Any
                return 0

            # Get the oldest entry to calculate remaining lockout time
            oldest_entries = self._redis.zrange(key, 0, 0, withscores=True)
            if not oldest_entries:
                return 0

            oldest_score = oldest_entries[0][1]  # type: ignore[index]  # redis sync stubs partial-typed: zrange returns Awaitable|Any
            now = time.time()
            remaining = self._window_seconds - (now - oldest_score)
            return max(1, int(remaining) + 1)
        except Exception:
            # Fail-closed: return full window on error
            logger.warning(
                "login_attempt.redis_retry_after_error",
                email=email,
                component="redis_login_tracker",
                exc_info=True,
            )
            return self._window_seconds


def _create_login_tracker() -> LoginAttemptTracker | RedisLoginAttemptTracker:
    """
    Factory function for creating the appropriate login attempt tracker.

    Reads LOGIN_TRACKER_BACKEND environment variable:
    - "redis": Creates a RedisLoginAttemptTracker with Redis sorted sets.
    - anything else: Creates the default in-memory LoginAttemptTracker.

    Production safety:
        When ENVIRONMENT=production and LOGIN_TRACKER_BACKEND=redis, a Redis
        connection failure raises RuntimeError. In production, falling back to
        per-worker in-memory tracking silently degrades brute-force protection
        across multiple workers — an attacker could spread attempts across
        workers to bypass the lockout threshold.

        In development/test environments, the factory falls back to in-memory
        with a warning for developer ergonomics.

    Returns:
        A login attempt tracker instance (either in-memory or Redis-backed).

    Raises:
        RuntimeError: If ENVIRONMENT=production, LOGIN_TRACKER_BACKEND=redis,
            and Redis connection fails or REDIS_URL is missing.

    Example:
        tracker = _create_login_tracker()
    """
    backend = os.environ.get("LOGIN_TRACKER_BACKEND", "memory").lower()
    environment = os.environ.get("ENVIRONMENT", "").lower()

    if backend == "redis":
        redis_url = os.environ.get("REDIS_URL")

        if not redis_url:
            if environment == "production":
                raise RuntimeError(
                    "REDIS_URL is required in production when LOGIN_TRACKER_BACKEND=redis. "
                    "Set REDIS_URL to your Redis cluster endpoint "
                    "(e.g. redis://redis:6379/0). Falling back to in-memory is not "
                    "permitted in production — brute-force protection must be "
                    "shared across all workers."
                )
            # Development/test: allow localhost fallback for developer ergonomics
            redis_url = "redis://localhost:6379/0"
            logger.warning(
                "login_tracker.localhost_fallback",
                component="login_tracker_factory",
                detail="REDIS_URL not set — falling back to localhost. "
                "This is acceptable for development but not production.",
            )

        try:
            import redis  # noqa: F811 — lazy import to avoid hard dependency

            client = redis.Redis.from_url(redis_url, decode_responses=False)
            client.ping()  # type: ignore[attr-defined]  # redis.Redis.from_url stub returns None-typed in some versions
            logger.info(
                "login_tracker.redis_connected",
                redis_url=redis_url.split("@")[-1],
                component="login_tracker_factory",
            )
            return RedisLoginAttemptTracker(client)
        except Exception as exc:
            if environment == "production":
                raise RuntimeError(
                    "Failed to connect to Redis for login attempt tracking. "
                    "In production, Redis is required for cross-worker brute-force "
                    "protection. Falling back to in-memory is not permitted. "
                    f"REDIS_URL={redis_url.split('@')[-1]}"
                ) from exc

            logger.warning(
                "login_tracker.redis_fallback",
                component="login_tracker_factory",
                detail="Failed to connect to Redis — falling back to in-memory tracker. "
                "Brute-force protection is per-worker only.",
                exc_info=True,
            )
            return LoginAttemptTracker()

    return LoginAttemptTracker()


# ---------------------------------------------------------------------------
# Module-level singleton — shared across the ASGI worker process.
# When LOGIN_TRACKER_BACKEND=redis, uses Redis sorted sets for cross-worker
# brute-force protection. Otherwise falls back to per-worker in-memory.
# ---------------------------------------------------------------------------
login_tracker = _create_login_tracker()
