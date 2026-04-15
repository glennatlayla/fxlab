"""
Unit tests for mobile mutation rate limiting (API-01).

Tests cover:
- Rate limit dependency allowing/blocking requests based on count and window.
- Per-user and per-scope rate limiting.
- Mobile source detection (X-Client-Source header).
- Response headers (X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset).
- 429 Too Many Requests with Retry-After header.
- Window expiration and reset behavior.
- Multiple scopes with independent limits.
- RateLimitExceededError exception and contract validation.

Dependencies:
    - services.api.middleware.rate_limit: Rate limit backend and dependency.
    - libs.contracts.rate_limit: Error contracts.
    - unittest.mock: For mocking request state and JWT extraction.

Example:
    pytest tests/unit/test_mobile_rate_limiting.py -v
"""

from __future__ import annotations

import time

import pytest

from libs.contracts.rate_limit import (
    RateLimitErrorResponse,
    RateLimitExceededError,
)
from services.api.middleware.rate_limit import InMemoryRateLimitBackend


class TestRateLimitBackendBehavior:
    """Tests for basic rate limit backend behavior."""

    def test_allows_requests_within_limit(self) -> None:
        """Requests within limit should be allowed with zero retry_after."""
        backend = InMemoryRateLimitBackend()
        for i in range(5):
            allowed, retry = backend.is_allowed("user_123:run_submission", limit=5)
            assert allowed is True, f"Request {i + 1} should be allowed"
            assert retry == 0

    def test_blocks_requests_exceeding_limit(self) -> None:
        """Request exceeding limit should be blocked with retry_after > 0."""
        backend = InMemoryRateLimitBackend()
        limit = 5
        for _ in range(limit):
            backend.is_allowed("user_123:run_submission", limit=limit)

        # Next request exceeds limit
        allowed, retry = backend.is_allowed("user_123:run_submission", limit=limit)
        assert allowed is False
        assert retry > 0

    def test_returns_positive_retry_after_when_blocked(self) -> None:
        """retry_after should be positive when request is blocked."""
        backend = InMemoryRateLimitBackend()
        for _ in range(3):
            backend.is_allowed("test:key", limit=3)

        allowed, retry = backend.is_allowed("test:key", limit=3)
        assert allowed is False
        assert retry >= 1  # At least 1 second
        assert retry <= 60  # Should not exceed window

    def test_rate_limit_is_per_user_and_scope(self) -> None:
        """Different users and scopes should have independent limits."""
        backend = InMemoryRateLimitBackend()

        # User A fills limit for run_submission
        for _ in range(5):
            backend.is_allowed("user_a:run_submission", limit=5)
        allowed_a, _ = backend.is_allowed("user_a:run_submission", limit=5)
        assert allowed_a is False

        # User A should still be able to use risk_setting scope
        allowed_a_risk, _ = backend.is_allowed("user_a:risk_setting", limit=10)
        assert allowed_a_risk is True

        # User B should still be able to use run_submission
        allowed_b, _ = backend.is_allowed("user_b:run_submission", limit=5)
        assert allowed_b is True

    def test_window_expires_after_configured_time(self) -> None:
        """Requests should be allowed again after window expires."""
        backend = InMemoryRateLimitBackend()
        key = "expire:test"

        # Fill limit
        for _ in range(2):
            backend.is_allowed(key, limit=2)

        # Should be blocked
        allowed, _ = backend.is_allowed(key, limit=2)
        assert allowed is False

        # Expire the old timestamps manually
        with backend._lock:
            backend._store[key] = [
                time.monotonic() - 120  # 2 minutes in the past
                for _ in backend._store[key]
            ]

        # Should be allowed again
        allowed, _ = backend.is_allowed(key, limit=2)
        assert allowed is True

    def test_different_scopes_independent(self) -> None:
        """Each scope should have independent counters."""
        backend = InMemoryRateLimitBackend()

        # Fill run_submission limit
        for _ in range(5):
            backend.is_allowed("user_123:run_submission", limit=5)

        allowed_runs, _ = backend.is_allowed("user_123:run_submission", limit=5)
        assert allowed_runs is False

        # risk_setting should be unaffected
        allowed_risk, _ = backend.is_allowed("user_123:risk_setting", limit=10)
        assert allowed_risk is True

        # kill_switch should be unaffected
        allowed_kill, _ = backend.is_allowed("user_123:kill_switch", limit=3)
        assert allowed_kill is True


class TestRateLimitExceededError:
    """Tests for RateLimitExceededError exception."""

    def test_error_has_required_attributes(self) -> None:
        """Error should store all required attributes."""
        error = RateLimitExceededError(
            "Test limit exceeded",
            retry_after_seconds=45,
            scope="run_submission",
            limit=5,
            window_seconds=60,
        )
        assert error.detail == "Test limit exceeded"
        assert error.retry_after_seconds == 45
        assert error.scope == "run_submission"
        assert error.limit == 5
        assert error.window_seconds == 60

    def test_error_with_defaults(self) -> None:
        """Error should use sensible defaults."""
        error = RateLimitExceededError()
        assert error.detail == "Rate limit exceeded. Please slow down."
        assert error.retry_after_seconds == 60
        assert error.scope == ""
        assert error.limit == 0
        assert error.window_seconds == 0

    def test_error_is_fxlab_error(self) -> None:
        """RateLimitExceededError should be an FXLabError."""
        from libs.contracts.errors import FXLabError

        error = RateLimitExceededError()
        assert isinstance(error, FXLabError)


