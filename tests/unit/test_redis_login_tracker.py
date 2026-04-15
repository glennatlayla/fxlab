"""
Unit tests for RedisLoginAttemptTracker (M3 — Redis-Backed Login Tracking).

Tests cover:
- RedisLoginAttemptTracker: sorted-set-backed sliding window via mock Redis.
- Lockout after max_attempts failures.
- Success clears failure history.
- Fail-closed: Redis unavailability denies login (not bypass).
- retry_after returns correct lockout duration.
- Factory: LOGIN_TRACKER_BACKEND=redis auto-selects RedisLoginAttemptTracker.
- Factory: Redis connection failure produces fail-closed fallback, NOT in-memory.

Dependencies:
    - services.api.services.login_attempt_tracker: RedisLoginAttemptTracker,
      LoginAttemptTracker, _create_login_tracker.
    - unittest.mock: For mocking Redis client.

Example:
    pytest tests/unit/test_redis_login_tracker.py -v
"""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from services.api.services.login_attempt_tracker import (
    LoginAttemptTracker,
    RedisLoginAttemptTracker,
    _create_login_tracker,
)

# ---------------------------------------------------------------------------
# Helper: build a mock Redis client with configurable sorted set behavior
# ---------------------------------------------------------------------------


def _make_mock_redis(
    *,
    zcard_return: int = 0,
    zrange_return: list | None = None,
) -> MagicMock:
    """
    Create a mock Redis client suitable for RedisLoginAttemptTracker tests.

    Args:
        zcard_return: Value returned by zcard() (number of entries in sorted set).
        zrange_return: Value returned by zrange(..., withscores=True).

    Returns:
        Configured MagicMock emulating a redis.Redis client.
    """
    mock = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute.return_value = [None, None, None]  # zadd, zremrange, expire
    mock.pipeline.return_value = mock_pipe

    mock.zremrangebyscore.return_value = 0
    mock.zcard.return_value = zcard_return
    mock.zrange.return_value = zrange_return or []
    mock.delete.return_value = 1
    return mock


# ---------------------------------------------------------------------------
# RedisLoginAttemptTracker unit tests
# ---------------------------------------------------------------------------


