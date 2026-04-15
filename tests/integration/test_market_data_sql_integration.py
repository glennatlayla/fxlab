"""
Integration tests for SqlMarketDataRepository.

Validates the SQL repository against a real SQLite database with SAVEPOINT
isolation. Tests verify that the SQL implementation matches the behavioural
contract defined by MockMarketDataRepository.

Architecture:
- Real SQLAlchemy session bound to SQLite in-memory.
- SAVEPOINT isolation via integration_db_session fixture.
- No mocks — all operations hit the database.

Responsibilities:
- Verify bulk upsert with ON CONFLICT DO UPDATE semantics.
- Verify cursor-based pagination correctness.
- Verify gap detection with real timestamp comparison.
- Verify time-based deletion.
- Benchmark bulk upsert performance (10,000 candles < 2 seconds).

Does NOT:
- Test business logic or indicator calculations.
- Test HTTP endpoints or authentication.

Dependencies:
- integration_db_session fixture (conftest.py): per-test SAVEPOINT session.
- libs.contracts.models: CandleRecord ORM model.
- services.api.repositories.sql_market_data_repository: System under test.

Example:
    pytest tests/integration/test_market_data_sql_integration.py -v
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from libs.contracts.market_data import (
    Candle,
    CandleInterval,
    MarketDataQuery,
)
from services.api.repositories.sql_market_data_repository import (
    SqlMarketDataRepository,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_TS = datetime(2026, 1, 2, 14, 30, 0, tzinfo=timezone.utc)


def _make_candle(
    symbol: str = "AAPL",
    interval: CandleInterval = CandleInterval.D1,
    timestamp: datetime | None = None,
    close: str = "175.90",
    volume: int = 58_000_000,
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
        volume=volume,
        timestamp=ts,
    )


def _make_daily_candles(
    symbol: str = "AAPL",
    count: int = 10,
    start: datetime | None = None,
) -> list[Candle]:
    """Create a series of daily candles."""
    base = start or _BASE_TS
    return [
        _make_candle(
            symbol=symbol,
            interval=CandleInterval.D1,
            timestamp=base + timedelta(days=i),
            close=str(Decimal("170.00") + Decimal(str(i))),
        )
        for i in range(count)
    ]


def _make_minute_candles(
    symbol: str = "AAPL",
    count: int = 60,
    start: datetime | None = None,
    gap_at: int | None = None,
) -> list[Candle]:
    """Create a series of 1-minute candles, optionally skipping one to create a gap."""
    base = start or _BASE_TS
    candles = []
    for i in range(count):
        if gap_at is not None and i == gap_at:
            continue
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


class TestSqlUpsertCandles:
    """Integration tests for SqlMarketDataRepository.upsert_candles()."""

    def test_upsert_inserts_new_candles(self, integration_db_session: Session) -> None:
        repo = SqlMarketDataRepository(db=integration_db_session)
        candles = _make_daily_candles(count=5)
        count = repo.upsert_candles(candles)
        assert count == 5

        page = repo.query_candles(MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1))
        assert page.total_count == 5

    def test_upsert_updates_existing_candles(self, integration_db_session: Session) -> None:
        repo = SqlMarketDataRepository(db=integration_db_session)

        # Insert original
        original = _make_candle(close="175.90")
        repo.upsert_candles([original])

        # Upsert with different close price
        updated = _make_candle(close="180.00")
        repo.upsert_candles([updated])

        page = repo.query_candles(MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1))
        assert page.total_count == 1
        assert page.candles[0].close == Decimal("180.00")

    def test_upsert_is_idempotent(self, integration_db_session: Session) -> None:
        """Re-upserting the same data does not create duplicates."""
        repo = SqlMarketDataRepository(db=integration_db_session)
        candles = _make_daily_candles(count=5)

        repo.upsert_candles(candles)
        repo.upsert_candles(candles)  # second upsert

        page = repo.query_candles(MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1))
        assert page.total_count == 5

    def test_upsert_empty_list_returns_zero(self, integration_db_session: Session) -> None:
        repo = SqlMarketDataRepository(db=integration_db_session)
        count = repo.upsert_candles([])
        assert count == 0

    def test_upsert_different_symbols_do_not_collide(self, integration_db_session: Session) -> None:
        repo = SqlMarketDataRepository(db=integration_db_session)
        aapl = _make_candle(symbol="AAPL")
        spy = _make_candle(symbol="SPY")
        repo.upsert_candles([aapl, spy])

        page_aapl = repo.query_candles(MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1))
        page_spy = repo.query_candles(MarketDataQuery(symbol="SPY", interval=CandleInterval.D1))
        assert page_aapl.total_count == 1
        assert page_spy.total_count == 1


# ---------------------------------------------------------------------------
# Query + pagination tests
# ---------------------------------------------------------------------------


class TestSqlQueryCandles:
    """Integration tests for cursor-based pagination."""

    def test_query_returns_ordered_by_timestamp(self, integration_db_session: Session) -> None:
        repo = SqlMarketDataRepository(db=integration_db_session)
        # Insert in reverse order
        candles = _make_daily_candles(count=10)
        repo.upsert_candles(list(reversed(candles)))

        page = repo.query_candles(MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1))
        timestamps = [c.timestamp for c in page.candles]
        assert timestamps == sorted(timestamps)

    def test_query_respects_limit_and_has_more(self, integration_db_session: Session) -> None:
        repo = SqlMarketDataRepository(db=integration_db_session)
        candles = _make_daily_candles(count=10)
        repo.upsert_candles(candles)

        page = repo.query_candles(
            MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1, limit=3)
        )
        assert len(page.candles) == 3
        assert page.total_count == 10
        assert page.has_more is True
        assert page.next_cursor is not None

    def test_cursor_pagination_covers_all_records(self, integration_db_session: Session) -> None:
        """Full pagination walk through all records without duplicates."""
        repo = SqlMarketDataRepository(db=integration_db_session)
        candles = _make_daily_candles(count=10)
        repo.upsert_candles(candles)

        all_candles: list[Candle] = []
        cursor = None
        pages = 0

        while True:
            page = repo.query_candles(
                MarketDataQuery(
                    symbol="AAPL",
                    interval=CandleInterval.D1,
                    limit=3,
                    cursor=cursor,
                )
            )
            all_candles.extend(page.candles)
            pages += 1
            if not page.has_more:
                break
            cursor = page.next_cursor

        assert len(all_candles) == 10
        assert pages == 4  # 3+3+3+1
        # No duplicates
        timestamps = [c.timestamp for c in all_candles]
        assert len(timestamps) == len(set(timestamps))

    def test_query_filters_by_time_range(self, integration_db_session: Session) -> None:
        repo = SqlMarketDataRepository(db=integration_db_session)
        candles = _make_daily_candles(count=10)
        repo.upsert_candles(candles)

        page = repo.query_candles(
            MarketDataQuery(
                symbol="AAPL",
                interval=CandleInterval.D1,
                start=_BASE_TS + timedelta(days=3),
                end=_BASE_TS + timedelta(days=6),
            )
        )
        assert page.total_count == 4  # days 3,4,5,6


# ---------------------------------------------------------------------------
# Latest candle tests
# ---------------------------------------------------------------------------


class TestSqlGetLatestCandle:
    """Integration tests for get_latest_candle()."""

    def test_returns_none_when_empty(self, integration_db_session: Session) -> None:
        repo = SqlMarketDataRepository(db=integration_db_session)
        result = repo.get_latest_candle("AAPL", CandleInterval.D1)
        assert result is None

    def test_returns_most_recent_candle(self, integration_db_session: Session) -> None:
        repo = SqlMarketDataRepository(db=integration_db_session)
        candles = _make_daily_candles(count=5)
        repo.upsert_candles(candles)

        latest = repo.get_latest_candle("AAPL", CandleInterval.D1)
        assert latest is not None
        assert latest.timestamp == _BASE_TS + timedelta(days=4)

    def test_scoped_to_symbol_and_interval(self, integration_db_session: Session) -> None:
        repo = SqlMarketDataRepository(db=integration_db_session)
        repo.upsert_candles(
            [
                _make_candle(symbol="AAPL", timestamp=_BASE_TS),
                _make_candle(
                    symbol="SPY",
                    timestamp=_BASE_TS + timedelta(days=1),
                ),
            ]
        )

        latest = repo.get_latest_candle("AAPL", CandleInterval.D1)
        assert latest is not None
        assert latest.symbol == "AAPL"
        assert latest.timestamp == _BASE_TS


# ---------------------------------------------------------------------------
# Gap detection tests
# ---------------------------------------------------------------------------


class TestSqlDetectGaps:
    """Integration tests for gap detection."""

    def test_no_gaps_in_continuous_data(self, integration_db_session: Session) -> None:
        repo = SqlMarketDataRepository(db=integration_db_session)
        candles = _make_minute_candles(count=60)
        repo.upsert_candles(candles)

        gaps = repo.detect_gaps(
            "AAPL",
            CandleInterval.M1,
            _BASE_TS,
            _BASE_TS + timedelta(hours=1),
        )
        assert gaps == []

    def test_detects_single_missing_candle(self, integration_db_session: Session) -> None:
        repo = SqlMarketDataRepository(db=integration_db_session)
        candles = _make_minute_candles(count=60, gap_at=30)
        repo.upsert_candles(candles)

        gaps = repo.detect_gaps(
            "AAPL",
            CandleInterval.M1,
            _BASE_TS,
            _BASE_TS + timedelta(hours=1),
        )
        assert len(gaps) == 1
        # SQLite stores naive datetimes, so compare without tzinfo
        expected_start = (_BASE_TS + timedelta(minutes=29)).replace(tzinfo=None)
        expected_end = (_BASE_TS + timedelta(minutes=31)).replace(tzinfo=None)
        assert gaps[0].gap_start.replace(tzinfo=None) == expected_start
        assert gaps[0].gap_end.replace(tzinfo=None) == expected_end


# ---------------------------------------------------------------------------
# Delete tests
# ---------------------------------------------------------------------------


class TestSqlDeleteCandles:
    """Integration tests for delete_candles()."""

    def test_deletes_old_records(self, integration_db_session: Session) -> None:
        repo = SqlMarketDataRepository(db=integration_db_session)
        candles = _make_daily_candles(count=10)
        repo.upsert_candles(candles)

        deleted = repo.delete_candles(
            "AAPL", CandleInterval.D1, before=_BASE_TS + timedelta(days=5)
        )
        assert deleted == 5

        page = repo.query_candles(MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1))
        assert page.total_count == 5

    def test_scoped_delete_does_not_affect_other_symbols(
        self, integration_db_session: Session
    ) -> None:
        repo = SqlMarketDataRepository(db=integration_db_session)
        repo.upsert_candles(
            [
                _make_candle(symbol="AAPL", timestamp=_BASE_TS),
                _make_candle(symbol="SPY", timestamp=_BASE_TS),
            ]
        )

        deleted = repo.delete_candles(
            "AAPL", CandleInterval.D1, before=_BASE_TS + timedelta(days=1)
        )
        assert deleted == 1

        page_spy = repo.query_candles(MarketDataQuery(symbol="SPY", interval=CandleInterval.D1))
        assert page_spy.total_count == 1


# ---------------------------------------------------------------------------
# Performance benchmark
# ---------------------------------------------------------------------------


class TestSqlPerformance:
    """Performance benchmarks for acceptance criteria."""

    def test_bulk_upsert_10000_candles_under_2_seconds(
        self, integration_db_session: Session
    ) -> None:
        """Acceptance criteria: bulk upsert of 10,000 candles < 2 seconds."""
        repo = SqlMarketDataRepository(db=integration_db_session)
        candles = [
            _make_candle(
                timestamp=_BASE_TS + timedelta(minutes=i),
                interval=CandleInterval.M1,
                close=str(Decimal("175.00") + Decimal(str(i)) * Decimal("0.001")),
                volume=1_000_000 + i,
            )
            for i in range(10_000)
        ]

        start = time.monotonic()
        count = repo.upsert_candles(candles)
        elapsed = time.monotonic() - start

        assert count == 10_000
        assert elapsed < 2.0, f"Bulk upsert took {elapsed:.2f}s, expected < 2.0s"

        # Verify data persisted correctly
        page = repo.query_candles(
            MarketDataQuery(symbol="AAPL", interval=CandleInterval.M1, limit=1)
        )
        assert page.total_count == 10_000
