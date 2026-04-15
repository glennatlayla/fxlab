"""
Unit tests for drill API routes.

Covers:
- POST /drills/{deployment_id}/execute → 200 / 404 / 422
- GET /drills/{deployment_id}/eligibility → 200 / 404
- GET /drills/{deployment_id}/history → 200

Per M9 spec: drill execution, live eligibility checks, drill history.

Dependencies:
- libs.contracts.mocks.mock_broker_adapter: MockBrokerAdapter
- libs.contracts.mocks.mock_deployment_repository: MockDeploymentRepository
- services.api.services.drill_service: DrillService
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from services.api.services.drill_service import DrillService

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
def drill_service(
    deployment_repo: MockDeploymentRepository,
    adapter: MockBrokerAdapter,
) -> DrillService:
    return DrillService(
        deployment_repo=deployment_repo,
        adapter_registry={DEP_ID: adapter},
    )


@pytest.fixture()
def client(drill_service: DrillService) -> TestClient:
    from services.api.routes.drills import set_drill_service

    set_drill_service(drill_service)
    from services.api.main import app

    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# POST /drills/{deployment_id}/execute
# ---------------------------------------------------------------------------


class TestExecuteDrill:
    """Tests for POST /drills/{deployment_id}/execute."""

    def test_execute_kill_switch_drill(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            f"/drills/{DEP_ID}/execute",
            json={"drill_type": "kill_switch"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["drill_type"] == "kill_switch"
        assert data["deployment_id"] == DEP_ID
        assert data["passed"] is True
        assert "result_id" in data

    def test_execute_rollback_drill(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            f"/drills/{DEP_ID}/execute",
            json={"drill_type": "rollback"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["drill_type"] == "rollback"
        assert data["passed"] is True

    def test_execute_drill_deployment_not_found(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            "/drills/nonexistent/execute",
            json={"drill_type": "kill_switch"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_execute_drill_invalid_type(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            f"/drills/{DEP_ID}/execute",
            json={"drill_type": "invalid"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_execute_drill_no_auth(
        self,
        client: TestClient,
    ) -> None:
        resp = client.post(
            f"/drills/{DEP_ID}/execute",
            json={"drill_type": "kill_switch"},
        )
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /drills/{deployment_id}/eligibility
# ---------------------------------------------------------------------------


class TestLiveEligibility:
    """Tests for GET /drills/{deployment_id}/eligibility."""

    def test_not_eligible_no_drills(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.get(
            f"/drills/{DEP_ID}/eligibility",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["eligible"] is False
        assert len(data["missing_requirements"]) == 4

    def test_eligible_after_all_drills(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        for dt in ["kill_switch", "rollback", "reconnect", "failover"]:
            client.post(
                f"/drills/{DEP_ID}/execute",
                json={"drill_type": dt},
                headers=auth_headers,
            )

        resp = client.get(
            f"/drills/{DEP_ID}/eligibility",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["eligible"] is True
        assert data["missing_requirements"] == []

    def test_eligibility_not_found(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.get(
            "/drills/nonexistent/eligibility",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /drills/{deployment_id}/history
# ---------------------------------------------------------------------------


class TestDrillHistory:
    """Tests for GET /drills/{deployment_id}/history."""

    def test_empty_history(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.get(
            f"/drills/{DEP_ID}/history",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_history_after_drills(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        client.post(
            f"/drills/{DEP_ID}/execute",
            json={"drill_type": "kill_switch"},
            headers=auth_headers,
        )
        client.post(
            f"/drills/{DEP_ID}/execute",
            json={"drill_type": "rollback"},
            headers=auth_headers,
        )

        resp = client.get(
            f"/drills/{DEP_ID}/history",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
