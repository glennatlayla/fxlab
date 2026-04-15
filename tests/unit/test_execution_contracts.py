"""
Unit tests for Phase 4 execution contracts (libs/contracts/execution.py).

Covers:
- OrderRequest validation: required fields, conditional validators (limit/stop price),
  positive quantity, frozen model
- OrderResponse serialization roundtrip
- OrderFillEvent validation: positive price and quantity
- OrderEvent structure
- PositionSnapshot and AccountSnapshot field constraints
- AdapterDiagnostics non-negative fields
- All enum values are accessible and stable
- Pydantic model_config frozen enforcement

Per M0 spec: "Unit tests for all schemas (validation, serialization roundtrip)"
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from libs.contracts.execution import (
    AccountSnapshot,
    AdapterDiagnostics,
    ConnectionStatus,
    ExecutionMode,
    OrderEvent,
    OrderFillEvent,
    OrderRequest,
    OrderResponse,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    TimeInForce,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def market_buy_request() -> OrderRequest:
    """Valid market buy order request."""
    return OrderRequest(
        client_order_id="ord-001",
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("100"),
        time_in_force=TimeInForce.DAY,
        deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
        strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
        correlation_id="corr-001",
        execution_mode=ExecutionMode.PAPER,
    )


@pytest.fixture()
def limit_buy_request() -> OrderRequest:
    """Valid limit buy order request."""
    return OrderRequest(
        client_order_id="ord-002",
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("50"),
        limit_price=Decimal("175.00"),
        time_in_force=TimeInForce.GTC,
        deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
        strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
        correlation_id="corr-002",
        execution_mode=ExecutionMode.LIVE,
    )


NOW = datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestOrderSide:
    """Verify OrderSide enum values are stable."""

    def test_enum_values(self) -> None:
        assert OrderSide.BUY == "buy"
        assert OrderSide.SELL == "sell"

    def test_enum_membership(self) -> None:
        assert len(OrderSide) == 2


class TestOrderType:
    """Verify OrderType enum values are stable."""

    def test_enum_values(self) -> None:
        assert OrderType.MARKET == "market"
        assert OrderType.LIMIT == "limit"
        assert OrderType.STOP == "stop"
        assert OrderType.STOP_LIMIT == "stop_limit"

    def test_enum_membership(self) -> None:
        assert len(OrderType) == 4


class TestTimeInForce:
    """Verify TimeInForce enum values are stable."""

    def test_enum_values(self) -> None:
        assert TimeInForce.DAY == "day"
        assert TimeInForce.GTC == "gtc"
        assert TimeInForce.IOC == "ioc"
        assert TimeInForce.FOK == "fok"


class TestOrderStatus:
    """Verify OrderStatus enum lifecycle states."""

    def test_all_states_present(self) -> None:
        expected = {
            "pending",
            "submitted",
            "partial_fill",
            "filled",
            "cancelled",
            "rejected",
            "expired",
        }
        actual = {s.value for s in OrderStatus}
        assert actual == expected

    def test_terminal_states(self) -> None:
        """Terminal states should include filled, cancelled, rejected, expired."""
        terminal = {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }
        assert len(terminal) == 4


class TestExecutionMode:
    """Verify ExecutionMode enum values."""

    def test_enum_values(self) -> None:
        assert ExecutionMode.SHADOW == "shadow"
        assert ExecutionMode.PAPER == "paper"
        assert ExecutionMode.LIVE == "live"


class TestConnectionStatus:
    """Verify ConnectionStatus enum values."""

    def test_enum_values(self) -> None:
        assert ConnectionStatus.CONNECTED == "connected"
        assert ConnectionStatus.DISCONNECTED == "disconnected"
        assert ConnectionStatus.RECONNECTING == "reconnecting"
        assert ConnectionStatus.ERROR == "error"


# ---------------------------------------------------------------------------
# OrderRequest tests
# ---------------------------------------------------------------------------


class TestOrderRequest:
    """OrderRequest validation and serialization tests."""

    def test_valid_market_order(self, market_buy_request: OrderRequest) -> None:
        assert market_buy_request.client_order_id == "ord-001"
        assert market_buy_request.symbol == "AAPL"
        assert market_buy_request.side == OrderSide.BUY
        assert market_buy_request.order_type == OrderType.MARKET
        assert market_buy_request.quantity == Decimal("100")
        assert market_buy_request.limit_price is None
        assert market_buy_request.stop_price is None

    def test_valid_limit_order(self, limit_buy_request: OrderRequest) -> None:
        assert limit_buy_request.limit_price == Decimal("175.00")
        assert limit_buy_request.order_type == OrderType.LIMIT

    def test_valid_stop_order(self) -> None:
        req = OrderRequest(
            client_order_id="ord-003",
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.STOP,
            quantity=Decimal("50"),
            stop_price=Decimal("170.00"),
            deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
            strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
            correlation_id="corr-003",
            execution_mode=ExecutionMode.PAPER,
        )
        assert req.stop_price == Decimal("170.00")

    def test_valid_stop_limit_order(self) -> None:
        req = OrderRequest(
            client_order_id="ord-004",
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.STOP_LIMIT,
            quantity=Decimal("50"),
            limit_price=Decimal("169.00"),
            stop_price=Decimal("170.00"),
            deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
            strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
            correlation_id="corr-004",
            execution_mode=ExecutionMode.PAPER,
        )
        assert req.limit_price == Decimal("169.00")
        assert req.stop_price == Decimal("170.00")

    def test_limit_order_without_limit_price_raises(self) -> None:
        with pytest.raises(ValidationError, match="limit_price is required"):
            OrderRequest(
                client_order_id="ord-bad",
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("100"),
                deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
                strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
                correlation_id="corr-bad",
                execution_mode=ExecutionMode.PAPER,
            )

    def test_stop_order_without_stop_price_raises(self) -> None:
        with pytest.raises(ValidationError, match="stop_price is required"):
            OrderRequest(
                client_order_id="ord-bad",
                symbol="AAPL",
                side=OrderSide.SELL,
                order_type=OrderType.STOP,
                quantity=Decimal("100"),
                deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
                strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
                correlation_id="corr-bad",
                execution_mode=ExecutionMode.PAPER,
            )

    def test_stop_limit_order_requires_both_prices(self) -> None:
        # Missing limit_price
        with pytest.raises(ValidationError, match="limit_price is required"):
            OrderRequest(
                client_order_id="ord-bad",
                symbol="AAPL",
                side=OrderSide.SELL,
                order_type=OrderType.STOP_LIMIT,
                quantity=Decimal("100"),
                stop_price=Decimal("170.00"),
                deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
                strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
                correlation_id="corr-bad",
                execution_mode=ExecutionMode.PAPER,
            )

    def test_zero_quantity_raises(self) -> None:
        with pytest.raises(ValidationError, match="greater than"):
            OrderRequest(
                client_order_id="ord-bad",
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("0"),
                deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
                strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
                correlation_id="corr-bad",
                execution_mode=ExecutionMode.PAPER,
            )

    def test_negative_quantity_raises(self) -> None:
        with pytest.raises(ValidationError, match="greater than"):
            OrderRequest(
                client_order_id="ord-bad",
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("-10"),
                deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
                strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
                correlation_id="corr-bad",
                execution_mode=ExecutionMode.PAPER,
            )

    def test_empty_client_order_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            OrderRequest(
                client_order_id="",
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("100"),
                deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
                strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
                correlation_id="corr-bad",
                execution_mode=ExecutionMode.PAPER,
            )

    def test_frozen_model_rejects_mutation(self, market_buy_request: OrderRequest) -> None:
        with pytest.raises(ValidationError):
            market_buy_request.quantity = Decimal("200")  # type: ignore[misc]

    def test_serialization_roundtrip(self, market_buy_request: OrderRequest) -> None:
        data = market_buy_request.model_dump()
        restored = OrderRequest(**data)
        assert restored == market_buy_request

    def test_json_roundtrip(self, market_buy_request: OrderRequest) -> None:
        json_str = market_buy_request.model_dump_json()
        restored = OrderRequest.model_validate_json(json_str)
        assert restored.client_order_id == market_buy_request.client_order_id
        assert restored.quantity == market_buy_request.quantity

    def test_default_metadata_is_empty_dict(self, market_buy_request: OrderRequest) -> None:
        assert market_buy_request.metadata == {}

    def test_metadata_preserved(self) -> None:
        req = OrderRequest(
            client_order_id="ord-meta",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
            strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
            correlation_id="corr-meta",
            execution_mode=ExecutionMode.PAPER,
            metadata={"signal": "crossover", "regime": "bull"},
        )
        assert req.metadata["signal"] == "crossover"


# ---------------------------------------------------------------------------
# OrderResponse tests
# ---------------------------------------------------------------------------


class TestOrderResponse:
    """OrderResponse serialization and field tests."""

    def test_valid_filled_response(self) -> None:
        resp = OrderResponse(
            client_order_id="ord-001",
            broker_order_id="BROKER-12345",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            filled_quantity=Decimal("100"),
            average_fill_price=Decimal("175.50"),
            status=OrderStatus.FILLED,
            time_in_force=TimeInForce.DAY,
            submitted_at=NOW,
            filled_at=NOW,
            correlation_id="corr-001",
            execution_mode=ExecutionMode.PAPER,
        )
        assert resp.status == OrderStatus.FILLED
        assert resp.filled_quantity == Decimal("100")

    def test_default_filled_quantity_is_zero(self) -> None:
        resp = OrderResponse(
            client_order_id="ord-001",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            status=OrderStatus.PENDING,
            time_in_force=TimeInForce.DAY,
            correlation_id="corr-001",
            execution_mode=ExecutionMode.PAPER,
        )
        assert resp.filled_quantity == Decimal("0")

    def test_serialization_roundtrip(self) -> None:
        resp = OrderResponse(
            client_order_id="ord-001",
            broker_order_id="BROKER-12345",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            status=OrderStatus.SUBMITTED,
            time_in_force=TimeInForce.DAY,
            submitted_at=NOW,
            correlation_id="corr-001",
            execution_mode=ExecutionMode.LIVE,
        )
        data = resp.model_dump()
        restored = OrderResponse(**data)
        assert restored.client_order_id == resp.client_order_id


# ---------------------------------------------------------------------------
# OrderFillEvent tests
# ---------------------------------------------------------------------------


class TestOrderFillEvent:
    """OrderFillEvent validation tests."""

    def test_valid_fill(self) -> None:
        fill = OrderFillEvent(
            fill_id="fill-001",
            order_id="ord-001",
            broker_order_id="BROKER-12345",
            symbol="AAPL",
            side=OrderSide.BUY,
            price=Decimal("175.50"),
            quantity=Decimal("50"),
            commission=Decimal("1.00"),
            filled_at=NOW,
            broker_execution_id="exec-001",
            correlation_id="corr-001",
        )
        assert fill.price == Decimal("175.50")
        assert fill.quantity == Decimal("50")

    def test_zero_price_raises(self) -> None:
        with pytest.raises(ValidationError, match="greater than"):
            OrderFillEvent(
                fill_id="fill-bad",
                order_id="ord-001",
                symbol="AAPL",
                side=OrderSide.BUY,
                price=Decimal("0"),
                quantity=Decimal("50"),
                filled_at=NOW,
                correlation_id="corr-bad",
            )

    def test_zero_quantity_raises(self) -> None:
        with pytest.raises(ValidationError, match="greater than"):
            OrderFillEvent(
                fill_id="fill-bad",
                order_id="ord-001",
                symbol="AAPL",
                side=OrderSide.BUY,
                price=Decimal("175.50"),
                quantity=Decimal("0"),
                filled_at=NOW,
                correlation_id="corr-bad",
            )

    def test_default_commission_is_zero(self) -> None:
        fill = OrderFillEvent(
            fill_id="fill-001",
            order_id="ord-001",
            symbol="AAPL",
            side=OrderSide.BUY,
            price=Decimal("175.50"),
            quantity=Decimal("50"),
            filled_at=NOW,
            correlation_id="corr-001",
        )
        assert fill.commission == Decimal("0")


# ---------------------------------------------------------------------------
# OrderEvent tests
# ---------------------------------------------------------------------------


class TestOrderEvent:
    """OrderEvent structure tests."""

    def test_valid_event(self) -> None:
        event = OrderEvent(
            event_id="evt-001",
            order_id="ord-001",
            event_type="submitted",
            timestamp=NOW,
            correlation_id="corr-001",
        )
        assert event.event_type == "submitted"
        assert event.details == {}

    def test_event_with_details(self) -> None:
        event = OrderEvent(
            event_id="evt-002",
            order_id="ord-001",
            event_type="rejected",
            timestamp=NOW,
            details={"reason": "insufficient funds"},
            correlation_id="corr-001",
        )
        assert event.details["reason"] == "insufficient funds"


# ---------------------------------------------------------------------------
# PositionSnapshot tests
# ---------------------------------------------------------------------------


class TestPositionSnapshot:
    """PositionSnapshot validation tests."""

    def test_valid_long_position(self) -> None:
        pos = PositionSnapshot(
            symbol="AAPL",
            quantity=Decimal("100"),
            average_entry_price=Decimal("175.00"),
            market_price=Decimal("180.00"),
            market_value=Decimal("18000.00"),
            unrealized_pnl=Decimal("500.00"),
            realized_pnl=Decimal("0"),
            cost_basis=Decimal("17500.00"),
            updated_at=NOW,
        )
        assert pos.quantity == Decimal("100")
        assert pos.unrealized_pnl == Decimal("500.00")

    def test_short_position_negative_quantity(self) -> None:
        pos = PositionSnapshot(
            symbol="AAPL",
            quantity=Decimal("-50"),
            average_entry_price=Decimal("180.00"),
            market_price=Decimal("175.00"),
            market_value=Decimal("-8750.00"),
            unrealized_pnl=Decimal("250.00"),
            cost_basis=Decimal("9000.00"),
            updated_at=NOW,
        )
        assert pos.quantity < 0


# ---------------------------------------------------------------------------
# AccountSnapshot tests
# ---------------------------------------------------------------------------


class TestAccountSnapshot:
    """AccountSnapshot validation tests."""

    def test_valid_account(self) -> None:
        acct = AccountSnapshot(
            account_id="ACCT-001",
            equity=Decimal("100000.00"),
            cash=Decimal("50000.00"),
            buying_power=Decimal("200000.00"),
            portfolio_value=Decimal("50000.00"),
            daily_pnl=Decimal("500.00"),
            pending_orders_count=2,
            positions_count=3,
            updated_at=NOW,
        )
        assert acct.equity == Decimal("100000.00")
        assert acct.pending_orders_count == 2

    def test_negative_pending_orders_count_raises(self) -> None:
        with pytest.raises(ValidationError, match="greater than or equal"):
            AccountSnapshot(
                account_id="ACCT-001",
                equity=Decimal("100000.00"),
                cash=Decimal("50000.00"),
                buying_power=Decimal("200000.00"),
                portfolio_value=Decimal("50000.00"),
                pending_orders_count=-1,
                updated_at=NOW,
            )

    def test_default_daily_pnl_is_zero(self) -> None:
        acct = AccountSnapshot(
            account_id="ACCT-001",
            equity=Decimal("100000.00"),
            cash=Decimal("50000.00"),
            buying_power=Decimal("200000.00"),
            portfolio_value=Decimal("50000.00"),
            updated_at=NOW,
        )
        assert acct.daily_pnl == Decimal("0")


# ---------------------------------------------------------------------------
# AdapterDiagnostics tests
# ---------------------------------------------------------------------------


class TestAdapterDiagnostics:
    """AdapterDiagnostics validation tests."""

    def test_valid_diagnostics(self) -> None:
        diag = AdapterDiagnostics(
            broker_name="alpaca",
            connection_status=ConnectionStatus.CONNECTED,
            latency_ms=45,
            error_count_1h=0,
            last_heartbeat=NOW,
            market_open=True,
            orders_submitted_today=15,
            orders_filled_today=12,
            uptime_seconds=3600,
        )
        assert diag.latency_ms == 45
        assert diag.market_open is True

    def test_negative_latency_raises(self) -> None:
        with pytest.raises(ValidationError, match="greater than or equal"):
            AdapterDiagnostics(
                broker_name="alpaca",
                connection_status=ConnectionStatus.CONNECTED,
                latency_ms=-1,
            )

    def test_defaults(self) -> None:
        diag = AdapterDiagnostics(
            broker_name="test",
            connection_status=ConnectionStatus.DISCONNECTED,
            latency_ms=0,
        )
        assert diag.error_count_1h == 0
        assert diag.market_open is False
        assert diag.orders_submitted_today == 0
        assert diag.uptime_seconds == 0
        assert diag.last_heartbeat is None
        assert diag.last_error is None
