"""
Unit tests for libs.strategy_ir.paper_broker_adapter.PaperBrokerAdapter.

Scope:
    Verify the paper adapter satisfies
    :class:`BrokerAdapterInterface` end-to-end and honours the
    contract documented in the module docstring:

        * Interface conformance.
        * place_order is idempotent on client_extension_id (same
          OrderRef, no duplicate position).
        * Market orders fill at the next bar's open.
        * Limit BUY orders fill when the bar low <= limit; remain
          pending when the bar stays above.
        * Stop SELL orders fill when the bar low <= stop.
        * Position bookkeeping tracks unrealised PnL as the
          mid-price moves.
        * Account bookkeeping moves realised PnL into the cash
          balance on close.
        * Per-symbol pip slippage moves the fill price in the WORSE
          direction (BUY pays more, SELL receives less).
        * Determinism: same orders + same bar stream produces
          byte-identical position and account snapshots.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from libs.contracts.market_data import Candle, CandleInterval
from libs.strategy_ir.interfaces.broker_adapter_interface import (
    BrokerAdapterInterface,
    OrderSide,
    OrderType,
)
from libs.strategy_ir.mocks.mock_market_data_provider import MockMarketDataProvider
from libs.strategy_ir.paper_broker_adapter import (
    FillEvent,
    PaperBrokerAdapter,
    PaperBrokerError,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _candle(
    *,
    symbol: str = "EURUSD",
    open_: str,
    high: str,
    low: str,
    close: str,
    minute: int = 0,
) -> Candle:
    """Build an H1 EURUSD candle with the supplied OHLC. Deterministic timestamps."""
    return Candle(
        symbol=symbol,
        interval=CandleInterval.H1,
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=10_000,
        timestamp=datetime(2026, 4, 25, 12, minute, tzinfo=timezone.utc),
    )


def _make_broker(
    *,
    starting_balance: Decimal = Decimal("100000"),
    pip_slippage: dict[str, int] | None = None,
) -> PaperBrokerAdapter:
    """Construct a PaperBrokerAdapter with a mock market-data provider."""
    provider = MockMarketDataProvider()
    return PaperBrokerAdapter(
        starting_balance=starting_balance,
        pip_slippage=pip_slippage,
        market_data=provider,
    )


# ---------------------------------------------------------------------------
# Interface conformance
# ---------------------------------------------------------------------------


def test_paper_broker_satisfies_broker_adapter_protocol() -> None:
    """The paper adapter must satisfy BrokerAdapterInterface structurally."""
    broker = _make_broker()
    assert isinstance(broker, BrokerAdapterInterface)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_place_order_is_idempotent_on_client_extension_id() -> None:
    """Same client_extension_id → same OrderRef, no duplicate position created."""
    broker = _make_broker()
    ref1 = broker.place_order(
        "EURUSD",
        OrderSide.BUY,
        10_000,
        order_type=OrderType.MARKET,
        client_extension_id="run-1-bar-1-leg-A",
    )
    ref2 = broker.place_order(
        "EURUSD",
        OrderSide.BUY,
        10_000,
        order_type=OrderType.MARKET,
        client_extension_id="run-1-bar-1-leg-A",
    )

    # Same ref byte-for-byte (Pydantic frozen models compare by field).
    assert ref1 == ref2
    assert ref1.broker_order_id == ref2.broker_order_id

    # Only one pending order; the duplicate place_order did not enqueue a second.
    assert broker.pending_orders() == [ref1]

    # Fill the bar — only one fill event must result.
    fills = broker.submit_bar(
        "EURUSD",
        _candle(open_="1.1000", high="1.1010", low="1.0990", close="1.1005"),
    )
    assert len(fills) == 1
    assert broker.get_position("EURUSD") is not None
    assert broker.get_position("EURUSD").units == 10_000  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Market order — fill at next bar open
# ---------------------------------------------------------------------------


def test_market_order_fills_at_next_bar_open() -> None:
    """A MARKET order placed before submit_bar fills at that bar's open."""
    broker = _make_broker()
    ref = broker.place_order(
        "EURUSD",
        OrderSide.BUY,
        10_000,
        order_type=OrderType.MARKET,
        client_extension_id="m-1",
    )
    fills = broker.submit_bar(
        "EURUSD",
        _candle(open_="1.1234", high="1.1250", low="1.1230", close="1.1245"),
    )

    assert len(fills) == 1
    fill = fills[0]
    assert isinstance(fill, FillEvent)
    assert fill.order_ref == ref
    assert fill.fill_price == Decimal("1.1234")
    assert fill.slippage_pips == 0
    assert fill.bar_index == 0
    assert broker.pending_orders() == []