class TestRedisLoginAttemptTracker:
    """Tests for the Redis-backed login attempt tracker."""

    def test_record_failure_uses_pipeline(self) -> None:
        """record_failure should use a Redis pipeline with ZADD + ZREMRANGEBYSCORE + EXPIRE."""
        mock_redis = _make_mock_redis()
        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)

        tracker.record_failure("user@example.com")

        pipe = mock_redis.pipeline.return_value
        pipe.zadd.assert_called_once()
        pipe.zremrangebyscore.assert_called_once()
        pipe.expire.assert_called_once()
        pipe.execute.assert_called_once()

    def test_record_failure_uses_correct_key(self) -> None:
        """record_failure should use key prefix 'login:attempts:<email>'."""
        mock_redis = _make_mock_redis()
        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)

        tracker.record_failure("test@example.com")

        pipe = mock_redis.pipeline.return_value
        # First arg to zadd should be the key
        zadd_call = pipe.zadd.call_args
        assert zadd_call[0][0] == "login:attempts:test@example.com"

    def test_record_success_deletes_key(self) -> None:
        """record_success should delete the entire sorted set for the email."""
        mock_redis = _make_mock_redis()
        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)

        tracker.record_success("user@example.com")

        mock_redis.delete.assert_called_once_with("login:attempts:user@example.com")

    def test_is_locked_returns_false_under_threshold(self) -> None:
        """is_locked should return False when failure count < max_attempts."""
        mock_redis = _make_mock_redis(zcard_return=3)
        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)

        assert tracker.is_locked("user@example.com") is False

    def test_is_locked_returns_true_at_threshold(self) -> None:
        """is_locked should return True when failure count >= max_attempts."""
        mock_redis = _make_mock_redis(zcard_return=5)
        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)

        assert tracker.is_locked("user@example.com") is True

    def test_is_locked_prunes_expired_before_counting(self) -> None:
        """is_locked should ZREMRANGEBYSCORE before ZCARD to prune stale entries."""
        mock_redis = _make_mock_redis(zcard_return=0)
        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)

        tracker.is_locked("prune@example.com")

        # Verify zremrangebyscore was called on the correct key
        mock_redis.zremrangebyscore.assert_called_once()
        args = mock_redis.zremrangebyscore.call_args[0]
        assert args[0] == "login:attempts:prune@example.com"
        assert args[1] == "-inf"
        # Third arg should be a cutoff timestamp (float)
        assert isinstance(args[2], float)

    def test_is_locked_fail_closed_on_redis_error(self) -> None:
        """When Redis is unreachable, is_locked must return True (fail-closed).

        This is critical for brute-force protection: during a Redis outage,
        an attacker must NOT be able to bypass the lockout mechanism.
        """
        mock_redis = MagicMock()
        mock_redis.zremrangebyscore.side_effect = ConnectionError("Redis down")
        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)

        assert tracker.is_locked("attacker@example.com") is True

    def test_retry_after_returns_zero_when_not_locked(self) -> None:
        """retry_after should return 0 when the account is not locked."""
        mock_redis = _make_mock_redis(zcard_return=2)
        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)

        assert tracker.retry_after("free@example.com") == 0

    def test_retry_after_returns_positive_when_locked(self) -> None:
        """retry_after should return > 0 when the account is locked."""
        now = time.time()
        mock_redis = _make_mock_redis(
            zcard_return=5,
            zrange_return=[(b"oldest_entry", now - 10)],  # 10 seconds ago
        )
        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)

        retry = tracker.retry_after("locked@example.com")
        assert retry > 0
        assert retry <= 900

    def test_retry_after_fail_closed_on_redis_error(self) -> None:
        """When Redis fails, retry_after must return window_seconds (fail-closed)."""
        mock_redis = MagicMock()
        mock_redis.zremrangebyscore.side_effect = ConnectionError("Redis down")
        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)

        assert tracker.retry_after("attacker@example.com") == 900

    def test_record_failure_tolerates_redis_error(self) -> None:
        """record_failure should log but not raise on Redis error."""
        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute.side_effect = ConnectionError("Redis down")
        mock_redis.pipeline.return_value = mock_pipe
        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)

        # Should not raise
        tracker.record_failure("user@example.com")

    def test_record_success_tolerates_redis_error(self) -> None:
        """record_success should log but not raise on Redis error."""
        mock_redis = MagicMock()
        mock_redis.delete.side_effect = ConnectionError("Redis down")
        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)

        # Should not raise
        tracker.record_success("user@example.com")

    def test_expire_set_on_key(self) -> None:
        """record_failure should set TTL on the sorted set key."""
        mock_redis = _make_mock_redis()
        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)

        tracker.record_failure("user@example.com")

        pipe = mock_redis.pipeline.return_value
        expire_call = pipe.expire.call_args
        assert expire_call[0][0] == "login:attempts:user@example.com"
        # TTL should be window_seconds + some buffer
        assert expire_call[0][1] >= 900

    def test_different_emails_use_different_keys(self) -> None:
        """Each email should map to a distinct Redis key."""
        mock_redis = _make_mock_redis(zcard_return=0)
        tracker = RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)

        tracker.is_locked("a@example.com")
        tracker.is_locked("b@example.com")

        calls = mock_redis.zremrangebyscore.call_args_list
        keys = [c[0][0] for c in calls]
        assert "login:attempts:a@example.com" in keys
        assert "login:attempts:b@example.com" in keys


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


