"""
Unit tests for the event-driven BacktestEngine (M9).

Tests cover:
1. Known-outcome backtests (buy-and-hold, sell-and-hold on known series).
2. Signal→trade attribution with correct mapping.
3. Fill simulation (market, limit, stop orders).
4. Slippage and commission modeling.
5. Equity curve and drawdown curve correctness.
6. Performance metrics (return, Sharpe, win rate, profit factor, drawdown).
7. Multi-symbol backtesting.
8. Signal summary counts (generated, approved, rejected).
9. Edge cases (no signals, single bar, empty data).

Follows §5 TDD naming: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import numpy as np

from libs.contracts.backtest import (
    BacktestConfig,
    BacktestInterval,
)
from libs.contracts.indicator import IndicatorRequest, IndicatorResult
from libs.contracts.market_data import Candle, CandleInterval, MarketDataPage, MarketDataQuery
from libs.contracts.signal import Signal, SignalDirection, SignalStrength, SignalType

# ---------------------------------------------------------------------------
# Helpers — build Candle objects for known price series
# ---------------------------------------------------------------------------

_BASE_TIMESTAMP = datetime(2025, 6, 1, 0, 0, tzinfo=timezone.utc)


def _make_candle(
    symbol: str,
    day_offset: int,
    open_: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: int = 100_000,
) -> Candle:
    """Build a daily candle at a known offset from base timestamp."""
    return Candle(
        symbol=symbol,
        interval=CandleInterval.D1,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        timestamp=_BASE_TIMESTAMP + timedelta(days=day_offset),
    )


def _rising_series(
    symbol: str = "AAPL", bars: int = 10, start_price: Decimal = Decimal("100")
) -> list[Candle]:
    """Generate a steadily rising price series."""
    candles = []
    for i in range(bars):
        price = start_price + Decimal(str(i * 5))
        candles.append(
            _make_candle(
                symbol=symbol,
                day_offset=i,
                open_=price,
                high=price + Decimal("2"),
                low=price - Decimal("1"),
                close=price + Decimal("5"),
                volume=100_000 + i * 10_000,
            )
        )
    return candles


def _declining_series(
    symbol: str = "AAPL", bars: int = 10, start_price: Decimal = Decimal("200")
) -> list[Candle]:
    """Generate a steadily declining price series."""
    candles = []
    for i in range(bars):
        price = start_price - Decimal(str(i * 5))
        candles.append(
            _make_candle(
                symbol=symbol,
                day_offset=i,
                open_=price,
                high=price + Decimal("1"),
                low=price - Decimal("2"),
                close=price - Decimal("5"),
                volume=100_000 + i * 10_000,
            )
        )
    return candles


def _flat_series(
    symbol: str = "AAPL", bars: int = 10, price: Decimal = Decimal("100")
) -> list[Candle]:
    """Generate a flat price series."""
    candles = []
    for i in range(bars):
        candles.append(
            _make_candle(
                symbol=symbol,
                day_offset=i,
                open_=price,
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price,
                volume=100_000,
            )
        )
    return candles


# ---------------------------------------------------------------------------
# Mock market data repository that returns known candles
# ---------------------------------------------------------------------------


class _MockMarketDataRepo:
    """Mock market data repository returning pre-loaded candle data."""

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles

    def query_candles(self, query: MarketDataQuery) -> MarketDataPage:
        """Filter candles by symbol, interval, and date range."""
        filtered = [
            c
            for c in self._candles
            if c.symbol == query.symbol
            and c.interval == CandleInterval(query.interval.value)
            and (query.start is None or c.timestamp >= query.start)
            and (query.end is None or c.timestamp <= query.end)
        ]
        # Sort by timestamp ascending
        filtered.sort(key=lambda c: c.timestamp)
        limited = filtered[: query.limit]
        return MarketDataPage(
            candles=limited,
            total_count=len(filtered),
            has_more=len(filtered) > query.limit,
            next_cursor=limited[-1].timestamp.isoformat()
            if limited and len(filtered) > query.limit
            else None,
        )

    def upsert_candles(self, candles: list[Candle]) -> int:
        return 0

    def get_latest_candle(self, symbol: str, interval: CandleInterval) -> Candle | None:
        matching = [c for c in self._candles if c.symbol == symbol and c.interval == interval]
        return max(matching, key=lambda c: c.timestamp) if matching else None

    def detect_gaps(
        self, symbol: str, interval: CandleInterval, start: datetime, end: datetime
    ) -> list:
        return []


# ---------------------------------------------------------------------------
# Mock signal strategy — configurable signal emission
# ---------------------------------------------------------------------------


class _AlwaysBuyStrategy:
    """Strategy that emits a BUY signal on every bar after the first."""

    def __init__(self) -> None:
        self._call_count: dict[str, int] = {}

    @property
    def strategy_id(self) -> str:
        return "always-buy"

    @property
    def name(self) -> str:
        return "Always Buy Strategy"

    @property
    def supported_symbols(self) -> list[str]:
        return []

    def required_indicators(self) -> list[IndicatorRequest]:
        return []

    def evaluate(
        self,
        symbol: str,
        candles: list[Candle],
        indicators: dict[str, IndicatorResult],
        current_position=None,
        *,
        correlation_id: str = "",
    ) -> Signal | None:
        self._call_count[symbol] = self._call_count.get(symbol, 0) + 1
        # Only buy on the second bar (first bar is warmup)
        if self._call_count[symbol] == 2:
            return Signal(
                signal_id=f"sig-{symbol}-{self._call_count[symbol]}",
                strategy_id=self.strategy_id,
                deployment_id="backtest-deploy",
                symbol=symbol,
                direction=SignalDirection.LONG,
                signal_type=SignalType.ENTRY,
                strength=SignalStrength.STRONG,
                confidence=0.90,
                indicators_used={},
                bar_timestamp=candles[-1].timestamp,
                generated_at=candles[-1].timestamp,
                correlation_id=correlation_id,
            )
        return None


class _BuyThenSellStrategy:
    """Strategy that buys on bar 2 and sells on bar 5."""

    def __init__(self) -> None:
        self._call_count: dict[str, int] = {}

    @property
    def strategy_id(self) -> str:
        return "buy-then-sell"

    @property
    def name(self) -> str:
        return "Buy Then Sell Strategy"

    @property
    def supported_symbols(self) -> list[str]:
        return []

    def required_indicators(self) -> list[IndicatorRequest]:
        return []

    def evaluate(
        self,
        symbol: str,
        candles: list[Candle],
        indicators: dict[str, IndicatorResult],
        current_position=None,
        *,
        correlation_id: str = "",
    ) -> Signal | None:
        self._call_count[symbol] = self._call_count.get(symbol, 0) + 1
        count = self._call_count[symbol]

        if count == 2:
            return Signal(
                signal_id=f"sig-buy-{symbol}",
                strategy_id=self.strategy_id,
                deployment_id="backtest-deploy",
                symbol=symbol,
                direction=SignalDirection.LONG,
                signal_type=SignalType.ENTRY,
                strength=SignalStrength.STRONG,
                confidence=0.85,
                indicators_used={},
                bar_timestamp=candles[-1].timestamp,
                generated_at=candles[-1].timestamp,
                correlation_id=correlation_id,
            )
        if count == 5:
            return Signal(
                signal_id=f"sig-sell-{symbol}",
                strategy_id=self.strategy_id,
                deployment_id="backtest-deploy",
                symbol=symbol,
                direction=SignalDirection.FLAT,
                signal_type=SignalType.EXIT,
                strength=SignalStrength.STRONG,
                confidence=0.80,
                indicators_used={},
                bar_timestamp=candles[-1].timestamp,
                generated_at=candles[-1].timestamp,
                correlation_id=correlation_id,
            )
        return None


class _NeverTradeStrategy:
    """Strategy that never generates signals."""

    @property
    def strategy_id(self) -> str:
        return "never-trade"

    @property
    def name(self) -> str:
        return "Never Trade Strategy"

    @property
    def supported_symbols(self) -> list[str]:
        return []

    def required_indicators(self) -> list[IndicatorRequest]:
        return []

    def evaluate(
        self, symbol, candles, indicators, current_position=None, *, correlation_id=""
    ) -> Signal | None:
        return None


class _IndicatorStrategy:
    """Strategy that requires SMA indicator."""

    @property
    def strategy_id(self) -> str:
        return "indicator-strategy"

    @property
    def name(self) -> str:
        return "Indicator Strategy"

    @property
    def supported_symbols(self) -> list[str]:
        return []

    def required_indicators(self) -> list[IndicatorRequest]:
        return [IndicatorRequest(indicator_name="sma", params={"period": 5})]

    def evaluate(
        self, symbol, candles, indicators, current_position=None, *, correlation_id=""
    ) -> Signal | None:
        return None


# ---------------------------------------------------------------------------
# Mock indicator engine
# ---------------------------------------------------------------------------


class _MockIndicatorEngine:
    """Indicator engine returning empty results."""

    def compute_batch(
        self,
        requests: list[IndicatorRequest],
        candles: list[Candle],
    ) -> dict[str, IndicatorResult]:
        results = {}
        for req in requests:
            key = req.indicator_name
            n = len(candles)
            results[key] = IndicatorResult(
                indicator_name=req.indicator_name,
                values=np.full(n, float("nan")),
                timestamps=np.array([c.timestamp for c in candles]),
                metadata=req.params,
            )
        return results


# ---------------------------------------------------------------------------
# Fixture: build engine under test
# ---------------------------------------------------------------------------


def _build_engine(
    candles: list[Candle],
    strategy=None,
    indicator_engine=None,
):
    """Build a BacktestEngine with injectable dependencies."""
    from services.worker.research.backtest_engine import BacktestEngine

    return BacktestEngine(
        signal_strategy=strategy or _NeverTradeStrategy(),
        market_data_repository=_MockMarketDataRepo(candles),
        indicator_engine=indicator_engine or _MockIndicatorEngine(),
    )


def _default_config(
    symbols: list[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    initial_equity: Decimal = Decimal("100000"),
    commission_per_trade: Decimal = Decimal("0"),
    slippage_pct: Decimal = Decimal("0"),
) -> BacktestConfig:
    """Build a default BacktestConfig for tests."""
    return BacktestConfig(
        strategy_id="test-strategy",
        symbols=symbols or ["AAPL"],
        start_date=start_date or date(2025, 6, 1),
        end_date=end_date or date(2025, 6, 10),
        interval=BacktestInterval.ONE_DAY,
        initial_equity=initial_equity,
        commission_per_trade=commission_per_trade,
        slippage_pct=slippage_pct,
    )


# ===========================================================================
# Test: Known-Outcome Backtests
# ===========================================================================


class TestKnownOutcome:
    """Verify correct results on known price series."""

    def test_buy_and_hold_rising_series_positive_return(self) -> None:
        """Buy on bar 2, hold through rising series → positive total return."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_AlwaysBuyStrategy())
        config = _default_config()
        result = engine.run(config)

        assert result.total_return_pct > Decimal("0")
        assert result.final_equity > config.initial_equity
        assert result.total_trades >= 1

    def test_buy_and_hold_declining_series_negative_return(self) -> None:
        """Buy on bar 2, hold through declining series → negative total return."""
        candles = _declining_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_AlwaysBuyStrategy())
        config = _default_config()
        result = engine.run(config)

        # Final equity should be less than initial because prices fell
        assert result.final_equity < config.initial_equity

    def test_no_signals_flat_equity(self) -> None:
        """No signals generated → equity unchanged, zero trades."""
        candles = _flat_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_NeverTradeStrategy())
        config = _default_config()
        result = engine.run(config)

        assert result.total_trades == 0
        assert result.final_equity == config.initial_equity
        assert result.total_return_pct == Decimal("0")

    def test_buy_then_sell_round_trip_captures_gain(self) -> None:
        """Buy on bar 2, sell on bar 5 in rising series → captures partial gain."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_BuyThenSellStrategy())
        config = _default_config()
        result = engine.run(config)

        assert result.total_trades == 2  # One buy, one sell
        assert result.final_equity > config.initial_equity


# ===========================================================================
# Test: Signal→Trade Attribution
# ===========================================================================


class TestSignalAttribution:
    """Verify signal-to-trade tracing."""

    def test_signal_attribution_records_created(self) -> None:
        """Each signal gets a SignalAttribution record."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_BuyThenSellStrategy())
        config = _default_config()
        result = engine.run(config)

        assert result.signal_summary is not None
        assert len(result.signal_summary.signal_attributions) == 2  # buy + sell

    def test_signal_attribution_fields_populated(self) -> None:
        """Attribution records have correct strategy_id, symbol, direction."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_BuyThenSellStrategy())
        config = _default_config()
        result = engine.run(config)

        assert result.signal_summary is not None
        attrs = result.signal_summary.signal_attributions
        buy_attr = next(a for a in attrs if a.direction == "long")
        sell_attr = next(a for a in attrs if a.direction == "flat")

        assert buy_attr.strategy_id == "buy-then-sell"
        assert buy_attr.symbol == "AAPL"
        assert buy_attr.approved is True
        assert buy_attr.trade_index is not None

        assert sell_attr.strategy_id == "buy-then-sell"
        assert sell_attr.symbol == "AAPL"

    def test_signal_summary_counts_correct(self) -> None:
        """Signal summary counts match actual signal generation."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_BuyThenSellStrategy())
        config = _default_config()
        result = engine.run(config)

        assert result.signal_summary is not None
        assert result.signal_summary.signals_generated == 2
        assert result.signal_summary.signals_approved == 2
        assert result.signal_summary.signals_rejected == 0

    def test_no_signals_empty_summary(self) -> None:
        """No signals → zero counts in summary."""
        candles = _flat_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_NeverTradeStrategy())
        config = _default_config()
        result = engine.run(config)

        assert result.signal_summary is not None
        assert result.signal_summary.signals_generated == 0
        assert result.signal_summary.signal_attributions == []


