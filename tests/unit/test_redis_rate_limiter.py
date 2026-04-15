"""
Unit tests for pluggable rate limiter backends (INFRA-4).

Tests cover:
- InMemoryRateLimitBackend: basic sliding window behavior.
- RedisRateLimitBackend: sorted-set based sliding window (with mock Redis).
- Backend factory: selects correct backend from RATE_LIMIT_BACKEND env var.
- RedisRateLimitBackend graceful degradation on Redis failure.

Dependencies:
    - services.api.middleware.rate_limit: All backend classes and factory.
    - unittest.mock: For mocking Redis client.

Example:
    pytest tests/unit/test_redis_rate_limiter.py -v
"""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from services.api.middleware.rate_limit import (
    _AUTH_LIMIT,
    _DEFAULT_LIMIT,
    _GOVERNANCE_LIMIT,
    InMemoryRateLimitBackend,
    RateLimitBackend,
    RedisRateLimitBackend,
    _create_backend,
)

# ---------------------------------------------------------------------------
# InMemoryRateLimitBackend tests
# ---------------------------------------------------------------------------


class TestInMemoryBackend:
    """Tests for the in-memory sliding window backend."""

    def test_allows_requests_under_limit(self) -> None:
        """Requests under the limit should be allowed."""
        backend = InMemoryRateLimitBackend()
        for _ in range(5):
            allowed, retry = backend.is_allowed("test:key", limit=10)
            assert allowed is True
            assert retry == 0

    def test_blocks_requests_over_limit(self) -> None:
        """Requests over the limit should be blocked with retry_after > 0."""
        backend = InMemoryRateLimitBackend()
        for _ in range(10):
            backend.is_allowed("test:key", limit=10)

        allowed, retry = backend.is_allowed("test:key", limit=10)
        assert allowed is False
        assert retry > 0

    def test_different_keys_isolated(self) -> None:
        """Each key should have its own independent counter."""
        backend = InMemoryRateLimitBackend()
        for _ in range(10):
            backend.is_allowed("key_a", limit=10)

        # key_b should still be allowed
        allowed, _ = backend.is_allowed("key_b", limit=10)
        assert allowed is True

    def test_window_expires(self) -> None:
        """Requests should be allowed again after the window expires."""
        backend = InMemoryRateLimitBackend()
        # Fill up with 2 requests (limit=2)
        backend.is_allowed("expire:key", limit=2)
        backend.is_allowed("expire:key", limit=2)

        # Should be blocked
        allowed, _ = backend.is_allowed("expire:key", limit=2)
        assert allowed is False

        # Manually expire the timestamps by manipulating the store
        with backend._lock:
            backend._store["expire:key"] = [
                time.monotonic() - 120  # 2 minutes ago (expired)
                for _ in backend._store["expire:key"]
            ]

        # Should be allowed now
        allowed, _ = backend.is_allowed("expire:key", limit=2)
        assert allowed is True

    def test_implements_backend_interface(self) -> None:
        """InMemoryRateLimitBackend must implement RateLimitBackend."""
        assert issubclass(InMemoryRateLimitBackend, RateLimitBackend)
        backend = InMemoryRateLimitBackend()
        assert isinstance(backend, RateLimitBackend)


# ---------------------------------------------------------------------------
# RedisRateLimitBackend tests (with mock Redis)
# ---------------------------------------------------------------------------


class TestRedisBackend:
    """Tests for the Redis-backed sliding window backend."""

    def _make_mock_redis(self, current_count: int = 0) -> MagicMock:
        """Create a mock Redis client with pipeline support."""
        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = [None, current_count]
        mock_redis.pipeline.return_value = mock_pipe
        mock_redis.zrange.return_value = []
        return mock_redis

    def test_allows_when_under_limit(self) -> None:
        """Requests under the limit should be allowed."""
        mock_redis = self._make_mock_redis(current_count=5)
        backend = RedisRateLimitBackend(mock_redis)

        allowed, retry = backend.is_allowed("test:key", limit=10)
        assert allowed is True
        assert retry == 0

    def test_blocks_when_at_limit(self) -> None:
        """Requests at or over the limit should be blocked."""
        mock_redis = self._make_mock_redis(current_count=10)
        mock_redis.zrange.return_value = [(b"member", time.time() - 30)]
        backend = RedisRateLimitBackend(mock_redis)

        allowed, retry = backend.is_allowed("test:key", limit=10)
        assert allowed is False
        assert retry > 0

    def test_fail_closed_on_redis_error(self) -> None:
        """On Redis failure, must DENY the request (fail-closed for security)."""
        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute.side_effect = ConnectionError("Redis down")
        mock_redis.pipeline.return_value = mock_pipe
        backend = RedisRateLimitBackend(mock_redis)

        allowed, retry = backend.is_allowed("test:key", limit=10)
        assert allowed is False, "Rate limiter must deny on Redis failure (fail-closed)"
        assert retry > 0, "retry_after must be positive"

    def test_implements_backend_interface(self) -> None:
        """RedisRateLimitBackend must implement RateLimitBackend."""
        assert issubclass(RedisRateLimitBackend, RateLimitBackend)
        mock_redis = MagicMock()
        backend = RedisRateLimitBackend(mock_redis)
        assert isinstance(backend, RateLimitBackend)

    def test_uses_sorted_set_operations(self) -> None:
        """Backend should use ZREMRANGEBYSCORE and ZCARD for sliding window."""
        mock_redis = self._make_mock_redis(current_count=0)
        backend = RedisRateLimitBackend(mock_redis)

        backend.is_allowed("test:sorted", limit=10)

        # Verify pipeline was used with sorted set operations
        pipe = mock_redis.pipeline.return_value
        pipe.zremrangebyscore.assert_called_once()
        pipe.zcard.assert_called_once()


