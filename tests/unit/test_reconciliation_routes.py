"""
Unit tests for reconciliation API routes.

Covers:
- POST /reconciliation/{deployment_id}/run → 200 / 404
- GET /reconciliation/reports/{report_id} → 200 / 404
- GET /reconciliation/reports?deployment_id=... → 200

Per M6 spec: reconciliation run trigger and report query endpoints.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from libs.contracts.execution import (
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)
from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from libs.contracts.mocks.mock_reconciliation_repository import (
    MockReconciliationRepository,
)
from services.api.services.reconciliation_service import ReconciliationService

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEP_ID = "01HTESTDEP0000000000000001"


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
        state="active",
        execution_mode="paper",
    )
    return repo


@pytest.fixture()
def recon_repo() -> MockReconciliationRepository:
    return MockReconciliationRepository()


@pytest.fixture()
def adapter() -> MockBrokerAdapter:
    return MockBrokerAdapter(fill_mode="instant")


@pytest.fixture()
def recon_service(
    deployment_repo: MockDeploymentRepository,
    recon_repo: MockReconciliationRepository,
    adapter: MockBrokerAdapter,
) -> ReconciliationService:
    return ReconciliationService(
        deployment_repo=deployment_repo,
        reconciliation_repo=recon_repo,
        adapter_registry={DEP_ID: adapter},
    )


@pytest.fixture()
def client(recon_service: ReconciliationService) -> TestClient:
    from services.api.routes.reconciliation import set_reconciliation_service

    set_reconciliation_service(recon_service)
    from services.api.main import app

    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# POST /reconciliation/{deployment_id}/run
# ---------------------------------------------------------------------------


class TestRunReconciliation:
    """Tests for POST /reconciliation/{deployment_id}/run."""

    def test_run_success_clean(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            f"/reconciliation/{DEP_ID}/run",
            json={"trigger": "manual"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["deployment_id"] == DEP_ID
        assert data["status"] == "completed"
        assert data["discrepancies"] == []
        assert "report_id" in data

    def test_run_with_discrepancies(
        self,
        client: TestClient,
        adapter: MockBrokerAdapter,
        recon_service: ReconciliationService,
        auth_headers: dict[str, str],
    ) -> None:
        # Submit an order to broker so internal_order_states (empty)
        # creates an extra-order discrepancy
        request = OrderRequest(
            client_order_id="broker-only",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            time_in_force=TimeInForce.DAY,
            deployment_id=DEP_ID,
            strategy_id="01HSTRAT0001",
            correlation_id="corr-001",
            execution_mode=ExecutionMode.PAPER,
        )
        adapter.submit_order(request)

        # Reconfigure service with explicit internal state (empty)
        recon_service._internal_order_states = {DEP_ID: {}}

        resp = client.post(
            f"/reconciliation/{DEP_ID}/run",
            json={"trigger": "startup"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed_with_discrepancies"
        assert len(data["discrepancies"]) >= 1

    def test_run_deployment_not_found(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            "/reconciliation/nonexistent/run",
            json={"trigger": "manual"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_run_invalid_trigger(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            f"/reconciliation/{DEP_ID}/run",
            json={"trigger": "invalid_trigger"},
            headers=auth_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /reconciliation/reports/{report_id}
# ---------------------------------------------------------------------------


class TestGetReport:
    """Tests for GET /reconciliation/reports/{report_id}."""

    def test_get_report_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        # First run a reconciliation to create a report
        run_resp = client.post(
            f"/reconciliation/{DEP_ID}/run",
            json={"trigger": "manual"},
            headers=auth_headers,
        )
        report_id = run_resp.json()["report_id"]

        resp = client.get(
            f"/reconciliation/reports/{report_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["report_id"] == report_id
        assert data["deployment_id"] == DEP_ID

    def test_get_report_not_found(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.get(
            "/reconciliation/reports/nonexistent",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /reconciliation/reports?deployment_id=...
# ---------------------------------------------------------------------------


class TestListReports:
    """Tests for GET /reconciliation/reports?deployment_id=..."""

    def test_list_reports_empty(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.get(
            f"/reconciliation/reports?deployment_id={DEP_ID}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_reports_with_data(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Create two reports
        client.post(
            f"/reconciliation/{DEP_ID}/run",
            json={"trigger": "startup"},
            headers=auth_headers,
        )
        client.post(
            f"/reconciliation/{DEP_ID}/run",
            json={"trigger": "scheduled"},
            headers=auth_headers,
        )

        resp = client.get(
            f"/reconciliation/reports?deployment_id={DEP_ID}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_list_reports_with_limit(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Create three reports
        for trigger in ["startup", "scheduled", "manual"]:
            client.post(
                f"/reconciliation/{DEP_ID}/run",
                json={"trigger": trigger},
                headers=auth_headers,
            )

        resp = client.get(
            f"/reconciliation/reports?deployment_id={DEP_ID}&limit=2",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_list_reports_missing_deployment_id(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.get(
            "/reconciliation/reports",
            headers=auth_headers,
        )
        assert resp.status_code == 422
