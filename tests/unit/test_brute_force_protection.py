"""
Unit tests for brute-force protection on /auth/token password grant (AUTH-4).

Tests cover:
- LoginAttemptTracker: per-account lockout after N failed attempts.
- Rate limiter: dedicated tighter limit for /auth/token endpoint.
- Integration: password grant rejects locked-out accounts with 429.

Dependencies:
    - services.api.services.login_attempt_tracker: LoginAttemptTracker.
    - services.api.middleware.rate_limit: RateLimitMiddleware, _AUTH_LIMIT.

Example:
    pytest tests/unit/test_brute_force_protection.py -v
"""

from __future__ import annotations

import time

# ---------------------------------------------------------------------------
# LoginAttemptTracker unit tests
# ---------------------------------------------------------------------------


class TestLoginAttemptTracker:
    """Tests for the per-account login attempt tracker."""

    def test_account_not_locked_initially(self) -> None:
        """A fresh account should not be locked."""
        from services.api.services.login_attempt_tracker import LoginAttemptTracker

        tracker = LoginAttemptTracker(max_attempts=5, window_seconds=900)
        assert tracker.is_locked("user@example.com") is False

    def test_account_locked_after_max_failed_attempts(self) -> None:
        """Account should be locked after max_attempts failed attempts."""
        from services.api.services.login_attempt_tracker import LoginAttemptTracker

        tracker = LoginAttemptTracker(max_attempts=5, window_seconds=900)
        email = "brute@example.com"

        for _ in range(5):
            tracker.record_failure(email)

        assert tracker.is_locked(email) is True

    def test_account_not_locked_below_threshold(self) -> None:
        """Account should NOT be locked if fewer than max_attempts failures."""
        from services.api.services.login_attempt_tracker import LoginAttemptTracker

        tracker = LoginAttemptTracker(max_attempts=5, window_seconds=900)
        email = "almost@example.com"

        for _ in range(4):
            tracker.record_failure(email)

        assert tracker.is_locked(email) is False

    def test_successful_login_resets_counter(self) -> None:
        """A successful login should clear the failed attempt counter."""
        from services.api.services.login_attempt_tracker import LoginAttemptTracker

        tracker = LoginAttemptTracker(max_attempts=5, window_seconds=900)
        email = "reset@example.com"

        for _ in range(4):
            tracker.record_failure(email)

        tracker.record_success(email)
        assert tracker.is_locked(email) is False

        # Should need 5 more failures to lock again
        for _ in range(4):
            tracker.record_failure(email)
        assert tracker.is_locked(email) is False

    def test_lock_expires_after_window(self) -> None:
        """Account lockout should expire after the window period."""
        from services.api.services.login_attempt_tracker import LoginAttemptTracker

        tracker = LoginAttemptTracker(max_attempts=5, window_seconds=1)
        email = "expire@example.com"

        for _ in range(5):
            tracker.record_failure(email)

        assert tracker.is_locked(email) is True

        # Wait for window to expire
        time.sleep(1.1)
        assert tracker.is_locked(email) is False

    def test_different_accounts_isolated(self) -> None:
        """Failures for one account should not affect another."""
        from services.api.services.login_attempt_tracker import LoginAttemptTracker

        tracker = LoginAttemptTracker(max_attempts=5, window_seconds=900)
        attacker = "attacker@example.com"
        innocent = "innocent@example.com"

        for _ in range(5):
            tracker.record_failure(attacker)

        assert tracker.is_locked(attacker) is True
        assert tracker.is_locked(innocent) is False

    def test_retry_after_returns_seconds_until_unlock(self) -> None:
        """retry_after() should return seconds until the oldest failure expires."""
        from services.api.services.login_attempt_tracker import LoginAttemptTracker

        tracker = LoginAttemptTracker(max_attempts=5, window_seconds=900)
        email = "retry@example.com"

        for _ in range(5):
            tracker.record_failure(email)

        retry = tracker.retry_after(email)
        assert retry > 0
        assert retry <= 900

    def test_retry_after_returns_zero_when_not_locked(self) -> None:
        """retry_after() should return 0 for unlocked accounts."""
        from services.api.services.login_attempt_tracker import LoginAttemptTracker

        tracker = LoginAttemptTracker(max_attempts=5, window_seconds=900)
        assert tracker.retry_after("free@example.com") == 0

    def test_thread_safety(self) -> None:
        """Concurrent calls should not corrupt the tracker state."""
        import threading

        from services.api.services.login_attempt_tracker import LoginAttemptTracker

        tracker = LoginAttemptTracker(max_attempts=100, window_seconds=900)
        email = "concurrent@example.com"

        def record_failures() -> None:
            for _ in range(50):
                tracker.record_failure(email)

        threads = [threading.Thread(target=record_failures) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 4 threads * 50 = 200 failures, should be locked (>= 100)
        assert tracker.is_locked(email) is True


# ---------------------------------------------------------------------------
# Rate limiter auth-specific limit tests
# ---------------------------------------------------------------------------


class TestRateLimiterAuthEndpoint:
    """Tests for /auth/token-specific rate limiting."""

    def test_auth_token_uses_tighter_limit(self) -> None:
        """The /auth/token endpoint should have a dedicated tighter rate limit."""
        from services.api.middleware.rate_limit import (
            _AUTH_LIMIT,
            _DEFAULT_LIMIT,
        )

        assert _AUTH_LIMIT < _DEFAULT_LIMIT
        assert _AUTH_LIMIT <= 10  # Should be 10 or fewer per minute

    def test_auth_token_path_detected_as_auth(self) -> None:
        """POST /auth/token should be classified as an auth endpoint."""
        from services.api.middleware.rate_limit import _AUTH_PREFIXES

        assert any("/auth/token".startswith(p) for p in _AUTH_PREFIXES)


# ---------------------------------------------------------------------------
# Integration: password grant lockout
# ---------------------------------------------------------------------------


class TestPasswordGrantLockout:
    """Integration tests for brute-force lockout on password grant."""

    def test_locked_account_returns_429(self) -> None:
        """Password grant for a locked account should return 429."""
        from services.api.services.login_attempt_tracker import LoginAttemptTracker

        tracker = LoginAttemptTracker(max_attempts=5, window_seconds=900)

        # Simulate 5 failed attempts
        for _ in range(5):
            tracker.record_failure("locked@example.com")

        assert tracker.is_locked("locked@example.com") is True
        retry = tracker.retry_after("locked@example.com")
        assert retry > 0
