"""
Unit tests for MockBrokerAdapter (libs/contracts/mocks/mock_broker_adapter.py).

Covers:
- Instant fill mode: submit → immediate FILLED status + position update
- Delayed fill mode: submit → SUBMITTED, then settle_order() → FILLED
- Partial fill mode: submit → PARTIAL_FILL at configured ratio
- Reject mode: submit → REJECTED with reason
- Idempotency: duplicate client_order_id returns existing order (no new submission)
- Cancel: cancels open orders, no-ops on terminal orders
- list_open_orders: only returns non-terminal orders
- get_fills: returns fill events per order
- get_positions: tracks position across multiple fills
- get_account: reflects position state in equity and P&L
- get_diagnostics: connection status, order counts, uptime
- is_market_open: reflects configured state
- Introspection helpers: get_submitted_orders_count, get_all_orders, clear
- Error paths: get_order/cancel_order on unknown broker_order_id raises NotFoundError

Per M0 spec: "Unit tests for mock adapter (all fill modes, idempotency check)"
"""

from decimal import Decimal

import pytest

from libs.contracts.errors import NotFoundError
from libs.contracts.execution import (
    ConnectionStatus,
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def market_buy() -> OrderRequest:
    """Standard market buy order."""
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
def market_sell() -> OrderRequest:
    """Standard market sell order."""
    return OrderRequest(
        client_order_id="ord-002",
        symbol="AAPL",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("50"),
        time_in_force=TimeInForce.DAY,
        deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
        strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
        correlation_id="corr-002",
        execution_mode=ExecutionMode.PAPER,
    )


# ---------------------------------------------------------------------------
# Instant fill mode
# ---------------------------------------------------------------------------


class TestInstantFillMode:
    """Tests for instant fill mode (default)."""

    def test_submit_fills_immediately(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="instant", fill_price=Decimal("175.50"))
        resp = adapter.submit_order(market_buy)

        assert resp.status == OrderStatus.FILLED
        assert resp.filled_quantity == Decimal("100")
        assert resp.average_fill_price == Decimal("175.50")
        assert resp.client_order_id == "ord-001"
        assert resp.broker_order_id is not None
        assert resp.broker_order_id.startswith("MOCK-")
        assert resp.filled_at is not None
        assert resp.submitted_at is not None

    def test_position_created_after_buy(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="instant", fill_price=Decimal("175.50"))
        adapter.submit_order(market_buy)

        positions = adapter.get_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos.symbol == "AAPL"
        assert pos.quantity == Decimal("100")
        assert pos.average_entry_price == Decimal("175.50")

    def test_position_reduced_after_sell(
        self, market_buy: OrderRequest, market_sell: OrderRequest
    ) -> None:
        adapter = MockBrokerAdapter(fill_mode="instant", fill_price=Decimal("175.50"))
        adapter.submit_order(market_buy)
        adapter.submit_order(market_sell)

        positions = adapter.get_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos.quantity == Decimal("50")

    def test_fills_recorded(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="instant", fill_price=Decimal("175.50"))
        resp = adapter.submit_order(market_buy)

        fills = adapter.get_fills(resp.broker_order_id)  # type: ignore[arg-type]
        assert len(fills) == 1
        assert fills[0].price == Decimal("175.50")
        assert fills[0].quantity == Decimal("100")
        assert fills[0].order_id == "ord-001"


# ---------------------------------------------------------------------------
# Delayed fill mode
# ---------------------------------------------------------------------------


class TestDelayedFillMode:
    """Tests for delayed fill mode."""

    def test_submit_stays_submitted(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="delayed")
        resp = adapter.submit_order(market_buy)

        assert resp.status == OrderStatus.SUBMITTED
        assert resp.filled_quantity == Decimal("0")
        assert resp.average_fill_price is None

    def test_settle_fills_order(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="delayed", fill_price=Decimal("176.00"))
        resp = adapter.submit_order(market_buy)

        settled = adapter.settle_order(resp.broker_order_id, Decimal("176.00"))  # type: ignore[arg-type]
        assert settled.status == OrderStatus.FILLED
        assert settled.filled_quantity == Decimal("100")
        assert settled.average_fill_price == Decimal("176.00")
        assert settled.filled_at is not None

    def test_settle_creates_position(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="delayed", fill_price=Decimal("176.00"))
        resp = adapter.submit_order(market_buy)

        # Before settlement: no positions
        assert len(adapter.get_positions()) == 0

        adapter.settle_order(resp.broker_order_id)  # type: ignore[arg-type]
        positions = adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == Decimal("100")

    def test_settle_unknown_order_raises(self) -> None:
        adapter = MockBrokerAdapter(fill_mode="delayed")
        with pytest.raises(NotFoundError):
            adapter.settle_order("NONEXISTENT")

    def test_settle_non_submitted_raises(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="instant")
        resp = adapter.submit_order(market_buy)
        # Already filled; settle should fail
        with pytest.raises(ValueError, match="expected SUBMITTED"):
            adapter.settle_order(resp.broker_order_id)  # type: ignore[arg-type]

    def test_open_orders_includes_submitted(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="delayed")
        adapter.submit_order(market_buy)

        open_orders = adapter.list_open_orders()
        assert len(open_orders) == 1
        assert open_orders[0].status == OrderStatus.SUBMITTED


# ---------------------------------------------------------------------------
# Partial fill mode
# ---------------------------------------------------------------------------


class TestPartialFillMode:
    """Tests for partial fill mode."""

    def test_partial_fill_ratio(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(
            fill_mode="partial",
            fill_price=Decimal("175.50"),
            partial_fill_ratio=Decimal("0.5"),
        )
        resp = adapter.submit_order(market_buy)

        assert resp.status == OrderStatus.PARTIAL_FILL
        assert resp.filled_quantity == Decimal("50.00")
        assert resp.average_fill_price == Decimal("175.50")

    def test_partial_fill_creates_position(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(
            fill_mode="partial",
            fill_price=Decimal("175.50"),
            partial_fill_ratio=Decimal("0.25"),
        )
        adapter.submit_order(market_buy)

        positions = adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == Decimal("25.00")

    def test_partial_fill_is_open_order(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="partial")
        adapter.submit_order(market_buy)

        # Partial fills are non-terminal
        open_orders = adapter.list_open_orders()
        assert len(open_orders) == 1


# ---------------------------------------------------------------------------
# Reject mode
# ---------------------------------------------------------------------------


class TestRejectMode:
    """Tests for reject fill mode."""

    def test_submit_rejects_immediately(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="reject", reject_reason="Insufficient buying power")
        resp = adapter.submit_order(market_buy)

        assert resp.status == OrderStatus.REJECTED
        assert resp.rejected_reason == "Insufficient buying power"
        assert resp.filled_quantity == Decimal("0")
        assert resp.average_fill_price is None

    def test_reject_creates_no_position(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="reject")
        adapter.submit_order(market_buy)
        assert len(adapter.get_positions()) == 0

    def test_reject_not_in_open_orders(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="reject")
        adapter.submit_order(market_buy)
        assert len(adapter.list_open_orders()) == 0


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Tests for client_order_id idempotency enforcement."""

    def test_duplicate_submit_returns_existing(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="instant", fill_price=Decimal("175.50"))

        resp1 = adapter.submit_order(market_buy)
        resp2 = adapter.submit_order(market_buy)

        # Same response object — no new submission
        assert resp1.broker_order_id == resp2.broker_order_id
        assert resp1.status == resp2.status
        assert adapter.get_submitted_orders_count() == 1

    def test_different_client_ids_create_separate_orders(self) -> None:
        adapter = MockBrokerAdapter(fill_mode="instant")

        req1 = OrderRequest(
            client_order_id="ord-A",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
            strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
            correlation_id="corr-A",
            execution_mode=ExecutionMode.PAPER,
        )
        req2 = OrderRequest(
            client_order_id="ord-B",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("50"),
            deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
            strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
            correlation_id="corr-B",
            execution_mode=ExecutionMode.PAPER,
        )

        resp1 = adapter.submit_order(req1)
        resp2 = adapter.submit_order(req2)

        assert resp1.broker_order_id != resp2.broker_order_id
        assert adapter.get_submitted_orders_count() == 2


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


class TestCancel:
    """Tests for order cancellation."""

    def test_cancel_open_order(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="delayed")
        resp = adapter.submit_order(market_buy)

        cancelled = adapter.cancel_order(resp.broker_order_id)  # type: ignore[arg-type]
        assert cancelled.status == OrderStatus.CANCELLED
        assert cancelled.cancelled_at is not None

    def test_cancel_filled_order_noop(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="instant")
        resp = adapter.submit_order(market_buy)

        # Already filled — cancel returns existing state
        result = adapter.cancel_order(resp.broker_order_id)  # type: ignore[arg-type]
        assert result.status == OrderStatus.FILLED

    def test_cancel_unknown_order_raises(self) -> None:
        adapter = MockBrokerAdapter()
        with pytest.raises(NotFoundError):
            adapter.cancel_order("NONEXISTENT")

    def test_cancelled_not_in_open_orders(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="delayed")
        resp = adapter.submit_order(market_buy)
        adapter.cancel_order(resp.broker_order_id)  # type: ignore[arg-type]

        assert len(adapter.list_open_orders()) == 0


# ---------------------------------------------------------------------------
# Query operations
# ---------------------------------------------------------------------------


class TestQueryOperations:
    """Tests for get_order, get_fills, list_open_orders."""

    def test_get_order_returns_current_state(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="instant", fill_price=Decimal("175.50"))
        resp = adapter.submit_order(market_buy)

        queried = adapter.get_order(resp.broker_order_id)  # type: ignore[arg-type]
        assert queried.status == OrderStatus.FILLED
        assert queried.client_order_id == "ord-001"

    def test_get_order_unknown_raises(self) -> None:
        adapter = MockBrokerAdapter()
        with pytest.raises(NotFoundError):
            adapter.get_order("NONEXISTENT")

    def test_get_fills_unknown_order_raises(self) -> None:
        adapter = MockBrokerAdapter()
        with pytest.raises(NotFoundError):
            adapter.get_fills("NONEXISTENT")

    def test_list_open_orders_empty_initially(self) -> None:
        adapter = MockBrokerAdapter()
        assert adapter.list_open_orders() == []


# ---------------------------------------------------------------------------
# Account and diagnostics
# ---------------------------------------------------------------------------


class TestAccountAndDiagnostics:
    """Tests for get_account and get_diagnostics."""

    def test_get_account_initial_state(self) -> None:
        adapter = MockBrokerAdapter(
            account_equity=Decimal("50000"),
            account_cash=Decimal("50000"),
        )
        acct = adapter.get_account()
        assert acct.account_id == "MOCK-ACCOUNT"
        assert acct.cash == Decimal("50000")
        assert acct.pending_orders_count == 0
        assert acct.positions_count == 0

    def test_get_account_reflects_positions(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(
            fill_mode="instant",
            fill_price=Decimal("175.50"),
            account_equity=Decimal("100000"),
            account_cash=Decimal("100000"),
        )
        adapter.submit_order(market_buy)

        acct = adapter.get_account()
        assert acct.positions_count == 1
        assert acct.portfolio_value > 0

    def test_get_diagnostics_connected(self) -> None:
        adapter = MockBrokerAdapter(market_open=True)
        diag = adapter.get_diagnostics()

        assert diag.broker_name == "mock"
        assert diag.connection_status == ConnectionStatus.CONNECTED
        assert diag.latency_ms == 1
        assert diag.market_open is True
        assert diag.uptime_seconds >= 0

    def test_get_diagnostics_order_counts(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="instant")
        adapter.submit_order(market_buy)

        diag = adapter.get_diagnostics()
        assert diag.orders_submitted_today == 1
        assert diag.orders_filled_today == 1

    def test_is_market_open(self) -> None:
        adapter_open = MockBrokerAdapter(market_open=True)
        adapter_closed = MockBrokerAdapter(market_open=False)

        assert adapter_open.is_market_open() is True
        assert adapter_closed.is_market_open() is False


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------


class TestIntrospection:
    """Tests for mock-only introspection helpers."""

    def test_get_submitted_orders_count(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter()
        assert adapter.get_submitted_orders_count() == 0

        adapter.submit_order(market_buy)
        assert adapter.get_submitted_orders_count() == 1

    def test_get_all_orders(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter()
        adapter.submit_order(market_buy)

        all_orders = adapter.get_all_orders()
        assert len(all_orders) == 1

    def test_get_all_fills(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="instant", fill_price=Decimal("175.50"))
        adapter.submit_order(market_buy)

        all_fills = adapter.get_all_fills()
        assert len(all_fills) == 1
        assert all_fills[0].price == Decimal("175.50")

    def test_clear_resets_state(self, market_buy: OrderRequest) -> None:
        adapter = MockBrokerAdapter(fill_mode="instant")
        adapter.submit_order(market_buy)

        adapter.clear()

        assert adapter.get_submitted_orders_count() == 0
        assert adapter.get_all_orders() == []
        assert adapter.get_all_fills() == []
        assert adapter.get_positions() == []


# ---------------------------------------------------------------------------
# Multi-symbol position tracking
# ---------------------------------------------------------------------------


class TestMultiSymbolPositions:
    """Test position tracking across multiple symbols."""

    def test_positions_tracked_per_symbol(self) -> None:
        adapter = MockBrokerAdapter(fill_mode="instant", fill_price=Decimal("100"))

        aapl = OrderRequest(
            client_order_id="ord-aapl",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("50"),
            deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
            strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
            correlation_id="corr-aapl",
            execution_mode=ExecutionMode.PAPER,
        )
        msft = OrderRequest(
            client_order_id="ord-msft",
            symbol="MSFT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("30"),
            deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
            strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
            correlation_id="corr-msft",
            execution_mode=ExecutionMode.PAPER,
        )

        adapter.submit_order(aapl)
        adapter.submit_order(msft)

        positions = adapter.get_positions()
        assert len(positions) == 2
        symbols = {p.symbol for p in positions}
        assert symbols == {"AAPL", "MSFT"}

    def test_position_closed_when_fully_sold(self) -> None:
        adapter = MockBrokerAdapter(fill_mode="instant", fill_price=Decimal("100"))

        buy = OrderRequest(
            client_order_id="ord-buy",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
            strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
            correlation_id="corr-buy",
            execution_mode=ExecutionMode.PAPER,
        )
        sell = OrderRequest(
            client_order_id="ord-sell",
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
            strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
            correlation_id="corr-sell",
            execution_mode=ExecutionMode.PAPER,
        )

        adapter.submit_order(buy)
        adapter.submit_order(sell)

        # Position closed — quantity is zero, should not appear in get_positions
        positions = adapter.get_positions()
        assert len(positions) == 0
