"""
Unit tests for risk API routes.

Covers:
- GET /risk-events → 200 (with deployment_id query)
- GET /deployments/{id}/risk-limits → 200 / 404
- PUT /deployments/{id}/risk-limits → 200
- DELETE /deployments/{id}/risk-limits → 200 / 404

Per M5 spec: risk event query and limits management endpoints.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from libs.contracts.mocks.mock_risk_event_repository import MockRiskEventRepository
from libs.contracts.risk import PreTradeRiskLimits, RiskEvent, RiskEventSeverity
from services.api.routes.risk import set_risk_gate_service
from services.api.services.risk_gate_service import RiskGateService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DEP_ID = "01HTESTDEP0000000000000001"


@pytest.fixture(autouse=True)
def _test_env():
    """Ensure ENVIRONMENT=test for TEST_TOKEN bypass."""
    old = os.environ.get("ENVIRONMENT")
    os.environ["ENVIRONMENT"] = "test"
    yield
    if old is None:
        os.environ.pop("ENVIRONMENT", None)
    else:
        os.environ["ENVIRONMENT"] = old


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer TEST_TOKEN"}


@pytest.fixture()
def deployment_repo() -> MockDeploymentRepository:
    repo = MockDeploymentRepository()
    repo.seed(deployment_id=DEP_ID, state="active", execution_mode="paper")
    return repo


@pytest.fixture()
def event_repo() -> MockRiskEventRepository:
    return MockRiskEventRepository()


@pytest.fixture()
def risk_service(
    deployment_repo: MockDeploymentRepository, event_repo: MockRiskEventRepository
) -> RiskGateService:
    return RiskGateService(deployment_repo=deployment_repo, risk_event_repo=event_repo)


@pytest.fixture()
def client(risk_service: RiskGateService) -> TestClient:
    set_risk_gate_service(risk_service)
    from services.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def client_with_limits(client: TestClient, risk_service: RiskGateService) -> TestClient:
    """Client with pre-configured risk limits."""
    risk_service.set_risk_limits(
        deployment_id=DEP_ID,
        limits=PreTradeRiskLimits(
            max_position_size=Decimal("1000"),
            max_daily_loss=Decimal("5000"),
            max_order_value=Decimal("50000"),
            max_concentration_pct=Decimal("25"),
            max_open_orders=10,
        ),
    )
    return client


# ---------------------------------------------------------------------------
# Risk events endpoint tests
# ---------------------------------------------------------------------------


class TestRiskEventsEndpoint:
    """Tests for GET /risk-events."""

    def test_empty_events(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.get(
            f"/risk/risk-events?deployment_id={DEP_ID}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_events_with_data(
        self,
        client: TestClient,
        event_repo: MockRiskEventRepository,
        auth_headers: dict[str, str],
    ) -> None:
        event_repo.save(
            RiskEvent(
                event_id="01HRISK0000000000000000001",
                deployment_id=DEP_ID,
                check_name="order_value",
                severity=RiskEventSeverity.CRITICAL,
                passed=False,
                reason="Value exceeded",
                created_at=datetime.now(timezone.utc),
            )
        )
        resp = client.get(
            f"/risk/risk-events?deployment_id={DEP_ID}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["check_name"] == "order_value"
        assert data[0]["passed"] is False

    def test_events_filter_by_severity(
        self,
        client: TestClient,
        event_repo: MockRiskEventRepository,
        auth_headers: dict[str, str],
    ) -> None:
        event_repo.save(
            RiskEvent(
                event_id="01HRISK0000000000000000001",
                deployment_id=DEP_ID,
                check_name="order_value",
                severity=RiskEventSeverity.INFO,
                passed=True,
            )
        )
        event_repo.save(
            RiskEvent(
                event_id="01HRISK0000000000000000002",
                deployment_id=DEP_ID,
                check_name="daily_loss",
                severity=RiskEventSeverity.CRITICAL,
                passed=False,
            )
        )
        resp = client.get(
            f"/risk/risk-events?deployment_id={DEP_ID}&severity=critical",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["severity"] == "critical"


# ---------------------------------------------------------------------------
# Risk limits endpoint tests
# ---------------------------------------------------------------------------


class TestGetRiskLimitsEndpoint:
    """Tests for GET /deployments/{id}/risk-limits."""

    def test_get_limits(self, client_with_limits: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client_with_limits.get(
            f"/risk/deployments/{DEP_ID}/risk-limits",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["max_position_size"] == "1000"
        assert data["max_open_orders"] == 10

    def test_get_limits_not_found(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.get(
            "/risk/deployments/nonexistent/risk-limits",
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestSetRiskLimitsEndpoint:
    """Tests for PUT /deployments/{id}/risk-limits."""

    def test_set_limits(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.put(
            f"/risk/deployments/{DEP_ID}/risk-limits",
            json={
                "max_position_size": "2000",
                "max_daily_loss": "10000",
                "max_order_value": "100000",
                "max_concentration_pct": "50",
                "max_open_orders": 20,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "limits_set"

        # Verify limits were set
        get_resp = client.get(
            f"/risk/deployments/{DEP_ID}/risk-limits",
            headers=auth_headers,
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["max_position_size"] == "2000"


class TestClearRiskLimitsEndpoint:
    """Tests for DELETE /deployments/{id}/risk-limits."""

    def test_clear_limits(
        self, client_with_limits: TestClient, auth_headers: dict[str, str]
    ) -> None:
        resp = client_with_limits.delete(
            f"/risk/deployments/{DEP_ID}/risk-limits",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "limits_cleared"

    def test_clear_limits_not_found(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.delete(
            "/risk/deployments/nonexistent/risk-limits",
            headers=auth_headers,
        )
        assert resp.status_code == 404
