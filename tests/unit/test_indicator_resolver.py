"""
Unit tests for IndicatorResolver (Phase 7 — M12).

Verifies:
- Indicator resolution over date ranges with lookback buffer.
- Single-bar resolution via resolve_at_bar.
- LRU cache behaviour (hits, misses, eviction).
- Cache clearing and statistics.
- Handling of empty candle data.
- NaN / None value handling in indicator output.
- Cache key determinism.
- Bars-to-days estimation for various intervals.

Dependencies:
- MockMarketDataRepository (libs/contracts/mocks): candle data source.
- IndicatorEngine + IndicatorRegistry: compute indicators.
- IndicatorResolver: unit under test.
- SMA indicator (libs/indicators/trend): real indicator for integration-style tests.

Example:
    pytest tests/unit/test_indicator_resolver.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pytest

from libs.contracts.errors import IndicatorNotFoundError
from libs.contracts.indicator import IndicatorInfo
from libs.contracts.market_data import Candle, CandleInterval
from libs.contracts.mocks.mock_market_data_repository import MockMarketDataRepository
from libs.indicators.engine import IndicatorEngine
from libs.indicators.registry import IndicatorRegistry
from services.worker.research.indicator_resolver import IndicatorResolver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candle(
    symbol: str,
    ts: datetime,
    close: Decimal,
    *,
    interval: CandleInterval = CandleInterval.D1,
) -> Candle:
    """Build a Candle with minimal OHLCV, close as the primary price."""
    return Candle(
        symbol=symbol,
        interval=interval,
        open=close - Decimal("1"),
        high=close + Decimal("1"),
        low=close - Decimal("2"),
        close=close,
        volume=100000,
        timestamp=ts,
    )


def _make_candle_series(
    symbol: str,
    start: datetime,
    count: int,
    base_price: Decimal = Decimal("100"),
    interval: CandleInterval = CandleInterval.D1,
) -> list[Candle]:
    """Generate a series of daily candles with incrementing prices."""
    candles = []
    for i in range(count):
        ts = start + timedelta(days=i)
        price = base_price + Decimal(str(i))
        candles.append(_make_candle(symbol, ts, price, interval=interval))
    return candles


class StubSMACalculator:
    """
    Stub calculator that computes a simple moving average.

    Satisfies the IndicatorCalculator protocol (calculate + info methods)
    so it can be registered with IndicatorRegistry for testing.
    """

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
        """Compute SMA over close prices."""
        period = int(params.get("period", 3))
        result = np.full(len(close), np.nan)
        for i in range(period - 1, len(close)):
            result[i] = float(np.mean(close[i - period + 1 : i + 1]))
        return result

    def info(self) -> IndicatorInfo:
        """Return metadata for this test calculator."""
        return IndicatorInfo(
            name="TEST_SMA",
            description="Test SMA stub for unit tests",
            category="test",
            output_names=["value"],
            default_params={"period": 3},
            param_constraints=[],
        )


class NaNIndicatorCalculator:
    """Calculator that returns all NaN values for testing NaN handling."""

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
        """Return all NaN values."""
        return np.full(len(close), np.nan)

    def info(self) -> IndicatorInfo:
        """Return metadata for this test calculator."""
        return IndicatorInfo(
            name="NAN_IND",
            description="Returns all NaN for testing",
            category="test",
            output_names=["value"],
            default_params={},
            param_constraints=[],
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_repo() -> MockMarketDataRepository:
    """Fresh mock market data repository."""
    return MockMarketDataRepository()


@pytest.fixture()
def engine() -> IndicatorEngine:
    """IndicatorEngine with test calculators registered."""
    registry = IndicatorRegistry()
    stub = StubSMACalculator()
    nan_calc = NaNIndicatorCalculator()
    registry.register("TEST_SMA", stub)
    registry.register("NAN_IND", nan_calc)
    return IndicatorEngine(registry=registry)


@pytest.fixture()
def resolver(mock_repo: MockMarketDataRepository, engine: IndicatorEngine) -> IndicatorResolver:
    """IndicatorResolver with small cache and 10-day lookback for testing."""
    return IndicatorResolver(
        market_data_repo=mock_repo,
        engine=engine,
        lookback_buffer_days=10,
        cache_max_size=3,
    )


@pytest.fixture()
def base_ts() -> datetime:
    """Base timestamp for test candle series."""
    return datetime(2025, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# resolve() tests
# ---------------------------------------------------------------------------


class TestResolve:
    """Tests for IndicatorResolver.resolve()."""

    def test_resolve_returns_values_for_date_range(
        self,
        mock_repo: MockMarketDataRepository,
        resolver: IndicatorResolver,
        base_ts: datetime,
    ) -> None:
        """resolve() returns trimmed indicator values within [start, end]."""
        # Seed 30 days of candles (10-day lookback buffer + 20 days in range)
        candles = _make_candle_series("AAPL", base_ts - timedelta(days=10), 30)
        mock_repo.upsert_candles(candles)

        start = base_ts
        end = base_ts + timedelta(days=19)
        values = resolver.resolve("TEST_SMA", "AAPL", start, end, period=3)

        # Should have values for the 20 bars in [start, end]
        assert len(values) > 0
        # All values should be Decimal or None
        for v in values:
            assert v is None or isinstance(v, Decimal)

    def test_resolve_returns_empty_when_no_candles(
        self,
        resolver: IndicatorResolver,
        base_ts: datetime,
    ) -> None:
        """resolve() returns empty list when repo has no candles."""
        values = resolver.resolve(
            "TEST_SMA", "AAPL", base_ts, base_ts + timedelta(days=10), period=3
        )
        assert values == []

    def test_resolve_caches_results(
        self,
        mock_repo: MockMarketDataRepository,
        resolver: IndicatorResolver,
        base_ts: datetime,
    ) -> None:
        """Second call with same params returns cached result."""
        candles = _make_candle_series("AAPL", base_ts - timedelta(days=10), 30)
        mock_repo.upsert_candles(candles)

        start = base_ts
        end = base_ts + timedelta(days=9)

        first = resolver.resolve("TEST_SMA", "AAPL", start, end, period=3)
        second = resolver.resolve("TEST_SMA", "AAPL", start, end, period=3)

        assert first == second
        stats = resolver.get_cache_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_resolve_evicts_oldest_when_cache_full(
        self,
        mock_repo: MockMarketDataRepository,
        resolver: IndicatorResolver,
        base_ts: datetime,
    ) -> None:
        """Cache evicts LRU entry when max_size exceeded (cache_max_size=3)."""
        candles = _make_candle_series("AAPL", base_ts - timedelta(days=10), 50)
        mock_repo.upsert_candles(candles)

        # Fill cache with 3 entries (different date ranges)
        for i in range(3):
            start = base_ts + timedelta(days=i * 5)
            end = start + timedelta(days=4)
            resolver.resolve("TEST_SMA", "AAPL", start, end, period=3)

        assert resolver.get_cache_stats()["size"] == 3

        # Add a 4th — should evict the first
        start = base_ts + timedelta(days=15)
        end = start + timedelta(days=4)
        resolver.resolve("TEST_SMA", "AAPL", start, end, period=3)

        assert resolver.get_cache_stats()["size"] == 3
        assert resolver.get_cache_stats()["misses"] == 4

    def test_resolve_different_params_are_separate_cache_keys(
        self,
        mock_repo: MockMarketDataRepository,
        resolver: IndicatorResolver,
        base_ts: datetime,
    ) -> None:
        """Different indicator params produce different cache entries."""
        candles = _make_candle_series("AAPL", base_ts - timedelta(days=10), 30)
        mock_repo.upsert_candles(candles)

        start = base_ts
        end = base_ts + timedelta(days=9)

        resolver.resolve("TEST_SMA", "AAPL", start, end, period=3)
        resolver.resolve("TEST_SMA", "AAPL", start, end, period=5)

        assert resolver.get_cache_stats()["size"] == 2
        assert resolver.get_cache_stats()["misses"] == 2

    def test_resolve_handles_nan_values(
        self,
        mock_repo: MockMarketDataRepository,
        resolver: IndicatorResolver,
        base_ts: datetime,
    ) -> None:
        """NaN indicator values are converted to None."""
        candles = _make_candle_series("AAPL", base_ts - timedelta(days=10), 20)
        mock_repo.upsert_candles(candles)

        start = base_ts
        end = base_ts + timedelta(days=9)
        values = resolver.resolve("NAN_IND", "AAPL", start, end)

        # All values should be None since NaN_IND returns all NaN
        assert all(v is None for v in values)

    def test_resolve_raises_on_unknown_indicator(
        self,
        mock_repo: MockMarketDataRepository,
        resolver: IndicatorResolver,
        base_ts: datetime,
    ) -> None:
        """resolve() raises IndicatorNotFoundError for unregistered indicator."""
        candles = _make_candle_series("AAPL", base_ts - timedelta(days=10), 20)
        mock_repo.upsert_candles(candles)

        with pytest.raises(IndicatorNotFoundError):
            resolver.resolve(
                "NONEXISTENT",
                "AAPL",
                base_ts,
                base_ts + timedelta(days=9),
            )

    def test_resolve_decimal_precision(
        self,
        mock_repo: MockMarketDataRepository,
        resolver: IndicatorResolver,
        base_ts: datetime,
    ) -> None:
        """Resolved values use 6-decimal-place precision."""
        candles = _make_candle_series("AAPL", base_ts - timedelta(days=10), 20)
        mock_repo.upsert_candles(candles)

        start = base_ts
        end = base_ts + timedelta(days=9)
        values = resolver.resolve("TEST_SMA", "AAPL", start, end, period=3)

        for v in values:
            if v is not None:
                # Decimal should have 6 decimal places
                assert v == v.quantize(Decimal("0.000001"))


# ---------------------------------------------------------------------------
# resolve_at_bar() tests
# ---------------------------------------------------------------------------


class TestResolveAtBar:
    """Tests for IndicatorResolver.resolve_at_bar()."""

    def test_resolve_at_bar_returns_single_value(
        self,
        mock_repo: MockMarketDataRepository,
        resolver: IndicatorResolver,
        base_ts: datetime,
    ) -> None:
        """resolve_at_bar returns a Decimal for a specific timestamp."""
        candles = _make_candle_series("AAPL", base_ts - timedelta(days=300), 310)
        mock_repo.upsert_candles(candles)

        target = base_ts + timedelta(days=5)
        value = resolver.resolve_at_bar("TEST_SMA", "AAPL", target, period=3)

        assert value is not None
        assert isinstance(value, Decimal)

    def test_resolve_at_bar_returns_none_when_no_data(
        self,
        resolver: IndicatorResolver,
        base_ts: datetime,
    ) -> None:
        """resolve_at_bar returns None when no candle data available."""
        value = resolver.resolve_at_bar("TEST_SMA", "AAPL", base_ts, period=3)
        assert value is None

    def test_resolve_at_bar_returns_none_for_all_nan(
        self,
        mock_repo: MockMarketDataRepository,
        resolver: IndicatorResolver,
        base_ts: datetime,
    ) -> None:
        """resolve_at_bar returns None when indicator computes all NaN."""
        candles = _make_candle_series("AAPL", base_ts - timedelta(days=300), 310)
        mock_repo.upsert_candles(candles)

        target = base_ts + timedelta(days=5)
        value = resolver.resolve_at_bar("NAN_IND", "AAPL", target)
        assert value is None

    def test_resolve_at_bar_raises_on_unknown_indicator(
        self,
        mock_repo: MockMarketDataRepository,
        resolver: IndicatorResolver,
        base_ts: datetime,
    ) -> None:
        """resolve_at_bar raises IndicatorNotFoundError for unregistered indicator."""
        candles = _make_candle_series("AAPL", base_ts - timedelta(days=300), 310)
        mock_repo.upsert_candles(candles)

        with pytest.raises(IndicatorNotFoundError):
            resolver.resolve_at_bar("UNKNOWN", "AAPL", base_ts)


# ---------------------------------------------------------------------------
# Cache management tests
# ---------------------------------------------------------------------------


class TestCacheManagement:
    """Tests for cache clearing and statistics."""

    def test_clear_cache_resets_all(
        self,
        mock_repo: MockMarketDataRepository,
        resolver: IndicatorResolver,
        base_ts: datetime,
    ) -> None:
        """clear_cache removes all entries and resets counters."""
        candles = _make_candle_series("AAPL", base_ts - timedelta(days=10), 20)
        mock_repo.upsert_candles(candles)

        resolver.resolve("TEST_SMA", "AAPL", base_ts, base_ts + timedelta(days=9), period=3)

        assert resolver.get_cache_stats()["size"] == 1
        assert resolver.get_cache_stats()["misses"] == 1

        resolver.clear_cache()

        stats = resolver.get_cache_stats()
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_cache_stats_initial_state(
        self,
        resolver: IndicatorResolver,
    ) -> None:
        """Fresh resolver has zero cache stats."""
        stats = resolver.get_cache_stats()
        assert stats == {"hits": 0, "misses": 0, "size": 0}


# ---------------------------------------------------------------------------
# Private helper tests
# ---------------------------------------------------------------------------


class TestHelpers:
    """Tests for IndicatorResolver static helpers."""

    def test_make_cache_key_deterministic(self) -> None:
        """Same inputs produce same cache key."""
        ts1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        ts2 = datetime(2025, 6, 30, tzinfo=timezone.utc)
        params = {"period": 20, "multiplier": 2}

        key1 = IndicatorResolver._make_cache_key("SMA", "AAPL", ts1, ts2, "1d", params)
        key2 = IndicatorResolver._make_cache_key("SMA", "AAPL", ts1, ts2, "1d", params)
        assert key1 == key2

    def test_make_cache_key_param_order_independent(self) -> None:
        """Cache key is the same regardless of param insertion order."""
        ts1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        ts2 = datetime(2025, 6, 30, tzinfo=timezone.utc)

        key1 = IndicatorResolver._make_cache_key("SMA", "AAPL", ts1, ts2, "1d", {"a": 1, "b": 2})
        key2 = IndicatorResolver._make_cache_key("SMA", "AAPL", ts1, ts2, "1d", {"b": 2, "a": 1})
        assert key1 == key2

    def test_make_cache_key_different_params_differ(self) -> None:
        """Different params produce different cache keys."""
        ts1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        ts2 = datetime(2025, 6, 30, tzinfo=timezone.utc)

        key1 = IndicatorResolver._make_cache_key("SMA", "AAPL", ts1, ts2, "1d", {"period": 20})
        key2 = IndicatorResolver._make_cache_key("SMA", "AAPL", ts1, ts2, "1d", {"period": 50})
        assert key1 != key2

    def test_bars_to_days_daily(self) -> None:
        """Daily interval: N bars ≈ 1.5N+1 calendar days."""
        days = IndicatorResolver._bars_to_days(100, "1d")
        assert days == int(100 / 1 * 1.5) + 1  # 151

    def test_bars_to_days_hourly(self) -> None:
        """Hourly interval: 7 bars/day, so 100 bars ≈ fewer calendar days."""
        days = IndicatorResolver._bars_to_days(100, "1h")
        expected = int(100 / 7 * 1.5) + 1  # ~22
        assert days == expected

    def test_bars_to_days_one_minute(self) -> None:
        """1-minute interval: 390 bars/day, so 100 bars ≈ 1-2 days."""
        days = IndicatorResolver._bars_to_days(100, "1m")
        expected = max(1, int(100 / 390 * 1.5) + 1)
        assert days == expected

    def test_bars_to_days_unknown_interval(self) -> None:
        """Unknown interval falls back to 1 bar/day."""
        days = IndicatorResolver._bars_to_days(100, "3d")
        assert days == int(100 / 1 * 1.5) + 1