# ---------------------------------------------------------------------------
# Limit BUY: fills when low <= limit; otherwise stays pending
# ---------------------------------------------------------------------------


def test_limit_buy_fills_when_price_drops_to_or_below_limit() -> None:
    """LIMIT BUY at 1.1000 fills when bar low touches 1.1000 (or below)."""
    broker = _make_broker()
    ref = broker.place_order(
        "EURUSD",
        OrderSide.BUY,
        10_000,
        order_type=OrderType.LIMIT,
        client_extension_id="lb-1",
        limit_price=Decimal("1.1000"),
    )
    fills = broker.submit_bar(
        "EURUSD",
        _candle(open_="1.1010", high="1.1020", low="1.0995", close="1.1005"),
    )
    assert len(fills) == 1
    assert fills[0].fill_price == Decimal("1.1000")
    assert fills[0].order_ref == ref


def test_limit_buy_stays_pending_when_price_stays_above_limit() -> None:
    """LIMIT BUY at 1.1000 does NOT fill when the bar low stays above 1.1000."""
    broker = _make_broker()
    ref = broker.place_order(
        "EURUSD",
        OrderSide.BUY,
        10_000,
        order_type=OrderType.LIMIT,
        client_extension_id="lb-2",
        limit_price=Decimal("1.1000"),
    )
    fills = broker.submit_bar(
        "EURUSD",
        _candle(open_="1.1050", high="1.1060", low="1.1010", close="1.1040"),
    )
    assert fills == []
    assert broker.pending_orders() == [ref]
    assert broker.get_position("EURUSD") is None


# ---------------------------------------------------------------------------
# Stop SELL: fills when low <= stop
# ---------------------------------------------------------------------------


def test_stop_sell_fills_when_price_crosses_below_stop() -> None:
    """STOP SELL at 1.0950 fills when the bar low touches 1.0950 (or below)."""
    broker = _make_broker()
    ref = broker.place_order(
        "EURUSD",
        OrderSide.SELL,
        10_000,
        order_type=OrderType.MARKET,
        client_extension_id="ss-1",
        stop_price=Decimal("1.0950"),
    )
    # First bar: stays well above the stop -> no fill.
    fills_pending = broker.submit_bar(
        "EURUSD",
        _candle(open_="1.1000", high="1.1010", low="1.0990", close="1.1000"),
    )
    assert fills_pending == []
    assert broker.pending_orders() == [ref]

    # Next bar: low touches 1.0945 -> stop triggers, fills at 1.0950.
    fills = broker.submit_bar(
        "EURUSD",
        _candle(
            open_="1.0980",
            high="1.0985",
            low="1.0945",
            close="1.0960",
            minute=1,
        ),
    )
    assert len(fills) == 1
    assert fills[0].fill_price == Decimal("1.0950")
    assert fills[0].order_ref == ref


# ---------------------------------------------------------------------------
# Position bookkeeping: unrealized PnL tracks mid-price
# ---------------------------------------------------------------------------


def test_position_unrealized_pnl_updates_as_mid_price_moves() -> None:
    """Open 10_000 LONG @ 1.1000, then mark-to-market at higher mid → positive PnL."""
    broker = _make_broker()
    broker.place_order(
        "EURUSD",
        OrderSide.BUY,
        10_000,
        order_type=OrderType.MARKET,
        client_extension_id="p-1",
    )
    # Entry bar -- opens at 1.1000.
    broker.submit_bar(
        "EURUSD",
        _candle(open_="1.1000", high="1.1005", low="1.0995", close="1.1000"),
    )

    pos = broker.get_position("EURUSD")
    assert pos is not None
    assert pos.units == 10_000
    assert pos.average_price == Decimal("1.1000")

    # Account snapshot: unrealized PnL ≈ (mid - entry) * units.
    # Bar mid = (1.1005 + 1.0995) / 2 = 1.1000 → 0 PnL initially.
    state_initial = broker.get_account_state()
    assert state_initial.unrealized_pl == Decimal(0)

    # Mark-to-market on a higher bar (no order placed -- just feed
    # a bar so the broker updates its mid).
    broker.submit_bar(
        "EURUSD",
        _candle(
            open_="1.1100",
            high="1.1110",
            low="1.1090",
            close="1.1100",
            minute=1,
        ),
    )
    # New mid = (1.1110 + 1.1090) / 2 = 1.1100; PnL = (1.11 - 1.10) * 10_000 = 100.
    state_after = broker.get_account_state()
    assert state_after.unrealized_pl == Decimal("100.0000")
    # Balance unchanged -- nothing realised.
    assert state_after.balance == Decimal("100000")


