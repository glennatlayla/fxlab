"""
Unit tests for stress testing API endpoints.

Validates HTTP routing, authentication, scope enforcement, response
serialization, and error handling. Uses a mock StressTestService.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest

from libs.contracts.errors import NotFoundError
from libs.contracts.stress_test import (
    PREDEFINED_SCENARIOS,
    ScenarioLibrary,
    StressScenario,
    StressTestResult,
    SymbolStressImpact,
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

_NOW = datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc)
_DEPLOY_ID = "01HTESTDEPLOY000000000000"


# ---------------------------------------------------------------------------
# Mock service
# ---------------------------------------------------------------------------


def _make_result(**overrides: Any) -> StressTestResult:
    defaults: dict[str, Any] = {
        "scenario_name": "Flash Crash 2010",
        "portfolio_pnl_impact": Decimal("-8700.00"),
        "per_symbol_impact": [
            SymbolStressImpact(
                symbol="AAPL",
                current_value=Decimal("100000"),
                shock_pct=Decimal("-8.7"),
                stressed_value=Decimal("91300"),
                pnl_impact=Decimal("-8700"),
            ),
        ],
        "margin_impact": Decimal("-4350.00"),
        "would_trigger_halt": False,
        "computed_at": _NOW,
    }
    defaults.update(overrides)
    return StressTestResult(**defaults)


class MockStressTestService:
    """In-memory mock for route testing."""

    def __init__(self) -> None:
        self._result: StressTestResult | None = None
        self._raise_not_found: bool = False

    def set_result(self, result: StressTestResult) -> None:
        self._result = result

    def set_raise_not_found(self) -> None:
        self._raise_not_found = True

    def run_predefined(
        self, *, deployment_id: str, scenario_name: ScenarioLibrary
    ) -> StressTestResult:
        if self._raise_not_found:
            raise NotFoundError("No positions")
        return self._result or _make_result()

    def run_scenario(self, *, deployment_id: str, scenario: StressScenario) -> StressTestResult:
        if self._raise_not_found:
            raise NotFoundError("No positions")
        return self._result or _make_result(scenario_name=scenario.name)

    def list_predefined_scenarios(self) -> list[StressScenario]:
        return sorted(PREDEFINED_SCENARIOS.values(), key=lambda s: s.name)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def stress_test_env():
    env_vars = {
        "ENVIRONMENT": "test",
        "DATABASE_URL": "sqlite:///:memory:",
        "JWT_SECRET_KEY": "test-secret-key-not-for-production-32bytes!!",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        from services.api.main import app
        from services.api.routes.stress_test import get_stress_test_service

        mock_service = MockStressTestService()
        app.dependency_overrides[get_stress_test_service] = lambda: mock_service

        try:
            from fastapi.testclient import TestClient

            client = TestClient(app, raise_server_exceptions=False)
            yield client, mock_service, app
        finally:
            app.dependency_overrides.pop(get_stress_test_service, None)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer TEST_TOKEN"}


def _override_auth(app: Any, user: AuthenticatedUser = _OPERATOR_USER) -> None:
    from services.api.auth import get_current_user

    async def _fake() -> AuthenticatedUser:
        return user

    app.dependency_overrides[get_current_user] = _fake


# ---------------------------------------------------------------------------
# POST /risk/stress-test (predefined)
# ---------------------------------------------------------------------------


class TestRunPredefined:
    """Tests for POST /risk/stress-test."""

    def test_returns_200_with_result(self, stress_test_env: Any) -> None:
        client, _, app = stress_test_env
        _override_auth(app)

        resp = client.post(
            "/risk/stress-test",
            json={
                "deployment_id": _DEPLOY_ID,
                "scenario": "flash_crash_2010",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "portfolio_pnl_impact" in data
        assert "per_symbol_impact" in data
        assert "would_trigger_halt" in data

    def test_returns_400_for_unknown_scenario(self, stress_test_env: Any) -> None:
        client, _, app = stress_test_env
        _override_auth(app)

        resp = client.post(
            "/risk/stress-test",
            json={
                "deployment_id": _DEPLOY_ID,
                "scenario": "nonexistent",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 400

    def test_returns_404_no_positions(self, stress_test_env: Any) -> None:
        client, mock_service, app = stress_test_env
        _override_auth(app)
        mock_service.set_raise_not_found()

        resp = client.post(
            "/risk/stress-test",
            json={
                "deployment_id": _DEPLOY_ID,
                "scenario": "flash_crash_2010",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 404

    def test_requires_auth(self, stress_test_env: Any) -> None:
        client, _, app = stress_test_env
        app.dependency_overrides.clear()

        resp = client.post(
            "/risk/stress-test",
            json={
                "deployment_id": _DEPLOY_ID,
                "scenario": "flash_crash_2010",
            },
        )
        assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# POST /risk/stress-test/custom
# ---------------------------------------------------------------------------


class TestRunCustom:
    """Tests for POST /risk/stress-test/custom."""

    def test_returns_200_with_custom_result(self, stress_test_env: Any) -> None:
        client, _, app = stress_test_env
        _override_auth(app)

        resp = client.post(
            "/risk/stress-test/custom",
            json={
                "deployment_id": _DEPLOY_ID,
                "name": "Custom Crash",
                "shocks": [
                    {"symbol": "AAPL", "shock_pct": "-50"},
                    {"symbol": "*", "shock_pct": "-10"},
                ],
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "portfolio_pnl_impact" in data

    def test_returns_404_no_positions(self, stress_test_env: Any) -> None:
        client, mock_service, app = stress_test_env
        _override_auth(app)
        mock_service.set_raise_not_found()

        resp = client.post(
            "/risk/stress-test/custom",
            json={
                "deployment_id": _DEPLOY_ID,
                "shocks": [{"symbol": "*", "shock_pct": "-20"}],
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /risk/stress-test/scenarios
# ---------------------------------------------------------------------------


class TestListScenarios:
    """Tests for GET /risk/stress-test/scenarios."""

    def test_returns_200_with_scenarios(self, stress_test_env: Any) -> None:
        client, _, app = stress_test_env
        _override_auth(app)

        resp = client.get("/risk/stress-test/scenarios", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == len(PREDEFINED_SCENARIOS)
        assert len(data["scenarios"]) == data["count"]

    def test_scenarios_have_required_fields(self, stress_test_env: Any) -> None:
        client, _, app = stress_test_env
        _override_auth(app)

        resp = client.get("/risk/stress-test/scenarios", headers=_auth_headers())

        for scenario in resp.json()["scenarios"]:
            assert "name" in scenario
            assert "shocks" in scenario
            assert "is_predefined" in scenario

    def test_requires_auth(self, stress_test_env: Any) -> None:
        client, _, app = stress_test_env
        app.dependency_overrides.clear()

        resp = client.get("/risk/stress-test/scenarios")
        assert resp.status_code in (401, 403, 422)
