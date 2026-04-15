"""
Unit tests for risk alert API endpoints.

Validates HTTP routing, authentication, scope enforcement, response
serialization, and error handling. Uses a mock RiskAlertService.

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
from libs.contracts.risk_alert import (
    RiskAlert,
    RiskAlertConfig,
    RiskAlertEvaluation,
    RiskAlertType,
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
    user_id="01HTESTV1EW000000000000000",
    role="viewer",
    email="viewer@fxlab.test",
    scopes=ROLE_SCOPES["viewer"],
)

_NOW = datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc)
_DEPLOY_ID = "01HTESTDEPLOY000000000000"


# ---------------------------------------------------------------------------
# Mock service
# ---------------------------------------------------------------------------


class MockRiskAlertService:
    """In-memory mock for route testing."""

    def __init__(self) -> None:
        self._evaluation: RiskAlertEvaluation | None = None
        self._config: RiskAlertConfig | None = None
        self._configs: list[RiskAlertConfig] = []
        self._raise_not_found: bool = False

    def set_evaluation(self, result: RiskAlertEvaluation) -> None:
        self._evaluation = result

    def set_config(self, config: RiskAlertConfig) -> None:
        self._config = config

    def set_configs(self, configs: list[RiskAlertConfig]) -> None:
        self._configs = configs

    def set_raise_not_found(self) -> None:
        self._raise_not_found = True

    def evaluate_alerts(self, deployment_id: str) -> RiskAlertEvaluation:
        if self._raise_not_found:
            raise NotFoundError("No positions found")
        return self._evaluation or RiskAlertEvaluation(
            deployment_id=deployment_id,
            alerts_triggered=[],
            total_rules_checked=3,
            evaluated_at=_NOW,
        )

    def get_config(self, deployment_id: str) -> RiskAlertConfig:
        return self._config or RiskAlertConfig(deployment_id=deployment_id)

    def update_config(self, config: RiskAlertConfig) -> RiskAlertConfig:
        return config

    def list_configs(self) -> list[RiskAlertConfig]:
        return self._configs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def alert_env():
    env_vars = {
        "ENVIRONMENT": "test",
        "DATABASE_URL": "sqlite:///:memory:",
        "JWT_SECRET_KEY": "test-secret-key-not-for-production-32bytes!!",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        from services.api.main import app
        from services.api.routes.risk_alert import get_risk_alert_service

        mock_service = MockRiskAlertService()
        app.dependency_overrides[get_risk_alert_service] = lambda: mock_service

        try:
            from fastapi.testclient import TestClient

            client = TestClient(app, raise_server_exceptions=False)
            yield client, mock_service, app
        finally:
            app.dependency_overrides.pop(get_risk_alert_service, None)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer TEST_TOKEN"}


def _override_auth(app: Any, user: AuthenticatedUser = _OPERATOR_USER) -> None:
    from services.api.auth import get_current_user

    async def _fake() -> AuthenticatedUser:
        return user

    app.dependency_overrides[get_current_user] = _fake


# ---------------------------------------------------------------------------
# POST /risk/alerts/evaluate/{deployment_id}
# ---------------------------------------------------------------------------


class TestEvaluateAlerts:
    """Tests for POST /risk/alerts/evaluate/{deployment_id}."""

    def test_returns_200_with_no_alerts(self, alert_env: Any) -> None:
        client, _, app = alert_env
        _override_auth(app)

        resp = client.post(
            f"/risk/alerts/evaluate/{_DEPLOY_ID}",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["deployment_id"] == _DEPLOY_ID
        assert data["alerts_triggered"] == []
        assert data["total_rules_checked"] == 3

    def test_returns_200_with_alerts(self, alert_env: Any) -> None:
        client, mock_service, app = alert_env
        _override_auth(app)

        mock_service.set_evaluation(
            RiskAlertEvaluation(
                deployment_id=_DEPLOY_ID,
                alerts_triggered=[
                    RiskAlert(
                        alert_type=RiskAlertType.VAR_BREACH,
                        message="VaR breach",
                        current_value=Decimal("6.0"),
                        threshold_value=Decimal("5.0"),
                    ),
                ],
                total_rules_checked=3,
                evaluated_at=_NOW,
            )
        )

        resp = client.post(
            f"/risk/alerts/evaluate/{_DEPLOY_ID}",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["alerts_triggered"]) == 1
        assert data["alerts_triggered"][0]["alert_type"] == "var_breach"

    def test_returns_404_no_positions(self, alert_env: Any) -> None:
        client, mock_service, app = alert_env
        _override_auth(app)
        mock_service.set_raise_not_found()

        resp = client.post(
            f"/risk/alerts/evaluate/{_DEPLOY_ID}",
            headers=_auth_headers(),
        )

        assert resp.status_code == 404

    def test_requires_auth(self, alert_env: Any) -> None:
        client, _, app = alert_env
        app.dependency_overrides.clear()

        resp = client.post(
            f"/risk/alerts/evaluate/{_DEPLOY_ID}",
        )
        assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# GET /risk/alerts/config/{deployment_id}
# ---------------------------------------------------------------------------


class TestGetConfig:
    """Tests for GET /risk/alerts/config/{deployment_id}."""

    def test_returns_200_with_defaults(self, alert_env: Any) -> None:
        client, _, app = alert_env
        _override_auth(app)

        resp = client.get(
            f"/risk/alerts/config/{_DEPLOY_ID}",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["deployment_id"] == _DEPLOY_ID
        assert "var_threshold_pct" in data
        assert "concentration_threshold_pct" in data
        assert "correlation_threshold" in data

    def test_requires_auth(self, alert_env: Any) -> None:
        client, _, app = alert_env
        app.dependency_overrides.clear()

        resp = client.get(f"/risk/alerts/config/{_DEPLOY_ID}")
        assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# PUT /risk/alerts/config
# ---------------------------------------------------------------------------


class TestUpdateConfig:
    """Tests for PUT /risk/alerts/config."""

    def test_returns_200_on_update(self, alert_env: Any) -> None:
        client, _, app = alert_env
        _override_auth(app)

        resp = client.put(
            "/risk/alerts/config",
            json={
                "deployment_id": _DEPLOY_ID,
                "var_threshold_pct": "3.0",
                "concentration_threshold_pct": "25.0",
                "correlation_threshold": "0.85",
                "lookback_days": 126,
                "enabled": False,
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["deployment_id"] == _DEPLOY_ID

    def test_requires_operator_write_scope(self, alert_env: Any) -> None:
        client, _, app = alert_env
        _override_auth(app, _VIEWER_USER)

        resp = client.put(
            "/risk/alerts/config",
            json={
                "deployment_id": _DEPLOY_ID,
                "var_threshold_pct": "3.0",
            },
            headers=_auth_headers(),
        )

        # Viewer doesn't have operator:write scope
        assert resp.status_code == 403

    def test_requires_auth(self, alert_env: Any) -> None:
        client, _, app = alert_env
        app.dependency_overrides.clear()

        resp = client.put(
            "/risk/alerts/config",
            json={"deployment_id": _DEPLOY_ID},
        )
        assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# GET /risk/alerts/configs
# ---------------------------------------------------------------------------


class TestListConfigs:
    """Tests for GET /risk/alerts/configs."""

    def test_returns_200_with_empty_list(self, alert_env: Any) -> None:
        client, _, app = alert_env
        _override_auth(app)

        resp = client.get(
            "/risk/alerts/configs",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["configs"] == []
        assert data["count"] == 0

    def test_returns_200_with_configs(self, alert_env: Any) -> None:
        client, mock_service, app = alert_env
        _override_auth(app)

        mock_service.set_configs(
            [
                RiskAlertConfig(deployment_id="01H_A"),
                RiskAlertConfig(deployment_id="01H_B"),
            ]
        )

        resp = client.get(
            "/risk/alerts/configs",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

    def test_requires_auth(self, alert_env: Any) -> None:
        client, _, app = alert_env
        app.dependency_overrides.clear()

        resp = client.get("/risk/alerts/configs")
        assert resp.status_code in (401, 403, 422)
