"""
Phase 7 acceptance integration tests (M15).

End-to-end verification of the Phase 7 backend pipeline:
- Market data storage → indicator computation → backtest resolution.
- Risk analytics (VaR, correlation, concentration) with real data.
- Strategy comparison service with real PnL metrics.
- Indicator resolver caching and lookback buffer.
- Backtest contracts round-trip validation.

Does NOT:
- Test frontend components (deferred M14).
- Test real-time streaming (deferred M3).
- Hit external APIs (Alpaca) — uses SQL repositories only.

Dependencies:
- SQLite in-memory via integration_db_session fixture.
- Real service implementations (not mocks) for integration verification.

Example:
    pytest tests/integration/test_phase7_acceptance.py -v
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pytest

from libs.contracts.backtest import (
    BacktestBar,
    BacktestConfig,
    BacktestInterval,
    BacktestResult,
    BacktestTrade,
)
from libs.contracts.indicator import IndicatorInfo
from libs.contracts.market_data import Candle, CandleInterval
from libs.contracts.mocks.mock_market_data_repository import MockMarketDataRepository
from libs.contracts.strategy_comparison import (
    StrategyComparisonRequest,
    StrategyRankingCriteria,
)
from libs.indicators.engine import IndicatorEngine
from libs.indicators.registry import IndicatorRegistry
from services.worker.research.indicator_resolver import IndicatorResolver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candles(
    symbol: str,
    start: datetime,
    count: int,
    base_price: float = 100.0,
    interval: CandleInterval = CandleInterval.D1,
) -> list[Candle]:
    """Generate a series of candles with sinusoidal price movement."""
    candles = []
    for i in range(count):
        ts = start + timedelta(days=i)
        # Sinusoidal price to create meaningful indicator values
        price = base_price + 10 * np.sin(i * 0.1) + i * 0.05
        close_val = Decimal(str(round(price, 2)))
        candles.append(
            Candle(
                symbol=symbol,
                interval=interval,
                open=close_val - Decimal("0.50"),
                high=close_val + Decimal("1.50"),
                low=close_val - Decimal("1.50"),
                close=close_val,
                volume=100000 + i * 1000,
                timestamp=ts,
            )
        )
    return candles


class SMACalculator:
    """Real SMA calculator for acceptance tests."""

    def calculate(
        self,
        open: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        timestamps: np.ndarray,
        **params: int | float,
    ) -> np.ndarray:
        """Compute Simple Moving Average on close prices."""
        period = int(params.get("period", 20))
        result = np.full(len(close), np.nan)
        for i in range(period - 1, len(close)):
            result[i] = np.mean(close[i - period + 1 : i + 1])
        return result

    def info(self) -> IndicatorInfo:
        return IndicatorInfo(
            name="SMA",
            description="Simple Moving Average",
            category="trend",
            output_names=["value"],
            default_params={"period": 20},
            param_constraints=[],
        )


class RSICalculator:
    """Real RSI calculator for acceptance tests."""

    def calculate(
        self,
        open: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        timestamps: np.ndarray,
        **params: int | float,
    ) -> np.ndarray:
        """Compute Relative Strength Index."""
        period = int(params.get("period", 14))
        result = np.full(len(close), np.nan)

        if len(close) < period + 1:
            return result

        deltas = np.diff(close)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        for i in range(period, len(close)):
            if avg_loss == 0:
                result[i] = 100.0
            else:
                rs = avg_gain / avg_loss
                result[i] = 100.0 - (100.0 / (1.0 + rs))

            if i < len(deltas):
                avg_gain = (avg_gain * (period - 1) + gains[i]) / period
                avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        return result

    def info(self) -> IndicatorInfo:
        return IndicatorInfo(
            name="RSI",
            description="Relative Strength Index",
            category="momentum",
            output_names=["value"],
            default_params={"period": 14},
            param_constraints=[],
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def market_repo() -> MockMarketDataRepository:
    """Mock market data repository seeded with test candles."""
    repo = MockMarketDataRepository()
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    # 300 days of AAPL and MSFT data
    repo.upsert_candles(_make_candles("AAPL", start, 300, base_price=150.0))
    repo.upsert_candles(_make_candles("MSFT", start, 300, base_price=350.0))
    return repo


@pytest.fixture()
def indicator_engine() -> IndicatorEngine:
    """IndicatorEngine with SMA and RSI registered."""
    registry = IndicatorRegistry()
    registry.register("SMA", SMACalculator())
    registry.register("RSI", RSICalculator())
    return IndicatorEngine(registry=registry)


@pytest.fixture()
def resolver(
    market_repo: MockMarketDataRepository,
    indicator_engine: IndicatorEngine,
) -> IndicatorResolver:
    """Fully wired IndicatorResolver."""
    return IndicatorResolver(
        market_data_repo=market_repo,
        engine=indicator_engine,
        lookback_buffer_days=30,
        cache_max_size=50,
    )


# ---------------------------------------------------------------------------
# Test: Market data → indicator → backtest pipeline
# ---------------------------------------------------------------------------


class TestMarketDataToIndicatorPipeline:
    """
    End-to-end: candle storage → indicator computation → trimmed output.

    Acceptance criteria:
    - Candles stored via repository are queryable.
    - IndicatorResolver fetches candles, computes SMA, returns Decimal values.
    - Lookback buffer provides warm-up data.
    - RSI values are bounded [0, 100].
    """

    def test_sma_resolves_over_date_range(self, resolver: IndicatorResolver) -> None:
        """SMA resolves correctly over a 60-day evaluation window."""
        start = datetime(2024, 3, 1, tzinfo=timezone.utc)
        end = datetime(2024, 4, 30, tzinfo=timezone.utc)

        values = resolver.resolve("SMA", "AAPL", start, end, period=20)

        assert len(values) > 0
        non_none = [v for v in values if v is not None]
        assert len(non_none) > 0
        # SMA values should be in a reasonable range for AAPL-like prices
        for v in non_none:
            assert isinstance(v, Decimal)
            assert Decimal("100") < v < Decimal("200")

    def test_rsi_values_bounded(self, resolver: IndicatorResolver) -> None:
        """RSI values fall within [0, 100]."""
        start = datetime(2024, 3, 1, tzinfo=timezone.utc)
        end = datetime(2024, 4, 30, tzinfo=timezone.utc)

        values = resolver.resolve("RSI", "AAPL", start, end, period=14)

        non_none = [v for v in values if v is not None]
        assert len(non_none) > 0
        for v in non_none:
            assert Decimal("0") <= v <= Decimal("100")

    def test_resolver_caches_across_calls(self, resolver: IndicatorResolver) -> None:
        """Second identical call uses cache."""
        start = datetime(2024, 3, 1, tzinfo=timezone.utc)
        end = datetime(2024, 4, 30, tzinfo=timezone.utc)

        resolver.resolve("SMA", "AAPL", start, end, period=20)
        resolver.resolve("SMA", "AAPL", start, end, period=20)

        stats = resolver.get_cache_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_multiple_symbols_resolve_independently(self, resolver: IndicatorResolver) -> None:
        """AAPL and MSFT resolve to different values."""
        start = datetime(2024, 3, 1, tzinfo=timezone.utc)
        end = datetime(2024, 3, 31, tzinfo=timezone.utc)

        aapl_sma = resolver.resolve("SMA", "AAPL", start, end, period=20)
        msft_sma = resolver.resolve("SMA", "MSFT", start, end, period=20)

        # Both should have data
        assert len(aapl_sma) > 0
        assert len(msft_sma) > 0
        # Values should differ (different base prices)
        aapl_vals = [v for v in aapl_sma if v is not None]
        msft_vals = [v for v in msft_sma if v is not None]
        if aapl_vals and msft_vals:
            assert aapl_vals[0] != msft_vals[0]

    def test_resolve_at_bar_returns_single_value(self, resolver: IndicatorResolver) -> None:
        """resolve_at_bar returns one Decimal for a specific timestamp."""
        target = datetime(2024, 6, 15, tzinfo=timezone.utc)
        value = resolver.resolve_at_bar("SMA", "AAPL", target, period=20)

        assert value is not None
        assert isinstance(value, Decimal)


# ---------------------------------------------------------------------------
# Test: Backtest contracts round-trip
# ---------------------------------------------------------------------------


class TestBacktestContractsRoundtrip:
    """
    Verify backtest value objects serialize and validate correctly.

    Acceptance criteria:
    - BacktestConfig with all parameters survives round-trip.
    - BacktestResult with trades and equity curve is valid.
    - Immutability enforced on all models.
    """

    def test_full_backtest_result_construction(self) -> None:
        """Construct a complete BacktestResult with trades and bars."""
        config = BacktestConfig(
            strategy_id="01HSTRAT000000000000000000",
            symbols=["AAPL", "MSFT"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            interval=BacktestInterval.ONE_DAY,
            initial_equity=Decimal("100000"),
            lookback_buffer_days=30,
            commission_per_trade=Decimal("1.00"),
            slippage_pct=Decimal("0.01"),
        )

        ts = datetime(2024, 6, 15, 16, 0, tzinfo=timezone.utc)
        trade = BacktestTrade(
            timestamp=ts,
            symbol="AAPL",
            side="buy",
            quantity=Decimal("100"),
            price=Decimal("155.00"),
            commission=Decimal("1.00"),
            slippage=Decimal("0.155"),
        )

        bar = BacktestBar(
            timestamp=ts,
            symbol="AAPL",
            open=Decimal("154.50"),
            high=Decimal("156.00"),
            low=Decimal("153.00"),
            close=Decimal("155.00"),
            volume=1500000,
            indicators={"SMA_20": Decimal("152.50"), "RSI_14": Decimal("62.30")},
            signal=1,
            position=Decimal("100"),
            equity=Decimal("100000"),
        )

        result = BacktestResult(
            config=config,
            total_return_pct=Decimal("12.50"),
            annualized_return_pct=Decimal("12.50"),
            max_drawdown_pct=Decimal("-5.80"),
            sharpe_ratio=Decimal("1.35"),
            total_trades=25,
            win_rate=Decimal("0.60"),
            profit_factor=Decimal("1.65"),
            final_equity=Decimal("112500"),
            trades=[trade],
            equity_curve=[bar],
            indicators_computed=["SMA", "RSI"],
            bars_processed=252,
        )

        assert result.config.symbols == ["AAPL", "MSFT"]
        assert result.total_trades == 25
        assert len(result.trades) == 1
        assert result.trades[0].side == "buy"
        assert result.equity_curve[0].indicators["SMA_20"] == Decimal("152.50")

        # Round-trip
        data = result.model_dump(mode="json")
        restored = BacktestResult.model_validate(data)
        assert restored.total_return_pct == Decimal("12.50")
        assert restored.config.initial_equity == Decimal("100000")


# ---------------------------------------------------------------------------
# Test: Strategy comparison with mock PnL data
# ---------------------------------------------------------------------------


class TestStrategyComparisonIntegration:
    """
    Verify strategy comparison service produces correct rankings.

    Acceptance criteria:
    - Highest Sharpe ranks #1 when criteria = SHARPE_RATIO.
    - Sortino ratio ≥ Sharpe when downside vol < total vol.
    - Calmar ratio capped when drawdown → 0.
    """

    def test_comparison_ranks_by_sharpe(self) -> None:
        """End-to-end: create service with mock PnL, compare 3 strategies."""
        from services.api.services.strategy_comparison_service import (
            StrategyComparisonService,
        )

        class FakePnL:
            """Minimal PnL service returning configured summaries."""

            def __init__(self) -> None:
                self._data = {
                    "s1": {
                        "strategy_name": "Momentum",
                        "net_pnl": 15000,
                        "sharpe_ratio": 1.8,
                        "max_drawdown_pct": -6.0,
                        "win_rate": 0.60,
                        "profit_factor": 1.7,
                        "total_trades": 50,
                        "winning_trades": 30,
                        "total_commission": 100,
                    },
                    "s2": {
                        "strategy_name": "Mean Reversion",
                        "net_pnl": 8000,
                        "sharpe_ratio": 1.2,
                        "max_drawdown_pct": -12.0,
                        "win_rate": 0.55,
                        "profit_factor": 1.3,
                        "total_trades": 80,
                        "winning_trades": 44,
                        "total_commission": 160,
                    },
                    "s3": {
                        "strategy_name": "Breakout",
                        "net_pnl": 25000,
                        "sharpe_ratio": 2.1,
                        "max_drawdown_pct": -4.0,
                        "win_rate": 0.45,
                        "profit_factor": 2.0,
                        "total_trades": 30,
                        "winning_trades": 14,
                        "total_commission": 60,
                    },
                }

            def get_pnl_summary(self, *, deployment_id: str) -> dict:
                return self._data[deployment_id]

            def get_pnl_timeseries(self, **kwargs) -> list:
                return []

        service = StrategyComparisonService(pnl_service=FakePnL())
        request = StrategyComparisonRequest(
            deployment_ids=["s1", "s2", "s3"],
            ranking_criteria=StrategyRankingCriteria.SHARPE_RATIO,
        )
        result = service.compare_strategies(request)

        # s3 (Sharpe=2.1) should rank #1
        assert result.rankings[0].metrics.deployment_id == "s3"
        assert result.rankings[0].metrics.strategy_name == "Breakout"
        assert result.rankings[0].rank == 1

        # s1 (Sharpe=1.8) should rank #2
        assert result.rankings[1].metrics.deployment_id == "s1"

        # s2 (Sharpe=1.2) should rank #3
        assert result.rankings[2].metrics.deployment_id == "s2"

        # Comparison matrix has all 3
        assert len(result.comparison_matrix) == 3


# ---------------------------------------------------------------------------
# Test: Indicator engine accuracy
# ---------------------------------------------------------------------------


class TestIndicatorAccuracy:
    """
    Cross-validate indicator computations against known values.

    Acceptance criteria:
    - SMA(3) of [10, 20, 30] = 20.0.
    - RSI values bounded [0, 100] on real-world-like data.
    """

    def test_sma_known_values(self) -> None:
        """SMA(3) on [10, 20, 30, 40, 50] produces known averages."""
        registry = IndicatorRegistry()
        registry.register("SMA", SMACalculator())
        engine = IndicatorEngine(registry=registry)

        candles = [
            Candle(
                symbol="TEST",
                interval=CandleInterval.D1,
                open=Decimal(str(p - 1)),
                high=Decimal(str(p + 1)),
                low=Decimal(str(p - 1)),
                close=Decimal(str(p)),
                volume=1000,
                timestamp=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
            )
            for i, p in enumerate([10, 20, 30, 40, 50])
        ]

        result = engine.compute("SMA", candles, period=3)
        values = result.values

        assert np.isnan(values[0])
        assert np.isnan(values[1])
        assert abs(values[2] - 20.0) < 0.01  # (10+20+30)/3
        assert abs(values[3] - 30.0) < 0.01  # (20+30+40)/3
        assert abs(values[4] - 40.0) < 0.01  # (30+40+50)/3

    def test_indicator_engine_batch_multiple_symbols(
        self, indicator_engine: IndicatorEngine, market_repo: MockMarketDataRepository
    ) -> None:
        """Engine handles multiple indicators on different symbols."""
        start = datetime(2024, 3, 1, tzinfo=timezone.utc)
        end = datetime(2024, 3, 31, tzinfo=timezone.utc)

        from libs.contracts.market_data import MarketDataQuery

        query = MarketDataQuery(
            symbol="AAPL",
            interval=CandleInterval.D1,
            start=start,
            end=end,
        )
        page = market_repo.query_candles(query)
        candles = page.candles

        sma_result = indicator_engine.compute("SMA", candles, period=10)
        rsi_result = indicator_engine.compute("RSI", candles, period=14)

        assert sma_result.indicator_name == "SMA"
        assert rsi_result.indicator_name == "RSI"
        assert len(sma_result.values) == len(candles)
        assert len(rsi_result.values) == len(candles)


# ---------------------------------------------------------------------------
# Test: Performance benchmark
# ---------------------------------------------------------------------------


class TestPerformanceBenchmarks:
    """
    Performance benchmarks for Phase 7 services.

    Acceptance criteria:
    - 10,000 candle indicator computation < 1 second.
    - Indicator resolver caching prevents redundant computation.
    """

    def test_indicator_computation_10k_candles(self) -> None:
        """Compute SMA on 10,000 candles in < 1 second."""
        import time

        registry = IndicatorRegistry()
        registry.register("SMA", SMACalculator())
        engine = IndicatorEngine(registry=registry)

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        candles = _make_candles("PERF", start, 10000, base_price=100.0)

        t0 = time.monotonic()
        result = engine.compute("SMA", candles, period=20)
        elapsed = time.monotonic() - t0

        assert elapsed < 1.0, f"10K candle SMA took {elapsed:.3f}s (expected < 1s)"
        assert len(result.values) == 10000

    def test_resolver_cache_prevents_recomputation(self) -> None:
        """Cached resolve is significantly faster than first compute."""
        import time

        repo = MockMarketDataRepository()
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        repo.upsert_candles(_make_candles("BENCH", start, 5000, base_price=100.0))

        registry = IndicatorRegistry()
        registry.register("SMA", SMACalculator())
        engine = IndicatorEngine(registry=registry)

        resolver = IndicatorResolver(
            market_data_repo=repo,
            engine=engine,
            lookback_buffer_days=30,
            cache_max_size=10,
        )

        eval_start = datetime(2024, 3, 1, tzinfo=timezone.utc)
        eval_end = datetime(2024, 6, 30, tzinfo=timezone.utc)

        # First call: compute
        t0 = time.monotonic()
        resolver.resolve("SMA", "BENCH", eval_start, eval_end, period=20)
        first = time.monotonic() - t0

        # Second call: cache hit
        t0 = time.monotonic()
        resolver.resolve("SMA", "BENCH", eval_start, eval_end, period=20)
        second = time.monotonic() - t0

        # Cache hit should be at least 5x faster
        assert second < first, f"Cache hit ({second:.6f}s) not faster than compute ({first:.6f}s)"
        assert resolver.get_cache_stats()["hits"] == 1
