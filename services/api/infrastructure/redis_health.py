"""
Redis health check and validation at application startup.

Responsibilities:
- Verify Redis connectivity before startup in production.
- Validate Redis version meets minimum requirements (6.0 for ACL support).
- Check critical Redis configuration (maxmemory-policy for eviction).
- Graceful fallback in non-production environments.
- Thread-safe connection management with automatic cleanup.

Does NOT:
- Perform periodic health monitoring (that is a separate concern).
- Modify Redis configuration.
- Handle business logic related to rate limiting or job queues.

Configuration:
- REDIS_URL: Connection string (e.g., redis://localhost:6379/0).
- ENVIRONMENT: Execution context (production enforces health checks).
- RATE_LIMIT_BACKEND: If set to "redis", triggers health check in production.

Error conditions:
- Redis unreachable: Raises ConfigError in production.
- Version < 6.0: Raises ConfigError (ACL support required for production).
- maxmemory-policy not set: Logs warning but allows startup.

Dependencies:
- redis: Python Redis client library (must be installed).

Example:
    from services.api.infrastructure.redis_health import verify_redis_connection

    try:
        verify_redis_connection(
            redis_url="redis://redis:6379/0",
            timeout_seconds=5.0
        )
        logger.info("Redis is healthy and ready for production")
    except ConfigError as exc:
        logger.critical(f"Redis health check failed: {exc}")
        raise
"""

from __future__ import annotations

import errno
import re
import socket
import ssl
import time
from typing import Any, Callable

import structlog

from libs.contracts.errors import ConfigError

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# TCP keepalive tuning for Redis client sockets.
#
# Values (seconds / count), chosen to balance "detect dead peer promptly" with
# "do not trip Linux kernel minimums":
#   - TCP_KEEPIDLE  = 60s   idle time before first probe is sent
#   - TCP_KEEPINTVL = 30s   interval between subsequent probes
#   - TCP_KEEPCNT   = 3     probes before the connection is dropped
# Total time to detect a dead peer: ~60 + (30 * 3) = 150 seconds.
#
# These values are well above the Linux kernel's minimum accepted settings
# and have been verified on kernel 6.17 in Docker's default network
# namespace. The previous implementation used {1: 1, 2: 1} — a 1-second
# idle with a 1-second interval — which the kernel rejects with EINVAL
# (errno 22) inside setsockopt(IPPROTO_TCP, TCP_KEEPIDLE, 1). That was the
# root cause of the 2026-04-15 minitux install failure.
#
# Platform note: socket.TCP_KEEPIDLE / TCP_KEEPINTVL / TCP_KEEPCNT are
# defined on Linux only. On macOS and Windows these symbols don't exist on
# the `socket` module, so _build_keepalive_options() returns an empty dict
# on those platforms. With socket_keepalive=True still set, redis-py will
# fall back to OS-default keepalive tuning — acceptable on developer
# machines where production kernel-specific tuning is irrelevant.
# ---------------------------------------------------------------------------

_KEEPALIVE_IDLE_SECONDS = 60
_KEEPALIVE_INTERVAL_SECONDS = 30
_KEEPALIVE_PROBE_COUNT = 3


def _build_keepalive_options() -> dict[int, int]:
    """
    Build a platform-appropriate TCP keepalive options dict for redis-py.

    Returns:
        dict mapping the Linux TCP_KEEPIDLE / TCP_KEEPINTVL / TCP_KEEPCNT
        socket option integers to their values, or an empty dict on
        non-Linux platforms where these symbols are not exposed by the
        ``socket`` module.

    Example:
        opts = _build_keepalive_options()
        # On Linux:
        #   {socket.TCP_KEEPIDLE: 60,
        #    socket.TCP_KEEPINTVL: 30,
        #    socket.TCP_KEEPCNT: 3}
        # On macOS / Windows: {}
    """
    opts: dict[int, int] = {}
    for attr_name, attr_value in (
        ("TCP_KEEPIDLE", _KEEPALIVE_IDLE_SECONDS),
        ("TCP_KEEPINTVL", _KEEPALIVE_INTERVAL_SECONDS),
        ("TCP_KEEPCNT", _KEEPALIVE_PROBE_COUNT),
    ):
        if hasattr(socket, attr_name):
            opts[getattr(socket, attr_name)] = attr_value
    return opts