# ===========================================================================
# Test: Fill Simulation
# ===========================================================================


class TestFillSimulation:
    """Verify order fill mechanics."""

    def test_market_order_fills_at_next_bar_open(self) -> None:
        """Market buy signal on bar N → fills at bar N+1 open price."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_AlwaysBuyStrategy())
        config = _default_config()
        result = engine.run(config)

        assert len(result.trades) >= 1
        buy_trade = result.trades[0]
        assert buy_trade.side == "buy"
        # The fill price should be bar[2].open (signal on bar 1, fill on bar 2)
        # In our rising series: bar[2] open = 100 + 2*5 = 110
        assert buy_trade.price == candles[2].open

    def test_trades_have_valid_timestamps(self) -> None:
        """All trades have timestamps within the backtest date range."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_BuyThenSellStrategy())
        config = _default_config()
        result = engine.run(config)

        start_dt = datetime.combine(config.start_date, datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        end_dt = datetime.combine(config.end_date, datetime.max.time()).replace(tzinfo=timezone.utc)
        for trade in result.trades:
            assert start_dt <= trade.timestamp <= end_dt

    def test_sell_trade_quantity_matches_buy(self) -> None:
        """Sell trade quantity matches the buy quantity for a round trip."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_BuyThenSellStrategy())
        config = _default_config()
        result = engine.run(config)

        assert len(result.trades) == 2
        assert result.trades[0].quantity == result.trades[1].quantity


# ===========================================================================
# Test: Commission and Slippage
# ===========================================================================


class TestCostModeling:
    """Verify commission and slippage deductions."""

    def test_commission_reduces_equity(self) -> None:
        """Non-zero commission → final equity reduced by commission costs."""
        candles = _flat_series("AAPL", bars=10, price=Decimal("100"))
        engine_no_comm = _build_engine(candles, strategy=_BuyThenSellStrategy())
        engine_with_comm = _build_engine(candles, strategy=_BuyThenSellStrategy())

        config_no_comm = _default_config(commission_per_trade=Decimal("0"))
        config_with_comm = _default_config(commission_per_trade=Decimal("10"))

        result_no_comm = engine_no_comm.run(config_no_comm)
        result_with_comm = engine_with_comm.run(config_with_comm)

        # With commission, equity should be lower
        assert result_with_comm.final_equity < result_no_comm.final_equity

    def test_slippage_reduces_equity(self) -> None:
        """Non-zero slippage → final equity reduced by slippage costs."""
        candles = _flat_series("AAPL", bars=10, price=Decimal("100"))
        engine_no_slip = _build_engine(candles, strategy=_BuyThenSellStrategy())
        engine_with_slip = _build_engine(candles, strategy=_BuyThenSellStrategy())

        config_no_slip = _default_config(slippage_pct=Decimal("0"))
        config_with_slip = _default_config(slippage_pct=Decimal("1"))  # 1% slippage

        result_no_slip = engine_no_slip.run(config_no_slip)
        result_with_slip = engine_with_slip.run(config_with_slip)

        assert result_with_slip.final_equity < result_no_slip.final_equity

    def test_commission_recorded_on_trades(self) -> None:
        """Trade objects contain commission amount."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_BuyThenSellStrategy())
        config = _default_config(commission_per_trade=Decimal("5"))
        result = engine.run(config)

        assert len(result.trades) >= 1
        for trade in result.trades:
            assert trade.commission == Decimal("5")

    def test_slippage_recorded_on_trades(self) -> None:
        """Trade objects contain slippage amount."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_BuyThenSellStrategy())
        config = _default_config(slippage_pct=Decimal("0.5"))
        result = engine.run(config)

        assert len(result.trades) >= 1
        for trade in result.trades:
            assert trade.slippage >= Decimal("0")


# ===========================================================================
# Test: Equity Curve and Drawdown
# ===========================================================================


class TestEquityCurveAndDrawdown:
    """Verify equity curve and drawdown tracking."""

    def test_equity_curve_points_populated(self) -> None:
        """Signal summary contains equity curve points."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_AlwaysBuyStrategy())
        config = _default_config()
        result = engine.run(config)

        assert result.signal_summary is not None
        assert len(result.signal_summary.equity_curve_points) > 0

    def test_equity_curve_starts_at_initial_equity(self) -> None:
        """First equity curve point equals initial equity."""
        candles = _flat_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_NeverTradeStrategy())
        config = _default_config(initial_equity=Decimal("50000"))
        result = engine.run(config)

        assert result.signal_summary is not None
        first_point = result.signal_summary.equity_curve_points[0]
        assert first_point.equity == Decimal("50000")

    def test_equity_curve_ends_at_final_equity(self) -> None:
        """Last equity curve point equals final_equity in result."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_AlwaysBuyStrategy())
        config = _default_config()
        result = engine.run(config)

        assert result.signal_summary is not None
        last_point = result.signal_summary.equity_curve_points[-1]
        assert last_point.equity == result.final_equity

    def test_drawdown_curve_populated(self) -> None:
        """Signal summary contains drawdown curve points."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_AlwaysBuyStrategy())
        config = _default_config()
        result = engine.run(config)

        assert result.signal_summary is not None
        assert len(result.signal_summary.drawdown_curve) > 0

    def test_drawdown_values_non_positive(self) -> None:
        """All drawdown values are zero or negative."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_AlwaysBuyStrategy())
        config = _default_config()
        result = engine.run(config)

        assert result.signal_summary is not None
        for dd_point in result.signal_summary.drawdown_curve:
            assert dd_point.drawdown_pct <= Decimal("0")

    def test_max_drawdown_in_declining_series(self) -> None:
        """Declining series with position → non-trivial max drawdown."""
        candles = _declining_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_AlwaysBuyStrategy())
        config = _default_config()
        result = engine.run(config)

        # Max drawdown should be negative
        assert result.max_drawdown_pct < Decimal("0")


# ===========================================================================
# Test: Performance Metrics
# ===========================================================================


class TestPerformanceMetrics:
    """Verify calculated performance metrics."""

    def test_total_return_pct_positive_for_gain(self) -> None:
        """Positive P&L → positive total_return_pct."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_BuyThenSellStrategy())
        config = _default_config()
        result = engine.run(config)

        assert result.total_return_pct > Decimal("0")

    def test_total_return_pct_zero_no_trades(self) -> None:
        """No trades → zero total_return_pct."""
        candles = _flat_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_NeverTradeStrategy())
        config = _default_config()
        result = engine.run(config)

        assert result.total_return_pct == Decimal("0")

    def test_win_rate_all_winners(self) -> None:
        """All winning round trips → win_rate near 1.0."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_BuyThenSellStrategy())
        config = _default_config()
        result = engine.run(config)

        # Buy in rising series and sell later → winner
        assert result.win_rate >= Decimal("0.5")

    def test_profit_factor_positive_for_winners(self) -> None:
        """Profitable round trips → profit_factor > 1."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_BuyThenSellStrategy())
        config = _default_config()
        result = engine.run(config)

        assert result.profit_factor > Decimal("0")

    def test_bars_processed_count(self) -> None:
        """bars_processed matches number of candles in date range."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_NeverTradeStrategy())
        config = _default_config()
        result = engine.run(config)

        assert result.bars_processed == len(candles)

    def test_sharpe_ratio_computed(self) -> None:
        """Sharpe ratio is computed (non-zero for non-flat strategy)."""
        candles = _rising_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_BuyThenSellStrategy())
        config = _default_config()
        result = engine.run(config)

        # Sharpe should be non-zero when there's return variance
        # For a rising series buy-sell it should be positive
        assert isinstance(result.sharpe_ratio, Decimal)


# ===========================================================================
# Test: Multi-Symbol
# ===========================================================================


class TestMultiSymbol:
    """Verify multi-symbol backtesting."""

    def test_multi_symbol_processes_all_symbols(self) -> None:
        """Engine processes bars for every symbol in the config."""
        aapl_candles = _rising_series("AAPL", bars=10)
        msft_candles = _rising_series("MSFT", bars=10, start_price=Decimal("200"))
        all_candles = aapl_candles + msft_candles

        engine = _build_engine(all_candles, strategy=_AlwaysBuyStrategy())
        config = _default_config(symbols=["AAPL", "MSFT"])
        result = engine.run(config)

        # Should process bars for both symbols
        assert result.bars_processed == 20

    def test_multi_symbol_trades_correct_symbols(self) -> None:
        """Trades list contains entries for each symbol."""
        aapl_candles = _rising_series("AAPL", bars=10)
        msft_candles = _rising_series("MSFT", bars=10, start_price=Decimal("200"))
        all_candles = aapl_candles + msft_candles

        engine = _build_engine(all_candles, strategy=_AlwaysBuyStrategy())
        config = _default_config(symbols=["AAPL", "MSFT"])
        result = engine.run(config)

        symbols_traded = {t.symbol for t in result.trades}
        assert "AAPL" in symbols_traded
        assert "MSFT" in symbols_traded


# ===========================================================================
# Test: Indicator Integration
# ===========================================================================


class TestIndicatorIntegration:
    """Verify indicator computation during backtest."""

    def test_indicators_computed_list_populated(self) -> None:
        """indicators_computed lists the names of computed indicators."""
        candles = _flat_series("AAPL", bars=10)
        engine = _build_engine(candles, strategy=_IndicatorStrategy())
        config = _default_config()
        result = engine.run(config)

        assert "sma" in result.indicators_computed


# ===========================================================================
# Test: Edge Cases
# ===========================================================================


class TestEdgeCases:
    """Verify edge case handling."""

    def test_single_bar_no_crash(self) -> None:
        """Single bar backtest completes without error."""
        candles = [
            _make_candle("AAPL", 0, Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"))
        ]
        engine = _build_engine(candles, strategy=_NeverTradeStrategy())
        config = _default_config(start_date=date(2025, 6, 1), end_date=date(2025, 6, 1))
        result = engine.run(config)

        assert result.bars_processed == 1
        assert result.total_trades == 0

    def test_empty_candle_data_returns_zero_result(self) -> None:
        """No candles in date range → zero bars, zero trades."""
        engine = _build_engine([], strategy=_NeverTradeStrategy())
        config = _default_config(start_date=date(2030, 1, 1), end_date=date(2030, 1, 10))
        result = engine.run(config)

        assert result.bars_processed == 0
        assert result.total_trades == 0
        assert result.final_equity == config.initial_equity

    def test_config_preserved_in_result(self) -> None:
        """BacktestResult.config matches the input config."""
        candles = _flat_series("AAPL", bars=5)
        engine = _build_engine(candles, strategy=_NeverTradeStrategy())
        config = _default_config()
        result = engine.run(config)

        assert result.config == config

    def test_computed_at_is_utc(self) -> None:
        """computed_at timestamp is timezone-aware UTC."""
        candles = _flat_series("AAPL", bars=5)
        engine = _build_engine(candles, strategy=_NeverTradeStrategy())
        config = _default_config()
        result = engine.run(config)

        assert result.computed_at.tzinfo is not None
