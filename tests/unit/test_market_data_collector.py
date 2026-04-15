"""
Unit tests for MarketDataCollectorService.

Validates collection orchestration using mocked provider and repository.
Tests cover happy path, partial failures, batching, and gap detection
integration.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from libs.contracts.collection import CollectionResult
from libs.contracts.errors import ExternalServiceError, TransientError
from libs.contracts.market_data import Candle, CandleInterval
from libs.contracts.mocks.mock_market_data_provider import MockMarketDataProvider
from libs.contracts.mocks.mock_market_data_repository import (
    MockMarketDataRepository,
)
from services.worker.collectors.market_data_collector import (
    MarketDataCollectorService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_TS = datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc)


def _make_candle(
    symbol: str = "AAPL",
    interval: CandleInterval = CandleInterval.D1,
    timestamp: datetime | None = None,
    close: str = "175.90",
) -> Candle:
    """Create a valid Candle with sensible defaults."""
    return Candle(
        symbol=symbol,
        interval=interval,
        open=Decimal("174.50"),
        high=Decimal("176.25"),
        low=Decimal("173.80"),
        close=Decimal(close),
        volume=58_000_000,
        timestamp=timestamp or _BASE_TS,
    )


def _make_daily_candles(
    symbol: str = "AAPL", count: int = 10, start: datetime | None = None
) -> list[Candle]:
    """Create a series of daily candles."""
    base = start or _BASE_TS
    return [
        _make_candle(
            symbol=symbol,
            timestamp=base + timedelta(days=i),
            close=str(Decimal("170.00") + Decimal(str(i))),
        )
        for i in range(count)
    ]


def _make_collector(
    provider: MockMarketDataProvider | None = None,
    repo: MockMarketDataRepository | None = None,
    chunk_size: int = 10,
) -> MarketDataCollectorService:
    """Create a collector with mock dependencies."""
    return MarketDataCollectorService(
        provider=provider or MockMarketDataProvider(),
        repository=repo or MockMarketDataRepository(),
        chunk_size=chunk_size,
    )


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------


class TestCollectorHappyPath:
    """Tests for successful collection scenarios."""

    def test_collect_single_symbol_persists_candles(self) -> None:
        """Collect candles for one symbol and verify persistence."""
        provider = MockMarketDataProvider()
        repo = MockMarketDataRepository()
        candles = _make_daily_candles(symbol="AAPL", count=5)
        provider.set_bars("AAPL", CandleInterval.D1, candles)

        collector = _make_collector(provider=provider, repo=repo)
        result = collector.collect(
            symbols=["AAPL"],
            interval=CandleInterval.D1,
            start=_BASE_TS,
            end=_BASE_TS + timedelta(days=100),
        )

        assert isinstance(result, CollectionResult)
        assert result.symbols_requested == ["AAPL"]
        assert result.symbols_succeeded == ["AAPL"]
        assert result.symbols_failed == []
        assert result.total_candles_collected == 5
        assert result.total_candles_persisted == 5
        assert repo.count() == 5

    def test_collect_multiple_symbols(self) -> None:
        """Collect candles for multiple symbols in a single call."""
        provider = MockMarketDataProvider()
        repo = MockMarketDataRepository()
        provider.set_bars("AAPL", CandleInterval.D1, _make_daily_candles("AAPL", 5))
        provider.set_bars("SPY", CandleInterval.D1, _make_daily_candles("SPY", 3))

        collector = _make_collector(provider=provider, repo=repo)
        result = collector.collect(
            symbols=["AAPL", "SPY"],
            interval=CandleInterval.D1,
            start=_BASE_TS,
            end=_BASE_TS + timedelta(days=100),
        )

        assert set(result.symbols_succeeded) == {"AAPL", "SPY"}
        assert result.total_candles_collected == 8
        assert result.total_candles_persisted == 8

    def test_collect_empty_symbol_list_returns_empty_result(self) -> None:
        """Empty symbol list produces a valid empty result."""
        collector = _make_collector()
        result = collector.collect(
            symbols=[],
            interval=CandleInterval.D1,
            start=_BASE_TS,
            end=_BASE_TS + timedelta(days=30),
        )

        assert result.symbols_requested == []
        assert result.total_candles_collected == 0
        assert result.completed_at is not None

    def test_collect_symbol_with_no_data_succeeds_with_zero_candles(self) -> None:
        """Symbol with no data in range still counts as successful."""
        provider = MockMarketDataProvider()
        collector = _make_collector(provider=provider)
        result = collector.collect(
            symbols=["AAPL"],
            interval=CandleInterval.D1,
            start=_BASE_TS,
            end=_BASE_TS + timedelta(days=30),
        )

        assert result.symbols_succeeded == ["AAPL"]
        assert result.total_candles_collected == 0

    def test_collect_returns_per_symbol_results(self) -> None:
        """Each symbol has a detailed SymbolCollectionResult."""
        provider = MockMarketDataProvider()
        repo = MockMarketDataRepository()
        provider.set_bars("AAPL", CandleInterval.D1, _make_daily_candles("AAPL", 5))

        collector = _make_collector(provider=provider, repo=repo)
        result = collector.collect(
            symbols=["AAPL"],
            interval=CandleInterval.D1,
            start=_BASE_TS,
            end=_BASE_TS + timedelta(days=100),
        )

        assert len(result.symbol_results) == 1
        sym_result = result.symbol_results[0]
        assert sym_result.symbol == "AAPL"
        assert sym_result.candles_collected == 5
        assert sym_result.candles_persisted == 5
        assert sym_result.error is None


# ---------------------------------------------------------------------------
# Failure handling tests
# ---------------------------------------------------------------------------


class TestCollectorFailureHandling:
    """Tests for partial failure and error isolation."""

    def test_provider_error_for_one_symbol_does_not_block_others(self) -> None:
        """If AAPL fails, SPY should still be collected."""
        provider = MockMarketDataProvider()
        repo = MockMarketDataRepository()
        provider.set_error("AAPL", ExternalServiceError("API down"))
        provider.set_bars("SPY", CandleInterval.D1, _make_daily_candles("SPY", 3))

        collector = _make_collector(provider=provider, repo=repo)
        result = collector.collect(
            symbols=["AAPL", "SPY"],
            interval=CandleInterval.D1,
            start=_BASE_TS,
            end=_BASE_TS + timedelta(days=100),
        )

        assert result.symbols_succeeded == ["SPY"]
        assert result.symbols_failed == ["AAPL"]
        assert result.total_candles_collected == 3

        # Verify AAPL failure is in symbol results
        aapl_result = next(r for r in result.symbol_results if r.symbol == "AAPL")
        assert aapl_result.error is not None
        assert "API down" in aapl_result.error

    def test_transient_error_recorded_in_symbol_result(self) -> None:
        """TransientError is captured, not re-raised."""
        provider = MockMarketDataProvider()
        provider.set_error("AAPL", TransientError("timeout"))

        collector = _make_collector(provider=provider)
        result = collector.collect(
            symbols=["AAPL"],
            interval=CandleInterval.D1,
            start=_BASE_TS,
            end=_BASE_TS + timedelta(days=30),
        )

        assert result.symbols_failed == ["AAPL"]
        assert result.total_candles_collected == 0

    def test_all_symbols_fail_returns_complete_failure_result(self) -> None:
        """All symbols failing still returns a valid CollectionResult."""
        provider = MockMarketDataProvider()
        provider.set_error("AAPL", ExternalServiceError("fail A"))
        provider.set_error("SPY", ExternalServiceError("fail B"))

        collector = _make_collector(provider=provider)
        result = collector.collect(
            symbols=["AAPL", "SPY"],
            interval=CandleInterval.D1,
            start=_BASE_TS,
            end=_BASE_TS + timedelta(days=30),
        )

        assert result.symbols_succeeded == []
        assert set(result.symbols_failed) == {"AAPL", "SPY"}
        assert result.total_candles_collected == 0


# ---------------------------------------------------------------------------
# Batching tests
# ---------------------------------------------------------------------------


class TestCollectorBatching:
    """Tests for symbol batching (chunk_size)."""

    def test_respects_chunk_size(self) -> None:
        """Symbols are processed in chunks of the configured size."""
        provider = MockMarketDataProvider()
        repo = MockMarketDataRepository()
        symbols = [f"SYM{i}" for i in range(5)]
        for sym in symbols:
            provider.set_bars(sym, CandleInterval.D1, _make_daily_candles(sym, 2))

        # chunk_size=2 → 3 batches (2+2+1)
        collector = _make_collector(provider=provider, repo=repo, chunk_size=2)
        result = collector.collect(
            symbols=symbols,
            interval=CandleInterval.D1,
            start=_BASE_TS,
            end=_BASE_TS + timedelta(days=100),
        )

        assert len(result.symbols_succeeded) == 5
        assert result.total_candles_collected == 10
        # Provider should be called once per symbol
        assert provider.fetch_count == 5


# ---------------------------------------------------------------------------
# Gap detection integration
# ---------------------------------------------------------------------------


class TestCollectorGapDetection:
    """Tests for gap detection after collection."""

    def test_detects_gaps_after_collection(self) -> None:
        """Gaps in collected data are reported in the result."""
        provider = MockMarketDataProvider()
        repo = MockMarketDataRepository()

        # Create minute candles with a gap at position 30
        base = _BASE_TS
        candles = []
        for i in range(60):
            if i == 30:
                continue  # skip minute 30
            candles.append(
                _make_candle(
                    symbol="AAPL",
                    interval=CandleInterval.M1,
                    timestamp=base + timedelta(minutes=i),
                    close=str(Decimal("175.00") + Decimal(str(i)) * Decimal("0.01")),
                )
            )
        provider.set_bars("AAPL", CandleInterval.M1, candles)

        collector = _make_collector(provider=provider, repo=repo)
        result = collector.collect(
            symbols=["AAPL"],
            interval=CandleInterval.M1,
            start=base,
            end=base + timedelta(hours=1),
        )

        assert result.total_gaps_detected >= 1
        aapl_result = result.symbol_results[0]
        assert len(aapl_result.gaps_detected) >= 1


# ---------------------------------------------------------------------------
# Idempotency tests
# ---------------------------------------------------------------------------


class TestCollectorIdempotency:
    """Tests verifying upsert semantics (idempotent re-runs)."""

    def test_re_collection_does_not_create_duplicates(self) -> None:
        """Running collection twice with the same data is idempotent."""
        provider = MockMarketDataProvider()
        repo = MockMarketDataRepository()
        candles = _make_daily_candles(count=5)
        provider.set_bars("AAPL", CandleInterval.D1, candles)

        collector = _make_collector(provider=provider, repo=repo)

        # First collection
        collector.collect(
            symbols=["AAPL"],
            interval=CandleInterval.D1,
            start=_BASE_TS,
            end=_BASE_TS + timedelta(days=100),
        )

        # Second collection (same data)
        result = collector.collect(
            symbols=["AAPL"],
            interval=CandleInterval.D1,
            start=_BASE_TS,
            end=_BASE_TS + timedelta(days=100),
        )

        assert result.total_candles_persisted == 5
        assert repo.count() == 5  # No duplicates