# ---------------------------------------------------------------------------
# Error classification for operator-facing diagnostics.
#
# The misleading message "Ensure Redis is running" is only correct when the
# failure is a network/server-availability failure. When the failure is a
# client-side defect — e.g. the kernel rejected one of our setsockopt calls
# with EINVAL — that message sends the operator on a wild goose chase.
#
# This classifier inspects the exception chain and returns:
#   * ("client_socket_option", ...) when an OSError with EINVAL/ENOPROTOOPT
#     appears — the kernel refused our socket options.
#   * ("tls", ...) when an ssl.SSLError appears — the TLS handshake failed.
#   * ("network", ...) otherwise — the generic "check Redis availability"
#     hint is appropriate.
# ---------------------------------------------------------------------------

# errno values that indicate the kernel rejected our setsockopt call.
# * EINVAL (22) — invalid value for the option (e.g. TCP_KEEPIDLE=1 under
#   Linux kernel 6.17 in Docker, the 2026-04-15 minitux install failure).
# * ENOPROTOOPT (92) — option not supported by this protocol level.
_CLIENT_SOCKET_OPTION_ERRNOS: frozenset[int] = frozenset(
    e
    for e in (getattr(errno, "EINVAL", None), getattr(errno, "ENOPROTOOPT", None))
    if e is not None
)


def _classify_connection_error(exc: BaseException) -> tuple[str, str]:
    """
    Classify a Redis connection error for operator-facing diagnostics.

    Walks ``exc.__cause__`` and ``exc.__context__`` to find the root cause
    and returns a ``(category, diagnostic)`` pair where:

    * ``category`` is one of ``"client_socket_option"``, ``"tls"``, or
      ``"network"`` — suitable for structured log fields.
    * ``diagnostic`` is a human-readable hint that tells the operator
      where to look. For ``client_socket_option`` the hint explicitly
      names the defect as client-side so operators do not waste time
      inspecting a healthy Redis server.

    Args:
        exc: The exception raised by redis-py or the underlying socket
             library.

    Returns:
        ``(category, diagnostic)`` — both strings, both non-empty.

    Example:
        >>> import errno as _errno
        >>> cat, msg = _classify_connection_error(
        ...     OSError(_errno.EINVAL, "Invalid argument")
        ... )
        >>> cat
        'client_socket_option'
    """
    root: BaseException | None = exc
    seen: set[int] = set()

    while root is not None and id(root) not in seen:
        seen.add(id(root))

        if isinstance(root, ssl.SSLError):
            return (
                "tls",
                "TLS/SSL handshake failure. Verify the rediss:// URL, the CA "
                "bundle, and the Redis server certificate. Underlying error: "
                f"{root.__class__.__name__}: {root}.",
            )

        if isinstance(root, OSError) and root.errno in _CLIENT_SOCKET_OPTION_ERRNOS:
            errno_name = errno.errorcode.get(root.errno, "unknown")
            return (
                "client_socket_option",
                (
                    f"Client-side socket option rejected by the kernel "
                    f"(errno={root.errno} {errno_name}). "
                    "This is a defect in the API socket configuration — NOT a "
                    "Redis server availability issue. Do NOT waste time "
                    "checking whether Redis is running. Inspect "
                    "services/api/infrastructure/redis_health.py "
                    "(_build_keepalive_options) and verify the keepalive "
                    "values meet the running kernel's accepted range."
                ),
            )

        if isinstance(root, OSError) and root.errno == getattr(errno, "ECONNREFUSED", None):
            return (
                "network",
                "Connection refused by host — Redis is not accepting connections "
                "at the configured address. Ensure the Redis service is running, "
                "the host:port in REDIS_URL is correct, and network policies "
                "permit egress to the Redis port.",
            )

        # Walk the chain. Prefer __cause__ (explicit `raise X from Y`) and
        # fall back to __context__ (implicit chaining from nested raises).
        next_exc = root.__cause__ or root.__context__
        root = next_exc

    return (
        "network",
        "Could not establish a connection to Redis. Ensure Redis is running "
        "and reachable at the configured REDIS_URL, and that network policies "
        "permit egress to the Redis port.",
    )