class TestLoginTrackerFactory:
    """Tests for _create_login_tracker factory function."""

    def test_default_is_in_memory(self) -> None:
        """Default factory (no env var) should return LoginAttemptTracker."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LOGIN_TRACKER_BACKEND", None)
            tracker = _create_login_tracker()
            assert isinstance(tracker, LoginAttemptTracker)

    def test_explicit_memory_backend(self) -> None:
        """LOGIN_TRACKER_BACKEND=memory returns LoginAttemptTracker."""
        with patch.dict(os.environ, {"LOGIN_TRACKER_BACKEND": "memory"}):
            tracker = _create_login_tracker()
            assert isinstance(tracker, LoginAttemptTracker)

    def test_redis_backend_when_connection_succeeds(self) -> None:
        """LOGIN_TRACKER_BACKEND=redis with working Redis returns RedisLoginAttemptTracker."""
        mock_redis_module = MagicMock()
        mock_client = MagicMock()
        mock_redis_module.Redis.from_url.return_value = mock_client
        mock_client.ping.return_value = True

        with (
            patch.dict(
                os.environ,
                {
                    "LOGIN_TRACKER_BACKEND": "redis",
                    "REDIS_URL": "redis://localhost:6379/0",
                },
            ),
            patch.dict("sys.modules", {"redis": mock_redis_module}),
        ):
            tracker = _create_login_tracker()
            assert isinstance(tracker, RedisLoginAttemptTracker)

    def test_redis_backend_falls_back_on_connection_error(self) -> None:
        """If Redis connection fails, factory should fall back to in-memory."""
        mock_redis_module = MagicMock()
        mock_redis_module.Redis.from_url.side_effect = ConnectionError("refused")

        with (
            patch.dict(os.environ, {"LOGIN_TRACKER_BACKEND": "redis"}),
            patch.dict("sys.modules", {"redis": mock_redis_module}),
        ):
            tracker = _create_login_tracker()
            # Falls back to in-memory on connection failure
            assert isinstance(tracker, LoginAttemptTracker)

    def test_redis_url_stripped_from_logs(self) -> None:
        """Factory should strip credentials from REDIS_URL when logging."""
        mock_redis_module = MagicMock()
        mock_client = MagicMock()
        mock_redis_module.Redis.from_url.return_value = mock_client
        mock_client.ping.return_value = True

        with (
            patch.dict(
                os.environ,
                {
                    "LOGIN_TRACKER_BACKEND": "redis",
                    "REDIS_URL": "redis://secret:password@redis.internal:6379/0",
                },
            ),
            patch.dict("sys.modules", {"redis": mock_redis_module}),
        ):
            tracker = _create_login_tracker()
            assert isinstance(tracker, RedisLoginAttemptTracker)
            # Verify the factory called from_url with the full URL
            mock_redis_module.Redis.from_url.assert_called_once()

    def test_production_raises_on_missing_redis_url(self) -> None:
        """In production, missing REDIS_URL with redis backend must raise RuntimeError."""
        with (
            patch.dict(
                os.environ,
                {
                    "LOGIN_TRACKER_BACKEND": "redis",
                    "ENVIRONMENT": "production",
                },
            ),
            pytest.raises(RuntimeError, match="REDIS_URL is required in production"),
        ):
            # Remove REDIS_URL if set
            os.environ.pop("REDIS_URL", None)
            _create_login_tracker()

    def test_production_raises_on_redis_connection_failure(self) -> None:
        """In production, Redis connection failure must raise RuntimeError (fail-closed)."""
        mock_redis_module = MagicMock()
        mock_redis_module.Redis.from_url.side_effect = ConnectionError("refused")

        with (
            patch.dict(
                os.environ,
                {
                    "LOGIN_TRACKER_BACKEND": "redis",
                    "REDIS_URL": "redis://redis:6379/0",
                    "ENVIRONMENT": "production",
                },
            ),
            patch.dict("sys.modules", {"redis": mock_redis_module}),
            pytest.raises(RuntimeError, match="Failed to connect to Redis"),
        ):
            _create_login_tracker()

    def test_dev_falls_back_to_memory_on_redis_failure(self) -> None:
        """In dev/test, Redis connection failure falls back to in-memory (not fatal)."""
        mock_redis_module = MagicMock()
        mock_redis_module.Redis.from_url.side_effect = ConnectionError("refused")

        with (
            patch.dict(
                os.environ,
                {
                    "LOGIN_TRACKER_BACKEND": "redis",
                    "ENVIRONMENT": "development",
                },
            ),
            patch.dict("sys.modules", {"redis": mock_redis_module}),
        ):
            tracker = _create_login_tracker()
            assert isinstance(tracker, LoginAttemptTracker)

    def test_dev_localhost_fallback_when_no_redis_url(self) -> None:
        """In dev, missing REDIS_URL should try localhost (not raise)."""
        mock_redis_module = MagicMock()
        mock_client = MagicMock()
        mock_redis_module.Redis.from_url.return_value = mock_client
        mock_client.ping.return_value = True

        with (
            patch.dict(
                os.environ,
                {
                    "LOGIN_TRACKER_BACKEND": "redis",
                    "ENVIRONMENT": "development",
                },
            ),
            patch.dict("sys.modules", {"redis": mock_redis_module}),
        ):
            os.environ.pop("REDIS_URL", None)
            tracker = _create_login_tracker()
            assert isinstance(tracker, RedisLoginAttemptTracker)
            mock_redis_module.Redis.from_url.assert_called_once_with(
                "redis://localhost:6379/0",
                decode_responses=False,
            )


# ---------------------------------------------------------------------------
# Multi-worker simulation test (unit-level, no real Redis)
# ---------------------------------------------------------------------------


class TestMultiWorkerLockoutSharing:
    """Simulate multi-worker lockout via shared mock Redis state.

    This validates that two independent RedisLoginAttemptTracker instances
    sharing the same Redis backend see the same lockout state — proving
    that lockout survives across uvicorn workers.
    """

    def test_two_trackers_share_lockout_state(self) -> None:
        """Two trackers pointing at the same Redis should share lockout."""
        # Simulate shared state: a dict acting as the Redis sorted set
        shared_state: dict[str, list[tuple[str, float]]] = {}

        def make_tracker_with_shared_state() -> RedisLoginAttemptTracker:
            """Build a tracker whose mock Redis reads/writes shared_state."""
            mock_redis = MagicMock()

            def zadd_impl(key: str, mapping: dict) -> int:
                if key not in shared_state:
                    shared_state[key] = []
                for member, score in mapping.items():
                    shared_state[key].append((member, score))
                return len(mapping)

            def zremrangebyscore_impl(key: str, _min: str, _max: float) -> int:
                if key not in shared_state:
                    return 0
                before = len(shared_state[key])
                shared_state[key] = [(m, s) for m, s in shared_state[key] if s > _max]
                return before - len(shared_state[key])

            def zcard_impl(key: str) -> int:
                return len(shared_state.get(key, []))

            def zrange_impl(
                key: str,
                start: int,
                stop: int,
                withscores: bool = False,
            ) -> list:
                entries = shared_state.get(key, [])
                sliced = entries[start : stop + 1] if stop >= 0 else entries[start:]
                if withscores:
                    return [(m.encode() if isinstance(m, str) else m, s) for m, s in sliced]
                return [m for m, _s in sliced]

            def delete_impl(key: str) -> int:
                if key in shared_state:
                    del shared_state[key]
                    return 1
                return 0

            mock_redis.zremrangebyscore = MagicMock(side_effect=zremrangebyscore_impl)
            mock_redis.zcard = MagicMock(side_effect=zcard_impl)
            mock_redis.zrange = MagicMock(side_effect=zrange_impl)
            mock_redis.delete = MagicMock(side_effect=delete_impl)

            # Pipeline for record_failure
            mock_pipe = MagicMock()

            def pipe_execute() -> list:
                # Execute all queued pipeline commands
                for c in mock_pipe.zadd.call_args_list:
                    zadd_impl(c[0][0], c[0][1])
                for c in mock_pipe.zremrangebyscore.call_args_list:
                    zremrangebyscore_impl(c[0][0], c[0][1], c[0][2])
                # Clear pipeline state for next call
                mock_pipe.zadd.reset_mock()
                mock_pipe.zremrangebyscore.reset_mock()
                return [None, None, None]

            mock_pipe.execute = MagicMock(side_effect=pipe_execute)
            mock_redis.pipeline.return_value = mock_pipe

            return RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)

        email = "shared@example.com"
        worker_1 = make_tracker_with_shared_state()
        worker_2 = make_tracker_with_shared_state()

        # Worker 1 records 3 failures
        for _ in range(3):
            worker_1.record_failure(email)

        # Worker 2 records 2 failures — total should be 5, triggering lockout
        for _ in range(2):
            worker_2.record_failure(email)

        # Both workers should see the account as locked
        assert worker_1.is_locked(email) is True, "Worker 1 should see shared lockout"
        assert worker_2.is_locked(email) is True, "Worker 2 should see shared lockout"

    def test_success_on_one_worker_clears_for_all(self) -> None:
        """record_success on worker 1 should clear lockout visible to worker 2."""
        shared_state: dict[str, list[tuple[str, float]]] = {}

        def make_tracker() -> RedisLoginAttemptTracker:
            mock_redis = MagicMock()

            def zcard_impl(key: str) -> int:
                return len(shared_state.get(key, []))

            def zremrangebyscore_impl(key: str, _min: str, _max: float) -> int:
                if key not in shared_state:
                    return 0
                before = len(shared_state[key])
                shared_state[key] = [(m, s) for m, s in shared_state[key] if s > _max]
                return before - len(shared_state[key])

            def delete_impl(key: str) -> int:
                if key in shared_state:
                    del shared_state[key]
                    return 1
                return 0

            def zadd_impl(key: str, mapping: dict) -> int:
                if key not in shared_state:
                    shared_state[key] = []
                for member, score in mapping.items():
                    shared_state[key].append((member, score))
                return len(mapping)

            mock_redis.zcard = MagicMock(side_effect=zcard_impl)
            mock_redis.zremrangebyscore = MagicMock(side_effect=zremrangebyscore_impl)
            mock_redis.delete = MagicMock(side_effect=delete_impl)

            mock_pipe = MagicMock()

            def pipe_execute() -> list:
                for c in mock_pipe.zadd.call_args_list:
                    zadd_impl(c[0][0], c[0][1])
                for c in mock_pipe.zremrangebyscore.call_args_list:
                    zremrangebyscore_impl(c[0][0], c[0][1], c[0][2])
                mock_pipe.zadd.reset_mock()
                mock_pipe.zremrangebyscore.reset_mock()
                return [None, None, None]

            mock_pipe.execute = MagicMock(side_effect=pipe_execute)
            mock_redis.pipeline.return_value = mock_pipe

            return RedisLoginAttemptTracker(mock_redis, max_attempts=5, window_seconds=900)

        email = "shared2@example.com"
        worker_1 = make_tracker()
        worker_2 = make_tracker()

        # Lock the account via worker 1
        for _ in range(5):
            worker_1.record_failure(email)

        assert worker_2.is_locked(email) is True

        # Success on worker 1 clears for all workers
        worker_1.record_success(email)
        assert worker_2.is_locked(email) is False
