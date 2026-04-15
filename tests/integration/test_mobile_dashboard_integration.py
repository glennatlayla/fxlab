"""
Integration tests for mobile dashboard endpoint.

Tests the full request/response cycle with real database and repositories.

Naming convention: test_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from services.api.auth import create_access_token
from services.api.main import app


@pytest.fixture
def client() -> TestClient:
    """Provide a FastAPI TestClient for the app."""
    return TestClient(app)


@pytest.fixture
def auth_token() -> str:
    """Create a valid JWT token for testing."""
    return create_access_token(
        user_id="01HQZXYZ123456789ABCDEFGHJ",
        role="operator",
        email="test@fxlab.test",
    )


@pytest.fixture
def auth_headers(auth_token: str) -> dict[str, str]:
    """Return auth headers with a valid JWT token."""
    return {"Authorization": f"Bearer {auth_token}"}


class TestMobileDashboardIntegration:
    """Integration tests for GET /mobile/dashboard endpoint."""

    def test_mobile_dashboard_returns_real_data(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """
        Test mobile dashboard returns aggregated real data.

        Scenario: Endpoint is called with valid auth.
        Expected: 200 response with valid MobileDashboardSummary.
        """
        response = client.get(
            "/mobile/dashboard",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify all required fields are present
        assert "active_runs" in data
        assert "completed_runs_24h" in data
        assert "pending_approvals" in data
        assert "active_kill_switches" in data
        assert "pnl_today_usd" in data
        assert "last_alert_severity" in data
        assert "last_alert_message" in data
        assert "generated_at" in data

        # Verify field types and constraints
        assert isinstance(data["active_runs"], int)
        assert data["active_runs"] >= 0
        assert isinstance(data["completed_runs_24h"], int)
        assert data["completed_runs_24h"] >= 0
        assert isinstance(data["pending_approvals"], int)
        assert data["pending_approvals"] >= 0
        assert isinstance(data["active_kill_switches"], int)
        assert data["active_kill_switches"] >= 0
        assert isinstance(data["generated_at"], str)

        # Optional fields can be null
        if data["pnl_today_usd"] is not None:
            assert isinstance(data["pnl_today_usd"], (int, float))
        if data["last_alert_severity"] is not None:
            assert isinstance(data["last_alert_severity"], str)
        if data["last_alert_message"] is not None:
            assert isinstance(data["last_alert_message"], str)

    def test_mobile_dashboard_unauthorized_without_token(
        self,
        client: TestClient,
    ) -> None:
        """
        Test mobile dashboard requires authentication.

        Scenario: Unauthenticated request (no auth header).
        Expected: 401 Unauthorized.
        """
        response = client.get("/mobile/dashboard")

        assert response.status_code == 401

    def test_mobile_dashboard_with_invalid_token(
        self,
        client: TestClient,
    ) -> None:
        """
        Test mobile dashboard rejects invalid tokens.

        Scenario: Request with malformed JWT.
        Expected: 401 Unauthorized.
        """
        response = client.get(
            "/mobile/dashboard",
            headers={"Authorization": "Bearer invalid_token"},
        )

        assert response.status_code == 401

    def test_mobile_dashboard_generated_at_is_iso_8601(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """
        Test generated_at timestamp is valid ISO 8601.

        Scenario: Endpoint returns a summary.
        Expected: generated_at is a parseable ISO 8601 string.
        """
        response = client.get(
            "/mobile/dashboard",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Should be parseable as ISO 8601
        from datetime import datetime

        ts_str = data["generated_at"].replace("Z", "+00:00")
        ts = datetime.fromisoformat(ts_str)
        assert ts.tzinfo is not None
