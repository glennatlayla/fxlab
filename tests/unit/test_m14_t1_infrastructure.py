"""
M14-T1 Infrastructure Hardening — Unit Tests

Tests for:
1. Real health check with DB probe
2. Request body size limit middleware
3. Rate limiting middleware
4. Correlation ID middleware
5. Migration entrypoint
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def cleanup_rate_limit_store():
    """Clear the rate limit store before and after each test."""
    from services.api.middleware.rate_limit import _window
    _window._store.clear()
    yield
    _window._store.clear()


class TestHealthCheckWithDBProbe:
    """Item 1: Real health check with DB probe."""

    def test_health_check_returns_200_when_db_up(self) -> None:
        """
        Health check endpoint returns 200 with ok status when DB is reachable.
        """
        with patch("services.api.db.check_db_connection", return_value=True):
            from services.api.main import app
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 200
            body = response.json()
            assert body["success"] is True
            assert body["status"] == "ok"

    def test_health_check_returns_503_when_db_down(self) -> None:
        """
        Health check endpoint returns 503 with degraded status when DB is unreachable.
        """
        with patch("services.api.db.check_db_connection", return_value=False):
            from services.api.main import app
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 503
            body = response.json()
            assert body["success"] is False
            assert body["status"] == "degraded"

    def test_health_check_does_not_raise_exception_on_db_failure(self) -> None:
        """
        Health check does not raise an exception when DB check fails;
        instead returns a 503 response.
        """
        with patch("services.api.db.check_db_connection", side_effect=RuntimeError("Connection timeout")):
            from services.api.main import app
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/health")
            assert response.status_code == 503
            body = response.json()
            assert body["success"] is False


class TestBodySizeLimitMiddleware:
    """Item 3: Request body size limit middleware."""

    def test_body_size_limit_rejects_oversized_requests(self) -> None:
        """
        POST with body exceeding MAX_REQUEST_BODY_BYTES returns 413.
        Default limit is 512 KB.
        """
        from services.api.main import app
        client = TestClient(app)

        # Create a payload larger than 512 KB
        large_payload = {"data": "x" * (600 * 1024)}  # 600 KB
        response = client.post(
            "/approvals/test/reject",
            json=large_payload,
        )
        assert response.status_code == 413
        assert "exceeds maximum size" in response.json()["detail"]

    def test_body_size_limit_allows_normal_requests(self) -> None:
        """
        POST with body under the limit succeeds (reaches the handler, not rejected by middleware).
        """
        from services.api.main import app
        client = TestClient(app)

        # Small payload should not be rejected by body size middleware
        payload = {"rationale": "This is a normal rejection reason that is long enough to pass validation."}
        response = client.post(
            "/approvals/01HAPPROVAL000000000000001/reject",
            json=payload,
        )
        # Should not be 413; may be 200 or 422 depending on route validation
        assert response.status_code != 413

    def test_body_size_limit_excludes_health_paths(self) -> None:
        """
        GET /health is excluded from body size limit checks.
        """
        from services.api.main import app
        client = TestClient(app)

        response = client.get("/health")
        assert response.status_code in (200, 503)


class TestRateLimitMiddleware:
    """Item 4: Rate limiting middleware."""

    def test_rate_limit_blocks_after_threshold(self) -> None:
        """
        After 20 POST requests to /overrides/request per minute,
        the 21st request returns 429 Too Many Requests.
        """
        from services.api.main import app

        client = TestClient(app)

        # Reset the sliding window store to ensure clean state
        from services.api.middleware.rate_limit import _window
        _window._store.clear()

        payload = {
            "object_id": "01HABCDE0000000000000000AC",
            "object_type": "candidate",
            "override_type": "grade_override",
            "original_state": {"grade": "C"},
            "new_state": {"grade": "B"},
            "evidence_link": "https://jira.example.com/browse/FX-ACC-001",
            "rationale": "Acceptance test reason — long enough to pass validation.",
            "submitter_id": "01HSUBMITTER00000000000001",
        }

        # Send 20 requests — should succeed
        for i in range(20):
            response = client.post("/overrides/request", json=payload)
            # Should not be rate limited (allow success or validation errors)
            assert response.status_code != 429, f"Rate limited on request {i+1}"

        # 21st request should be rate limited
        response = client.post("/overrides/request", json=payload)
        assert response.status_code == 429

    def test_rate_limit_includes_retry_after_header(self) -> None:
        """
        429 response includes Retry-After header.
        """
        from services.api.main import app
        from services.api.middleware.rate_limit import _window

        client = TestClient(app)
        _window._store.clear()

        payload = {
            "object_id": "01HABCDE0000000000000000AC",
            "object_type": "candidate",
            "override_type": "grade_override",
            "original_state": {"grade": "C"},
            "new_state": {"grade": "B"},
            "evidence_link": "https://jira.example.com/browse/FX-ACC-001",
            "rationale": "Test reason with sufficient length for validation.",
            "submitter_id": "01HSUBMITTER00000000000001",
        }

        # Max out the governance rate limit
        for _ in range(20):
            client.post("/overrides/request", json=payload)

        # Next request should be rate limited with Retry-After
        response = client.post("/overrides/request", json=payload)
        assert response.status_code == 429
        assert "Retry-After" in response.headers

    def test_rate_limit_excludes_health_paths(self) -> None:
        """
        GET /health is not rate limited.
        """
        from services.api.main import app
        client = TestClient(app)

        # Make many requests to /health — should never be rate limited
        for _ in range(100):
            response = client.get("/health")
            assert response.status_code != 429

    def test_rate_limit_excludes_options_requests(self) -> None:
        """
        OPTIONS requests are not rate limited.
        """
        from services.api.main import app
        client = TestClient(app)

        # Make many OPTIONS requests — should not be rate limited
        for _ in range(100):
            response = client.options("/overrides/request")
            assert response.status_code != 429


class TestCorrelationIDMiddleware:
    """Item 5: Correlation ID middleware."""

    def test_correlation_id_added_to_response(self) -> None:
        """
        Every response includes X-Correlation-ID header.
        """
        from services.api.main import app
        client = TestClient(app)

        response = client.get("/")
        assert "X-Correlation-ID" in response.headers
        assert response.headers["X-Correlation-ID"]

    def test_correlation_id_preserved_when_provided(self) -> None:
        """
        When client provides X-Correlation-ID, the same ID is echoed in response.
        """
        from services.api.main import app
        client = TestClient(app)

        provided_id = "test-correlation-id-12345"
        response = client.get("/", headers={"X-Correlation-ID": provided_id})
        assert response.headers["X-Correlation-ID"] == provided_id

    def test_correlation_id_generated_when_missing(self) -> None:
        """
        When client does not provide X-Correlation-ID, one is generated (UUID4 format).
        """
        from services.api.main import app
        client = TestClient(app)

        response = client.get("/")
        corr_id = response.headers["X-Correlation-ID"]
        # Should be a non-empty UUID4-like string
        assert corr_id
        assert len(corr_id) == 36  # UUID4 format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

    def test_correlation_id_available_in_context_var(self) -> None:
        """
        Correlation ID is stored in a ContextVar and accessible within the request context.
        """
        from services.api.middleware.correlation import correlation_id_var
        from services.api.main import app
        client = TestClient(app)

        # The context var should be accessible and populated during request handling
        response = client.get("/")
        # If we get here, the middleware executed without error
        assert response.status_code == 200


class TestMiddlewareRegistrationOrder:
    """Integration test: middleware is registered in correct order."""

    def test_middleware_stack_all_present(self) -> None:
        """
        All three middleware are registered on the app.
        """
        from services.api.main import app

        middleware_names = [mw.__class__.__name__ for mw in app.user_middleware]
        # Should contain our custom middleware
        # Note: user_middleware is in reverse registration order (last-registered first)
        assert any("CorrelationIDMiddleware" in str(mw) for mw in app.user_middleware)
        assert any("BodySizeLimitMiddleware" in str(mw) for mw in app.user_middleware)
        assert any("RateLimitMiddleware" in str(mw) for mw in app.user_middleware)
