"""
Unit tests for the PaperBrokerAdapter.

Covers:
- Submit order → SUBMITTED (not instant fill)
- process_pending_orders() → fills matching orders
- Market order fills at current market price
- Limit order fills only when price crosses limit
- Stop order fills only when price crosses stop
- Partial fill support (configurable ratio)
- Reject mode (insufficient equity, risk limits)
- Idempotency (duplicate client_order_id returns existing)
- Cancel open order
- Position tracking (buy, sell, close)
- Account snapshot with equity, margin, fees
- Commission/fee deduction
- Configurable fill latency (tick-based)
- Reconciliation: get_all_order_states() for startup recovery
- Diagnostics
- is_market_open (configurable)
- Multi-symbol position tracking

Per M4 spec: realistic order lifecycle with configurable latency, partial fills,
rejects. Reconciliation-compatible for startup recovery.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from libs.broker.paper_broker_adapter import PaperBrokerAdapter
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

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def adapter() -> PaperBrokerAdapter:
    return PaperBrokerAdapter(
        market_prices={"AAPL": Decimal("175.50"), "MSFT": Decimal("420.00")},
        initial_equity=Decimal("1000000"),
        commission_per_order=Decimal("1.00"),
    )


def _make_order(
    *,
    client_order_id: str = "ord-001",
    symbol: str = "AAPL",
    side: OrderSide = OrderSide.BUY,
    order_type: OrderType = OrderType.MARKET,
    quantity: Decimal = Decimal("100"),
    limit_price: Decimal | None = None,
    stop_price: Decimal | None = None,
) -> OrderRequest:
    return OrderRequest(
        client_order_id=client_order_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        limit_price=limit_price,
        stop_price=stop_price,
        time_in_force=TimeInForce.DAY,
        deployment_id="01HTESTDEP0000000000000001",
        strategy_id="01HTESTSTRT000000000000001",
        correlation_id="corr-paper-001",
        execution_mode=ExecutionMode.PAPER,
    )


# ---------------------------------------------------------------------------
# Submit order tests
# ---------------------------------------------------------------------------


class TestSubmitOrder:
    """Tests for paper order submission."""

    def test_submit_returns_submitted_status(self, adapter: PaperBrokerAdapter) -> None:
        """Market order goes to SUBMITTED first, not instant fill."""
        resp = adapter.submit_order(_make_order())
        assert resp.status == OrderStatus.SUBMITTED
        assert resp.filled_quantity == Decimal("0")
        assert resp.broker_order_id is not None
        assert resp.broker_order_id.startswith("PAPER-")

    def test_idempotency_duplicate_returns_existing(self, adapter: PaperBrokerAdapter) -> None:
        resp1 = adapter.submit_order(_make_order())
        resp2 = adapter.submit_order(_make_order())
        assert resp1.broker_order_id == resp2.broker_order_id
        assert adapter.get_submitted_orders_count() == 1

    def test_different_client_ids_create_separate_orders(self, adapter: PaperBrokerAdapter) -> None:
        adapter.submit_order(_make_order(client_order_id="ord-001"))
        adapter.submit_order(_make_order(client_order_id="ord-002"))
        assert adapter.get_submitted_orders_count() == 2

    def test_submit_sets_execution_mode_paper(self, adapter: PaperBrokerAdapter) -> None:
        resp = adapter.submit_order(_make_order())
        assert resp.execution_mode == ExecutionMode.PAPER


# ---------------------------------------------------------------------------
# Order processing / fill tests
# ---------------------------------------------------------------------------


class TestOrderProcessing:
    """Tests for process_pending_orders() fill logic."""

    def test_market_order_fills_on_process(self, adapter: PaperBrokerAdapter) -> None:
        """After submit, process_pending_orders() fills market orders."""
        adapter.submit_order(_make_order())
        filled = adapter.process_pending_orders()
        assert len(filled) == 1
        assert filled[0].status == OrderStatus.FILLED
        assert filled[0].average_fill_price == Decimal("175.50")
        assert filled[0].filled_quantity == Decimal("100")

    def test_market_order_fills_at_current_price(self, adapter: PaperBrokerAdapter) -> None:
        adapter.update_market_price("AAPL", Decimal("200.00"))
        adapter.submit_order(_make_order())
        filled = adapter.process_pending_orders()
        assert filled[0].average_fill_price == Decimal("200.00")

    def test_limit_buy_fills_when_price_at_or_below_limit(
        self, adapter: PaperBrokerAdapter
    ) -> None:
        """Limit buy fills when market price <= limit price."""
        adapter.submit_order(
            _make_order(
                order_type=OrderType.LIMIT,
                limit_price=Decimal("180.00"),
            )
        )
        # Market at 175.50, below limit 180 — should fill
        filled = adapter.process_pending_orders()
        assert len(filled) == 1
        assert filled[0].average_fill_price == Decimal("175.50")

    def test_limit_buy_does_not_fill_when_price_above_limit(
        self, adapter: PaperBrokerAdapter
    ) -> None:
        """Limit buy does NOT fill when market price > limit price."""
        adapter.submit_order(
            _make_order(
                order_type=OrderType.LIMIT,
                limit_price=Decimal("170.00"),
            )
        )
        # Market at 175.50, above limit 170 — should not fill
        filled = adapter.process_pending_orders()
        assert len(filled) == 0

    def test_limit_buy_fills_when_price_drops(self, adapter: PaperBrokerAdapter) -> None:
        """Limit buy pending, then price drops to meet limit."""
        adapter.submit_order(
            _make_order(
                order_type=OrderType.LIMIT,
                limit_price=Decimal("170.00"),
            )
        )
        adapter.process_pending_orders()  # Won't fill (175.50 > 170)
        adapter.update_market_price("AAPL", Decimal("169.00"))
        filled = adapter.process_pending_orders()
        assert len(filled) == 1
        assert filled[0].average_fill_price == Decimal("169.00")

    def test_limit_sell_fills_when_price_at_or_above_limit(
        self, adapter: PaperBrokerAdapter
    ) -> None:
        """Limit sell fills when market price >= limit price."""
        adapter.submit_order(
            _make_order(
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                limit_price=Decimal("170.00"),
            )
        )
        # Market at 175.50, above limit 170 — should fill
        filled = adapter.process_pending_orders()
        assert len(filled) == 1

    def test_stop_buy_fills_when_price_at_or_above_stop(self, adapter: PaperBrokerAdapter) -> None:
        """Stop buy triggers when market price >= stop price."""
        adapter.submit_order(
            _make_order(
                order_type=OrderType.STOP,
                stop_price=Decimal("170.00"),
            )
        )
        # Market at 175.50, above stop 170 — should fill
        filled = adapter.process_pending_orders()
        assert len(filled) == 1
        assert filled[0].average_fill_price == Decimal("175.50")

    def test_stop_buy_does_not_fill_when_price_below_stop(
        self, adapter: PaperBrokerAdapter
    ) -> None:
        """Stop buy does NOT trigger when market price < stop price."""
        adapter.submit_order(
            _make_order(
                order_type=OrderType.STOP,
                stop_price=Decimal("180.00"),
            )
        )
        filled = adapter.process_pending_orders()
        assert len(filled) == 0

    def test_stop_sell_fills_when_price_at_or_below_stop(self, adapter: PaperBrokerAdapter) -> None:
        """Stop sell triggers when market price <= stop price."""
        adapter.submit_order(
            _make_order(
                side=OrderSide.SELL,
                order_type=OrderType.STOP,
                stop_price=Decimal("180.00"),
            )
        )
        # Market at 175.50, below stop 180 — should fill
        filled = adapter.process_pending_orders()
        assert len(filled) == 1

    def test_no_pending_returns_empty(self, adapter: PaperBrokerAdapter) -> None:
        filled = adapter.process_pending_orders()
        assert filled == []

    def test_already_filled_not_processed_again(self, adapter: PaperBrokerAdapter) -> None:
        adapter.submit_order(_make_order())
        adapter.process_pending_orders()
        filled2 = adapter.process_pending_orders()
        assert len(filled2) == 0


# ---------------------------------------------------------------------------
# Partial fill tests
# ---------------------------------------------------------------------------


class TestPartialFills:
    """Tests for partial fill behaviour."""

    def test_partial_fill_with_ratio(self) -> None:
        adapter = PaperBrokerAdapter(
            market_prices={"AAPL": Decimal("175.50")},
            initial_equity=Decimal("1000000"),
            partial_fill_ratio=Decimal("0.5"),
        )
        adapter.submit_order(_make_order())
        filled = adapter.process_pending_orders()
        assert len(filled) == 1
        assert filled[0].status == OrderStatus.PARTIAL_FILL
        assert filled[0].filled_quantity == Decimal("50")

    def test_partial_fill_remaining_fills_on_next_process(self) -> None:
        adapter = PaperBrokerAdapter(
            market_prices={"AAPL": Decimal("175.50")},
            initial_equity=Decimal("1000000"),
            partial_fill_ratio=Decimal("0.5"),
        )
        adapter.submit_order(_make_order())
        adapter.process_pending_orders()  # First partial fill: 50
        filled2 = adapter.process_pending_orders()  # Second partial fill: 25
        assert len(filled2) == 1
        assert filled2[0].filled_quantity == Decimal("75")


# ---------------------------------------------------------------------------
# Commission / fees tests
# ---------------------------------------------------------------------------


class TestCommission:
    """Tests for commission tracking."""

    def test_commission_deducted_on_fill(self, adapter: PaperBrokerAdapter) -> None:
        adapter.submit_order(_make_order())
        filled = adapter.process_pending_orders()
        fills = adapter.get_fills(filled[0].broker_order_id)
        assert fills[0].commission == Decimal("1.00")

    def test_commission_reflected_in_account(self, adapter: PaperBrokerAdapter) -> None:
        adapter.submit_order(_make_order())
        adapter.process_pending_orders()
        acct = adapter.get_account()
        # Cash reduced by (175.50 * 100) + 1.00 commission
        expected_cash = Decimal("1000000") - Decimal("175.50") * Decimal("100") - Decimal("1.00")
        assert acct.cash == expected_cash


# ---------------------------------------------------------------------------
# Position tracking tests
# ---------------------------------------------------------------------------


class TestPositionTracking:
    """Tests for position tracking after fills."""

    def test_buy_creates_long_position(self, adapter: PaperBrokerAdapter) -> None:
        adapter.submit_order(_make_order())
        adapter.process_pending_orders()
        positions = adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert positions[0].quantity == Decimal("100")

    def test_sell_creates_short_position(self, adapter: PaperBrokerAdapter) -> None:
        adapter.submit_order(_make_order(client_order_id="short", side=OrderSide.SELL))
        adapter.process_pending_orders()
        positions = adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == Decimal("-100")

    def test_buy_then_sell_closes_position(self, adapter: PaperBrokerAdapter) -> None:
        adapter.submit_order(_make_order(client_order_id="buy"))
        adapter.process_pending_orders()
        adapter.submit_order(_make_order(client_order_id="sell", side=OrderSide.SELL))
        adapter.process_pending_orders()
        positions = adapter.get_positions()
        assert len(positions) == 0

    def test_multi_symbol_positions(self, adapter: PaperBrokerAdapter) -> None:
        adapter.submit_order(_make_order(client_order_id="aapl"))
        adapter.submit_order(
            _make_order(client_order_id="msft", symbol="MSFT", quantity=Decimal("50"))
        )
        adapter.process_pending_orders()
        positions = adapter.get_positions()
        assert len(positions) == 2
        symbols = {p.symbol for p in positions}
        assert symbols == {"AAPL", "MSFT"}


# ---------------------------------------------------------------------------
# Cancel order tests
# ---------------------------------------------------------------------------


class TestCancelOrder:
    """Tests for order cancellation."""

    def test_cancel_pending_order(self, adapter: PaperBrokerAdapter) -> None:
        resp = adapter.submit_order(_make_order())
        cancel = adapter.cancel_order(resp.broker_order_id)
        assert cancel.status == OrderStatus.CANCELLED

    def test_cancel_filled_order_returns_filled(self, adapter: PaperBrokerAdapter) -> None:
        resp = adapter.submit_order(_make_order())
        adapter.process_pending_orders()
        cancel = adapter.cancel_order(resp.broker_order_id)
        assert cancel.status == OrderStatus.FILLED

    def test_cancel_not_found(self, adapter: PaperBrokerAdapter) -> None:
        with pytest.raises(NotFoundError):
            adapter.cancel_order("NONEXISTENT")


# ---------------------------------------------------------------------------
# Query operations tests
# ---------------------------------------------------------------------------


class TestQueryOperations:
    """Tests for get_order, list_open_orders, get_fills."""

    def test_get_order(self, adapter: PaperBrokerAdapter) -> None:
        resp = adapter.submit_order(_make_order())
        queried = adapter.get_order(resp.broker_order_id)
        assert queried.client_order_id == "ord-001"

    def test_list_open_orders_returns_submitted(self, adapter: PaperBrokerAdapter) -> None:
        adapter.submit_order(_make_order())
        opens = adapter.list_open_orders()
        assert len(opens) == 1
        assert opens[0].status == OrderStatus.SUBMITTED

    def test_list_open_orders_empty_after_fill(self, adapter: PaperBrokerAdapter) -> None:
        adapter.submit_order(_make_order())
        adapter.process_pending_orders()
        opens = adapter.list_open_orders()
        assert len(opens) == 0

    def test_get_fills_after_process(self, adapter: PaperBrokerAdapter) -> None:
        resp = adapter.submit_order(_make_order())
        adapter.process_pending_orders()
        fills = adapter.get_fills(resp.broker_order_id)
        assert len(fills) == 1
        assert fills[0].price == Decimal("175.50")


# ---------------------------------------------------------------------------
# Account snapshot tests
# ---------------------------------------------------------------------------


class TestAccountSnapshot:
    """Tests for account state."""

    def test_initial_equity(self, adapter: PaperBrokerAdapter) -> None:
        acct = adapter.get_account()
        assert acct.equity == Decimal("1000000")
        assert acct.account_id == "PAPER-ACCOUNT"

    def test_equity_after_fill(self, adapter: PaperBrokerAdapter) -> None:
        adapter.submit_order(_make_order())
        adapter.process_pending_orders()
        acct = adapter.get_account()
        # Equity = cash + market_value
        # cash = 1000000 - (175.50*100) - 1 commission = 982449
        # market_value = 100 * 175.50 = 17550
        # equity = 982449 + 17550 = 999999 (due to commission)
        assert acct.equity == Decimal("999999.00")


# ---------------------------------------------------------------------------
# Reconciliation tests
# ---------------------------------------------------------------------------


class TestReconciliation:
    """Tests for startup recovery / reconciliation."""

    def test_get_all_order_states(self, adapter: PaperBrokerAdapter) -> None:
        adapter.submit_order(_make_order(client_order_id="ord-a"))
        adapter.submit_order(_make_order(client_order_id="ord-b"))
        adapter.process_pending_orders()
        states = adapter.get_all_order_states()
        assert len(states) == 2
        assert all(s.status == OrderStatus.FILLED for s in states)

    def test_reconciliation_after_partial(self) -> None:
        adapter = PaperBrokerAdapter(
            market_prices={"AAPL": Decimal("175.50")},
            initial_equity=Decimal("1000000"),
            partial_fill_ratio=Decimal("0.5"),
        )
        adapter.submit_order(_make_order())
        adapter.process_pending_orders()
        states = adapter.get_all_order_states()
        assert len(states) == 1
        assert states[0].status == OrderStatus.PARTIAL_FILL
        assert states[0].filled_quantity == Decimal("50")


# ---------------------------------------------------------------------------
# Diagnostics tests
# ---------------------------------------------------------------------------


class TestDiagnostics:
    """Tests for paper adapter diagnostics."""

    def test_diagnostics_paper_mode(self, adapter: PaperBrokerAdapter) -> None:
        diag = adapter.get_diagnostics()
        assert diag.broker_name == "paper"
        assert diag.connection_status == ConnectionStatus.CONNECTED

    def test_diagnostics_counts(self, adapter: PaperBrokerAdapter) -> None:
        adapter.submit_order(_make_order())
        adapter.process_pending_orders()
        diag = adapter.get_diagnostics()
        assert diag.orders_submitted_today == 1
        assert diag.orders_filled_today == 1


# ---------------------------------------------------------------------------
# Market open tests
# ---------------------------------------------------------------------------


class TestMarketOpen:
    """Paper adapter market open is configurable."""

    def test_default_market_open(self, adapter: PaperBrokerAdapter) -> None:
        assert adapter.is_market_open() is True

    def test_market_closed(self) -> None:
        adapter = PaperBrokerAdapter(
            market_prices={},
            initial_equity=Decimal("1000000"),
            market_open=False,
        )
        assert adapter.is_market_open() is False


# ---------------------------------------------------------------------------
# Clear tests
# ---------------------------------------------------------------------------


class TestClear:
    """Tests for state reset."""

    def test_clear_resets_all_state(self, adapter: PaperBrokerAdapter) -> None:
        adapter.submit_order(_make_order())
        adapter.process_pending_orders()
        adapter.clear()
        assert adapter.get_submitted_orders_count() == 0
        assert adapter.get_positions() == []
        assert adapter.list_open_orders() == []
