"""
Unit tests for the mock market data repository.

These tests define the expected behaviour of the MarketDataRepositoryInterface.
The mock implementation is the system-under-test. The same behavioural contract
must hold for the SQL implementation (verified in integration tests).

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from libs.contracts.market_data import (
    Candle,
    CandleInterval,
    MarketDataQuery,
)
from libs.contracts.mocks.mock_market_data_repository import MockMarketDataRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_TS = datetime(2026, 4, 10, 14, 0, 0, tzinfo=timezone.utc)


def _make_candle(
    symbol: str = "AAPL",
    interval: CandleInterval = CandleInterval.D1,
    timestamp: datetime | None = None,
    close: str = "175.90",
) -> Candle:
    """Create a valid Candle with sensible defaults."""
    ts = timestamp or _BASE_TS
    return Candle(
        symbol=symbol,
        interval=interval,
        open=Decimal("174.50"),
        high=Decimal("176.25"),
        low=Decimal("173.80"),
        close=Decimal(close),
        volume=58_000_000,
        timestamp=ts,
    )


def _make_minute_candles(
    symbol: str = "AAPL",
    count: int = 60,
    start: datetime | None = None,
    gap_at: int | None = None,
) -> list[Candle]:
    """
    Create a series of 1-minute candles.

    Args:
        symbol: Ticker symbol.
        count: Number of candles to create.
        start: Starting timestamp (default: _BASE_TS).
        gap_at: If set, skip the candle at this index to create a gap.
    """
    base = start or _BASE_TS
    candles = []
    for i in range(count):
        if gap_at is not None and i == gap_at:
            continue  # Skip this candle to create a gap
        ts = base + timedelta(minutes=i)
        candles.append(
            _make_candle(
                symbol=symbol,
                interval=CandleInterval.M1,
                timestamp=ts,
                close=str(Decimal("175.00") + Decimal(str(i)) * Decimal("0.01")),
            )
        )
    return candles


# ---------------------------------------------------------------------------
# Upsert tests
# ---------------------------------------------------------------------------


class TestUpsertCandles:
    """Tests for MarketDataRepository.upsert_candles()."""

    def test_upsert_candles_empty_list_returns_zero(self) -> None:
        repo = MockMarketDataRepository()
        count = repo.upsert_candles([])
        assert count == 0

    def test_upsert_candles_inserts_new_records(self) -> None:
        repo = MockMarketDataRepository()
        candles = [_make_candle(timestamp=_BASE_TS + timedelta(days=i)) for i in range(5)]
        count = repo.upsert_candles(candles)
        assert count == 5

    def test_upsert_candles_updates_existing_records(self) -> None:
        """Upserting the same (symbol, interval, timestamp) updates OHLCV values."""
        repo = MockMarketDataRepository()
        original = _make_candle(close="175.90")
        repo.upsert_candles([original])

        updated = _make_candle(close="180.00")
        count = repo.upsert_candles([updated])
        assert count == 1

        # Verify the close price was updated
        page = repo.query_candles(MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1))
        assert len(page.candles) == 1
        assert page.candles[0].close == Decimal("180.00")

    def test_upsert_candles_mixed_insert_and_update(self) -> None:
        repo = MockMarketDataRepository()
        c1 = _make_candle(timestamp=_BASE_TS)
        repo.upsert_candles([c1])

        c1_updated = _make_candle(timestamp=_BASE_TS, close="999.00")
        c2_new = _make_candle(timestamp=_BASE_TS + timedelta(days=1))
        count = repo.upsert_candles([c1_updated, c2_new])
        assert count == 2

        page = repo.query_candles(MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1))
        assert page.total_count == 2

    def test_upsert_candles_different_symbols_do_not_collide(self) -> None:
        repo = MockMarketDataRepository()
        aapl = _make_candle(symbol="AAPL")
        spy = _make_candle(symbol="SPY")
        count = repo.upsert_candles([aapl, spy])
        assert count == 2

        page_aapl = repo.query_candles(MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1))
        page_spy = repo.query_candles(MarketDataQuery(symbol="SPY", interval=CandleInterval.D1))
        assert page_aapl.total_count == 1
        assert page_spy.total_count == 1


# ---------------------------------------------------------------------------
# Query tests
# ---------------------------------------------------------------------------


class TestQueryCandles:
    """Tests for MarketDataRepository.query_candles()."""

    def test_query_candles_empty_store_returns_empty_page(self) -> None:
        repo = MockMarketDataRepository()
        page = repo.query_candles(MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1))
        assert page.candles == []
        assert page.total_count == 0
        assert page.has_more is False

    def test_query_candles_filters_by_symbol(self) -> None:
        repo = MockMarketDataRepository()
        repo.upsert_candles(
            [
                _make_candle(symbol="AAPL"),
                _make_candle(symbol="SPY"),
            ]
        )
        page = repo.query_candles(MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1))
        assert page.total_count == 1
        assert page.candles[0].symbol == "AAPL"

    def test_query_candles_filters_by_interval(self) -> None:
        repo = MockMarketDataRepository()
        repo.upsert_candles(
            [
                _make_candle(interval=CandleInterval.D1),
                _make_candle(interval=CandleInterval.M1),
            ]
        )
        page = repo.query_candles(MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1))
        assert page.total_count == 1

    def test_query_candles_filters_by_time_range(self) -> None:
        repo = MockMarketDataRepository()
        candles = [_make_candle(timestamp=_BASE_TS + timedelta(days=i)) for i in range(10)]
        repo.upsert_candles(candles)

        page = repo.query_candles(
            MarketDataQuery(
                symbol="AAPL",
                interval=CandleInterval.D1,
                start=_BASE_TS + timedelta(days=3),
                end=_BASE_TS + timedelta(days=6),
            )
        )
        # Days 3, 4, 5, 6 = 4 candles (inclusive)
        assert page.total_count == 4

    def test_query_candles_returns_ordered_by_timestamp_asc(self) -> None:
        repo = MockMarketDataRepository()
        # Insert in reverse order
        candles = [_make_candle(timestamp=_BASE_TS + timedelta(days=i)) for i in range(5, -1, -1)]
        repo.upsert_candles(candles)

        page = repo.query_candles(MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1))
        timestamps = [c.timestamp for c in page.candles]
        assert timestamps == sorted(timestamps)

    def test_query_candles_respects_limit(self) -> None:
        repo = MockMarketDataRepository()
        candles = [_make_candle(timestamp=_BASE_TS + timedelta(days=i)) for i in range(10)]
        repo.upsert_candles(candles)

        page = repo.query_candles(
            MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1, limit=3)
        )
        assert len(page.candles) == 3
        assert page.total_count == 10
        assert page.has_more is True
        assert page.next_cursor is not None

    def test_query_candles_cursor_pagination(self) -> None:
        """Cursor-based pagination returns correct subsequent pages."""
        repo = MockMarketDataRepository()
        candles = [_make_candle(timestamp=_BASE_TS + timedelta(days=i)) for i in range(10)]
        repo.upsert_candles(candles)

        # Page 1
        page1 = repo.query_candles(
            MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1, limit=4)
        )
        assert len(page1.candles) == 4
        assert page1.has_more is True

        # Page 2 (using cursor)
        page2 = repo.query_candles(
            MarketDataQuery(
                symbol="AAPL",
                interval=CandleInterval.D1,
                limit=4,
                cursor=page1.next_cursor,
            )
        )
        assert len(page2.candles) == 4
        assert page2.has_more is True

        # Page 3 (last page)
        page3 = repo.query_candles(
            MarketDataQuery(
                symbol="AAPL",
                interval=CandleInterval.D1,
                limit=4,
                cursor=page2.next_cursor,
            )
        )
        assert len(page3.candles) == 2
        assert page3.has_more is False

        # No duplicates across pages
        all_timestamps = (
            [c.timestamp for c in page1.candles]
            + [c.timestamp for c in page2.candles]
            + [c.timestamp for c in page3.candles]
        )
        assert len(all_timestamps) == len(set(all_timestamps))


# ---------------------------------------------------------------------------
# Get latest candle tests
# ---------------------------------------------------------------------------


class TestGetLatestCandle:
    """Tests for MarketDataRepository.get_latest_candle()."""

    def test_get_latest_candle_returns_none_when_empty(self) -> None:
        repo = MockMarketDataRepository()
        result = repo.get_latest_candle("AAPL", CandleInterval.D1)
        assert result is None

    def test_get_latest_candle_returns_most_recent(self) -> None:
        repo = MockMarketDataRepository()
        candles = [
            _make_candle(timestamp=_BASE_TS + timedelta(days=i), close=str(170 + i))
            for i in range(5)
        ]
        repo.upsert_candles(candles)

        latest = repo.get_latest_candle("AAPL", CandleInterval.D1)
        assert latest is not None
        assert latest.timestamp == _BASE_TS + timedelta(days=4)

    def test_get_latest_candle_scoped_to_symbol_and_interval(self) -> None:
        repo = MockMarketDataRepository()
        aapl_daily = _make_candle(
            symbol="AAPL",
            interval=CandleInterval.D1,
            timestamp=_BASE_TS,
        )
        spy_daily = _make_candle(
            symbol="SPY",
            interval=CandleInterval.D1,
            timestamp=_BASE_TS + timedelta(days=1),
        )
        repo.upsert_candles([aapl_daily, spy_daily])

        latest = repo.get_latest_candle("AAPL", CandleInterval.D1)
        assert latest is not None
        assert latest.symbol == "AAPL"
        assert latest.timestamp == _BASE_TS


# ---------------------------------------------------------------------------
# Gap detection tests
# ---------------------------------------------------------------------------


class TestDetectGaps:
    """Tests for MarketDataRepository.detect_gaps()."""

    def test_detect_gaps_returns_empty_for_no_data(self) -> None:
        repo = MockMarketDataRepository()
        gaps = repo.detect_gaps(
            "AAPL",
            CandleInterval.M1,
            _BASE_TS,
            _BASE_TS + timedelta(hours=1),
        )
        assert gaps == []

    def test_detect_gaps_returns_empty_for_continuous_data(self) -> None:
        repo = MockMarketDataRepository()
        candles = _make_minute_candles(count=60)
        repo.upsert_candles(candles)

        gaps = repo.detect_gaps(
            "AAPL",
            CandleInterval.M1,
            _BASE_TS,
            _BASE_TS + timedelta(hours=1),
        )
        assert gaps == []

    def test_detect_gaps_finds_missing_candle(self) -> None:
        """Skipping candle at index 30 creates a gap."""
        repo = MockMarketDataRepository()
        candles = _make_minute_candles(count=60, gap_at=30)
        repo.upsert_candles(candles)

        gaps = repo.detect_gaps(
            "AAPL",
            CandleInterval.M1,
            _BASE_TS,
            _BASE_TS + timedelta(hours=1),
        )
        assert len(gaps) == 1
        gap = gaps[0]
        assert gap.symbol == "AAPL"
        assert gap.interval == CandleInterval.M1
        # Gap should span from minute 29 to minute 31
        assert gap.gap_start == _BASE_TS + timedelta(minutes=29)
        assert gap.gap_end == _BASE_TS + timedelta(minutes=31)

    def test_detect_gaps_finds_multiple_gaps(self) -> None:
        """Skipping candles at indices 10 and 40 creates two gaps."""
        repo = MockMarketDataRepository()
        # Create candles with two gaps manually
        candles = []
        for i in range(60):
            if i in (10, 40):
                continue
            ts = _BASE_TS + timedelta(minutes=i)
            candles.append(
                _make_candle(
                    interval=CandleInterval.M1,
                    timestamp=ts,
                )
            )
        repo.upsert_candles(candles)

        gaps = repo.detect_gaps(
            "AAPL",
            CandleInterval.M1,
            _BASE_TS,
            _BASE_TS + timedelta(hours=1),
        )
        assert len(gaps) == 2

    def test_detect_gaps_scoped_to_time_range(self) -> None:
        """Gap outside the queried time range is not reported."""
        repo = MockMarketDataRepository()
        # Gap at minute 5 (inside first 30 min range)
        candles = _make_minute_candles(count=60, gap_at=5)
        repo.upsert_candles(candles)

        # Query only the second half (minutes 30-59) — no gap there
        gaps = repo.detect_gaps(
            "AAPL",
            CandleInterval.M1,
            _BASE_TS + timedelta(minutes=30),
            _BASE_TS + timedelta(hours=1),
        )
        assert len(gaps) == 0


# ---------------------------------------------------------------------------
# Delete candles tests
# ---------------------------------------------------------------------------


class TestDeleteCandles:
    """Tests for MarketDataRepository.delete_candles()."""

    def test_delete_candles_removes_old_records(self) -> None:
        repo = MockMarketDataRepository()
        candles = [_make_candle(timestamp=_BASE_TS + timedelta(days=i)) for i in range(10)]
        repo.upsert_candles(candles)

        deleted = repo.delete_candles(
            "AAPL",
            CandleInterval.D1,
            before=_BASE_TS + timedelta(days=5),
        )
        assert deleted == 5

        page = repo.query_candles(MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1))
        assert page.total_count == 5

    def test_delete_candles_returns_zero_when_nothing_to_delete(self) -> None:
        repo = MockMarketDataRepository()
        deleted = repo.delete_candles(
            "AAPL",
            CandleInterval.D1,
            before=_BASE_TS,
        )
        assert deleted == 0

    def test_delete_candles_scoped_to_symbol_and_interval(self) -> None:
        """Deleting AAPL daily candles does not affect SPY or AAPL minute data."""
        repo = MockMarketDataRepository()
        repo.upsert_candles(
            [
                _make_candle(symbol="AAPL", interval=CandleInterval.D1, timestamp=_BASE_TS),
                _make_candle(symbol="SPY", interval=CandleInterval.D1, timestamp=_BASE_TS),
                _make_candle(symbol="AAPL", interval=CandleInterval.M1, timestamp=_BASE_TS),
            ]
        )

        deleted = repo.delete_candles(
            "AAPL",
            CandleInterval.D1,
            before=_BASE_TS + timedelta(days=1),
        )
        assert deleted == 1

        # SPY daily still exists
        page_spy = repo.query_candles(MarketDataQuery(symbol="SPY", interval=CandleInterval.D1))
        assert page_spy.total_count == 1

        # AAPL minute still exists
        page_m1 = repo.query_candles(MarketDataQuery(symbol="AAPL", interval=CandleInterval.M1))
        assert page_m1.total_count == 1


# ---------------------------------------------------------------------------
# Mock introspection helpers
# ---------------------------------------------------------------------------


class TestMockIntrospection:
    """Tests for MockMarketDataRepository introspection helpers."""

    def test_count_returns_total_candles(self) -> None:
        repo = MockMarketDataRepository()
        repo.upsert_candles(
            [
                _make_candle(symbol="AAPL"),
                _make_candle(symbol="SPY"),
            ]
        )
        assert repo.count() == 2

    def test_clear_removes_all_candles(self) -> None:
        repo = MockMarketDataRepository()
        repo.upsert_candles([_make_candle()])
        repo.clear()
        assert repo.count() == 0

    def test_get_all_returns_all_candles(self) -> None:
        repo = MockMarketDataRepository()
        candles = [_make_candle(timestamp=_BASE_TS + timedelta(days=i)) for i in range(3)]
        repo.upsert_candles(candles)
        assert len(repo.get_all()) == 3
