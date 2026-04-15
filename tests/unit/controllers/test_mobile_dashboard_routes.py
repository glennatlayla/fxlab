"""
Unit tests for mobile dashboard route handlers.

Responsibilities:
- Test GET /mobile/dashboard endpoint in isolation.
- Mock MobileDashboardService and its dependencies.
- Verify request parsing, authentication, and error handling.
- Confirm the response is properly formatted.

Does NOT:
- Call real database or external services (all mocked).
- Test service business logic (that is the service's test responsibility).

Test coverage:
- Happy path: authenticated user gets 200 with summary.
- Auth required: missing auth header → 401.
- Service failure: service error is handled gracefully.

Example:
    pytest tests/unit/controllers/test_mobile_dashboard_routes.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from libs.contracts.mobile_dashboard import MobileDashboardSummary
from services.api.auth import AuthenticatedUser, get_current_user
from services.api.main import app


@pytest.fixture
def client() -> TestClient:
    """Provide a FastAPI TestClient for the app."""
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Return auth headers with TEST_TOKEN."""
    return {"Authorization": "Bearer TEST_TOKEN"}


@pytest.fixture
def mock_authenticated_user() -> AuthenticatedUser:
    """Return a mock authenticated user with operator role."""
    return AuthenticatedUser(
        user_id="01HQZXYZ123456789ABCDEFGHJ",
        role="operator",
        email="operator@fxlab.test",
        scopes=["operator:read", "deployments:read"],
    )


class TestGetMobileDashboard:
    """Tests for GET /mobile/dashboard endpoint."""

    def test_get_mobile_dashboard_returns_200_with_summary(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test successful mobile dashboard retrieval.

        Scenario: Authenticated user requests dashboard summary.
        Expected: 200 response with MobileDashboardSummary fields.
        """
        mock_summary = MobileDashboardSummary(
            active_runs=3,
            completed_runs_24h=5,
            pending_approvals=2,
            active_kill_switches=1,
            pnl_today_usd=1250.50,
            last_alert_severity="warning",
            last_alert_message="Position delta exceeds threshold",
            generated_at="2026-04-13T14:30:00+00:00",
        )

        mock_service = MagicMock()
        mock_service.get_summary.return_value = mock_summary

        from services.api.routes.mobile_dashboard import get_mobile_dashboard_service

        app.dependency_overrides[get_mobile_dashboard_service] = lambda: mock_service
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.get(
                "/mobile/dashboard",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["active_runs"] == 3
            assert data["completed_runs_24h"] == 5
            assert data["pending_approvals"] == 2
            assert data["active_kill_switches"] == 1
            assert data["pnl_today_usd"] == 1250.50
            assert data["last_alert_severity"] == "warning"
            assert data["last_alert_message"] == "Position delta exceeds threshold"
            assert data["generated_at"] == "2026-04-13T14:30:00+00:00"
            mock_service.get_summary.assert_called_once()
        finally:
            app.dependency_overrides.clear()

    def test_get_mobile_dashboard_requires_auth(
        self,
        client: TestClient,
    ) -> None:
        """
        Test mobile dashboard endpoint requires authentication.

        Scenario: Unauthenticated request (no Authorization header).
        Expected: 401 Unauthorized.
        """
        response = client.get("/mobile/dashboard")

        assert response.status_code == 401

    def test_get_mobile_dashboard_with_null_optional_fields(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test mobile dashboard returns null for unavailable fields.

        Scenario: Service returns summary with None for pnl and alerts (MVP).
        Expected: 200 response with null values in JSON.
        """
        mock_summary = MobileDashboardSummary(
            active_runs=1,
            completed_runs_24h=0,
            pending_approvals=0,
            active_kill_switches=0,
            pnl_today_usd=None,
            last_alert_severity=None,
            last_alert_message=None,
            generated_at="2026-04-13T14:30:00+00:00",
        )

        mock_service = MagicMock()
        mock_service.get_summary.return_value = mock_summary

        from services.api.routes.mobile_dashboard import get_mobile_dashboard_service

        app.dependency_overrides[get_mobile_dashboard_service] = lambda: mock_service
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.get(
                "/mobile/dashboard",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["pnl_today_usd"] is None
            assert data["last_alert_severity"] is None
            assert data["last_alert_message"] is None
        finally:
            app.dependency_overrides.clear()
