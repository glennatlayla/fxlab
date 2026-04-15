"""
Unit tests for paper API routes.

Covers:
- POST /paper/{id}/register → 201
- POST /paper/{id}/orders → 200 (SUBMITTED)
- POST /paper/{id}/process → 200 (fills)
- POST /paper/{id}/orders/{bid}/cancel → 200
- POST /paper/{id}/market-price → 200
- GET /paper/{id}/positions → 200
- GET /paper/{id}/account → 200
- GET /paper/{id}/open-orders → 200
- GET /paper/{id}/all-orders → 200 (reconciliation)
- DELETE /paper/{id} → 200 (deregister)
- Error paths: 404, 409, 422

Per M4 spec: paper execution API with tick-based processing.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from libs.contracts.mocks.mock_risk_event_repository import MockRiskEventRepository
from services.api.routes.paper import set_paper_service
from services.api.services.paper_execution_service import PaperExecutionService
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
    """Return auth headers with TEST_TOKEN."""
    return {"Authorization": "Bearer TEST_TOKEN"}


@pytest.fixture()
def deployment_repo() -> MockDeploymentRepository:
    repo = MockDeploymentRepository()
    repo.seed(
        deployment_id=DEP_ID,
        state="active",
        execution_mode="paper",
        emergency_posture="flatten_all",
    )
    return repo


@pytest.fixture()
def risk_gate(deployment_repo: MockDeploymentRepository) -> RiskGateService:
    return RiskGateService(
        deployment_repo=deployment_repo,
        risk_event_repo=MockRiskEventRepository(),
    )


@pytest.fixture()
def paper_service(
    deployment_repo: MockDeploymentRepository, risk_gate: RiskGateService
) -> PaperExecutionService:
    return PaperExecutionService(deployment_repo=deployment_repo, risk_gate=risk_gate)


@pytest.fixture()
def client(paper_service: PaperExecutionService) -> TestClient:
    set_paper_service(paper_service)
    from services.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def registered_client(
    client: TestClient,
    paper_service: PaperExecutionService,
) -> TestClient:
    """Client with a pre-registered paper deployment."""
    paper_service.register_deployment(
        deployment_id=DEP_ID,
        initial_equity=Decimal("1000000"),
        market_prices={"AAPL": Decimal("175.50"), "MSFT": Decimal("420.00")},
        commission_per_order=Decimal("1.00"),
    )
    return client


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestRegisterEndpoint:
    """Tests for POST /paper/{id}/register."""

    def test_register_success(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.post(
            f"/paper/{DEP_ID}/register",
            json={
                "initial_equity": "1000000",
                "market_prices": {"AAPL": "175.50"},
                "commission_per_order": "1.00",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["deployment_id"] == DEP_ID
        assert data["status"] == "registered"

    def test_register_duplicate_returns_422(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        resp = registered_client.post(
            f"/paper/{DEP_ID}/register",
            json={"initial_equity": "1000000"},
            headers=auth_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Order submission tests
# ---------------------------------------------------------------------------


class TestOrderEndpoint:
    """Tests for POST /paper/{id}/orders."""

    def test_submit_order_returns_submitted(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        resp = registered_client.post(
            f"/paper/{DEP_ID}/orders",
            json={
                "client_order_id": "ord-route-001",
                "symbol": "AAPL",
                "side": "buy",
                "order_type": "market",
                "quantity": "100",
                "strategy_id": "01HTESTSTRT000000000000001",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "submitted"
        assert data["broker_order_id"].startswith("PAPER-")
        assert data["execution_mode"] == "paper"

    def test_submit_order_not_registered_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            f"/paper/{DEP_ID}/orders",
            json={
                "client_order_id": "ord-route-002",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "100",
                "strategy_id": "01HTESTSTRT000000000000001",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_submit_order_not_active_returns_409(
        self,
        client: TestClient,
        deployment_repo: MockDeploymentRepository,
        paper_service: PaperExecutionService,
        auth_headers: dict[str, str],
    ) -> None:
        dep = deployment_repo.seed(
            state="created",
            execution_mode="paper",
        )
        paper_service.register_deployment(
            deployment_id=dep["id"],
            initial_equity=Decimal("1000000"),
            market_prices={"AAPL": Decimal("175.50")},
        )
        resp = client.post(
            f"/paper/{dep['id']}/orders",
            json={
                "client_order_id": "ord-route-003",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "100",
                "strategy_id": "01HTESTSTRT000000000000001",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Process pending orders tests
# ---------------------------------------------------------------------------


class TestProcessEndpoint:
    """Tests for POST /paper/{id}/process."""

    def test_process_fills_market_order(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        # Submit an order first
        registered_client.post(
            f"/paper/{DEP_ID}/orders",
            json={
                "client_order_id": "ord-proc-001",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "100",
                "strategy_id": "01HTESTSTRT000000000000001",
            },
            headers=auth_headers,
        )
        # Process pending orders
        resp = registered_client.post(
            f"/paper/{DEP_ID}/process",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["filled_count"] == 1
        assert data["orders"][0]["status"] == "filled"
        assert data["orders"][0]["average_fill_price"] == "175.50"

    def test_process_not_found(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.post(
            "/paper/nonexistent/process",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Cancel order tests
# ---------------------------------------------------------------------------


class TestCancelEndpoint:
    """Tests for POST /paper/{id}/orders/{bid}/cancel."""

    def test_cancel_pending_order(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        # Submit an order
        submit_resp = registered_client.post(
            f"/paper/{DEP_ID}/orders",
            json={
                "client_order_id": "ord-cancel-001",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "100",
                "strategy_id": "01HTESTSTRT000000000000001",
            },
            headers=auth_headers,
        )
        broker_id = submit_resp.json()["broker_order_id"]
        # Cancel it
        resp = registered_client.post(
            f"/paper/{DEP_ID}/orders/{broker_id}/cancel",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_cancel_not_found(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        resp = registered_client.post(
            f"/paper/{DEP_ID}/orders/PAPER-NONEXISTENT/cancel",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Market price update tests
# ---------------------------------------------------------------------------


class TestMarketPriceEndpoint:
    """Tests for POST /paper/{id}/market-price."""

    def test_update_price_success(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        resp = registered_client.post(
            f"/paper/{DEP_ID}/market-price",
            json={"symbol": "AAPL", "price": "200.00"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"

    def test_update_price_not_found(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.post(
            "/paper/nonexistent/market-price",
            json={"symbol": "AAPL", "price": "200.00"},
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Positions tests
# ---------------------------------------------------------------------------


class TestPositionsEndpoint:
    """Tests for GET /paper/{id}/positions."""

    def test_positions_after_fill(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        registered_client.post(
            f"/paper/{DEP_ID}/orders",
            json={
                "client_order_id": "ord-pos-001",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "100",
                "strategy_id": "01HTESTSTRT000000000000001",
            },
            headers=auth_headers,
        )
        registered_client.post(f"/paper/{DEP_ID}/process", headers=auth_headers)
        resp = registered_client.get(f"/paper/{DEP_ID}/positions", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["symbol"] == "AAPL"
        assert data[0]["quantity"] == "100"

    def test_positions_not_found(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.get("/paper/nonexistent/positions", headers=auth_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Account tests
# ---------------------------------------------------------------------------


class TestAccountEndpoint:
    """Tests for GET /paper/{id}/account."""

    def test_account_initial(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        resp = registered_client.get(f"/paper/{DEP_ID}/account", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["equity"] == "1000000"
        assert data["account_id"] == "PAPER-ACCOUNT"

    def test_account_not_found(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.get("/paper/nonexistent/account", headers=auth_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Open orders tests
# ---------------------------------------------------------------------------


class TestOpenOrdersEndpoint:
    """Tests for GET /paper/{id}/open-orders."""

    def test_open_orders_after_submit(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        registered_client.post(
            f"/paper/{DEP_ID}/orders",
            json={
                "client_order_id": "ord-open-001",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "100",
                "strategy_id": "01HTESTSTRT000000000000001",
            },
            headers=auth_headers,
        )
        resp = registered_client.get(f"/paper/{DEP_ID}/open-orders", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "submitted"

    def test_open_orders_empty_after_fill(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        registered_client.post(
            f"/paper/{DEP_ID}/orders",
            json={
                "client_order_id": "ord-open-002",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "100",
                "strategy_id": "01HTESTSTRT000000000000001",
            },
            headers=auth_headers,
        )
        registered_client.post(f"/paper/{DEP_ID}/process", headers=auth_headers)
        resp = registered_client.get(f"/paper/{DEP_ID}/open-orders", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 0

    def test_open_orders_not_found(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.get("/paper/nonexistent/open-orders", headers=auth_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# All orders (reconciliation) tests
# ---------------------------------------------------------------------------


class TestAllOrdersEndpoint:
    """Tests for GET /paper/{id}/all-orders."""

    def test_all_orders_includes_filled(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        registered_client.post(
            f"/paper/{DEP_ID}/orders",
            json={
                "client_order_id": "ord-recon-001",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "100",
                "strategy_id": "01HTESTSTRT000000000000001",
            },
            headers=auth_headers,
        )
        registered_client.post(f"/paper/{DEP_ID}/process", headers=auth_headers)
        resp = registered_client.get(f"/paper/{DEP_ID}/all-orders", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "filled"

    def test_all_orders_not_found(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.get("/paper/nonexistent/all-orders", headers=auth_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Deregister tests
# ---------------------------------------------------------------------------


class TestDeregisterEndpoint:
    """Tests for DELETE /paper/{id}."""

    def test_deregister_success(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        resp = registered_client.delete(f"/paper/{DEP_ID}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "deregistered"

    def test_deregister_not_found(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.delete("/paper/nonexistent", headers=auth_headers)
        assert resp.status_code == 404