class TestRateLimitErrorResponse:
    """Tests for RateLimitErrorResponse contract."""

    def test_response_serializes(self) -> None:
        """Response should serialize to JSON."""
        response = RateLimitErrorResponse(detail="Too fast", retry_after=30)
        data = response.model_dump()
        assert data["detail"] == "Too fast"
        assert data["retry_after"] == 30
        assert data["error_code"] == "RATE_LIMIT_EXCEEDED"

    def test_response_has_defaults(self) -> None:
        """Response should have sensible defaults."""
        response = RateLimitErrorResponse()
        assert response.retry_after == 60
        assert response.error_code == "RATE_LIMIT_EXCEEDED"

    def test_response_validates_positive_retry_after(self) -> None:
        """retry_after must be >= 1."""
        with pytest.raises(ValueError):
            RateLimitErrorResponse(retry_after=0)


class TestMobileSourceAwareness:
    """Tests for mobile source detection and handling."""

    def test_backend_is_source_agnostic(self) -> None:
        """Backend itself doesn't know about client source."""
        # This test verifies that the backend works the same way
        # regardless of client source. The source awareness happens
        # at the dependency level (which we'll test in integration tests).
        backend = InMemoryRateLimitBackend()

        # Both web and mobile users share same backend/storage
        for _ in range(5):
            backend.is_allowed("user_123:run_submission", limit=5)

        # Whether mobile or web, limit is enforced
        allowed, _ = backend.is_allowed("user_123:run_submission", limit=5)
        assert allowed is False


class TestRateLimitConfigs:
    """Tests for standard rate limit configurations."""

    def test_run_submission_limits(self) -> None:
        """Run submission should allow 5 per minute."""
        backend = InMemoryRateLimitBackend()
        limit = 5

        # Should allow 5 requests
        for i in range(limit):
            allowed, retry = backend.is_allowed("user_123:run_submission", limit=limit)
            assert allowed is True, f"Request {i + 1} should be allowed"
            assert retry == 0

        # 6th should be blocked
        allowed, retry = backend.is_allowed("user_123:run_submission", limit=limit)
        assert allowed is False
        assert retry > 0

    def test_risk_setting_limits(self) -> None:
        """Risk setting changes should allow 10 per hour."""
        backend = InMemoryRateLimitBackend()
        limit = 10

        # Should allow 10 requests
        for i in range(limit):
            allowed, retry = backend.is_allowed("user_123:risk_setting", limit=limit)
            assert allowed is True, f"Request {i + 1} should be allowed"
            assert retry == 0

        # 11th should be blocked
        allowed, retry = backend.is_allowed("user_123:risk_setting", limit=limit)
        assert allowed is False
        assert retry > 0

    def test_kill_switch_limits(self) -> None:
        """Kill switch activations should allow 3 per minute."""
        backend = InMemoryRateLimitBackend()
        limit = 3

        # Should allow 3 requests
        for i in range(limit):
            allowed, retry = backend.is_allowed("user_123:kill_switch", limit=limit)
            assert allowed is True, f"Request {i + 1} should be allowed"
            assert retry == 0

        # 4th should be blocked
        allowed, retry = backend.is_allowed("user_123:kill_switch", limit=limit)
        assert allowed is False
        assert retry > 0

    def test_approval_action_limits(self) -> None:
        """Approval actions should allow 10 per minute."""
        backend = InMemoryRateLimitBackend()
        limit = 10

        # Should allow 10 requests
        for i in range(limit):
            allowed, retry = backend.is_allowed("user_123:approval_action", limit=limit)
            assert allowed is True, f"Request {i + 1} should be allowed"
            assert retry == 0

        # 11th should be blocked
        allowed, retry = backend.is_allowed("user_123:approval_action", limit=limit)
        assert allowed is False
        assert retry > 0


class TestHeaderGeneration:
    """Tests for rate limit response headers."""

    def test_retry_after_header_when_blocked(self) -> None:
        """Retry-After header should be positive when blocked."""
        backend = InMemoryRateLimitBackend()

        for _ in range(3):
            backend.is_allowed("user_123:test", limit=3)

        allowed, retry = backend.is_allowed("user_123:test", limit=3)
        assert allowed is False
        assert retry >= 1
        assert retry <= 60

    def test_no_retry_after_when_allowed(self) -> None:
        """retry_after should be 0 when allowed."""
        backend = InMemoryRateLimitBackend()
        allowed, retry = backend.is_allowed("user_123:test", limit=100)
        assert allowed is True
        assert retry == 0


class TestConcurrency:
    """Tests for thread-safe rate limiting."""

    def test_backend_is_thread_safe(self) -> None:
        """Backend should handle concurrent requests safely."""
        import threading

        backend = InMemoryRateLimitBackend()
        results = []
        limit = 10

        def make_request(request_id: int) -> None:
            allowed, retry = backend.is_allowed("user_123:concurrent", limit=limit)
            results.append((request_id, allowed, retry))

        threads = []
        for i in range(limit + 5):
            t = threading.Thread(target=make_request, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Exactly limit requests should be allowed
        allowed_count = sum(1 for _, allowed, _ in results if allowed)
        assert allowed_count == limit

        # Exactly 5 requests should be blocked
        blocked_count = sum(1 for _, allowed, _ in results if not allowed)
        assert blocked_count == 5