# ---------------------------------------------------------------------------
# Retry budget for transient Redis health-check failures (B2).
#
# Rationale:
#   * A brief network hiccup or Redis server GC pause should not abort API
#     startup — retrying a few times with backoff is appropriate.
#   * A permanent error (auth failure, client-side socket option defect,
#     TLS mismatch) MUST NOT retry. Retries just delay operator visibility
#     into the real root cause; see D2 for the classification logic.
#   * The schedule is 1s, 2s, 4s, 8s, 16s (doubling) with a hard upper
#     cap so a misconfigured max_retries cannot produce a multi-minute
#     sleep that makes the API startup appear hung.
# ---------------------------------------------------------------------------

_DEFAULT_MAX_RETRIES: int = 5
_DEFAULT_INITIAL_BACKOFF_SECONDS: float = 1.0
_BACKOFF_CAP_SECONDS: float = 30.0

# Categories that must NOT be retried (see _classify_connection_error).
# Retrying these only delays operator visibility into the real defect.
_NON_RETRYABLE_CATEGORIES: frozenset[str] = frozenset({"client_socket_option", "tls", "auth"})


def _compute_backoff_seconds(attempt: int, initial: float, cap: float) -> float:
    """
    Compute the exponential backoff delay for a given retry attempt.

    Formula: ``min(initial * 2**(attempt-1), cap)``.

    Args:
        attempt: 1-based attempt number (1 for the first retry after the
                 initial try, 2 for the second retry, and so on).
        initial: Base delay in seconds for attempt=1 (typically 1.0).
        cap: Maximum delay in seconds. Prevents runaway backoff when
             max_retries is large.

    Returns:
        The delay in seconds to wait before the next attempt.

    Example:
        >>> _compute_backoff_seconds(attempt=1, initial=1.0, cap=30.0)
        1.0
        >>> _compute_backoff_seconds(attempt=4, initial=1.0, cap=30.0)
        8.0
        >>> _compute_backoff_seconds(attempt=20, initial=1.0, cap=30.0)
        30.0
    """
    if attempt < 1:
        raise ValueError(f"attempt must be >= 1, got {attempt}")
    delay = initial * (2 ** (attempt - 1))
    return min(delay, cap)


