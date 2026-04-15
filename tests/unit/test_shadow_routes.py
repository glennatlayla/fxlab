"""
Unit tests for shadow API routes.

Covers:
- POST /shadow/{id}/register → 201
- POST /shadow/{id}/orders → 200 (shadow fill)
- POST /shadow/{id}/market-price → 200
- GET /shadow/{id}/decisions → 200
- GET /shadow/{id}/pnl → 200
- GET /shadow/{id}/positions → 200
- GET /shadow/{id}/account → 200
- DELETE /shadow/{id} → 200 (deregister)
- Error paths: 404, 409, 422

Per M3 spec: shadow-specific query routes for decision timeline and P&L.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from libs.contracts.mocks.mock_risk_event_repository import MockRiskEventRepository
from services.api.routes.shadow import set_shadow_service
from services.api.services.risk_gate_service import RiskGateService
from services.api.services.shadow_execution_service import ShadowExecutionService

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
        execution_mode="shadow",
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
def shadow_service(
    deployment_repo: MockDeploymentRepository, risk_gate: RiskGateService
) -> ShadowExecutionService:
    svc = ShadowExecutionService(deployment_repo=deployment_repo, risk_gate=risk_gate)
    return svc


@pytest.fixture()
def client(shadow_service: ShadowExecutionService) -> TestClient:
    set_shadow_service(shadow_service)
    from services.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def registered_client(
    client: TestClient,
    shadow_service: ShadowExecutionService,
) -> TestClient:
    """Client with a pre-registered shadow deployment."""
    shadow_service.register_deployment(
        deployment_id=DEP_ID,
        initial_equity=Decimal("1000000"),
        market_prices={"AAPL": Decimal("175.50"), "MSFT": Decimal("420.00")},
    )
    return client


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestRegisterEndpoint:
    """Tests for POST /shadow/{id}/register."""

    def test_register_success(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.post(
            f"/shadow/{DEP_ID}/register",
            json={
                "initial_equity": "1000000",
                "market_prices": {"AAPL": "175.50"},
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
            f"/shadow/{DEP_ID}/register",
            json={"initial_equity": "1000000"},
            headers=auth_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Order submission tests
# ---------------------------------------------------------------------------


class TestOrderEndpoint:
    """Tests for POST /shadow/{id}/orders."""

    def test_submit_order_success(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        resp = registered_client.post(
            f"/shadow/{DEP_ID}/orders",
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
        assert data["status"] == "filled"
        assert data["average_fill_price"] == "175.50"
        assert data["execution_mode"] == "shadow"

    def test_submit_order_not_registered_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            f"/shadow/{DEP_ID}/orders",
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
        shadow_service: ShadowExecutionService,
        auth_headers: dict[str, str],
    ) -> None:
        dep = deployment_repo.seed(
            state="created",
            execution_mode="shadow",
        )
        shadow_service.register_deployment(
            deployment_id=dep["id"],
            initial_equity=Decimal("1000000"),
            market_prices={"AAPL": Decimal("175.50")},
        )
        resp = client.post(
            f"/shadow/{dep['id']}/orders",
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
# Market price update tests
# ---------------------------------------------------------------------------


class TestMarketPriceEndpoint:
    """Tests for POST /shadow/{id}/market-price."""

    def test_update_price_success(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        resp = registered_client.post(
            f"/shadow/{DEP_ID}/market-price",
            json={"symbol": "AAPL", "price": "200.00"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"

    def test_update_price_not_found(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.post(
            "/shadow/nonexistent/market-price",
            json={"symbol": "AAPL", "price": "200.00"},
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Decision timeline tests
# ---------------------------------------------------------------------------


class TestDecisionsEndpoint:
    """Tests for GET /shadow/{id}/decisions."""

    def test_empty_decisions(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        resp = registered_client.get(f"/shadow/{DEP_ID}/decisions", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_decisions_after_order(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        registered_client.post(
            f"/shadow/{DEP_ID}/orders",
            json={
                "client_order_id": "ord-dec-001",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "100",
                "strategy_id": "01HTESTSTRT000000000000001",
            },
            headers=auth_headers,
        )
        resp = registered_client.get(f"/shadow/{DEP_ID}/decisions", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["event_type"] == "shadow_order_submitted"
        assert data[1]["event_type"] == "shadow_order_filled"

    def test_decisions_not_found(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.get("/shadow/nonexistent/decisions", headers=auth_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# P&L tests
# ---------------------------------------------------------------------------


class TestPnLEndpoint:
    """Tests for GET /shadow/{id}/pnl."""

    def test_pnl_with_position(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        registered_client.post(
            f"/shadow/{DEP_ID}/orders",
            json={
                "client_order_id": "ord-pnl-001",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "100",
                "strategy_id": "01HTESTSTRT000000000000001",
            },
            headers=auth_headers,
        )
        registered_client.post(
            f"/shadow/{DEP_ID}/market-price",
            json={"symbol": "AAPL", "price": "180.00"},
            headers=auth_headers,
        )
        resp = registered_client.get(f"/shadow/{DEP_ID}/pnl", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_unrealized_pnl"] == "450.00"

    def test_pnl_not_found(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.get("/shadow/nonexistent/pnl", headers=auth_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Positions tests
# ---------------------------------------------------------------------------


class TestPositionsEndpoint:
    """Tests for GET /shadow/{id}/positions."""

    def test_positions_after_buy(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        registered_client.post(
            f"/shadow/{DEP_ID}/orders",
            json={
                "client_order_id": "ord-pos-001",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "100",
                "strategy_id": "01HTESTSTRT000000000000001",
            },
            headers=auth_headers,
        )
        resp = registered_client.get(f"/shadow/{DEP_ID}/positions", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["symbol"] == "AAPL"
        assert data[0]["quantity"] == "100"

    def test_positions_not_found(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.get("/shadow/nonexistent/positions", headers=auth_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Account tests
# ---------------------------------------------------------------------------


class TestAccountEndpoint:
    """Tests for GET /shadow/{id}/account."""

    def test_account_initial(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        resp = registered_client.get(f"/shadow/{DEP_ID}/account", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["equity"] == "1000000"
        assert data["account_id"] == "SHADOW-ACCOUNT"

    def test_account_not_found(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.get("/shadow/nonexistent/account", headers=auth_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Deregister tests
# ---------------------------------------------------------------------------


class TestDeregisterEndpoint:
    """Tests for DELETE /shadow/{id}."""

    def test_deregister_success(
        self, registered_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        resp = registered_client.delete(f"/shadow/{DEP_ID}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "deregistered"

    def test_deregister_not_found(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.delete("/shadow/nonexistent", headers=auth_headers)
        assert resp.status_code == 404