# ---------------------------------------------------------------------------
# Account bookkeeping: realised PnL on close
# ---------------------------------------------------------------------------


def test_account_balance_accumulates_realized_pnl_on_close() -> None:
    """Open 10_000 LONG @ 1.1000, close at 1.1100 → realised +100 to balance."""
    broker = _make_broker(starting_balance=Decimal("100000"))

    broker.place_order(
        "EURUSD",
        OrderSide.BUY,
        10_000,
        order_type=OrderType.MARKET,
        client_extension_id="open-1",
    )
    broker.submit_bar(
        "EURUSD",
        _candle(open_="1.1000", high="1.1005", low="1.0995", close="1.1000"),
    )

    broker.place_order(
        "EURUSD",
        OrderSide.SELL,
        10_000,
        order_type=OrderType.MARKET,
        client_extension_id="close-1",
    )
    broker.submit_bar(
        "EURUSD",
        _candle(
            open_="1.1100",
            high="1.1110",
            low="1.1090",
            close="1.1100",
            minute=1,
        ),
    )

    # Position fully closed.
    assert broker.get_position("EURUSD") is None

    # Realised PnL: (1.1100 - 1.1000) * 10_000 = 100 -> balance.
    state = broker.get_account_state()
    assert state.balance == Decimal("100100.0000")
    assert state.unrealized_pl == Decimal(0)


# ---------------------------------------------------------------------------
# Slippage
# ---------------------------------------------------------------------------


def test_one_pip_slippage_on_eurusd_buy_makes_fill_price_worse_by_0_0001() -> None:
    """1 pip slippage: BUY fills 0.0001 ABOVE the true fill price (paying more)."""
    broker = _make_broker(pip_slippage={"EURUSD": 1})
    broker.place_order(
        "EURUSD",
        OrderSide.BUY,
        10_000,
        order_type=OrderType.MARKET,
        client_extension_id="slip-1",
    )
    fills = broker.submit_bar(
        "EURUSD",
        _candle(open_="1.1000", high="1.1010", low="1.0990", close="1.1005"),
    )
    assert len(fills) == 1
    # True fill price = 1.1000, slippage adds 0.0001 → 1.1001.
    assert fills[0].fill_price == Decimal("1.1001")
    assert fills[0].slippage_pips == 1


