"""
Unit tests for portfolio risk analytics REST API endpoints.

Validates HTTP routing, authentication, scope enforcement, response
serialization, and error handling. Uses a mock RiskAnalyticsService
to isolate from database, market data, and numerical computation.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest

from libs.contracts.errors import NotFoundError, ValidationError
from libs.contracts.risk_analytics import (
    ConcentrationReport,
    CorrelationEntry,
    CorrelationMatrix,
    PortfolioRiskSummary,
    SymbolConcentration,
    VaRMethod,
    VaRResult,
)
from services.api.auth import ROLE_SCOPES, AuthenticatedUser

# ---------------------------------------------------------------------------
# Fake users
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

_DEPLOY_ID = "01HTESTDEPLOY000000000000"
_NOW = datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures for mock service results
# ---------------------------------------------------------------------------


def _make_var_result() -> VaRResult:
    return VaRResult(
        var_95=Decimal("-2500.00"),
        var_99=Decimal("-4100.00"),
        cvar_95=Decimal("-3200.00"),
        cvar_99=Decimal("-5000.00"),
        method=VaRMethod.HISTORICAL,
        lookback_days=252,
        computed_at=_NOW,
    )


def _make_correlation_matrix() -> CorrelationMatrix:
    return CorrelationMatrix(
        symbols=["AAPL", "MSFT"],
        entries=[
            CorrelationEntry(
                symbol_a="AAPL", symbol_b="AAPL", correlation=Decimal("1.0"), lookback_days=252
            ),
            CorrelationEntry(
                symbol_a="AAPL", symbol_b="MSFT", correlation=Decimal("0.85"), lookback_days=252
            ),
            CorrelationEntry(
                symbol_a="MSFT", symbol_b="AAPL", correlation=Decimal("0.85"), lookback_days=252
            ),
            CorrelationEntry(
                symbol_a="MSFT", symbol_b="MSFT", correlation=Decimal("1.0"), lookback_days=252
            ),
        ],
        matrix=[["1.0", "0.85"], ["0.85", "1.0"]],
        lookback_days=252,
        computed_at=_NOW,
    )


def _make_concentration_report() -> ConcentrationReport:
    return ConcentrationReport(
        per_symbol=[
            SymbolConcentration(
                symbol="AAPL", market_value=Decimal("50000"), pct_of_portfolio=Decimal("50.0")
            ),
            SymbolConcentration(
                symbol="MSFT", market_value=Decimal("50000"), pct_of_portfolio=Decimal("50.0")
            ),
        ],
        herfindahl_index=Decimal("5000"),
        top_5_pct=Decimal("100.0"),
        computed_at=_NOW,
    )


def _make_summary() -> PortfolioRiskSummary:
    return PortfolioRiskSummary(
        var=_make_var_result(),
        correlation=_make_correlation_matrix(),
        concentration=_make_concentration_report(),
        total_exposure=Decimal("100000"),
        net_exposure=Decimal("80000"),
        gross_exposure=Decimal("100000"),
        long_exposure=Decimal("90000"),
        short_exposure=Decimal("10000"),
        computed_at=_NOW,
    )


# ---------------------------------------------------------------------------
# Mock service
# ---------------------------------------------------------------------------


class MockRiskAnalyticsService:
    """In-memory mock that returns canned results for route testing."""

    def __init__(self) -> None:
        self._var_result: VaRResult | None = None
        self._correlation_result: CorrelationMatrix | None = None
        self._concentration_result: ConcentrationReport | None = None
        self._summary_result: PortfolioRiskSummary | None = None
        self._raise_not_found: bool = False
        self._raise_validation: bool = False

    def set_var_result(self, result: VaRResult) -> None:
        self._var_result = result

    def set_correlation_result(self, result: CorrelationMatrix) -> None:
        self._correlation_result = result

    def set_concentration_result(self, result: ConcentrationReport) -> None:
        self._concentration_result = result

    def set_summary_result(self, result: PortfolioRiskSummary) -> None:
        self._summary_result = result

    def set_raise_not_found(self, message: str = "Not found") -> None:
        self._raise_not_found = True
        self._not_found_msg = message

    def set_raise_validation(self, message: str = "Invalid") -> None:
        self._raise_validation = True
        self._validation_msg = message

    def _check_errors(self) -> None:
        if self._raise_not_found:
            raise NotFoundError(self._not_found_msg)
        if self._raise_validation:
            raise ValidationError(self._validation_msg)

    def compute_var(self, *, deployment_id: str, lookback_days: int = 252) -> VaRResult:
        self._check_errors()
        return self._var_result or _make_var_result()

    def compute_correlation_matrix(
        self, *, deployment_id: str, lookback_days: int = 252
    ) -> CorrelationMatrix:
        self._check_errors()
        return self._correlation_result or _make_correlation_matrix()

    def compute_concentration(self, *, deployment_id: str) -> ConcentrationReport:
        self._check_errors()
        return self._concentration_result or _make_concentration_report()

    def get_portfolio_risk_summary(
        self, *, deployment_id: str, lookback_days: int = 252
    ) -> PortfolioRiskSummary:
        self._check_errors()
        return self._summary_result or _make_summary()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def risk_analytics_test_env():
    """
    Set up test app with risk analytics routes wired to mock service.

    Yields (client, mock_service, app) tuple.
    """
    env_vars = {
        "ENVIRONMENT": "test",
        "DATABASE_URL": "sqlite:///:memory:",
        "JWT_SECRET_KEY": "test-secret-key-not-for-production-32bytes!!",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        from services.api.main import app
        from services.api.routes.risk_analytics import get_risk_analytics_service

        mock_service = MockRiskAnalyticsService()
        app.dependency_overrides[get_risk_analytics_service] = lambda: mock_service

        try:
            from fastapi.testclient import TestClient

            client = TestClient(app, raise_server_exceptions=False)
            yield client, mock_service, app
        finally:
            app.dependency_overrides.pop(get_risk_analytics_service, None)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer TEST_TOKEN"}


def _override_auth(app: Any, user: AuthenticatedUser = _OPERATOR_USER) -> None:
    from services.api.auth import get_current_user

    async def _fake() -> AuthenticatedUser:
        return user

    app.dependency_overrides[get_current_user] = _fake


# ---------------------------------------------------------------------------
# GET /risk/analytics/var/{deployment_id}
# ---------------------------------------------------------------------------


class TestGetVaR:
    """Tests for GET /risk/analytics/var/{deployment_id}."""

    def test_returns_200_with_var_result(self, risk_analytics_test_env: Any) -> None:
        client, _, app = risk_analytics_test_env
        _override_auth(app)

        resp = client.get(f"/risk/analytics/var/{_DEPLOY_ID}", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert "var_95" in data
        assert "var_99" in data
        assert "cvar_95" in data
        assert "cvar_99" in data
        assert data["method"] == "historical"

    def test_returns_404_when_no_positions(self, risk_analytics_test_env: Any) -> None:
        client, mock_service, app = risk_analytics_test_env
        _override_auth(app)
        mock_service.set_raise_not_found("No positions")

        resp = client.get(f"/risk/analytics/var/{_DEPLOY_ID}", headers=_auth_headers())

        assert resp.status_code == 404
        assert "No positions" in resp.json()["detail"]

    def test_custom_lookback_days(self, risk_analytics_test_env: Any) -> None:
        client, _, app = risk_analytics_test_env
        _override_auth(app)

        resp = client.get(
            f"/risk/analytics/var/{_DEPLOY_ID}?lookback_days=60",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200

    def test_requires_auth(self, risk_analytics_test_env: Any) -> None:
        client, _, app = risk_analytics_test_env
        app.dependency_overrides.clear()

        resp = client.get(f"/risk/analytics/var/{_DEPLOY_ID}")
        assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# GET /risk/analytics/correlation/{deployment_id}
# ---------------------------------------------------------------------------


class TestGetCorrelation:
    """Tests for GET /risk/analytics/correlation/{deployment_id}."""

    def test_returns_200_with_matrix(self, risk_analytics_test_env: Any) -> None:
        client, _, app = risk_analytics_test_env
        _override_auth(app)

        resp = client.get(f"/risk/analytics/correlation/{_DEPLOY_ID}", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert "symbols" in data
        assert "entries" in data
        assert "matrix" in data
        assert len(data["symbols"]) == 2

    def test_returns_404_when_no_positions(self, risk_analytics_test_env: Any) -> None:
        client, mock_service, app = risk_analytics_test_env
        _override_auth(app)
        mock_service.set_raise_not_found("No positions")

        resp = client.get(f"/risk/analytics/correlation/{_DEPLOY_ID}", headers=_auth_headers())

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /risk/analytics/concentration/{deployment_id}
# ---------------------------------------------------------------------------


class TestGetConcentration:
    """Tests for GET /risk/analytics/concentration/{deployment_id}."""

    def test_returns_200_with_report(self, risk_analytics_test_env: Any) -> None:
        client, _, app = risk_analytics_test_env
        _override_auth(app)

        resp = client.get(f"/risk/analytics/concentration/{_DEPLOY_ID}", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert "per_symbol" in data
        assert "herfindahl_index" in data
        assert "top_5_pct" in data

    def test_returns_404_when_no_positions(self, risk_analytics_test_env: Any) -> None:
        client, mock_service, app = risk_analytics_test_env
        _override_auth(app)
        mock_service.set_raise_not_found("No positions")

        resp = client.get(f"/risk/analytics/concentration/{_DEPLOY_ID}", headers=_auth_headers())

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /risk/analytics/summary/{deployment_id}
# ---------------------------------------------------------------------------


class TestGetSummary:
    """Tests for GET /risk/analytics/summary/{deployment_id}."""

    def test_returns_200_with_full_summary(self, risk_analytics_test_env: Any) -> None:
        client, _, app = risk_analytics_test_env
        _override_auth(app)

        resp = client.get(f"/risk/analytics/summary/{_DEPLOY_ID}", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert "var" in data
        assert "correlation" in data
        assert "concentration" in data
        assert "total_exposure" in data
        assert "net_exposure" in data
        assert "long_exposure" in data
        assert "short_exposure" in data

    def test_returns_404_when_no_positions(self, risk_analytics_test_env: Any) -> None:
        client, mock_service, app = risk_analytics_test_env
        _override_auth(app)
        mock_service.set_raise_not_found("No positions")

        resp = client.get(f"/risk/analytics/summary/{_DEPLOY_ID}", headers=_auth_headers())

        assert resp.status_code == 404

    def test_viewer_can_access(self, risk_analytics_test_env: Any) -> None:
        """Viewer role has deployments:read and can access analytics."""
        client, _, app = risk_analytics_test_env
        _override_auth(app, _VIEWER_USER)

        resp = client.get(f"/risk/analytics/summary/{_DEPLOY_ID}", headers=_auth_headers())

        assert resp.status_code == 200

    def test_requires_auth(self, risk_analytics_test_env: Any) -> None:
        client, _, app = risk_analytics_test_env
        app.dependency_overrides.clear()

        resp = client.get(f"/risk/analytics/summary/{_DEPLOY_ID}")
        assert resp.status_code in (401, 403, 422)
