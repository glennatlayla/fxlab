"""
Unit tests for SchwabBrokerAdapter (M4 — Multi-Broker Expansion).

Tests cover:
- connect(): creates httpx client, validates via account endpoint
- disconnect(): closes client, idempotent
- submit_order(): POST to orders endpoint, status mapping
- cancel_order(): DELETE to orders endpoint, refetch after 200
- get_order(): GET order by broker ID
- list_open_orders(): GET orders with status filter
- get_fills(): extract fill info from order response
- get_positions(): GET account with positions field
- get_account(): GET account snapshot
- get_diagnostics(): latency, connection status
- is_market_open(): GET market hours
- Error mapping: 401→AuthError, 404→NotFoundError, 429/5xx→TransientError
- Schwab order status → OrderStatus mapping
- OAuth Bearer token injection via SchwabOAuthManager

Dependencies:
    - services.api.adapters.schwab_broker_adapter: SchwabBrokerAdapter
    - libs.contracts.schwab_config: SchwabConfig
    - services.api.infrastructure.schwab_auth: SchwabOAuthManager
    - httpx: MockTransport for request interception
    - libs.contracts.errors: domain exceptions

Example:
    pytest tests/unit/test_schwab_broker_adapter.py -v
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from libs.contracts.errors import AuthError, ExternalServiceError, NotFoundError, TransientError
from libs.contracts.execution import (
    OrderRequest,
    OrderSide,
    OrderStatus,
)
from libs.contracts.schwab_config import SchwabConfig

# Import will fail until implementation exists — that's expected for RED phase.
# Tests should be written to the expected interface.
from services.api.adapters.schwab_broker_adapter import (
    _SCHWAB_STATUS_MAP,
    SchwabBrokerAdapter,
)
from services.api.infrastructure.schwab_auth import SchwabOAuthManager
from services.api.infrastructure.timeout_config import BrokerTimeoutConfig

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_TEST_CONFIG = SchwabConfig(
    client_id="test-client-id",
    client_secret="test-client-secret",
    redirect_uri="https://localhost/callback",
    account_hash="TEST_ACCT_HASH",
)

_ACCOUNT_RESPONSE: dict[str, Any] = {
    "securitiesAccount": {
        "type": "MARGIN",
        "accountNumber": "123456789",
        "currentBalances": {
            "liquidationValue": "100000.00",
            "cashBalance": "50000.00",
            "buyingPower": "200000.00",
            "availableFunds": "75000.00",
        },
        "positions": [
            {
                "instrument": {
                    "symbol": "AAPL",
                    "assetType": "EQUITY",
                },
                "longQuantity": 100.0,
                "averagePrice": 148.50,
                "marketValue": 15000.00,
                "currentDayProfitLoss": 150.00,
                "currentDayProfitLossPercentage": 1.01,
                "longOpenProfitLoss": 150.00,
            }
        ],
    }
}

_ACCOUNT_NO_POSITIONS: dict[str, Any] = {
    "securitiesAccount": {
        "type": "MARGIN",
        "accountNumber": "123456789",
        "currentBalances": {
            "liquidationValue": "100000.00",
            "cashBalance": "50000.00",
            "buyingPower": "200000.00",
            "availableFunds": "75000.00",
        },
    }
}

_ORDER_RESPONSE: dict[str, Any] = {
    "orderId": 12345678,
    "cancelable": True,
    "editable": False,
    "status": "WORKING",
    "enteredTime": "2026-04-11T14:00:00+0000",
    "closeTime": None,
    "tag": "API_TOS:test-order-001",
    "accountNumber": 123456789,
    "orderActivityCollection": [],
    "orderLegCollection": [
        {
            "orderLegType": "EQUITY",
            "legId": 1,
            "instrument": {
                "symbol": "AAPL",
                "assetType": "EQUITY",
            },
            "instruction": "BUY",
            "quantity": 10.0,
            "positionEffect": "OPENING",
        }
    ],
    "orderStrategyType": "SINGLE",
    "orderType": "MARKET",
    "session": "NORMAL",
    "duration": "DAY",
    "quantity": 10.0,
    "filledQuantity": 0.0,
    "remainingQuantity": 10.0,
    "price": None,
    "stopPrice": None,
}

_FILLED_ORDER: dict[str, Any] = {
    **_ORDER_RESPONSE,
    "status": "FILLED",
    "filledQuantity": 10.0,
    "remainingQuantity": 0.0,
    "closeTime": "2026-04-11T14:01:00+0000",
    "orderActivityCollection": [
        {
            "activityType": "EXECUTION",
            "executionType": "FILL",
            "quantity": 10.0,
            "orderRemainingQuantity": 0.0,
            "executionLegs": [
                {
                    "legId": 1,
                    "price": 150.50,
                    "quantity": 10.0,
                    "time": "2026-04-11T14:01:00+0000",
                }
            ],
        }
    ],
}

_CANCELLED_ORDER: dict[str, Any] = {
    **_ORDER_RESPONSE,
    "status": "CANCELED",
    "cancelable": False,
    "closeTime": "2026-04-11T14:02:00+0000",
}

_MARKET_HOURS_RESPONSE: dict[str, Any] = {
    "equity": {
        "EQ": {
            "date": "2026-04-11",
            "marketType": "EQUITY",
            "isOpen": True,
            "sessionHours": {
                "regularMarket": [
                    {
                        "start": "2026-04-11T09:30:00-04:00",
                        "end": "2026-04-11T16:00:00-04:00",
                    }
                ]
            },
        }
    }
}

_MARKET_HOURS_CLOSED: dict[str, Any] = {
    "equity": {
        "EQ": {
            "date": "2026-04-11",
            "marketType": "EQUITY",
            "isOpen": False,
        }
    }
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_oauth_manager(access_token: str = "test-bearer-token") -> MagicMock:
    """Create a mock SchwabOAuthManager that returns a fixed access token."""
    mock = MagicMock(spec=SchwabOAuthManager)
    mock.get_access_token.return_value = access_token
    mock.is_initialized = True
    return mock


def _make_transport(
    *,
    responses: dict[str, tuple[int, Any]] | None = None,
    default_status: int = 200,
    default_body: Any = None,
) -> httpx.MockTransport:
    """
    Create a mock transport that returns configured responses by URL path.

    Args:
        responses: Dict mapping URL path fragment → (status_code, response_body).
        default_status: Default HTTP status for unmatched paths.
        default_body: Default response body for unmatched paths.

    Returns:
        httpx.MockTransport instance.
    """
    resp_map = responses or {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = str(request.url)
        for key, (status, body) in resp_map.items():
            if key in path:
                content = json.dumps(body) if isinstance(body, (dict, list)) else body
                return httpx.Response(
                    status, content=content, headers={"content-type": "application/json"}
                )
        body_content = json.dumps(default_body) if default_body else "{}"
        return httpx.Response(
            default_status, content=body_content, headers={"content-type": "application/json"}
        )

    return httpx.MockTransport(handler)


def _make_adapter(
    transport: httpx.MockTransport | None = None,
    oauth_manager: MagicMock | None = None,
) -> SchwabBrokerAdapter:
    """Create a SchwabBrokerAdapter with mock transport pre-connected."""
    oauth = oauth_manager or _make_oauth_manager()
    adapter = SchwabBrokerAdapter(config=_TEST_CONFIG, oauth_manager=oauth)

    if transport is not None:
        adapter._client = httpx.Client(
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
        "execution_mode": "live",
    }
    defaults.update(overrides)
    return OrderRequest(**defaults)


# ---------------------------------------------------------------------------
# Connect / Disconnect tests
# ---------------------------------------------------------------------------


class TestSchwabConnect:
    """Tests for connect() and disconnect() lifecycle."""

    def test_connect_creates_client(self) -> None:
        """connect() should create an httpx client and validate via account endpoint."""
        transport = _make_transport(
            responses={"accounts": (200, _ACCOUNT_NO_POSITIONS)},
        )
        oauth = _make_oauth_manager()
        adapter = SchwabBrokerAdapter(config=_TEST_CONFIG, oauth_manager=oauth)

        # Inject mock transport via patching httpx.Client
        mock_client = httpx.Client(transport=transport)
        with patch.object(httpx, "Client", return_value=mock_client):
            adapter.connect()

        assert adapter._client is not None

    def test_connect_idempotent(self) -> None:
        """Calling connect() twice should be a no-op."""
        transport = _make_transport(
            responses={"accounts": (200, _ACCOUNT_NO_POSITIONS)},
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
        adapter = SchwabBrokerAdapter(config=_TEST_CONFIG, oauth_manager=_make_oauth_manager())
        adapter.disconnect()
        adapter.disconnect()

    def test_get_timeout_config_returns_config(self) -> None:
        """get_timeout_config() should return the configured timeouts."""
        custom = BrokerTimeoutConfig(order_timeout_s=20.0)
        adapter = SchwabBrokerAdapter(
            config=_TEST_CONFIG,
            oauth_manager=_make_oauth_manager(),
            timeout_config=custom,
        )
        assert adapter.get_timeout_config().order_timeout_s == 20.0


# ---------------------------------------------------------------------------
# OAuth Bearer token injection tests
# ---------------------------------------------------------------------------


class TestSchwabOAuthInjection:
    """Tests verifying OAuth Bearer token is injected into requests."""

    def test_submit_order_includes_bearer_token(self) -> None:
        """submit_order should include Authorization: Bearer header."""
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                201,
                content=json.dumps(_ORDER_RESPONSE),
                headers={"content-type": "application/json"},
            )

        transport = httpx.MockTransport(handler)
        oauth = _make_oauth_manager(access_token="my-bearer-token-abc")
        adapter = _make_adapter(transport, oauth)

        adapter.submit_order(_make_order_request())

        assert len(captured) >= 1
        auth_header = captured[0].headers.get("authorization", "")
        assert auth_header == "Bearer my-bearer-token-abc"

    def test_get_account_includes_bearer_token(self) -> None:
        """get_account should include Authorization: Bearer header."""
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                200,
                content=json.dumps(_ACCOUNT_RESPONSE),
                headers={"content-type": "application/json"},
            )

        transport = httpx.MockTransport(handler)
        oauth = _make_oauth_manager(access_token="bearer-for-account")
        adapter = _make_adapter(transport, oauth)

        adapter.get_account()

        assert len(captured) >= 1
        auth_header = captured[0].headers.get("authorization", "")
        assert auth_header == "Bearer bearer-for-account"


# ---------------------------------------------------------------------------
# Order submission tests
# ---------------------------------------------------------------------------


class TestSchwabSubmitOrder:
    """Tests for submit_order()."""

    def test_submit_order_happy_path(self) -> None:
        """submit_order should POST to orders endpoint and return OrderResponse."""
        transport = _make_transport(
            responses={"orders": (201, _ORDER_RESPONSE)},
        )
        adapter = _make_adapter(transport)

        resp = adapter.submit_order(_make_order_request())

        assert resp.client_order_id == "test-order-001"
        assert resp.broker_order_id == "12345678"
        assert resp.symbol == "AAPL"
        assert resp.side == OrderSide.BUY
        assert resp.status == OrderStatus.SUBMITTED  # WORKING maps to SUBMITTED

    def test_submit_order_filled_status(self) -> None:
        """A filled order response should map to OrderStatus.FILLED."""
        transport = _make_transport(
            responses={"orders": (201, _FILLED_ORDER)},
        )
        adapter = _make_adapter(transport)

        resp = adapter.submit_order(_make_order_request())

        assert resp.status == OrderStatus.FILLED
        assert resp.filled_quantity == Decimal("10")

    def test_submit_order_not_connected_raises(self) -> None:
        """submit_order without connect() should raise ExternalServiceError."""
        adapter = SchwabBrokerAdapter(config=_TEST_CONFIG, oauth_manager=_make_oauth_manager())

        with pytest.raises(ExternalServiceError, match="not connected"):
            adapter.submit_order(_make_order_request())

    def test_submit_order_auth_failure(self) -> None:
        """401 from Schwab should raise AuthError."""
        transport = _make_transport(
            responses={"orders": (401, {"error": "Unauthorized"})},
        )
        adapter = _make_adapter(transport)

        with pytest.raises(AuthError, match="authentication failed"):
            adapter.submit_order(_make_order_request())

    def test_submit_order_limit_order(self) -> None:
        """submit_order with limit price should include price in payload."""
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                201,
                content=json.dumps(_ORDER_RESPONSE),
                headers={"content-type": "application/json"},
            )

        transport = httpx.MockTransport(handler)
        adapter = _make_adapter(transport)

        adapter.submit_order(
            _make_order_request(
                order_type="limit",
                limit_price=Decimal("150.00"),
            )
        )

        assert len(captured) >= 1
        body = json.loads(captured[0].content.decode())
        assert "price" in body
        assert body["price"] == "150.00"


# ---------------------------------------------------------------------------
# Cancel order tests
# ---------------------------------------------------------------------------


class TestSchwabCancelOrder:
    """Tests for cancel_order()."""

    def test_cancel_order_success(self) -> None:
        """cancel_order with 200 response should return cancelled status."""
        call_count = {"delete": 0, "get": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "DELETE":
                call_count["delete"] += 1
                return httpx.Response(200, content="")
            if request.method == "GET" and "orders" in str(request.url):
                call_count["get"] += 1
                return httpx.Response(
                    200,
                    content=json.dumps(_CANCELLED_ORDER),
                    headers={"content-type": "application/json"},
                )
            return httpx.Response(200, content="{}")

        transport = httpx.MockTransport(handler)
        adapter = _make_adapter(transport)

        resp = adapter.cancel_order("12345678")

        assert call_count["delete"] == 1
        assert resp.status == OrderStatus.CANCELLED

    def test_cancel_order_404_raises(self) -> None:
        """404 from Schwab cancel should raise NotFoundError."""
        transport = _make_transport(
            responses={"orders": (404, {"error": "Order not found"})},
        )
        adapter = _make_adapter(transport)

        with pytest.raises(NotFoundError):
            adapter.cancel_order("nonexistent-id")


# ---------------------------------------------------------------------------
# Get order tests
# ---------------------------------------------------------------------------


class TestSchwabGetOrder:
    """Tests for get_order()."""

    def test_get_order_returns_response(self) -> None:
        """get_order should return mapped OrderResponse."""
        transport = _make_transport(
            responses={"orders": (200, _ORDER_RESPONSE)},
        )
        adapter = _make_adapter(transport)

        resp = adapter.get_order("12345678")

        assert resp.broker_order_id == "12345678"
        assert resp.status == OrderStatus.SUBMITTED

    def test_get_order_not_found(self) -> None:
        """get_order with unknown ID should raise NotFoundError."""
        transport = _make_transport(
            responses={"orders": (404, {"error": "Not found"})},
        )
        adapter = _make_adapter(transport)

        with pytest.raises(NotFoundError):
            adapter.get_order("unknown")


# ---------------------------------------------------------------------------
# List open orders tests
# ---------------------------------------------------------------------------


class TestSchwabListOpenOrders:
    """Tests for list_open_orders()."""

    def test_list_open_orders_returns_list(self) -> None:
        """list_open_orders should return a list of OrderResponse."""
        transport = _make_transport(
            responses={"orders": (200, [_ORDER_RESPONSE, _ORDER_RESPONSE])},
        )
        adapter = _make_adapter(transport)

        orders = adapter.list_open_orders()

        assert len(orders) == 2
        assert all(o.symbol == "AAPL" for o in orders)

    def test_list_open_orders_empty(self) -> None:
        """list_open_orders with no open orders returns empty list."""
        transport = _make_transport(
            responses={"orders": (200, [])},
        )
        adapter = _make_adapter(transport)

        orders = adapter.list_open_orders()
        assert orders == []


# ---------------------------------------------------------------------------
# Get fills tests
# ---------------------------------------------------------------------------


class TestSchwabGetFills:
    """Tests for get_fills()."""

    def test_get_fills_from_filled_order(self) -> None:
        """get_fills should extract fill info from order activity collection."""
        transport = _make_transport(
            responses={"orders": (200, _FILLED_ORDER)},
        )
        adapter = _make_adapter(transport)

        fills = adapter.get_fills("12345678")

        assert len(fills) >= 1
        assert fills[0].quantity == Decimal("10")
        assert fills[0].price == Decimal("150.50")
        assert fills[0].symbol == "AAPL"

    def test_get_fills_unfilled_order(self) -> None:
        """get_fills for unfilled order should return empty list."""
        transport = _make_transport(
            responses={"orders": (200, _ORDER_RESPONSE)},
        )
        adapter = _make_adapter(transport)

        fills = adapter.get_fills("12345678")
        assert fills == []


# ---------------------------------------------------------------------------
# Get positions tests
# ---------------------------------------------------------------------------


class TestSchwabGetPositions:
    """Tests for get_positions()."""

    def test_get_positions_returns_list(self) -> None:
        """get_positions should return PositionSnapshot list."""
        transport = _make_transport(
            responses={"positions": (200, _ACCOUNT_RESPONSE)},
        )
        adapter = _make_adapter(transport)

        positions = adapter.get_positions()

        assert len(positions) == 1
        p = positions[0]
        assert p.symbol == "AAPL"
        assert p.quantity == Decimal("100")
        assert p.average_entry_price == Decimal("148.50")

    def test_get_positions_empty(self) -> None:
        """get_positions with no positions returns empty list."""
        transport = _make_transport(
            responses={"positions": (200, _ACCOUNT_NO_POSITIONS)},
        )
        adapter = _make_adapter(transport)

        positions = adapter.get_positions()
        assert positions == []


# ---------------------------------------------------------------------------
# Get account tests
# ---------------------------------------------------------------------------


class TestSchwabGetAccount:
    """Tests for get_account()."""

    def test_get_account_returns_snapshot(self) -> None:
        """get_account should return AccountSnapshot."""
        transport = _make_transport(
            responses={"accounts": (200, _ACCOUNT_RESPONSE)},
        )
        adapter = _make_adapter(transport)

        acct = adapter.get_account()

        assert acct.account_id == "123456789"
        assert acct.equity == Decimal("100000.00")
        assert acct.cash == Decimal("50000.00")
        assert acct.buying_power == Decimal("200000.00")


# ---------------------------------------------------------------------------
# Diagnostics tests
# ---------------------------------------------------------------------------


class TestSchwabDiagnostics:
    """Tests for get_diagnostics()."""

    def test_diagnostics_connected(self) -> None:
        """get_diagnostics should report CONNECTED when account responds."""
        transport = _make_transport(
            responses={"accounts": (200, _ACCOUNT_NO_POSITIONS)},
        )
        adapter = _make_adapter(transport)

        diag = adapter.get_diagnostics()

        assert diag.broker_name == "schwab"
        assert diag.connection_status.value == "connected"
        assert diag.latency_ms >= 0


# ---------------------------------------------------------------------------
# Market open tests
# ---------------------------------------------------------------------------


class TestSchwabIsMarketOpen:
    """Tests for is_market_open()."""

    def test_market_open_true(self) -> None:
        """is_market_open should return True when Schwab says market is open."""
        transport = _make_transport(
            responses={"markets": (200, _MARKET_HOURS_RESPONSE)},
        )
        adapter = _make_adapter(transport)

        assert adapter.is_market_open() is True

    def test_market_open_false(self) -> None:
        """is_market_open should return False when market is closed."""
        transport = _make_transport(
            responses={"markets": (200, _MARKET_HOURS_CLOSED)},
        )
        adapter = _make_adapter(transport)

        assert adapter.is_market_open() is False


# ---------------------------------------------------------------------------
# Status mapping tests
# ---------------------------------------------------------------------------


class TestSchwabStatusMapping:
    """Tests for Schwab → OrderStatus mapping."""

    @pytest.mark.parametrize(
        ("schwab_status", "expected"),
        [
            ("WORKING", OrderStatus.SUBMITTED),
            ("ACCEPTED", OrderStatus.SUBMITTED),
            ("PENDING_ACTIVATION", OrderStatus.PENDING),
            ("QUEUED", OrderStatus.PENDING),
            ("NEW", OrderStatus.PENDING),
            ("AWAITING_PARENT_ORDER", OrderStatus.PENDING),
            ("AWAITING_CONDITION", OrderStatus.PENDING),
            ("FILLED", OrderStatus.FILLED),
            ("CANCELED", OrderStatus.CANCELLED),
            ("PENDING_CANCEL", OrderStatus.SUBMITTED),
            ("REJECTED", OrderStatus.REJECTED),
            ("EXPIRED", OrderStatus.EXPIRED),
            ("REPLACED", OrderStatus.CANCELLED),
            ("PENDING_REPLACE", OrderStatus.SUBMITTED),
        ],
    )
    def test_status_mapping(self, schwab_status: str, expected: OrderStatus) -> None:
        """Each Schwab status should map to the correct OrderStatus."""
        assert _SCHWAB_STATUS_MAP[schwab_status] == expected

    def test_all_known_statuses_are_mapped(self) -> None:
        """All known Schwab statuses should have a mapping."""
        known = [
            "AWAITING_PARENT_ORDER",
            "AWAITING_CONDITION",
            "AWAITING_STOP_CONDITION",
            "AWAITING_MANUAL_REVIEW",
            "ACCEPTED",
            "AWAITING_UR_OUT",
            "PENDING_ACTIVATION",
            "QUEUED",
            "WORKING",
            "REJECTED",
            "PENDING_CANCEL",
            "CANCELED",
            "PENDING_REPLACE",
            "REPLACED",
            "FILLED",
            "EXPIRED",
            "NEW",
            "AWAITING_RELEASE_TIME",
            "PENDING_ACKNOWLEDGEMENT",
            "UNKNOWN",
        ]
        for status in known:
            assert status in _SCHWAB_STATUS_MAP, f"Missing mapping for: {status}"


# ---------------------------------------------------------------------------
# Error mapping tests
# ---------------------------------------------------------------------------


class TestSchwabErrorMapping:
    """Tests for HTTP error → domain exception mapping."""

    def test_401_raises_auth_error(self) -> None:
        """HTTP 401 should raise AuthError."""
        transport = _make_transport(
            responses={"accounts": (401, {"error": "Not authenticated"})},
        )
        adapter = _make_adapter(transport)

        with pytest.raises(AuthError):
            adapter.get_account()

    def test_403_raises_auth_error(self) -> None:
        """HTTP 403 should raise AuthError."""
        transport = _make_transport(
            responses={"accounts": (403, {"error": "Forbidden"})},
        )
        adapter = _make_adapter(transport)

        with pytest.raises(AuthError):
            adapter.get_account()

    def test_404_raises_not_found(self) -> None:
        """HTTP 404 should raise NotFoundError."""
        transport = _make_transport(
            responses={"orders": (404, {"error": "Not found"})},
        )
        adapter = _make_adapter(transport)

        with pytest.raises(NotFoundError):
            adapter.get_order("nonexistent")

    def test_429_raises_transient_error(self) -> None:
        """HTTP 429 should raise TransientError."""
        transport = _make_transport(
            responses={"markets": (429, {"error": "Rate limited"})},
        )
        adapter = _make_adapter(transport)

        with pytest.raises(TransientError):
            adapter.is_market_open()

    def test_500_raises_transient_error(self) -> None:
        """HTTP 500 should raise TransientError."""
        transport = _make_transport(
            responses={"markets": (500, {"error": "Server error"})},
        )
        adapter = _make_adapter(transport)

        with pytest.raises(TransientError):
            adapter.is_market_open()
