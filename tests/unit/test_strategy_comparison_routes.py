"""
Unit tests for strategy comparison API routes (Phase 7 — M13).

Verifies:
- POST /strategies/compare returns ranked results.
- POST /strategies/compare returns 400 on validation error.
- POST /strategies/compare requires auth.
- GET /strategies/{id}/metrics returns expanded metrics.
- GET /strategies/{id}/metrics returns 404 for missing deployment.
- GET /strategies/{id}/metrics requires auth.

Dependencies:
- FastAPI TestClient.
- Mock StrategyComparisonService injected via DI override.

Example:
    pytest tests/unit/test_strategy_comparison_routes.py -v
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from libs.contracts.errors import NotFoundError, ValidationError
from libs.contracts.strategy_comparison import (
    StrategyComparisonResult,
    StrategyMetrics,
    StrategyRank,
    StrategyRankingCriteria,
)
from services.api.auth import ROLE_SCOPES, AuthenticatedUser

# ---------------------------------------------------------------------------
# Mock service
# ---------------------------------------------------------------------------


class MockStrategyComparisonService:
    """Mock StrategyComparisonService for route testing."""

    def __init__(self) -> None:
        self._compare_result: StrategyComparisonResult | None = None
        self._metrics_result: StrategyMetrics | None = None
        self._raise_validation: bool = False
        self._raise_not_found: bool = False

    def set_compare_result(self, result: StrategyComparisonResult) -> None:
        self._compare_result = result

    def set_metrics_result(self, result: StrategyMetrics) -> None:
        self._metrics_result = result

    def set_raise_validation(self) -> None:
        self._raise_validation = True

    def set_raise_not_found(self) -> None:
        self._raise_not_found = True

    def compare_strategies(self, request: Any) -> StrategyComparisonResult:
        if self._raise_validation:
            raise ValidationError("At least 2 deployments must have P&L data")
        if self._compare_result:
            return self._compare_result
        return StrategyComparisonResult()

    def get_strategy_metrics(self, deployment_id: str) -> StrategyMetrics:
        if self._raise_not_found:
            raise NotFoundError(f"Deployment {deployment_id} not found")
        if self._metrics_result:
            return self._metrics_result
        return StrategyMetrics(deployment_id=deployment_id)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

_OPERATOR_USER = AuthenticatedUser(
    user_id="01HTESTFAKE000000000000000",
    role="operator",
    email="test@fxlab.test",
    scopes=ROLE_SCOPES.get("operator", []),
)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer TEST_TOKEN"}


def _override_auth(app_instance: Any, user: AuthenticatedUser = _OPERATOR_USER) -> None:
    """Override get_current_user to return the test user."""
    from services.api.auth import get_current_user

    async def _fake() -> AuthenticatedUser:
        return user

    app_instance.dependency_overrides[get_current_user] = _fake


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def comparison_env():
    """DI-overridden test client with mock service and auth."""
    env_vars = {
        "ENVIRONMENT": "test",
        "DATABASE_URL": "sqlite:///:memory:",
        "JWT_SECRET_KEY": "test-secret-key-not-for-production-32bytes!!",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        from services.api.main import app
        from services.api.routes.strategy_comparison import (
            get_strategy_comparison_service,
        )

        mock_service = MockStrategyComparisonService()
        app.dependency_overrides[get_strategy_comparison_service] = lambda: mock_service

        try:
            client = TestClient(app, raise_server_exceptions=False)
            yield client, mock_service, app
        finally:
            app.dependency_overrides.pop(get_strategy_comparison_service, None)


# ---------------------------------------------------------------------------
# POST /strategies/compare
# ---------------------------------------------------------------------------


class TestCompareStrategies:
    """Tests for POST /strategies/compare."""

    def test_compare_returns_200_with_rankings(self, comparison_env) -> None:
        """Successful comparison returns ranked results."""
        client, mock_svc, app_inst = comparison_env
        _override_auth(app_inst)

        m1 = StrategyMetrics(deployment_id="d1", sharpe_ratio=Decimal("2.0"))
        m2 = StrategyMetrics(deployment_id="d2", sharpe_ratio=Decimal("1.0"))
        result = StrategyComparisonResult(
            rankings=[
                StrategyRank(rank=1, metrics=m1),
                StrategyRank(rank=2, metrics=m2),
            ],
            ranking_criteria=StrategyRankingCriteria.SHARPE_RATIO,
            comparison_matrix=[m1, m2],
        )
        mock_svc.set_compare_result(result)

        resp = client.post(
            "/strategies/compare",
            json={
                "deployment_ids": ["d1", "d2"],
                "ranking_criteria": "sharpe_ratio",
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["rankings"]) == 2
        assert data["rankings"][0]["rank"] == 1

    def test_compare_returns_400_on_validation_error(self, comparison_env) -> None:
        """Returns 400 when service raises ValidationError."""
        client, mock_svc, app_inst = comparison_env
        _override_auth(app_inst)
        mock_svc.set_raise_validation()

        resp = client.post(
            "/strategies/compare",
            json={"deployment_ids": ["d1", "d2"]},
            headers=_auth_headers(),
        )
        assert resp.status_code == 400

    def test_compare_returns_422_with_single_deployment(self, comparison_env) -> None:
        """FastAPI validation rejects single deployment."""
        client, _, app_inst = comparison_env
        _override_auth(app_inst)

        resp = client.post(
            "/strategies/compare",
            json={"deployment_ids": ["only_one"]},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422

    def test_compare_requires_auth(self, comparison_env) -> None:
        """Unauthenticated request returns 401."""
        client, _, app_inst = comparison_env
        # Clear any auth override so the real auth runs
        from services.api.auth import get_current_user

        app_inst.dependency_overrides.pop(get_current_user, None)

        resp = client.post(
            "/strategies/compare",
            json={"deployment_ids": ["d1", "d2"]},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /strategies/{id}/metrics
# ---------------------------------------------------------------------------


class TestGetStrategyMetrics:
    """Tests for GET /strategies/{deployment_id}/metrics."""

    def test_metrics_returns_200(self, comparison_env) -> None:
        """Successful metrics request returns 200."""
        client, mock_svc, app_inst = comparison_env
        _override_auth(app_inst)
        mock_svc.set_metrics_result(
            StrategyMetrics(
                deployment_id="d1",
                strategy_name="Alpha",
                sharpe_ratio=Decimal("1.80"),
            )
        )

        resp = client.get("/strategies/d1/metrics", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["deployment_id"] == "d1"
        assert data["strategy_name"] == "Alpha"

    def test_metrics_returns_404_for_missing(self, comparison_env) -> None:
        """Returns 404 when deployment not found."""
        client, mock_svc, app_inst = comparison_env
        _override_auth(app_inst)
        mock_svc.set_raise_not_found()

        resp = client.get("/strategies/missing/metrics", headers=_auth_headers())
        assert resp.status_code == 404

    def test_metrics_requires_auth(self, comparison_env) -> None:
        """Unauthenticated request returns 401."""
        client, _, app_inst = comparison_env
        from services.api.auth import get_current_user

        app_inst.dependency_overrides.pop(get_current_user, None)

        resp = client.get("/strategies/d1/metrics")
        assert resp.status_code == 401
