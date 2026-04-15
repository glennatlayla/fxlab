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

import re
import socket
from typing import Any

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


def verify_redis_connection(redis_url: str, timeout_seconds: float = 5.0) -> None:
    """
    Verify Redis is available and meets production requirements.

    Performs the following checks:
    1. Connection: Attempts PING and verifies Redis responds.
    2. Version: Verifies Redis >= 6.0 (for ACL support and stability).
    3. Configuration: Checks maxmemory-policy is set (warns if missing).
    4. Cleanup: Properly closes connection after verification.

    Thread-safe: Creates and destroys a connection per call. Multiple
    concurrent calls do not share connection state.

    Args:
        redis_url: Redis connection URL (e.g., redis://redis:6379/0).
                   Supports TLS (rediss://), authentication, and DB selection.
        timeout_seconds: Maximum time to wait for each operation (default: 5.0).

    Returns:
        None on success.

    Raises:
        ConfigError: If Redis is unreachable, version is too old,
                     or any required configuration is missing.
        ImportError: If redis library is not installed (should be caught
                     at container build time).

    Example:
        verify_redis_connection("redis://redis-cluster:6379/0", timeout_seconds=3.0)
        # Raises ConfigError if Redis is unavailable
    """
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

        # Check 1: Connectivity via PING
        try:
            pong = client.ping()
            if pong is not True:
                raise ConfigError(f"Redis PING failed: expected True, got {pong}")
            logger.debug(
                "redis.ping_success",
                component="redis_health",
            )
        except ConfigError:
            # Re-raise our ConfigError as-is
            raise
        except (redis.ConnectionError, redis.TimeoutError) as exc:
            # Handle redis-specific exceptions
            if isinstance(exc, redis.TimeoutError):
                raise ConfigError(
                    f"Redis connection timed out after {timeout_seconds}s at "
                    f"{_strip_credentials(redis_url)}. "
                    f"Error: {str(exc)}. "
                    f"Increase timeout_seconds or check Redis availability."
                ) from exc
            else:
                raise ConfigError(
                    f"Cannot connect to Redis at {_strip_credentials(redis_url)}. "
                    f"Error: {str(exc)}. "
                    f"Ensure Redis is running and reachable. "
                    f"Check REDIS_URL environment variable."
                ) from exc
        except Exception as exc:
            # Catch any other exception during PING as a connection error
            raise ConfigError(
                f"Cannot connect to Redis at {_strip_credentials(redis_url)}. "
                f"Error: {str(exc)}. "
                f"Ensure Redis is running and reachable. "
                f"Check REDIS_URL environment variable."
            ) from exc

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
