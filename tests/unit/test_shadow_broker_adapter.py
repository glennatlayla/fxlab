"""
Unit tests for the ShadowBrokerAdapter.

Covers:
- Submit order → instant fill at market price
- Idempotency (duplicate client_order_id returns existing)
- Market price updates
- Hypothetical position tracking (buy, sell, close)
- Hypothetical P&L calculation
- Account snapshot with equity tracking
- Decision timeline recording
- Shadow P&L aggregation
- Cancel/get_order/list_open_orders/get_fills
- Diagnostics
- is_market_open always True
- Limit/stop order fill price logic
- Multi-symbol position tracking

Per M3 spec: signal → shadow fill → position update → audit trail, no broker side-effects.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from libs.contracts.execution import (
    ConnectionStatus,
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from libs.contracts.mocks.shadow_broker_adapter import ShadowBrokerAdapter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def adapter() -> ShadowBrokerAdapter:
    return ShadowBrokerAdapter(
        market_prices={"AAPL": Decimal("175.50"), "MSFT": Decimal("420.00")},
        initial_equity=Decimal("1000000"),
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
        correlation_id="corr-shadow-001",
        execution_mode=ExecutionMode.SHADOW,
    )


# ---------------------------------------------------------------------------
# Submit order tests
# ---------------------------------------------------------------------------


class TestSubmitOrder:
    """Tests for shadow order submission."""

    def test_instant_fill_at_market_price(self, adapter: ShadowBrokerAdapter) -> None:
        resp = adapter.submit_order(_make_order())
        assert resp.status == OrderStatus.FILLED
        assert resp.average_fill_price == Decimal("175.50")
        assert resp.filled_quantity == Decimal("100")
        assert resp.execution_mode == ExecutionMode.SHADOW

    def test_broker_order_id_assigned(self, adapter: ShadowBrokerAdapter) -> None:
        resp = adapter.submit_order(_make_order())
        assert resp.broker_order_id is not None
        assert resp.broker_order_id.startswith("SHADOW-")

    def test_idempotency_duplicate_returns_existing(self, adapter: ShadowBrokerAdapter) -> None:
        resp1 = adapter.submit_order(_make_order())
        resp2 = adapter.submit_order(_make_order())
        assert resp1.broker_order_id == resp2.broker_order_id
        assert adapter.get_submitted_orders_count() == 1

    def test_different_client_ids_create_separate_orders(
        self, adapter: ShadowBrokerAdapter
    ) -> None:
        adapter.submit_order(_make_order(client_order_id="ord-001"))
        adapter.submit_order(_make_order(client_order_id="ord-002"))
        assert adapter.get_submitted_orders_count() == 2

    def test_limit_order_fills_at_limit_price(self, adapter: ShadowBrokerAdapter) -> None:
        resp = adapter.submit_order(
            _make_order(
                order_type=OrderType.LIMIT,
                limit_price=Decimal("170.00"),
            )
        )
        assert resp.average_fill_price == Decimal("170.00")

    def test_stop_order_fills_at_stop_price(self, adapter: ShadowBrokerAdapter) -> None:
        resp = adapter.submit_order(
            _make_order(
                order_type=OrderType.STOP,
                stop_price=Decimal("180.00"),
            )
        )
        assert resp.average_fill_price == Decimal("180.00")

    def test_market_order_uses_current_price(self, adapter: ShadowBrokerAdapter) -> None:
        adapter.update_market_price("AAPL", Decimal("200.00"))
        resp = adapter.submit_order(_make_order())
        assert resp.average_fill_price == Decimal("200.00")


# ---------------------------------------------------------------------------
# Position tracking tests
# ---------------------------------------------------------------------------


class TestPositionTracking:
    """Tests for hypothetical position tracking."""

    def test_buy_creates_long_position(self, adapter: ShadowBrokerAdapter) -> None:
        adapter.submit_order(_make_order(side=OrderSide.BUY, quantity=Decimal("100")))
        positions = adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert positions[0].quantity == Decimal("100")

    def test_sell_creates_short_position(self, adapter: ShadowBrokerAdapter) -> None:
        adapter.submit_order(
            _make_order(
                client_order_id="ord-short",
                side=OrderSide.SELL,
                quantity=Decimal("50"),
            )
        )
        positions = adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == Decimal("-50")

    def test_buy_then_sell_closes_position(self, adapter: ShadowBrokerAdapter) -> None:
        adapter.submit_order(
            _make_order(
                client_order_id="ord-buy",
                side=OrderSide.BUY,
                quantity=Decimal("100"),
            )
        )
        adapter.submit_order(
            _make_order(
                client_order_id="ord-sell",
                side=OrderSide.SELL,
                quantity=Decimal("100"),
            )
        )
        # Position should be zero (not in the list)
        positions = adapter.get_positions()
        assert len(positions) == 0

    def test_multi_symbol_positions(self, adapter: ShadowBrokerAdapter) -> None:
        adapter.submit_order(
            _make_order(
                client_order_id="ord-aapl",
                symbol="AAPL",
                quantity=Decimal("100"),
            )
        )
        adapter.submit_order(
            _make_order(
                client_order_id="ord-msft",
                symbol="MSFT",
                quantity=Decimal("50"),
            )
        )
        positions = adapter.get_positions()
        assert len(positions) == 2
        symbols = {p.symbol for p in positions}
        assert symbols == {"AAPL", "MSFT"}


# ---------------------------------------------------------------------------
# Account snapshot tests
# ---------------------------------------------------------------------------


class TestAccountSnapshot:
    """Tests for hypothetical account state."""

    def test_initial_equity(self, adapter: ShadowBrokerAdapter) -> None:
        acct = adapter.get_account()
        assert acct.equity == Decimal("1000000")
        assert acct.account_id == "SHADOW-ACCOUNT"

    def test_equity_reflects_unrealized_pnl(self, adapter: ShadowBrokerAdapter) -> None:
        adapter.submit_order(_make_order())
        # Bought 100 AAPL at 175.50, update price to 180.00
        adapter.update_market_price("AAPL", Decimal("180.00"))
        acct = adapter.get_account()
        # Unrealized: (180 - 175.50) * 100 = 450
        expected_equity = Decimal("1000000") + Decimal("450")
        assert acct.equity == expected_equity

    def test_positions_count(self, adapter: ShadowBrokerAdapter) -> None:
        adapter.submit_order(_make_order())
        acct = adapter.get_account()
        assert acct.positions_count == 1


# ---------------------------------------------------------------------------
# Decision timeline tests
# ---------------------------------------------------------------------------


class TestDecisionTimeline:
    """Tests for shadow decision recording."""

    def test_submit_records_two_events(self, adapter: ShadowBrokerAdapter) -> None:
        """Each submit produces a 'submitted' and a 'filled' event."""
        adapter.submit_order(_make_order())
        timeline = adapter.get_decision_timeline()
        assert len(timeline) == 2
        assert timeline[0]["event_type"] == "shadow_order_submitted"
        assert timeline[1]["event_type"] == "shadow_order_filled"

    def test_timeline_includes_correlation_id(self, adapter: ShadowBrokerAdapter) -> None:
        adapter.submit_order(_make_order())
        timeline = adapter.get_decision_timeline()
        assert timeline[0]["correlation_id"] == "corr-shadow-001"

    def test_timeline_includes_fill_price(self, adapter: ShadowBrokerAdapter) -> None:
        adapter.submit_order(_make_order())
        timeline = adapter.get_decision_timeline()
        assert timeline[1]["fill_price"] == "175.50"


# ---------------------------------------------------------------------------
# Shadow P&L tests
# ---------------------------------------------------------------------------


class TestShadowPnL:
    """Tests for shadow P&L aggregation."""

    def test_pnl_with_open_position(self, adapter: ShadowBrokerAdapter) -> None:
        adapter.submit_order(_make_order())
        adapter.update_market_price("AAPL", Decimal("180.00"))
        pnl = adapter.get_shadow_pnl()
        # Unrealized: (180 - 175.50) * 100 = 450
        assert pnl["total_unrealized_pnl"] == "450.00"
        assert pnl["total_realized_pnl"] == "0"

    def test_pnl_after_close(self, adapter: ShadowBrokerAdapter) -> None:
        adapter.submit_order(_make_order(client_order_id="buy"))
        adapter.update_market_price("AAPL", Decimal("180.00"))
        adapter.submit_order(
            _make_order(
                client_order_id="sell",
                side=OrderSide.SELL,
                quantity=Decimal("100"),
            )
        )
        pnl = adapter.get_shadow_pnl()
        # Realized: (180 - 175.50) * 100 = 450
        assert pnl["total_realized_pnl"] == "450.00"


# ---------------------------------------------------------------------------
# Query operations tests
# ---------------------------------------------------------------------------


class TestQueryOperations:
    """Tests for cancel, get_order, list_open_orders, get_fills."""

    def test_cancel_returns_filled_order(self, adapter: ShadowBrokerAdapter) -> None:
        resp = adapter.submit_order(_make_order())
        cancel_resp = adapter.cancel_order(resp.broker_order_id)
        assert cancel_resp.status == OrderStatus.FILLED

    def test_cancel_not_found(self, adapter: ShadowBrokerAdapter) -> None:
        from libs.contracts.errors import NotFoundError

        with pytest.raises(NotFoundError):
            adapter.cancel_order("NONEXISTENT")

    def test_get_order(self, adapter: ShadowBrokerAdapter) -> None:
        resp = adapter.submit_order(_make_order())
        queried = adapter.get_order(resp.broker_order_id)
        assert queried.client_order_id == "ord-001"

    def test_list_open_orders_always_empty(self, adapter: ShadowBrokerAdapter) -> None:
        adapter.submit_order(_make_order())
        assert adapter.list_open_orders() == []

    def test_get_fills(self, adapter: ShadowBrokerAdapter) -> None:
        resp = adapter.submit_order(_make_order())
        fills = adapter.get_fills(resp.broker_order_id)
        assert len(fills) == 1
        assert fills[0].price == Decimal("175.50")
        assert fills[0].quantity == Decimal("100")


# ---------------------------------------------------------------------------
# Diagnostics tests
# ---------------------------------------------------------------------------


class TestDiagnostics:
    """Tests for shadow adapter diagnostics."""

    def test_diagnostics_shadow_mode(self, adapter: ShadowBrokerAdapter) -> None:
        diag = adapter.get_diagnostics()
        assert diag.broker_name == "shadow"
        assert diag.connection_status == ConnectionStatus.CONNECTED

    def test_diagnostics_counts(self, adapter: ShadowBrokerAdapter) -> None:
        adapter.submit_order(_make_order())
        diag = adapter.get_diagnostics()
        assert diag.orders_submitted_today == 1
        assert diag.orders_filled_today == 1


# ---------------------------------------------------------------------------
# Market open tests
# ---------------------------------------------------------------------------


class TestMarketOpen:
    """Shadow adapter always considers market open."""

    def test_is_market_open(self, adapter: ShadowBrokerAdapter) -> None:
        assert adapter.is_market_open() is True


# ---------------------------------------------------------------------------
# Clear tests
# ---------------------------------------------------------------------------


class TestClear:
    """Tests for state reset."""

    def test_clear_resets_all_state(self, adapter: ShadowBrokerAdapter) -> None:
        adapter.submit_order(_make_order())
        adapter.clear()
        assert adapter.get_submitted_orders_count() == 0
        assert adapter.get_positions() == []
        assert adapter.get_decision_timeline() == []
