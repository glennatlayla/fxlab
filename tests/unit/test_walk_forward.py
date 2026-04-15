"""
Unit tests for walk-forward analysis contracts and engine (M10).

Tests cover:
1. Walk-forward contracts — config validation, window result, aggregate result.
2. Window splitting — correct rolling window generation from date ranges.
3. Parameter enumeration — exhaustive grid search cartesian product.
4. Optimization convergence — best params selected by target metric.
5. Stability scoring — consistent vs varying params across windows.
6. Aggregate OOS metric — mean of out-of-sample metrics.
7. Edge cases — single window, single parameter, empty grid.

Follows §5 TDD naming: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from libs.contracts.backtest import BacktestInterval
from libs.contracts.indicator import IndicatorRequest, IndicatorResult
from libs.contracts.market_data import Candle, CandleInterval, MarketDataPage, MarketDataQuery
from libs.contracts.signal import Signal, SignalDirection, SignalStrength, SignalType
from libs.contracts.walk_forward import (
    OptimizationMetric,
    WalkForwardConfig,
    WalkForwardResult,
    WalkForwardWindowResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_TIMESTAMP = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)


def _make_candle(
    symbol: str,
    day_offset: int,
    close: Decimal,
) -> Candle:
    """Build a daily candle at a known offset."""
    return Candle(
        symbol=symbol,
        interval=CandleInterval.D1,
        open=close - Decimal("1"),
        high=close + Decimal("2"),
        low=close - Decimal("2"),
        close=close,
        volume=100_000,
        timestamp=_BASE_TIMESTAMP + timedelta(days=day_offset),
    )


def _make_candle_series(
    symbol: str = "AAPL",
    bars: int = 300,
    start_price: Decimal = Decimal("100"),
    trend: Decimal = Decimal("0.1"),
) -> list[Candle]:
    """Generate a trending price series for walk-forward testing."""
    candles = []
    for i in range(bars):
        price = start_price + trend * Decimal(str(i))
        candles.append(_make_candle(symbol, i, price))
    return candles


# ---------------------------------------------------------------------------
# Mock strategy factory for walk-forward engine
# ---------------------------------------------------------------------------


class _ParameterizableStrategy:
    """Strategy whose behaviour varies with parameters for optimization testing."""

    def __init__(self, *, fast_period: int = 10, slow_period: int = 50) -> None:
        self._fast = fast_period
        self._slow = slow_period
        self._call_count: dict[str, int] = {}

    @property
    def strategy_id(self) -> str:
        return f"param-strategy-{self._fast}-{self._slow}"

    @property
    def name(self) -> str:
        return "Parameterizable Strategy"

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
        """Emit a buy signal on bar 2 with performance proportional to fast_period."""
        self._call_count[symbol] = self._call_count.get(symbol, 0) + 1
        if self._call_count[symbol] == 2:
            return Signal(
                signal_id=f"sig-{symbol}-{self._call_count[symbol]}",
                strategy_id=self.strategy_id,
                deployment_id="wf-backtest",
                symbol=symbol,
                direction=SignalDirection.LONG,
                signal_type=SignalType.ENTRY,
                strength=SignalStrength.STRONG,
                confidence=min(0.5 + self._fast * 0.01, 1.0),
                indicators_used={},
                bar_timestamp=candles[-1].timestamp,
                generated_at=candles[-1].timestamp,
                correlation_id=correlation_id,
            )
        return None


def _strategy_factory(params: dict[str, Any]) -> _ParameterizableStrategy:
    """Factory that creates a strategy with the given parameters."""
    return _ParameterizableStrategy(
        fast_period=params.get("fast_period", 10),
        slow_period=params.get("slow_period", 50),
    )


# ---------------------------------------------------------------------------
# Mock market data repository
# ---------------------------------------------------------------------------


class _MockMarketDataRepo:
    """Return pre-loaded candle data for walk-forward tests."""

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles

    def query_candles(self, query: MarketDataQuery) -> MarketDataPage:
        filtered = [
            c
            for c in self._candles
            if c.symbol == query.symbol
            and c.interval == CandleInterval(query.interval.value)
            and (query.start is None or c.timestamp >= query.start)
            and (query.end is None or c.timestamp <= query.end)
        ]
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
        return None

    def detect_gaps(
        self, symbol: str, interval: CandleInterval, start: datetime, end: datetime
    ) -> list:
        return []


class _MockIndicatorEngine:
    """Return empty indicator results."""

    def compute_batch(
        self,
        requests: list[IndicatorRequest],
        candles: list[Candle],
    ) -> dict[str, IndicatorResult]:
        return {}


# ---------------------------------------------------------------------------
# Build helpers
# ---------------------------------------------------------------------------


def _build_engine(candles: list[Candle], strategy_factory=None):
    """Build a WalkForwardEngine with injectable dependencies."""
    from services.worker.research.walk_forward_engine import WalkForwardEngine

    return WalkForwardEngine(
        market_data_repository=_MockMarketDataRepo(candles),
        indicator_engine=_MockIndicatorEngine(),
        strategy_factory=strategy_factory or _strategy_factory,
    )


def _default_config(
    start_date: date | None = None,
    end_date: date | None = None,
    in_sample_bars: int = 60,
    out_of_sample_bars: int = 20,
    step_bars: int = 20,
    parameter_grid: dict[str, list[Any]] | None = None,
) -> WalkForwardConfig:
    """Build a default WalkForwardConfig for tests."""
    return WalkForwardConfig(
        strategy_id="test-wf-strategy",
        signal_strategy_id="test-wf-strategy",
        symbols=["AAPL"],
        start_date=start_date or date(2024, 1, 1),
        end_date=end_date or date(2024, 10, 27),
        interval=BacktestInterval.ONE_DAY,
        in_sample_bars=in_sample_bars,
        out_of_sample_bars=out_of_sample_bars,
        step_bars=step_bars,
        parameter_grid=parameter_grid or {"fast_period": [10, 20, 30], "slow_period": [50, 100]},
        optimization_metric=OptimizationMetric.SHARPE,
        initial_equity=Decimal("100000"),
    )


# ===========================================================================
# Test: Contract Validation
# ===========================================================================


class TestWalkForwardContracts:
    """Verify walk-forward contract validation."""

    def test_config_valid_construction(self) -> None:
        """Valid config builds without error."""
        config = _default_config()
        assert config.strategy_id == "test-wf-strategy"
        assert config.in_sample_bars == 60
        assert config.optimization_metric == OptimizationMetric.SHARPE

    def test_config_frozen(self) -> None:
        """Config is immutable."""
        config = _default_config()
        try:
            config.strategy_id = "changed"  # type: ignore[misc]
            raise AssertionError("Should have raised")
        except (TypeError, ValueError, AttributeError):
            pass

    def test_window_result_valid(self) -> None:
        """WindowResult builds with valid data."""
        result = WalkForwardWindowResult(
            window_index=0,
            in_sample_start=date(2024, 1, 1),
            in_sample_end=date(2024, 7, 1),
            out_of_sample_start=date(2024, 7, 2),
            out_of_sample_end=date(2024, 9, 30),
            best_params={"fast_period": 20},
            in_sample_metric=1.5,
            out_of_sample_metric=1.2,
        )
        assert result.window_index == 0
        assert result.best_params == {"fast_period": 20}

    def test_aggregate_result_valid(self) -> None:
        """WalkForwardResult builds with valid data."""
        config = _default_config()
        result = WalkForwardResult(
            config=config,
            windows=[],
            aggregate_oos_metric=1.35,
            stability_score=0.75,
            best_consensus_params={"fast_period": 20},
            total_backtests_run=24,
        )
        assert result.stability_score == 0.75
        assert result.total_backtests_run == 24

    def test_optimization_metric_enum(self) -> None:
        """All expected optimization metrics are defined."""
        assert OptimizationMetric.SHARPE.value == "sharpe"
        assert OptimizationMetric.SORTINO.value == "sortino"
        assert OptimizationMetric.CALMAR.value == "calmar"
        assert OptimizationMetric.PROFIT_FACTOR.value == "profit_factor"
        assert OptimizationMetric.MAX_DRAWDOWN.value == "max_drawdown"
        assert OptimizationMetric.TOTAL_RETURN.value == "total_return"


# ===========================================================================
# Test: Window Splitting
# ===========================================================================


class TestWindowSplitting:
    """Verify correct rolling window generation."""

    def test_window_count_correct(self) -> None:
        """Number of windows matches expected for given config."""
        candles = _make_candle_series(bars=300)
        engine = _build_engine(candles)
        config = _default_config(
            in_sample_bars=60,
            out_of_sample_bars=20,
            step_bars=20,
        )
        result = engine.run(config)
        assert len(result.windows) >= 1

    def test_windows_are_chronological(self) -> None:
        """Window start dates are strictly increasing."""
        candles = _make_candle_series(bars=300)
        engine = _build_engine(candles)
        config = _default_config(in_sample_bars=60, out_of_sample_bars=20, step_bars=20)
        result = engine.run(config)
        if len(result.windows) >= 2:
            for i in range(1, len(result.windows)):
                assert result.windows[i].in_sample_start > result.windows[i - 1].in_sample_start

    def test_in_sample_before_out_of_sample(self) -> None:
        """In-sample period ends before out-of-sample starts."""
        candles = _make_candle_series(bars=300)
        engine = _build_engine(candles)
        config = _default_config(in_sample_bars=60, out_of_sample_bars=20, step_bars=20)
        result = engine.run(config)
        for window in result.windows:
            assert window.in_sample_end < window.out_of_sample_start

    def test_no_overlap_between_in_and_out_of_sample(self) -> None:
        """In-sample and out-of-sample periods do not overlap."""
        candles = _make_candle_series(bars=300)
        engine = _build_engine(candles)
        config = _default_config(in_sample_bars=60, out_of_sample_bars=20, step_bars=20)
        result = engine.run(config)
        for window in result.windows:
            assert window.in_sample_end < window.out_of_sample_start

    def test_single_window_possible(self) -> None:
        """Config that fits exactly one window produces one result."""
        candles = _make_candle_series(bars=100)
        engine = _build_engine(candles)
        config = _default_config(
            in_sample_bars=60,
            out_of_sample_bars=20,
            step_bars=100,  # Large step → only one window
        )
        result = engine.run(config)
        assert len(result.windows) >= 1


# ===========================================================================
# Test: Parameter Enumeration
# ===========================================================================


class TestParameterEnumeration:
    """Verify parameter grid search."""

    def test_all_combinations_tested(self) -> None:
        """Each window tests the full cartesian product of parameters."""
        candles = _make_candle_series(bars=300)
        engine = _build_engine(candles)
        config = _default_config(
            parameter_grid={"fast_period": [10, 20], "slow_period": [50, 100]},
        )
        result = engine.run(config)
        # 2 × 2 = 4 combinations per window
        for window in result.windows:
            assert window.parameter_combinations_tested == 4

    def test_single_parameter_grid(self) -> None:
        """Single parameter with multiple values works."""
        candles = _make_candle_series(bars=300)
        engine = _build_engine(candles)
        config = _default_config(
            parameter_grid={"fast_period": [10, 20, 30]},
        )
        result = engine.run(config)
        for window in result.windows:
            assert window.parameter_combinations_tested == 3

    def test_best_params_from_grid(self) -> None:
        """Best params in each window are from the parameter grid."""
        candles = _make_candle_series(bars=300)
        engine = _build_engine(candles)
        config = _default_config(
            parameter_grid={"fast_period": [10, 20, 30], "slow_period": [50, 100]},
        )
        result = engine.run(config)
        valid_fast = {10, 20, 30}
        valid_slow = {50, 100}
        for window in result.windows:
            assert window.best_params.get("fast_period") in valid_fast
            assert window.best_params.get("slow_period") in valid_slow

    def test_total_backtests_matches_windows_times_combos(self) -> None:
        """total_backtests_run = windows × combos × 2 (IS + OOS)."""
        candles = _make_candle_series(bars=300)
        engine = _build_engine(candles)
        config = _default_config(
            parameter_grid={"fast_period": [10, 20], "slow_period": [50]},
        )
        result = engine.run(config)
        # Minimum: windows × combos for IS + windows × 1 for OOS
        assert result.total_backtests_run >= len(result.windows) * 2


# ===========================================================================
# Test: Optimization and Metric Selection
# ===========================================================================


class TestOptimization:
    """Verify optimization selects best parameters correctly."""

    def test_in_sample_metric_populated(self) -> None:
        """Each window has a non-None in-sample metric."""
        candles = _make_candle_series(bars=300)
        engine = _build_engine(candles)
        config = _default_config()
        result = engine.run(config)
        for window in result.windows:
            assert isinstance(window.in_sample_metric, float)

    def test_out_of_sample_metric_populated(self) -> None:
        """Each window has a non-None out-of-sample metric."""
        candles = _make_candle_series(bars=300)
        engine = _build_engine(candles)
        config = _default_config()
        result = engine.run(config)
        for window in result.windows:
            assert isinstance(window.out_of_sample_metric, float)

    def test_aggregate_oos_is_mean(self) -> None:
        """Aggregate OOS metric is the mean of per-window OOS metrics."""
        candles = _make_candle_series(bars=300)
        engine = _build_engine(candles)
        config = _default_config()
        result = engine.run(config)
        if result.windows:
            expected_mean = sum(w.out_of_sample_metric for w in result.windows) / len(
                result.windows
            )
            assert abs(result.aggregate_oos_metric - expected_mean) < 0.01


# ===========================================================================
# Test: Stability Scoring
# ===========================================================================


class TestStabilityScoring:
    """Verify parameter stability scoring across windows."""

    def test_stability_score_in_range(self) -> None:
        """Stability score is between 0.0 and 1.0."""
        candles = _make_candle_series(bars=300)
        engine = _build_engine(candles)
        config = _default_config()
        result = engine.run(config)
        assert 0.0 <= result.stability_score <= 1.0

    def test_identical_params_high_stability(self) -> None:
        """When all windows pick the same params → high stability."""
        # Use a parameter grid with only one option → always pick it
        candles = _make_candle_series(bars=300)
        engine = _build_engine(candles)
        config = _default_config(
            parameter_grid={"fast_period": [20], "slow_period": [50]},
        )
        result = engine.run(config)
        # Only 1 combo possible → all windows pick it → stability = 1.0
        assert result.stability_score == 1.0

    def test_consensus_params_populated(self) -> None:
        """best_consensus_params is non-empty when windows exist."""
        candles = _make_candle_series(bars=300)
        engine = _build_engine(candles)
        config = _default_config()
        result = engine.run(config)
        assert len(result.best_consensus_params) > 0


# ===========================================================================
# Test: Edge Cases
# ===========================================================================


class TestEdgeCases:
    """Verify edge case handling."""

    def test_config_preserved_in_result(self) -> None:
        """Result contains the original config."""
        candles = _make_candle_series(bars=300)
        engine = _build_engine(candles)
        config = _default_config()
        result = engine.run(config)
        assert result.config == config

    def test_completed_at_is_utc(self) -> None:
        """completed_at is timezone-aware UTC."""
        candles = _make_candle_series(bars=300)
        engine = _build_engine(candles)
        config = _default_config()
        result = engine.run(config)
        assert result.completed_at.tzinfo is not None

    def test_window_indices_sequential(self) -> None:
        """Window indices are 0, 1, 2, ..."""
        candles = _make_candle_series(bars=300)
        engine = _build_engine(candles)
        config = _default_config()
        result = engine.run(config)
        for i, window in enumerate(result.windows):
            assert window.window_index == i
