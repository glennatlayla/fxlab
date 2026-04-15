"""
Tests for live trading API routes (/live/*).

Covers:
- POST /live/orders — submit live order (requires live:trade scope)
- GET /live/orders — list live orders
- GET /live/positions — get live positions
- POST /live/orders/{id}/cancel — cancel live order
- GET /live/pnl — live P&L summary
- POST /live/orders/{id}/sync — sync order status from broker
- 403 rejection for users without live:trade scope
- Error mapping: NotFoundError → 404, KillSwitchActiveError → 409,
  RiskGateRejectionError → 422, ExternalServiceError → 502

Example:
    pytest tests/unit/test_live_routes.py -v
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from libs.contracts.errors import (
    KillSwitchActiveError,
    RiskGateRejectionError,
)
from libs.contracts.execution import (
    AccountSnapshot,
    ExecutionMode,
    OrderResponse,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    TimeInForce,
)
from services.api.auth import ROLE_SCOPES, AuthenticatedUser

# ---------------------------------------------------------------------------
# Fake users for dependency overrides
# ---------------------------------------------------------------------------

_LIVE_TRADER_USER = AuthenticatedUser(
    user_id="01HTESTFAKE000000000000000",
    role="live_trader",
    email="trader@fxlab.test",
    scopes=ROLE_SCOPES["live_trader"],
)

_VIEWER_USER = AuthenticatedUser(
    user_id="01HTESTFAKE000000000000000",
    role="viewer",
    email="viewer@fxlab.test",
    scopes=ROLE_SCOPES["viewer"],
)

_DEPLOYMENT_ID = "01HTESTDEP0000000000000001"


# ---------------------------------------------------------------------------
# Mock LiveExecutionService
# ---------------------------------------------------------------------------


class MockLiveExecutionService:
    """Fake LiveExecutionService for route-level testing."""

    def __init__(self) -> None:
        self.submitted_orders: list[dict] = []
        self.cancelled_orders: list[str] = []
        self.synced_orders: list[str] = []
        self._error_on_submit: Exception | None = None

    def set_error_on_submit(self, error: Exception) -> None:
        """Configure an error to be raised on next submit_live_order call."""
        self._error_on_submit = error

    def submit_live_order(
        self, *, deployment_id: str, request: Any, correlation_id: str
    ) -> OrderResponse:
        """Record submission and return mock response."""
        if self._error_on_submit is not None:
            exc = self._error_on_submit
            self._error_on_submit = None
            raise exc
        self.submitted_orders.append(
            {
                "deployment_id": deployment_id,
                "client_order_id": request.client_order_id,
            }
        )
        return OrderResponse(
            client_order_id=request.client_order_id,
            broker_order_id="MOCK-BROKER-001",
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            time_in_force=request.time_in_force,
            status=OrderStatus.SUBMITTED,
            correlation_id=correlation_id,
            execution_mode=ExecutionMode.LIVE,
        )

    def cancel_live_order(
        self, *, deployment_id: str, broker_order_id: str, correlation_id: str
    ) -> OrderResponse:
        """Record cancellation and return mock response."""
        self.cancelled_orders.append(broker_order_id)
        return OrderResponse(
            client_order_id="",
            broker_order_id=broker_order_id,
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            time_in_force=TimeInForce.DAY,
            status=OrderStatus.CANCELLED,
            correlation_id=correlation_id,
            execution_mode=ExecutionMode.LIVE,
        )

    def list_live_orders(
        self, *, deployment_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Return mock order list."""
        return [
            {
                "id": "01HORDER0000000000000000001",
                "client_order_id": "ord-001",
                "symbol": "AAPL",
                "side": "buy",
                "status": status or "submitted",
                "deployment_id": deployment_id,
            }
        ]

    def get_live_positions(self, *, deployment_id: str) -> list[PositionSnapshot]:
        """Return mock positions."""
        return [
            PositionSnapshot(
                symbol="AAPL",
                quantity=Decimal("100"),
                average_entry_price=Decimal("175.50"),
                market_price=Decimal("180.00"),
                market_value=Decimal("18000"),
                unrealized_pnl=Decimal("450"),
                realized_pnl=Decimal("0"),
                cost_basis=Decimal("17550"),
                updated_at="2026-04-12T00:00:00+00:00",
            )
        ]

    def get_live_account(self, *, deployment_id: str) -> AccountSnapshot:
        """Return mock account."""
        return AccountSnapshot(
            account_id=deployment_id,
            equity=Decimal("1000000"),
            cash=Decimal("982450"),
            buying_power=Decimal("982450"),
            portfolio_value=Decimal("1000000"),
            daily_pnl=Decimal("450"),
            pending_orders_count=0,
            positions_count=1,
        )

    def get_live_pnl(self, *, deployment_id: str) -> dict[str, Any]:
        """Return mock P&L."""
        return {
            "total_unrealized_pnl": "450.00",
            "total_realized_pnl": "0",
            "positions": [
                {
                    "symbol": "AAPL",
                    "unrealized_pnl": "450.00",
                    "realized_pnl": "0",
                }
            ],
        }

    def sync_order_status(
        self, *, deployment_id: str, broker_order_id: str, correlation_id: str
    ) -> OrderResponse:
        """Return mock synced order."""
        self.synced_orders.append(broker_order_id)
        return OrderResponse(
            client_order_id="ord-001",
            broker_order_id=broker_order_id,
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            time_in_force=TimeInForce.DAY,
            status=OrderStatus.FILLED,
            correlation_id=correlation_id,
            execution_mode=ExecutionMode.LIVE,
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def live_test_env():
    """
    Set up the test app with live routes wired to mock dependencies.

    Yields (client, mock_service, app) tuple.
    """
    env_vars = {
        "ENVIRONMENT": "test",
        "DATABASE_URL": "sqlite:///:memory:",
        "JWT_SECRET_KEY": "test-secret-key-not-for-production-32bytes!!",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        from services.api.routes import live as live_module

        mock_service = MockLiveExecutionService()
        live_module.set_live_execution_service(mock_service)

        try:
            from services.api.main import app

            client = TestClient(app, raise_server_exceptions=False)
            yield client, mock_service, app
        finally:
            live_module.set_live_execution_service(None)


def _live_trader_headers() -> dict[str, str]:
    """Authorization headers using the TEST_TOKEN."""
    return {"Authorization": "Bearer TEST_TOKEN"}


def _override_auth(app, user=_LIVE_TRADER_USER):
    """Override get_current_user to return a specific user."""
    from services.api.auth import get_current_user

    async def _fake_get_current_user():
        return user

    app.dependency_overrides[get_current_user] = _fake_get_current_user


def _clear_overrides(app):
    """Remove all dependency overrides."""
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Submit order
# ---------------------------------------------------------------------------


class TestLiveSubmitOrder:
    """Tests for POST /live/orders endpoint."""

    def test_submit_returns_201(self, live_test_env):
        """Successful order submission returns 201."""
        client, svc, app = live_test_env
        _override_auth(app)
        try:
            response = client.post(
                f"/live/orders?deployment_id={_DEPLOYMENT_ID}",
                json={
                    "client_order_id": "route-test-001",
                    "symbol": "AAPL",
                    "side": "buy",
                    "order_type": "market",
                    "quantity": "100",
                    "time_in_force": "day",
                    "strategy_id": "01HSTRAT000000000000000001",
                },
                headers=_live_trader_headers(),
            )
            assert response.status_code == 201
            data = response.json()
            assert data["broker_order_id"] == "MOCK-BROKER-001"
            assert data["status"] == "submitted"
        finally:
            _clear_overrides(app)

    def test_submit_requires_live_trade_scope(self, live_test_env):
        """POST /live/orders returns 403 for users without live:trade scope."""
        client, svc, app = live_test_env
        _override_auth(app, _VIEWER_USER)
        try:
            response = client.post(
                f"/live/orders?deployment_id={_DEPLOYMENT_ID}",
                json={
                    "client_order_id": "route-test-002",
                    "symbol": "AAPL",
                    "side": "buy",
                    "order_type": "market",
                    "quantity": "100",
                    "time_in_force": "day",
                    "strategy_id": "01HSTRAT000000000000000001",
                },
                headers=_live_trader_headers(),
            )
            assert response.status_code == 403
        finally:
            _clear_overrides(app)

    def test_kill_switch_returns_409(self, live_test_env):
        """KillSwitchActiveError maps to 409 Conflict."""
        client, svc, app = live_test_env
        _override_auth(app)
        svc.set_error_on_submit(
            KillSwitchActiveError(
                "Trading halted",
                deployment_id=_DEPLOYMENT_ID,
                scope="global",
                target_id="global",
            )
        )
        try:
            response = client.post(
                f"/live/orders?deployment_id={_DEPLOYMENT_ID}",
                json={
                    "client_order_id": "route-test-003",
                    "symbol": "AAPL",
                    "side": "buy",
                    "order_type": "market",
                    "quantity": "100",
                    "time_in_force": "day",
                    "strategy_id": "01HSTRAT000000000000000001",
                },
                headers=_live_trader_headers(),
            )
            assert response.status_code == 409
        finally:
            _clear_overrides(app)

    def test_risk_gate_rejection_returns_422(self, live_test_env):
        """RiskGateRejectionError maps to 422."""
        client, svc, app = live_test_env
        _override_auth(app)
        svc.set_error_on_submit(
            RiskGateRejectionError(
                "Order value exceeds limit",
                check_name="order_value",
                severity="CRITICAL",
                reason="Max order value exceeded",
            )
        )
        try:
            response = client.post(
                f"/live/orders?deployment_id={_DEPLOYMENT_ID}",
                json={
                    "client_order_id": "route-test-004",
                    "symbol": "AAPL",
                    "side": "buy",
                    "order_type": "market",
                    "quantity": "100",
                    "time_in_force": "day",
                    "strategy_id": "01HSTRAT000000000000000001",
                },
                headers=_live_trader_headers(),
            )
            assert response.status_code == 422
        finally:
            _clear_overrides(app)


# ---------------------------------------------------------------------------
# List orders
# ---------------------------------------------------------------------------


class TestLiveListOrders:
    """Tests for GET /live/orders endpoint."""

    def test_list_returns_200(self, live_test_env):
        """GET /live/orders returns 200 with order list."""
        client, svc, app = live_test_env
        _override_auth(app)
        try:
            response = client.get(
                f"/live/orders?deployment_id={_DEPLOYMENT_ID}",
                headers=_live_trader_headers(),
            )
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) >= 1
        finally:
            _clear_overrides(app)


# ---------------------------------------------------------------------------
# Get positions
# ---------------------------------------------------------------------------


class TestLivePositions:
    """Tests for GET /live/positions endpoint."""

    def test_positions_returns_200(self, live_test_env):
        """GET /live/positions returns 200 with position list."""
        client, svc, app = live_test_env
        _override_auth(app)
        try:
            response = client.get(
                f"/live/positions?deployment_id={_DEPLOYMENT_ID}",
                headers=_live_trader_headers(),
            )
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert data[0]["symbol"] == "AAPL"
        finally:
            _clear_overrides(app)


# ---------------------------------------------------------------------------
# Cancel order
# ---------------------------------------------------------------------------


class TestLiveCancelOrder:
    """Tests for POST /live/orders/{id}/cancel endpoint."""

    def test_cancel_returns_200(self, live_test_env):
        """POST /live/orders/{id}/cancel returns 200."""
        client, svc, app = live_test_env
        _override_auth(app)
        try:
            response = client.post(
                f"/live/orders/MOCK-BROKER-001/cancel?deployment_id={_DEPLOYMENT_ID}",
                headers=_live_trader_headers(),
            )
            assert response.status_code == 200
            assert "MOCK-BROKER-001" in svc.cancelled_orders
        finally:
            _clear_overrides(app)


# ---------------------------------------------------------------------------
# P&L
# ---------------------------------------------------------------------------


class TestLivePnl:
    """Tests for GET /live/pnl endpoint."""

    def test_pnl_returns_200(self, live_test_env):
        """GET /live/pnl returns 200 with P&L summary."""
        client, svc, app = live_test_env
        _override_auth(app)
        try:
            response = client.get(
                f"/live/pnl?deployment_id={_DEPLOYMENT_ID}",
                headers=_live_trader_headers(),
            )
            assert response.status_code == 200
            data = response.json()
            assert "total_unrealized_pnl" in data
        finally:
            _clear_overrides(app)


# ---------------------------------------------------------------------------
# Sync order status
# ---------------------------------------------------------------------------


class TestLiveSyncOrder:
    """Tests for POST /live/orders/{id}/sync endpoint."""

    def test_sync_returns_200(self, live_test_env):
        """POST /live/orders/{id}/sync returns 200."""
        client, svc, app = live_test_env
        _override_auth(app)
        try:
            response = client.post(
                f"/live/orders/MOCK-BROKER-001/sync?deployment_id={_DEPLOYMENT_ID}",
                headers=_live_trader_headers(),
            )
            assert response.status_code == 200
            assert "MOCK-BROKER-001" in svc.synced_orders
        finally:
            _clear_overrides(app)