# ---------------------------------------------------------------------------
# Backend factory tests
# ---------------------------------------------------------------------------


class TestBackendFactory:
    """Tests for the _create_backend factory function."""

    def test_default_is_memory(self) -> None:
        """Default backend (no env var) should be InMemoryRateLimitBackend."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RATE_LIMIT_BACKEND", None)
            backend = _create_backend()
            assert isinstance(backend, InMemoryRateLimitBackend)

    def test_explicit_memory_backend(self) -> None:
        """RATE_LIMIT_BACKEND=memory should return InMemoryRateLimitBackend."""
        with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "memory"}):
            backend = _create_backend()
            assert isinstance(backend, InMemoryRateLimitBackend)

    def test_redis_backend_with_connection(self) -> None:
        """RATE_LIMIT_BACKEND=redis should try to create RedisRateLimitBackend."""
        mock_redis_module = MagicMock()
        mock_client = MagicMock()
        mock_redis_module.Redis.from_url.return_value = mock_client
        mock_client.ping.return_value = True

        with (
            patch.dict(
                os.environ,
                {
                    "RATE_LIMIT_BACKEND": "redis",
                    "REDIS_URL": "redis://localhost:6379/0",
                },
            ),
            patch.dict("sys.modules", {"redis": mock_redis_module}),
        ):
            backend = _create_backend()
            assert isinstance(backend, RedisRateLimitBackend)

    def test_redis_backend_falls_back_on_connection_error(self) -> None:
        """If Redis connection fails, should fall back to InMemoryRateLimitBackend."""
        mock_redis_module = MagicMock()
        mock_redis_module.Redis.from_url.side_effect = ConnectionError("refused")

        with (
            patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "redis"}),
            patch.dict("sys.modules", {"redis": mock_redis_module}),
        ):
            backend = _create_backend()
            assert isinstance(backend, InMemoryRateLimitBackend)

    def test_redis_backend_falls_back_on_import_error(self) -> None:
        """If redis module is not installed, should fall back to InMemoryRateLimitBackend."""
        import sys

        with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "redis"}):
            # Temporarily remove redis from sys.modules and make import fail
            saved = sys.modules.pop("redis", None)
            try:
                with patch.dict("sys.modules", {"redis": None}):
                    backend = _create_backend()
                    assert isinstance(backend, InMemoryRateLimitBackend)
            finally:
                if saved is not None:
                    sys.modules["redis"] = saved

    def test_unknown_backend_raises_error(self) -> None:
        """Unknown backend value should raise ValueError."""
        with (
            patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "memcached"}),
            pytest.raises(ValueError, match="Unknown RATE_LIMIT_BACKEND"),
        ):
            _create_backend()


# ---------------------------------------------------------------------------
# Configuration constants tests
# ---------------------------------------------------------------------------


class TestRateLimitConfiguration:
    """Tests for rate limit configuration constants."""

    def test_auth_limit_is_tightest(self) -> None:
        """Auth limit should be the tightest (lowest) of all limits."""
        assert _AUTH_LIMIT <= _GOVERNANCE_LIMIT
        assert _AUTH_LIMIT <= _DEFAULT_LIMIT

    def test_governance_limit_is_tighter_than_default(self) -> None:
        """Governance limit should be tighter than the default limit."""
        assert _GOVERNANCE_LIMIT <= _DEFAULT_LIMIT