def test_one_pip_slippage_on_eurusd_sell_makes_fill_price_worse_by_0_0001() -> None:
    """1 pip slippage: SELL fills 0.0001 BELOW the true fill price (receiving less)."""
    broker = _make_broker(pip_slippage={"EURUSD": 1})
    broker.place_order(
        "EURUSD",
        OrderSide.SELL,
        10_000,
        order_type=OrderType.MARKET,
        client_extension_id="slip-2",
    )
    fills = broker.submit_bar(
        "EURUSD",
        _candle(open_="1.1000", high="1.1010", low="1.0990", close="1.1005"),
    )
    assert len(fills) == 1
    assert fills[0].fill_price == Decimal("1.0999")
    assert fills[0].slippage_pips == 1


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def _run_scenario() -> tuple[list[FillEvent], dict[str, object]]:
    """Run a fixed order + bar stream and return (fills, snapshot)."""
    broker = _make_broker(pip_slippage={"EURUSD": 1})

    # Bar 0: open LONG via MARKET.
    broker.place_order(
        "EURUSD",
        OrderSide.BUY,
        10_000,
        order_type=OrderType.MARKET,
        client_extension_id="d-open",
    )
    f0 = broker.submit_bar(
        "EURUSD",
        _candle(open_="1.1000", high="1.1010", low="1.0995", close="1.1005"),
    )

    # Bar 1: place LIMIT BUY at 1.0980 (will not fill on this bar).
    broker.place_order(
        "EURUSD",
        OrderSide.BUY,
        5_000,
        order_type=OrderType.LIMIT,
        client_extension_id="d-limit",
        limit_price=Decimal("1.0980"),
    )
    f1 = broker.submit_bar(
        "EURUSD",
        _candle(
            open_="1.1005",
            high="1.1015",
            low="1.0990",
            close="1.1000",
            minute=1,
        ),
    )

    # Bar 2: low dips to 1.0975 -> LIMIT fills at 1.0980.
    f2 = broker.submit_bar(
        "EURUSD",
        _candle(
            open_="1.1000",
            high="1.1005",
            low="1.0975",
            close="1.0990",
            minute=2,
        ),
    )

    # Bar 3: close the WHOLE long position via MARKET SELL.
    broker.place_order(
        "EURUSD",
        OrderSide.SELL,
        15_000,
        order_type=OrderType.MARKET,
        client_extension_id="d-close",
    )
    f3 = broker.submit_bar(
        "EURUSD",
        _candle(
            open_="1.1100",
            high="1.1110",
            low="1.1090",
            close="1.1100",
            minute=3,
        ),
    )

    state = broker.get_account_state()
    snapshot: dict[str, object] = {
        "balance": state.balance,
        "unrealized_pl": state.unrealized_pl,
        "position": broker.get_position("EURUSD"),
    }
    return f0 + f1 + f2 + f3, snapshot


def test_same_orders_and_bars_produce_byte_identical_state() -> None:
    """Determinism: two independent runs of the same scenario produce identical results."""
    fills_a, snap_a = _run_scenario()
    fills_b, snap_b = _run_scenario()

    assert fills_a == fills_b
    assert snap_a == snap_b
    # And the position is None at the end of both runs (fully closed).
    assert snap_a["position"] is None


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_cancel_order_removes_pending_order_so_it_does_not_fill() -> None:
    """A cancelled LIMIT order does not fill on a bar that would have triggered it."""
    broker = _make_broker()
    ref = broker.place_order(
        "EURUSD",
        OrderSide.BUY,
        10_000,
        order_type=OrderType.LIMIT,
        client_extension_id="cancel-me",
        limit_price=Decimal("1.1000"),
    )
    broker.cancel_order(ref)
    assert broker.pending_orders() == []

    fills = broker.submit_bar(
        "EURUSD",
        _candle(open_="1.1010", high="1.1020", low="1.0990", close="1.1000"),
    )
    assert fills == []
    assert ref.broker_order_id in broker.cancelled_order_ids()


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


def test_place_order_rejects_empty_symbol() -> None:
    broker = _make_broker()
    with pytest.raises(ValueError, match="symbol must be non-empty"):
        broker.place_order(
            "",
            OrderSide.BUY,
            10_000,
            order_type=OrderType.MARKET,
            client_extension_id="x",
        )


def test_place_order_rejects_non_positive_units() -> None:
    broker = _make_broker()
    with pytest.raises(ValueError, match="units must be positive"):
        broker.place_order(
            "EURUSD",
            OrderSide.BUY,
            0,
            order_type=OrderType.MARKET,
            client_extension_id="x",
        )


def test_place_order_rejects_unsupported_symbol() -> None:
    """Unsupported symbol → PaperBrokerError (cannot compute pip-based slippage)."""
    broker = _make_broker()
    with pytest.raises(PaperBrokerError, match="not supported"):
        broker.place_order(
            "XAUUSD",  # not in the mock provider's seven majors
            OrderSide.BUY,
            10_000,
            order_type=OrderType.MARKET,
            client_extension_id="x",
        )


def test_submit_bar_rejects_symbol_mismatch() -> None:
    broker = _make_broker()
    with pytest.raises(ValueError, match="symbol mismatch"):
        broker.submit_bar(
            "GBPUSD",
            _candle(open_="1.1000", high="1.1010", low="1.0990", close="1.1005"),
        )


def test_constructor_rejects_negative_starting_balance() -> None:
    with pytest.raises(ValueError, match="starting_balance must be non-negative"):
        PaperBrokerAdapter(
            starting_balance=Decimal("-1"),
            market_data=MockMarketDataProvider(),
        )
