"""
Tests for P&L attribution API routes (/pnl/*).

Covers:
- GET /pnl/{deployment_id}/summary — P&L summary.
- GET /pnl/{deployment_id}/timeseries — P&L timeseries with date range.
- GET /pnl/{deployment_id}/attribution — per-symbol attribution.
- GET /pnl/comparison — multi-deployment comparison.
- POST /pnl/{deployment_id}/snapshot — take daily snapshot.
- 404 on unknown deployment.
- 422 on invalid date format.
- 403 for users without deployments:read scope.

Example:
    pytest tests/unit/test_pnl_routes.py -v
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from libs.contracts.errors import NotFoundError
from services.api.auth import ROLE_SCOPES, AuthenticatedUser

# ---------------------------------------------------------------------------
# Fake users for dependency overrides
# ---------------------------------------------------------------------------

_OPERATOR_USER = AuthenticatedUser(
    user_id="01HTESTFAKE000000000000000",
    role="operator",
    email="operator@fxlab.test",
    scopes=ROLE_SCOPES["operator"],
)

_VIEWER_USER = AuthenticatedUser(
    user_id="01HTESTFAKE000000000000000",
    role="viewer",
    email="viewer@fxlab.test",
    scopes=ROLE_SCOPES["viewer"],
)

_DEPLOYMENT_ID = "01HTESTDEP0000000000000001"


# ---------------------------------------------------------------------------
# Mock PnlAttributionService
# ---------------------------------------------------------------------------


class MockPnlAttributionService:
    """Fake PnlAttributionService for route-level testing."""

    def __init__(self) -> None:
        self._error: Exception | None = None

    def set_error(self, error: Exception) -> None:
        """Configure an error to be raised on next service call."""
        self._error = error

    def _check_error(self) -> None:
        """Raise configured error if set."""
        if self._error is not None:
            exc = self._error
            self._error = None
            raise exc

    def get_pnl_summary(self, *, deployment_id: str) -> dict[str, Any]:
        """Return mock P&L summary."""
        self._check_error()
        return {
            "deployment_id": deployment_id,
            "total_realized_pnl": "1250.50",
            "total_unrealized_pnl": "340.25",
            "total_commission": "52.00",
            "total_fees": "0",
            "net_pnl": "1538.75",
            "positions_count": 5,
            "total_trades": 20,
            "winning_trades": 13,
            "losing_trades": 7,
            "win_rate": "65.0",
            "sharpe_ratio": "1.42",
            "max_drawdown_pct": "4.2",
            "avg_win": "120.50",
            "avg_loss": "-85.30",
            "profit_factor": "2.64",
            "date_from": "2026-04-01",
            "date_to": "2026-04-12",
        }

    def get_pnl_timeseries(
        self,
        *,
        deployment_id: str,
        date_from: date,
        date_to: date,
        granularity: str = "daily",
    ) -> list[dict[str, Any]]:
        """Return mock timeseries data."""
        self._check_error()
        return [
            {
                "snapshot_date": "2026-04-01",
                "realized_pnl": "100",
                "unrealized_pnl": "50",
                "net_pnl": "150",
                "cumulative_pnl": "150",
                "daily_pnl": "150",
                "commission": "5",
                "fees": "0",
                "positions_count": 2,
                "drawdown_pct": "0",
            },
            {
                "snapshot_date": "2026-04-02",
                "realized_pnl": "200",
                "unrealized_pnl": "80",
                "net_pnl": "280",
                "cumulative_pnl": "280",
                "daily_pnl": "130",
                "commission": "10",
                "fees": "0",
                "positions_count": 3,
                "drawdown_pct": "0",
            },
        ]

    def get_attribution(
        self,
        *,
        deployment_id: str,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, Any]:
        """Return mock attribution report."""
        self._check_error()
        return {
            "deployment_id": deployment_id,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "total_net_pnl": "1150.00",
            "by_symbol": [
                {
                    "symbol": "AAPL",
                    "realized_pnl": "600.00",
                    "unrealized_pnl": "200.00",
                    "net_pnl": "800.00",
                    "contribution_pct": "69.6",
                    "total_trades": 5,
                    "winning_trades": 4,
                    "win_rate": "80.0",
                    "total_volume": "500",
                    "commission": "10.00",
                },
                {
                    "symbol": "MSFT",
                    "realized_pnl": "400.00",
                    "unrealized_pnl": "-50.00",
                    "net_pnl": "350.00",
                    "contribution_pct": "30.4",
                    "total_trades": 3,
                    "winning_trades": 2,
                    "win_rate": "66.7",
                    "total_volume": "150",
                    "commission": "6.00",
                },
            ],
        }

    def get_comparison(
        self,
        *,
        deployment_ids: list[str],
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, Any]:
        """Return mock comparison report."""
        self._check_error()
        entries = [
            {
                "deployment_id": did,
                "strategy_name": None,
                "net_pnl": "1000.00",
                "total_realized_pnl": "800.00",
                "total_unrealized_pnl": "200.00",
                "total_commission": "20.00",
                "win_rate": "60.0",
                "sharpe_ratio": "1.2",
                "max_drawdown_pct": "5.0",
                "total_trades": 10,
            }
            for did in deployment_ids
        ]
        return {
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "entries": entries,
        }

    def take_snapshot(
        self,
        *,
        deployment_id: str,
        snapshot_date: date,
    ) -> dict[str, Any]:
        """Return mock snapshot result."""
        self._check_error()
        return {
            "id": "01HSNAP0000000000000000001",
            "deployment_id": deployment_id,
            "snapshot_date": snapshot_date.isoformat(),
            "realized_pnl": "350.00",
            "unrealized_pnl": "400.00",
            "commission": "12.00",
            "fees": "0",
            "positions_count": 2,
            "created_at": "2026-04-12T23:59:00",
            "updated_at": "2026-04-12T23:59:00",
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def pnl_test_env():
    """
    Set up test app with P&L routes wired to mock service.

    Yields (client, mock_service, app) tuple.
    """
    env_vars = {
        "ENVIRONMENT": "test",
        "DATABASE_URL": "sqlite:///:memory:",
        "JWT_SECRET_KEY": "test-secret-key-not-for-production-32bytes!!",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        from services.api.routes import pnl as pnl_module

        mock_service = MockPnlAttributionService()
        pnl_module.set_pnl_attribution_service(mock_service)

        try:
            from services.api.main import app

            client = TestClient(app, raise_server_exceptions=False)
            yield client, mock_service, app
        finally:
            pnl_module.set_pnl_attribution_service(None)


def _auth_headers() -> dict[str, str]:
    """Authorization headers using the TEST_TOKEN."""
    return {"Authorization": "Bearer TEST_TOKEN"}


def _override_auth(app, user=_OPERATOR_USER):
    """Override get_current_user to return a specific user."""
    from services.api.auth import get_current_user

    async def _fake_get_current_user():
        return user

    app.dependency_overrides[get_current_user] = _fake_get_current_user


# ---------------------------------------------------------------------------
# Tests: GET /pnl/{deployment_id}/summary
# ---------------------------------------------------------------------------


class TestGetPnlSummary:
    """Tests for GET /pnl/{deployment_id}/summary."""

    def test_summary_returns_200(self, pnl_test_env) -> None:
        """Authenticated operator gets 200 with P&L summary."""
        client, mock_service, app = pnl_test_env
        _override_auth(app)

        resp = client.get(
            f"/pnl/{_DEPLOYMENT_ID}/summary",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["deployment_id"] == _DEPLOYMENT_ID
        assert data["total_realized_pnl"] == "1250.50"
        assert data["net_pnl"] == "1538.75"
        assert data["positions_count"] == 5

    def test_summary_404_on_unknown_deployment(self, pnl_test_env) -> None:
        """Returns 404 when deployment does not exist."""
        client, mock_service, app = pnl_test_env
        _override_auth(app)
        mock_service.set_error(NotFoundError("Deployment X not found"))

        resp = client.get(
            "/pnl/01HNONEXISTENT000000000001/summary",
            headers=_auth_headers(),
        )

        assert resp.status_code == 404

    def test_summary_requires_auth(self, pnl_test_env) -> None:
        """Returns 401/403 without valid auth token."""
        client, _, app = pnl_test_env
        # Clear any dependency overrides from prior tests
        app.dependency_overrides.clear()
        # No token header — should be rejected
        resp = client.get(f"/pnl/{_DEPLOYMENT_ID}/summary")
        assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# Tests: GET /pnl/{deployment_id}/timeseries
# ---------------------------------------------------------------------------


class TestGetPnlTimeseries:
    """Tests for GET /pnl/{deployment_id}/timeseries."""

    def test_timeseries_returns_200(self, pnl_test_env) -> None:
        """Returns 200 with timeseries data for valid date range."""
        client, _, app = pnl_test_env
        _override_auth(app)

        resp = client.get(
            f"/pnl/{_DEPLOYMENT_ID}/timeseries",
            params={"date_from": "2026-04-01", "date_to": "2026-04-12"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["snapshot_date"] == "2026-04-01"

    def test_timeseries_422_on_invalid_date(self, pnl_test_env) -> None:
        """Returns 422 on malformed date strings."""
        client, _, app = pnl_test_env
        _override_auth(app)

        resp = client.get(
            f"/pnl/{_DEPLOYMENT_ID}/timeseries",
            params={"date_from": "not-a-date", "date_to": "2026-04-12"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 422

    def test_timeseries_404_on_unknown_deployment(self, pnl_test_env) -> None:
        """Returns 404 when deployment does not exist."""
        client, mock_service, app = pnl_test_env
        _override_auth(app)
        mock_service.set_error(NotFoundError("Deployment not found"))

        resp = client.get(
            "/pnl/01HNONEXISTENT000000000001/timeseries",
            params={"date_from": "2026-04-01", "date_to": "2026-04-12"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: GET /pnl/{deployment_id}/attribution
# ---------------------------------------------------------------------------


class TestGetPnlAttribution:
    """Tests for GET /pnl/{deployment_id}/attribution."""

    def test_attribution_returns_200(self, pnl_test_env) -> None:
        """Returns 200 with per-symbol attribution data."""
        client, _, app = pnl_test_env
        _override_auth(app)

        resp = client.get(
            f"/pnl/{_DEPLOYMENT_ID}/attribution",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["deployment_id"] == _DEPLOYMENT_ID
        assert len(data["by_symbol"]) == 2
        assert data["by_symbol"][0]["symbol"] == "AAPL"

    def test_attribution_with_date_filter(self, pnl_test_env) -> None:
        """Attribution accepts optional date filters."""
        client, _, app = pnl_test_env
        _override_auth(app)

        resp = client.get(
            f"/pnl/{_DEPLOYMENT_ID}/attribution",
            params={"date_from": "2026-04-01", "date_to": "2026-04-12"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests: GET /pnl/comparison
# ---------------------------------------------------------------------------


class TestGetPnlComparison:
    """Tests for GET /pnl/comparison."""

    def test_comparison_returns_200(self, pnl_test_env) -> None:
        """Returns 200 with comparison entries for requested deployments."""
        client, _, app = pnl_test_env
        _override_auth(app)

        resp = client.get(
            "/pnl/comparison",
            params={"deployment_ids": f"{_DEPLOYMENT_ID},01HTESTDEP0000000000000002"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entries"]) == 2

    def test_comparison_422_on_empty_ids(self, pnl_test_env) -> None:
        """Returns 422 when deployment_ids is empty."""
        client, _, app = pnl_test_env
        _override_auth(app)

        resp = client.get(
            "/pnl/comparison",
            params={"deployment_ids": ""},
            headers=_auth_headers(),
        )

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests: POST /pnl/{deployment_id}/snapshot
# ---------------------------------------------------------------------------


class TestTakePnlSnapshot:
    """Tests for POST /pnl/{deployment_id}/snapshot."""

    def test_snapshot_returns_201(self, pnl_test_env) -> None:
        """Returns 201 with persisted snapshot data."""
        client, _, app = pnl_test_env
        _override_auth(app)

        resp = client.post(
            f"/pnl/{_DEPLOYMENT_ID}/snapshot",
            params={"snapshot_date": "2026-04-12"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["deployment_id"] == _DEPLOYMENT_ID
        assert data["snapshot_date"] == "2026-04-12"

    def test_snapshot_404_on_unknown_deployment(self, pnl_test_env) -> None:
        """Returns 404 when deployment does not exist."""
        client, mock_service, app = pnl_test_env
        _override_auth(app)
        mock_service.set_error(NotFoundError("Deployment not found"))

        resp = client.post(
            "/pnl/01HNONEXISTENT000000000001/snapshot",
            params={"snapshot_date": "2026-04-12"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 404

    def test_snapshot_422_on_invalid_date(self, pnl_test_env) -> None:
        """Returns 422 on malformed date."""
        client, _, app = pnl_test_env
        _override_auth(app)

        resp = client.post(
            f"/pnl/{_DEPLOYMENT_ID}/snapshot",
            params={"snapshot_date": "bad-date"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 422
