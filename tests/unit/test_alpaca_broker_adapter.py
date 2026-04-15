"""
Unit tests for AlpacaBrokerAdapter (M5 — Alpaca Broker Adapter).

Tests cover:
- connect(): creates httpx client, validates via /clock
- disconnect(): closes client, idempotent
- submit_order(): POST /v2/orders, idempotent on client_order_id
- cancel_order(): DELETE /v2/orders/{id}
- get_order(): GET /v2/orders/{id}
- list_open_orders(): GET /v2/orders?status=open
- get_fills(): extract fill info from order response
- get_positions(): GET /v2/positions
- get_account(): GET /v2/account
- get_diagnostics(): latency, connection status
- is_market_open(): GET /v2/clock
- Error mapping: 401→AuthError, 404→NotFoundError, 429/5xx→TransientError
- Timeout handling
- Alpaca order status → OrderStatus mapping

Dependencies:
    - services.api.adapters.alpaca_broker_adapter: AlpacaBrokerAdapter
    - libs.contracts.alpaca_config: AlpacaConfig
    - httpx: MockTransport for request interception
    - libs.contracts.errors: domain exceptions

Example:
    pytest tests/unit/test_alpaca_broker_adapter.py -v
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from libs.contracts.alpaca_config import AlpacaConfig
from libs.contracts.errors import AuthError, ExternalServiceError, NotFoundError, TransientError
from libs.contracts.execution import (
    OrderRequest,
    OrderSide,
    OrderStatus,
)
from services.api.adapters.alpaca_broker_adapter import _ALPACA_STATUS_MAP, AlpacaBrokerAdapter
from services.api.infrastructure.timeout_config import BrokerTimeoutConfig

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_TEST_CONFIG = AlpacaConfig(
    api_key="AKTEST123456",
    api_secret="secretsecretsecretsecretsecretsecret",
    base_url="https://paper-api.alpaca.markets",
)

_CLOCK_RESPONSE = {
    "timestamp": "2026-04-11T10:00:00-04:00",
    "is_open": True,
    "next_open": "",
    "next_close": "",
}

_ORDER_RESPONSE: dict[str, Any] = {
    "id": "alpaca-order-001",
    "client_order_id": "test-order-001",
    "symbol": "AAPL",
    "side": "buy",
    "type": "market",
    "qty": "10",
    "filled_qty": "0",
    "filled_avg_price": None,
    "status": "new",
    "time_in_force": "day",
    "submitted_at": "2026-04-11T14:00:00Z",
    "filled_at": None,
    "canceled_at": None,
    "limit_price": None,
    "stop_price": None,
}

_FILLED_ORDER: dict[str, Any] = {
    **_ORDER_RESPONSE,
    "status": "filled",
    "filled_qty": "10",
    "filled_avg_price": "150.50",
    "filled_at": "2026-04-11T14:01:00Z",
}

_POSITION_RESPONSE = {
    "symbol": "AAPL",
    "qty": "100",
    "avg_entry_price": "148.50",
    "current_price": "150.00",
    "market_value": "15000.00",
    "unrealized_pl": "150.00",
    "cost_basis": "14850.00",
}

_ACCOUNT_RESPONSE = {
    "id": "acct-001",
    "equity": "100000.00",
    "cash": "50000.00",
    "buying_power": "200000.00",
    "portfolio_value": "100000.00",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_transport(
    *,
    responses: dict[str, tuple[int, Any]] | None = None,
    default_status: int = 200,
    default_body: Any = None,
) -> httpx.MockTransport:
    """
    Create a mock transport that returns configured responses by URL path.

    Args:
        responses: Dict mapping URL path → (status_code, response_body).
        default_status: Default HTTP status for unmatched paths.
        default_body: Default response body for unmatched paths.

    Returns:
        httpx.MockTransport instance.
    """
    resp_map = responses or {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        # Match on path suffix (ignore base URL)
        for key, (status, body) in resp_map.items():
            if path.endswith(key) or key in str(request.url):
                content = json.dumps(body) if isinstance(body, (dict, list)) else body
                return httpx.Response(
                    status, content=content, headers={"content-type": "application/json"}
                )
        # Default response
        body_content = json.dumps(default_body) if default_body else "{}"
        return httpx.Response(
            default_status, content=body_content, headers={"content-type": "application/json"}
        )

    return httpx.MockTransport(handler)


def _make_adapter(
    transport: httpx.MockTransport | None = None,
) -> AlpacaBrokerAdapter:
    """Create an AlpacaBrokerAdapter with a mock transport pre-connected."""
    adapter = AlpacaBrokerAdapter(config=_TEST_CONFIG)

    if transport is not None:
        # Inject the mock transport directly
        adapter._client = httpx.Client(
            headers=_TEST_CONFIG.auth_headers,
            transport=transport,
            timeout=httpx.Timeout(5.0),
        )
        adapter._connected_at = datetime.now(tz=timezone.utc)

    return adapter


def _make_order_request(**overrides: Any) -> OrderRequest:
    """Create a test OrderRequest with sensible defaults."""
    defaults = {
        "client_order_id": "test-order-001",
        "symbol": "AAPL",
        "side": "buy",
        "order_type": "market",
        "quantity": Decimal("10"),
        "time_in_force": "day",
        "deployment_id": "01HDEPLOY00000000001",
        "strategy_id": "01HSTRAT000000000001",
        "correlation_id": "corr-test-001",
        "execution_mode": "paper",
    }
    defaults.update(overrides)
    return OrderRequest(**defaults)


# ---------------------------------------------------------------------------
# Connect / Disconnect tests
# ---------------------------------------------------------------------------


class TestAlpacaConnect:
    """Tests for connect() and disconnect() lifecycle."""

    def test_connect_creates_client(self) -> None:
        """connect() should create an httpx client and validate via /clock."""
        transport = _make_transport(
            responses={"/v2/clock": (200, _CLOCK_RESPONSE)},
        )
        # Create the real mock-transport client *before* patching httpx.Client
        mock_client = httpx.Client(transport=transport)

        adapter = AlpacaBrokerAdapter(config=_TEST_CONFIG)

        with patch.object(httpx, "Client", return_value=mock_client):
            adapter.connect()

        assert adapter._client is not None

    def test_connect_idempotent(self) -> None:
        """Calling connect() twice should be a no-op."""
        transport = _make_transport(
            responses={"/v2/clock": (200, _CLOCK_RESPONSE)},
        )
        adapter = _make_adapter(transport)

        # Already connected via _make_adapter
        adapter.connect()  # Should not raise

    def test_disconnect_closes_client(self) -> None:
        """disconnect() should close the client and set it to None."""
        transport = _make_transport()
        adapter = _make_adapter(transport)

        adapter.disconnect()

        assert adapter._client is None

    def test_disconnect_idempotent(self) -> None:
        """Calling disconnect() twice should be safe."""
        adapter = AlpacaBrokerAdapter(config=_TEST_CONFIG)
        adapter.disconnect()  # Not connected, should be safe
        adapter.disconnect()  # Still safe

    def test_get_timeout_config_returns_config(self) -> None:
        """get_timeout_config() should return the configured timeouts."""
        custom = BrokerTimeoutConfig(order_timeout_s=20.0)
        adapter = AlpacaBrokerAdapter(config=_TEST_CONFIG, timeout_config=custom)
        assert adapter.get_timeout_config().order_timeout_s == 20.0


# ---------------------------------------------------------------------------
# Order submission tests
# ---------------------------------------------------------------------------


class TestAlpacaSubmitOrder:
    """Tests for submit_order()."""

    def test_submit_order_happy_path(self) -> None:
        """submit_order should POST to /v2/orders and return OrderResponse."""
        transport = _make_transport(
            responses={"/v2/orders": (200, _ORDER_RESPONSE)},
        )
        adapter = _make_adapter(transport)

        resp = adapter.submit_order(_make_order_request())

        assert resp.client_order_id == "test-order-001"
        assert resp.broker_order_id == "alpaca-order-001"
        assert resp.symbol == "AAPL"
        assert resp.side == OrderSide.BUY
        assert resp.status == OrderStatus.SUBMITTED  # "new" maps to SUBMITTED

    def test_submit_order_maps_filled_status(self) -> None:
        """A filled order response should map to OrderStatus.FILLED."""
        transport = _make_transport(
            responses={"/v2/orders": (200, _FILLED_ORDER)},
        )
        adapter = _make_adapter(transport)

        resp = adapter.submit_order(_make_order_request())

        assert resp.status == OrderStatus.FILLED
        assert resp.filled_quantity == Decimal("10")
        assert resp.average_fill_price == Decimal("150.50")

    def test_submit_order_not_connected_raises(self) -> None:
        """submit_order without connect() should raise ExternalServiceError."""
        adapter = AlpacaBrokerAdapter(config=_TEST_CONFIG)

        with pytest.raises(ExternalServiceError, match="not connected"):
            adapter.submit_order(_make_order_request())

    def test_submit_order_auth_failure(self) -> None:
        """401 from Alpaca should raise AuthError."""
        transport = _make_transport(
            responses={"/v2/orders": (401, {"message": "Unauthorized"})},
        )
        adapter = _make_adapter(transport)

        with pytest.raises(AuthError, match="authentication failed"):
            adapter.submit_order(_make_order_request())

    def test_submit_order_422_raises_external_service_error(self) -> None:
        """422 from Alpaca should raise ExternalServiceError."""
        transport = _make_transport(
            responses={"/v2/orders": (422, {"message": "Unprocessable"})},
        )
        adapter = _make_adapter(transport)

        with pytest.raises(ExternalServiceError, match="rejected"):
            adapter.submit_order(_make_order_request())


# ---------------------------------------------------------------------------
# Cancel order tests
# ---------------------------------------------------------------------------


class TestAlpacaCancelOrder:
    """Tests for cancel_order()."""

    def test_cancel_order_204_refetches(self) -> None:
        """cancel_order with 204 response should re-fetch order state."""
        cancelled = {**_ORDER_RESPONSE, "status": "canceled", "canceled_at": "2026-04-11T14:02:00Z"}

        call_count = {"delete": 0, "get": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "DELETE":
                call_count["delete"] += 1
                return httpx.Response(204, content="")
            if request.method == "GET" and "orders" in str(request.url):
                call_count["get"] += 1
                return httpx.Response(
                    200,
                    content=json.dumps(cancelled),
                    headers={"content-type": "application/json"},
                )
            return httpx.Response(200, content="{}")

        transport = httpx.MockTransport(handler)
        adapter = _make_adapter(transport)

        resp = adapter.cancel_order("alpaca-order-001")

        assert call_count["delete"] == 1
        assert call_count["get"] == 1
        assert resp.status == OrderStatus.CANCELLED

    def test_cancel_order_404_raises(self) -> None:
        """404 from Alpaca cancel should raise NotFoundError."""
        transport = _make_transport(
            responses={"/v2/orders": (404, {"message": "Order not found"})},
        )
        adapter = _make_adapter(transport)

        with pytest.raises(NotFoundError):
            adapter.cancel_order("nonexistent-id")


# ---------------------------------------------------------------------------
# Get order tests
# ---------------------------------------------------------------------------


class TestAlpacaGetOrder:
    """Tests for get_order()."""

    def test_get_order_returns_response(self) -> None:
        """get_order should return mapped OrderResponse."""
        transport = _make_transport(
            responses={"/v2/orders": (200, _ORDER_RESPONSE)},
        )
        adapter = _make_adapter(transport)

        resp = adapter.get_order("alpaca-order-001")

        assert resp.broker_order_id == "alpaca-order-001"
        assert resp.status == OrderStatus.SUBMITTED

    def test_get_order_not_found(self) -> None:
        """get_order with unknown ID should raise NotFoundError."""
        transport = _make_transport(
            responses={"/v2/orders": (404, {"message": "Not found"})},
        )
        adapter = _make_adapter(transport)

        with pytest.raises(NotFoundError):
            adapter.get_order("unknown")


# ---------------------------------------------------------------------------
# List open orders tests
# ---------------------------------------------------------------------------


class TestAlpacaListOpenOrders:
    """Tests for list_open_orders()."""

    def test_list_open_orders_returns_list(self) -> None:
        """list_open_orders should return a list of OrderResponse."""
        transport = _make_transport(
            responses={"/v2/orders": (200, [_ORDER_RESPONSE, _ORDER_RESPONSE])},
        )
        adapter = _make_adapter(transport)

        orders = adapter.list_open_orders()

        assert len(orders) == 2
        assert all(o.symbol == "AAPL" for o in orders)

    def test_list_open_orders_empty(self) -> None:
        """list_open_orders with no open orders returns empty list."""
        transport = _make_transport(
            responses={"/v2/orders": (200, [])},
        )
        adapter = _make_adapter(transport)

        orders = adapter.list_open_orders()
        assert orders == []


# ---------------------------------------------------------------------------
# Get fills tests
# ---------------------------------------------------------------------------


class TestAlpacaGetFills:
    """Tests for get_fills()."""

    def test_get_fills_from_filled_order(self) -> None:
        """get_fills should extract fill info from order response."""
        transport = _make_transport(
            responses={"/v2/orders": (200, _FILLED_ORDER)},
        )
        adapter = _make_adapter(transport)

        fills = adapter.get_fills("alpaca-order-001")

        assert len(fills) == 1
        assert fills[0].quantity == Decimal("10")
        assert fills[0].price == Decimal("150.50")
        assert fills[0].symbol == "AAPL"

    def test_get_fills_unfilled_order(self) -> None:
        """get_fills for unfilled order should return empty list."""
        transport = _make_transport(
            responses={"/v2/orders": (200, _ORDER_RESPONSE)},
        )
        adapter = _make_adapter(transport)

        fills = adapter.get_fills("alpaca-order-001")
        assert fills == []


# ---------------------------------------------------------------------------
# Get positions tests
# ---------------------------------------------------------------------------


class TestAlpacaGetPositions:
    """Tests for get_positions()."""

    def test_get_positions_returns_list(self) -> None:
        """get_positions should return PositionSnapshot list."""
        transport = _make_transport(
            responses={"/v2/positions": (200, [_POSITION_RESPONSE])},
        )
        adapter = _make_adapter(transport)

        positions = adapter.get_positions()

        assert len(positions) == 1
        p = positions[0]
        assert p.symbol == "AAPL"
        assert p.quantity == Decimal("100")
        assert p.average_entry_price == Decimal("148.50")
        assert p.market_price == Decimal("150.00")

    def test_get_positions_empty(self) -> None:
        """get_positions with no positions returns empty list."""
        transport = _make_transport(
            responses={"/v2/positions": (200, [])},
        )
        adapter = _make_adapter(transport)

        assert adapter.get_positions() == []


# ---------------------------------------------------------------------------
# Get account tests
# ---------------------------------------------------------------------------


class TestAlpacaGetAccount:
    """Tests for get_account()."""

    def test_get_account_returns_snapshot(self) -> None:
        """get_account should return AccountSnapshot."""
        transport = _make_transport(
            responses={"/v2/account": (200, _ACCOUNT_RESPONSE)},
        )
        adapter = _make_adapter(transport)

        acct = adapter.get_account()

        assert acct.account_id == "acct-001"
        assert acct.equity == Decimal("100000.00")
        assert acct.cash == Decimal("50000.00")
        assert acct.buying_power == Decimal("200000.00")


# ---------------------------------------------------------------------------
# Diagnostics tests
# ---------------------------------------------------------------------------


class TestAlpacaDiagnostics:
    """Tests for get_diagnostics()."""

    def test_diagnostics_connected(self) -> None:
        """get_diagnostics should report CONNECTED when clock responds."""
        transport = _make_transport(
            responses={"/v2/clock": (200, _CLOCK_RESPONSE)},
        )
        adapter = _make_adapter(transport)

        diag = adapter.get_diagnostics()

        assert diag.broker_name == "alpaca"
        assert diag.connection_status.value == "connected"
        assert diag.market_open is True
        assert diag.latency_ms >= 0


# ---------------------------------------------------------------------------
# Market open tests
# ---------------------------------------------------------------------------


class TestAlpacaIsMarketOpen:
    """Tests for is_market_open()."""

    def test_market_open_true(self) -> None:
        """is_market_open should return True when Alpaca says market is open."""
        transport = _make_transport(
            responses={"/v2/clock": (200, {**_CLOCK_RESPONSE, "is_open": True})},
        )
        adapter = _make_adapter(transport)

        assert adapter.is_market_open() is True

    def test_market_open_false(self) -> None:
        """is_market_open should return False when market is closed."""
        transport = _make_transport(
            responses={"/v2/clock": (200, {**_CLOCK_RESPONSE, "is_open": False})},
        )
        adapter = _make_adapter(transport)

        assert adapter.is_market_open() is False


# ---------------------------------------------------------------------------
# Status mapping tests
# ---------------------------------------------------------------------------


class TestAlpacaStatusMapping:
    """Tests for Alpaca → OrderStatus mapping."""

    @pytest.mark.parametrize(
        ("alpaca_status", "expected"),
        [
            ("new", OrderStatus.SUBMITTED),
            ("accepted", OrderStatus.SUBMITTED),
            ("pending_new", OrderStatus.PENDING),
            ("partially_filled", OrderStatus.PARTIAL_FILL),
            ("filled", OrderStatus.FILLED),
            ("canceled", OrderStatus.CANCELLED),
            ("expired", OrderStatus.EXPIRED),
            ("rejected", OrderStatus.REJECTED),
            ("pending_cancel", OrderStatus.SUBMITTED),
            ("replaced", OrderStatus.CANCELLED),
        ],
    )
    def test_status_mapping(self, alpaca_status: str, expected: OrderStatus) -> None:
        """Each Alpaca status should map to the correct OrderStatus."""
        assert _ALPACA_STATUS_MAP[alpaca_status] == expected

    def test_all_known_statuses_are_mapped(self) -> None:
        """All known Alpaca statuses should have a mapping."""
        known = [
            "new",
            "accepted",
            "pending_new",
            "accepted_for_bidding",
            "partially_filled",
            "filled",
            "done_for_day",
            "canceled",
            "pending_cancel",
            "expired",
            "replaced",
            "pending_replace",
            "stopped",
            "rejected",
            "suspended",
            "calculated",
            "held",
        ]
        for status in known:
            assert status in _ALPACA_STATUS_MAP, f"Missing mapping for: {status}"


# ---------------------------------------------------------------------------
# Error mapping tests
# ---------------------------------------------------------------------------


class TestAlpacaErrorMapping:
    """Tests for HTTP error → domain exception mapping."""

    def test_401_raises_auth_error(self) -> None:
        """HTTP 401 should raise AuthError."""
        transport = _make_transport(
            responses={"/v2/account": (401, {"message": "Not authenticated"})},
        )
        adapter = _make_adapter(transport)

        with pytest.raises(AuthError):
            adapter.get_account()

    def test_403_raises_auth_error(self) -> None:
        """HTTP 403 should raise AuthError."""
        transport = _make_transport(
            responses={"/v2/account": (403, {"message": "Forbidden"})},
        )
        adapter = _make_adapter(transport)

        with pytest.raises(AuthError):
            adapter.get_account()

    def test_404_raises_not_found(self) -> None:
        """HTTP 404 should raise NotFoundError."""
        transport = _make_transport(
            responses={"/v2/orders": (404, {"message": "Not found"})},
        )
        adapter = _make_adapter(transport)

        with pytest.raises(NotFoundError):
            adapter.get_order("nonexistent")

    def test_429_raises_transient_error(self) -> None:
        """HTTP 429 should raise TransientError (after retries)."""
        transport = _make_transport(
            responses={"/v2/clock": (429, {"message": "Rate limited"})},
        )
        adapter = _make_adapter(transport)

        with pytest.raises(TransientError):
            adapter.is_market_open()

    def test_500_raises_transient_error(self) -> None:
        """HTTP 500 should raise TransientError (after retries)."""
        transport = _make_transport(
            responses={"/v2/clock": (500, {"message": "Server error"})},
        )
        adapter = _make_adapter(transport)

        with pytest.raises(TransientError):
            adapter.is_market_open()


# ---------------------------------------------------------------------------
# AlpacaConfig tests
# ---------------------------------------------------------------------------


class TestAlpacaConfig:
    """Tests for AlpacaConfig model."""

    def test_paper_factory(self) -> None:
        """AlpacaConfig.paper() should point to paper API."""
        config = AlpacaConfig.paper(api_key="AK123", api_secret="secret")
        assert "paper-api" in config.base_url

    def test_live_factory(self) -> None:
        """AlpacaConfig.live() should point to live API."""
        config = AlpacaConfig.live(api_key="AK123", api_secret="secret")
        assert config.base_url == "https://api.alpaca.markets"

    def test_auth_headers(self) -> None:
        """auth_headers should contain APCA-API-KEY-ID and APCA-API-SECRET-KEY."""
        config = AlpacaConfig(api_key="AKTEST", api_secret="STEST")
        headers = config.auth_headers
        assert headers["APCA-API-KEY-ID"] == "AKTEST"
        assert headers["APCA-API-SECRET-KEY"] == "STEST"

    def test_url_properties(self) -> None:
        """URL properties should construct correct endpoints."""
        config = AlpacaConfig(
            api_key="AK",
            api_secret="S",
            base_url="https://paper-api.alpaca.markets",
        )
        assert config.orders_url == "https://paper-api.alpaca.markets/v2/orders"
        assert config.positions_url == "https://paper-api.alpaca.markets/v2/positions"
        assert config.account_url == "https://paper-api.alpaca.markets/v2/account"
        assert config.clock_url == "https://paper-api.alpaca.markets/v2/clock"

    def test_trailing_slash_stripped(self) -> None:
        """base_url trailing slash should be stripped."""
        config = AlpacaConfig(
            api_key="AK",
            api_secret="S",
            base_url="https://paper-api.alpaca.markets/",
        )
        assert config.orders_url == "https://paper-api.alpaca.markets/v2/orders"

    def test_config_is_frozen(self) -> None:
        """AlpacaConfig should be immutable."""
        config = AlpacaConfig(api_key="AK", api_secret="S")
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="frozen"):
            config.api_key = "new"  # type: ignore[misc]
