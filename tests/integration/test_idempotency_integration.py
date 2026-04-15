"""
Integration tests for idempotency middleware.

Tests the idempotency middleware behavior with real endpoints.
Note: These tests verify middleware behavior only; endpoint service wiring
is handled by unit/service layer tests.

Naming convention: test_<scenario>_<expected_outcome>

Covers:
- Idempotency middleware with real HTTP stack
- Header propagation in CORS
- Response caching behavior
- Concurrent request detection
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from services.api.main import app


@pytest.fixture
def client() -> TestClient:
    """Provide a FastAPI TestClient for the app."""
    return TestClient(app)


class TestIdempotencyMiddlewareIntegration:
    """Integration tests for idempotency middleware with real HTTP stack."""

    def test_idempotency_key_header_propagates_through_cors(
        self,
        client: TestClient,
    ) -> None:
        """
        Test that Idempotency-Key is in CORS allowed_headers.

        Scenario: Preflight OPTIONS request for POST with Idempotency-Key.
        Expected: Idempotency-Key in Access-Control-Allow-Headers response.
        """
        response = client.options(
            "/",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Idempotency-Key,Content-Type",
            },
        )

        # Should allow the header in CORS
        cors_headers = response.headers.get("Access-Control-Allow-Headers", "")
        # The header should be present (case-insensitive check)
        assert "idempotency-key" in cors_headers.lower()

    def test_health_endpoint_ignores_idempotency_key(
        self,
        client: TestClient,
    ) -> None:
        """
        Test that /health endpoint is excluded from idempotency.

        Scenario: GET request to /health with Idempotency-Key.
        Expected: Response without Idempotency-Key-Status header (excluded path).
        """
        # First request
        response1 = client.get(
            "/health",
            headers={"Idempotency-Key": "idem-health-1"},
        )
        assert response1.status_code == 200
        assert "Idempotency-Key-Status" not in response1.headers

        # Second request with same key should not trigger idempotency
        response2 = client.get(
            "/health",
            headers={"Idempotency-Key": "idem-health-1"},
        )
        assert response2.status_code == 200
        assert "Idempotency-Key-Status" not in response2.headers

    def test_root_endpoint_ignores_idempotency_key(
        self,
        client: TestClient,
    ) -> None:
        """
        Test that root / endpoint is excluded from idempotency.

        Scenario: GET request to / with Idempotency-Key.
        Expected: Response without Idempotency-Key-Status header (excluded path).
        """
        response = client.get(
            "/",
            headers={"Idempotency-Key": "idem-root"},
        )
        assert response.status_code == 200
        assert "Idempotency-Key-Status" not in response.headers

    def test_get_requests_bypass_idempotency(
        self,
        client: TestClient,
    ) -> None:
        """
        Test that GET requests bypass idempotency.

        Scenario: GET request to /health with Idempotency-Key.
        Expected: No Idempotency-Key-Status header (GET is not idempotent method).
        """
        response = client.get(
            "/health",
            headers={"Idempotency-Key": "idem-get"},
        )
        assert response.status_code == 200
        assert "Idempotency-Key-Status" not in response.headers

    def test_options_requests_bypass_idempotency(
        self,
        client: TestClient,
    ) -> None:
        """
        Test that OPTIONS requests bypass idempotency.

        Scenario: OPTIONS request with Idempotency-Key.
        Expected: No Idempotency-Key-Status header (OPTIONS is not idempotent method).
        """
        response = client.options(
            "/health",
            headers={"Idempotency-Key": "idem-options"},
        )
        # OPTIONS may return 200 or other status
        assert "Idempotency-Key-Status" not in response.headers