def verify_redis_connection(
    redis_url: str,
    timeout_seconds: float = 5.0,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    initial_backoff_seconds: float = _DEFAULT_INITIAL_BACKOFF_SECONDS,
    sleep: Callable[[float], None] | None = None,
) -> None:
    """
    Verify Redis is available and meets production requirements.

    Performs the following checks:
    1. Connection: Attempts PING and verifies Redis responds. Transient
       failures (timeout, network) retry with exponential backoff up to
       ``max_retries`` attempts. Permanent failures (auth, client-side
       socket-option defects, TLS handshake failure) fail fast without
       retry — retrying them just hides the real root cause.
    2. Version: Verifies Redis >= 6.0 (for ACL support and stability).
    3. Configuration: Checks maxmemory-policy is set (warns if missing).
    4. Cleanup: Properly closes connection after verification.

    Thread-safe: Creates and destroys a connection per call. Multiple
    concurrent calls do not share connection state.

    Args:
        redis_url: Redis connection URL (e.g., redis://redis:6379/0).
                   Supports TLS (rediss://), authentication, and DB selection.
        timeout_seconds: Maximum time to wait for each operation (default: 5.0).
        max_retries: Maximum number of PING attempts for transient failures
                     (default: 5). 1 means "no retries". Auth errors and
                     client-side defects never retry regardless of this value.
        initial_backoff_seconds: Base delay before the first retry
                     (default: 1.0). Each subsequent retry doubles the delay,
                     capped at 30 seconds.
        sleep: Injectable sleep callable for tests. Defaults to ``time.sleep``
               when None. Signature: ``sleep(seconds: float) -> None``.

    Returns:
        None on success.

    Raises:
        ConfigError: If Redis is unreachable after exhausting retries,
                     version is too old, any required configuration is
                     missing, or a permanent (non-retryable) error occurred.
        ImportError: If redis library is not installed (should be caught
                     at container build time).

    Example:
        verify_redis_connection("redis://redis-cluster:6379/0", timeout_seconds=3.0)
        # Raises ConfigError if Redis is unavailable after 5 retries
    """
    if max_retries < 1:
        raise ValueError(f"max_retries must be >= 1, got {max_retries}")
    _sleep: Callable[[float], None] = sleep if sleep is not None else time.sleep
    try:
        import redis
    except ImportError as exc:
        raise ConfigError(
            "redis library is not installed. Install it with: pip install redis"
        ) from exc

    client: Any = None
    try:
        # Create connection with timeout.
        # socket_keepalive_options is built via _build_keepalive_options() to
        # use kernel-sane values (see module-level comment). Passing raw
        # integer keys with sub-minimum values here will cause setsockopt to
        # raise EINVAL on Linux and crash startup before PING ever fires.
        client = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=timeout_seconds,
            socket_keepalive=True,
            socket_keepalive_options=_build_keepalive_options(),
        )

        # Check 1: Connectivity via PING — with transient-failure retry (B2).
        #
        # Loop invariant: exactly one PING is attempted per loop iteration.
        # On success the loop breaks. On a permanent failure (auth, client
        # socket option defect, TLS) we raise immediately. On a transient
        # failure we either sleep and retry, or (if the retry budget is
        # exhausted) raise with a message naming the attempt count.
        last_category: str = "unknown"
        last_diagnostic: str = ""
        last_exc: BaseException | None = None
        for attempt in range(1, max_retries + 1):
            try:
                pong = client.ping()
                if pong is not True:
                    raise ConfigError(f"Redis PING failed: expected True, got {pong}")
                logger.debug(
                    "redis.ping_success",
                    component="redis_health",
                    attempt=attempt,
                )
                break  # Success — exit retry loop.
            except ConfigError:
                # Re-raise our ConfigError (bad PING response) — this is not
                # a transient condition; the server is responding with the
                # wrong value and retries will not help.
                raise
            except redis.AuthenticationError as exc:
                # Permanent: credentials are wrong. Do not retry.
                logger.warning(
                    "redis.auth_failed",
                    component="redis_health",
                    category="auth",
                    redis_url=_strip_credentials(redis_url),
                    underlying_error=str(exc),
                    attempt=attempt,
                )
                raise ConfigError(
                    f"Redis authentication failed at {_strip_credentials(redis_url)}. "
                    f"Category: auth. "
                    f"Underlying error: {exc!s}. "
                    "Verify the credentials in REDIS_URL and any Redis ACL "
                    "configuration on the server. This error is not retried."
                ) from exc
            except (redis.ConnectionError, redis.TimeoutError) as exc:
                # Redis-library errors. Classify to decide retry vs fail-fast.
                if isinstance(exc, redis.TimeoutError):
                    category, diagnostic = (
                        "timeout",
                        (
                            f"Redis PING timed out after {timeout_seconds}s. "
                            "The socket connected but the server did not reply "
                            "in time. Increase timeout_seconds or check Redis "
                            "load and availability."
                        ),
                    )
                else:
                    category, diagnostic = _classify_connection_error(exc)
                last_category, last_diagnostic, last_exc = category, diagnostic, exc

                if category in _NON_RETRYABLE_CATEGORIES:
                    logger.warning(
                        "redis.ping_failed_permanent",
                        component="redis_health",
                        category=category,
                        redis_url=_strip_credentials(redis_url),
                        underlying_error=str(exc),
                        attempt=attempt,
                    )
                    raise ConfigError(
                        f"Redis health check failed at {_strip_credentials(redis_url)}. "
                        f"Category: {category}. "
                        f"Underlying error: {exc!s}. "
                        f"{diagnostic} "
                        "This error is not retried."
                    ) from exc

                # Transient — retry if we have budget left.
                if attempt < max_retries:
                    delay = _compute_backoff_seconds(
                        attempt=attempt,
                        initial=initial_backoff_seconds,
                        cap=_BACKOFF_CAP_SECONDS,
                    )
                    logger.warning(
                        "redis.ping_retry",
                        component="redis_health",
                        category=category,
                        redis_url=_strip_credentials(redis_url),
                        underlying_error=str(exc),
                        attempt=attempt,
                        max_retries=max_retries,
                        delay_seconds=delay,
                    )
                    _sleep(delay)
                    continue
                # Retry budget exhausted.
                logger.warning(
                    "redis.ping_exhausted",
                    component="redis_health",
                    category=category,
                    redis_url=_strip_credentials(redis_url),
                    underlying_error=str(exc),
                    attempts=attempt,
                )
                raise ConfigError(
                    f"Redis health check failed at {_strip_credentials(redis_url)} "
                    f"after {attempt} attempts. "
                    f"Category: {category}. "
                    f"Underlying error: {exc!s}. "
                    f"{diagnostic}"
                ) from exc
            except Exception as exc:
                # Any other exception — classify so socket-option defects
                # raised as plain OSError are still diagnosed correctly.
                category, diagnostic = _classify_connection_error(exc)
                last_category, last_diagnostic, last_exc = category, diagnostic, exc

                if category in _NON_RETRYABLE_CATEGORIES:
                    logger.warning(
                        "redis.ping_failed_permanent",
                        component="redis_health",
                        category=category,
                        redis_url=_strip_credentials(redis_url),
                        underlying_error=str(exc),
                        attempt=attempt,
                    )
                    raise ConfigError(
                        f"Redis health check failed at {_strip_credentials(redis_url)}. "
                        f"Category: {category}. "
                        f"Underlying error: {exc!s}. "
                        f"{diagnostic} "
                        "This error is not retried."
                    ) from exc

                if attempt < max_retries:
                    delay = _compute_backoff_seconds(
                        attempt=attempt,
                        initial=initial_backoff_seconds,
                        cap=_BACKOFF_CAP_SECONDS,
                    )
                    logger.warning(
                        "redis.ping_retry",
                        component="redis_health",
                        category=category,
                        redis_url=_strip_credentials(redis_url),
                        underlying_error=str(exc),
                        attempt=attempt,
                        max_retries=max_retries,
                        delay_seconds=delay,
                    )
                    _sleep(delay)
                    continue
                logger.warning(
                    "redis.ping_exhausted",
                    component="redis_health",
                    category=category,
                    redis_url=_strip_credentials(redis_url),
                    underlying_error=str(exc),
                    attempts=attempt,
                )
                raise ConfigError(
                    f"Redis health check failed at {_strip_credentials(redis_url)} "
                    f"after {attempt} attempts. "
                    f"Category: {category}. "
                    f"Underlying error: {exc!s}. "
                    f"{diagnostic}"
                ) from exc
        else:
            # for-else runs when the loop completes without break — i.e. we
            # never succeeded. Defensive: this path should be unreachable
            # because the final attempt's exception handler raises. Kept as
            # a safety net so we never fall through silently into Check 2
            # with an un-PINGed client.
            raise ConfigError(
                f"Redis health check failed at {_strip_credentials(redis_url)} "
                f"after {max_retries} attempts. "
                f"Category: {last_category}. "
                f"Underlying error: {last_exc!s}. "
                f"{last_diagnostic}"
            )

        # Check 2: Version >= 6.0 (ACL support required)
        try:
            info_response = client.info("server")
            version_str = info_response.get("redis_version", "unknown")
            version_tuple = _parse_redis_version(version_str)

            if version_tuple < (6, 0):
                raise ConfigError(
                    f"Redis version {version_str} is too old. "
                    f"Minimum required version is 6.0 (for ACL support). "
                    f"Please upgrade Redis before deploying to production."
                )

            logger.info(
                "redis.version_check_passed",
                version=version_str,
                component="redis_health",
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ConfigError(
                f"Cannot determine Redis version. "
                f"Error: {str(exc)}. "
                f"Ensure Redis is responding to INFO commands."
            ) from exc

        # Check 3: Configuration validation (maxmemory-policy)
        try:
            config = client.config_get("maxmemory-policy")
            policy = config.get("maxmemory-policy", "")

            if not policy or policy == "noeviction":
                logger.warning(
                    "redis.maxmemory_policy_not_set",
                    detail=(
                        "Redis maxmemory-policy is not set or is 'noeviction'. "
                        "When Redis reaches maxmemory, commands will start failing. "
                        "Recommended: Set to 'allkeys-lru' or 'allkeys-lfu' to enable "
                        "automatic key eviction. "
                        "Command: CONFIG SET maxmemory-policy allkeys-lru"
                    ),
                    component="redis_health",
                )
            else:
                logger.info(
                    "redis.maxmemory_policy_configured",
                    policy=policy,
                    component="redis_health",
                )
        except Exception as exc:
            # Configuration check is advisory; do not fail startup
            logger.warning(
                "redis.config_check_failed",
                error=str(exc),
                component="redis_health",
                detail="Could not verify maxmemory-policy. "
                "Startup will continue, but monitor Redis memory usage.",
            )

        logger.info(
            "redis.health_check_passed",
            component="redis_health",
            detail=f"Connected to Redis at {_strip_credentials(redis_url)}",
        )

    except ConfigError:
        # Re-raise ConfigError as-is
        raise
    except Exception as exc:
        # Catch any other unexpected errors
        raise ConfigError(f"Unexpected error during Redis health check: {str(exc)}") from exc
    finally:
        # Always close the connection
        if client is not None:
            try:
                client.close()
            except Exception as cleanup_exc:  # pragma: no cover
                logger.warning(
                    "redis.cleanup_failed",
                    error=str(cleanup_exc),
                    component="redis_health",
                )


def _parse_redis_version(version_str: str) -> tuple[int, ...]:
    """
    Parse a Redis version string into a comparable tuple.

    Args:
        version_str: Version string like "7.0.0" or "6.2.1-rc1".

    Returns:
        Tuple of integers like (7, 0, 0) for comparison.

    Raises:
        ValueError: If version string cannot be parsed.

    Example:
        _parse_redis_version("6.2.1") → (6, 2, 1)
        _parse_redis_version("7.0.0-rc1") → (7, 0, 0)
    """
    # Extract numeric part before any suffix (e.g., "-rc1", "-alpha")
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version_str)
    if not match:
        raise ValueError(f"Cannot parse Redis version: {version_str}")
    return tuple(int(x) for x in match.groups())


def _strip_credentials(redis_url: str) -> str:
    """
    Remove credentials from Redis URL for safe logging.

    Args:
        redis_url: Full Redis URL (e.g., redis://user:pass@host:6379/0).

    Returns:
        URL with credentials replaced by "..." (e.g., redis://...@host:6379/0).

    Example:
        _strip_credentials("redis://mypass@redis:6379/0")
        → "redis://...@redis:6379/0"
    """
    # Replace anything between :// and @ with ...
    return re.sub(r"://[^@]+@", "://...@", redis_url)
