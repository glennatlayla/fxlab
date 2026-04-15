"""
Unit tests for kill switch API routes.

Covers:
- POST /kill-switch/global → 200 / 409
- POST /kill-switch/strategy/{strategy_id} → 200 / 409
- POST /kill-switch/symbol/{symbol} → 200 / 409
- DELETE /kill-switch/{scope}/{target_id} → 200 / 404
- GET /kill-switch/status → 200
- POST /kill-switch/emergency-posture/{deployment_id} → 200 / 404

Per M7 spec: kill switch management and emergency posture endpoints.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from libs.contracts.mocks.mock_kill_switch_event_repository import (
    MockKillSwitchEventRepository,
)
from services.api.services.kill_switch_service import KillSwitchService

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEP_ID = "01HTESTDEP0000000000000001"
STRAT_ID = "01HTESTSTRT000000000000001"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    repo.seed(
        deployment_id=DEP_ID,
        strategy_id=STRAT_ID,
        state="active",
        execution_mode="paper",
        emergency_posture="flatten_all",
    )
    return repo


@pytest.fixture()
def adapter() -> MockBrokerAdapter:
    return MockBrokerAdapter(fill_mode="instant")


@pytest.fixture()
def kill_switch_service(
    deployment_repo: MockDeploymentRepository,
    adapter: MockBrokerAdapter,
) -> KillSwitchService:
    return KillSwitchService(
        deployment_repo=deployment_repo,
        ks_event_repo=MockKillSwitchEventRepository(),
        adapter_registry={DEP_ID: adapter},
    )


@pytest.fixture()
def client(kill_switch_service: KillSwitchService) -> TestClient:
    from services.api.routes.kill_switch import set_kill_switch_service

    set_kill_switch_service(kill_switch_service)
    from services.api.main import app

    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# POST /kill-switch/global
# ---------------------------------------------------------------------------


class TestActivateGlobal:
    """Tests for POST /kill-switch/global."""

    def test_activate_global_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            "/kill-switch/global",
            json={
                "reason": "Emergency halt",
                "activated_by": "user:admin",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["scope"] == "global"
        assert data["target_id"] == "global"
        assert "event_id" in data

    def test_activate_global_already_active(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        client.post(
            "/kill-switch/global",
            json={"reason": "First", "activated_by": "admin"},
            headers=auth_headers,
        )
        resp = client.post(
            "/kill-switch/global",
            json={"reason": "Second", "activated_by": "admin"},
            headers=auth_headers,
        )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST /kill-switch/strategy/{strategy_id}
# ---------------------------------------------------------------------------


class TestActivateStrategy:
    """Tests for POST /kill-switch/strategy/{strategy_id}."""

    def test_activate_strategy_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            f"/kill-switch/strategy/{STRAT_ID}",
            json={
                "reason": "Strategy breach",
                "activated_by": "system:risk_gate",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["scope"] == "strategy"
        assert data["target_id"] == STRAT_ID


# ---------------------------------------------------------------------------
# POST /kill-switch/symbol/{symbol}
# ---------------------------------------------------------------------------


class TestActivateSymbol:
    """Tests for POST /kill-switch/symbol/{symbol}."""

    def test_activate_symbol_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            "/kill-switch/symbol/AAPL",
            json={
                "reason": "Volatility halt",
                "activated_by": "system:test",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["scope"] == "symbol"
        assert data["target_id"] == "AAPL"


# ---------------------------------------------------------------------------
# DELETE /kill-switch/{scope}/{target_id}
# ---------------------------------------------------------------------------


class TestDeactivate:
    """Tests for DELETE /kill-switch/{scope}/{target_id}."""

    def test_deactivate_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        # First activate
        client.post(
            "/kill-switch/global",
            json={"reason": "Test", "activated_by": "admin"},
            headers=auth_headers,
        )
        # Then deactivate
        resp = client.delete(
            "/kill-switch/global/global",
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_deactivate_not_found(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.delete(
            "/kill-switch/global/global",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /kill-switch/status
# ---------------------------------------------------------------------------


class TestGetStatus:
    """Tests for GET /kill-switch/status."""

    def test_empty_status(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.get("/kill-switch/status", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_status_with_active(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        client.post(
            "/kill-switch/global",
            json={"reason": "Test", "activated_by": "admin"},
            headers=auth_headers,
        )
        resp = client.get("/kill-switch/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["is_active"] is True


# ---------------------------------------------------------------------------
# POST /kill-switch/emergency-posture/{deployment_id}
# ---------------------------------------------------------------------------


class TestEmergencyPosture:
    """Tests for POST /kill-switch/emergency-posture/{deployment_id}."""

    def test_execute_posture_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            f"/kill-switch/emergency-posture/{DEP_ID}",
            json={
                "trigger": "kill_switch",
                "reason": "Global halt",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["deployment_id"] == DEP_ID
        assert data["posture"] == "flatten_all"

    def test_execute_posture_not_found(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            "/kill-switch/emergency-posture/nonexistent",
            json={
                "trigger": "manual",
                "reason": "Test",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 404
