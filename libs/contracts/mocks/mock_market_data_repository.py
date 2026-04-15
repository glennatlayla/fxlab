"""
In-memory mock market data repository for unit testing.

Responsibilities:
- Implement MarketDataRepositoryInterface with list-backed storage.
- Support idempotent upsert keyed by (symbol, interval, timestamp).
- Support cursor-based pagination matching the SQL repository's behaviour.
- Detect gaps by comparing consecutive candle timestamps.
- Provide introspection helpers for test setup and assertions.

Does NOT:
- Persist data across process restarts.
- Contain business logic or indicator calculations.
- Use SQL or any database driver.

Dependencies:
- libs.contracts.interfaces.market_data_repository.MarketDataRepositoryInterface
- libs.contracts.market_data (Candle, CandleInterval, DataGap, MarketDataQuery, MarketDataPage)

Error conditions:
- None raised by the mock (all operations succeed).

Example:
    repo = MockMarketDataRepository()
    count = repo.upsert_candles([candle1, candle2])
    page = repo.query_candles(
        MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1)
    )
    assert page.total_count == 2
"""

from __future__ import annotations

from datetime import datetime, timezone

from libs.contracts.interfaces.market_data_repository import (
    MarketDataRepositoryInterface,
)
from libs.contracts.market_data import (
    INTERVAL_SECONDS,
    Candle,
    CandleInterval,
    DataGap,
    MarketDataPage,
    MarketDataQuery,
)


class MockMarketDataRepository(MarketDataRepositoryInterface):
    """
    In-memory implementation of MarketDataRepositoryInterface for unit testing.

    Stores candles in a dict keyed by (symbol, interval_value, timestamp_iso)
    for O(1) upsert deduplication. Query operations filter and sort this store.

    Responsibilities:
    - Behavioural parity with SqlMarketDataRepository.
    - Introspection helpers (count, get_all, clear) for test assertions.

    Does NOT:
    - Use SQL or any external storage.

    Example:
        repo = MockMarketDataRepository()
        repo.upsert_candles([candle])
        assert repo.count() == 1
    """

    def __init__(self) -> None:
        # Key: (symbol, interval_value, timestamp_isoformat) → Candle
        self._store: dict[tuple[str, str, str], Candle] = {}

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    def upsert_candles(self, candles: list[Candle]) -> int:
        """
        Bulk upsert candles into the in-memory store.

        If a candle with the same (symbol, interval, timestamp) exists, it is
        replaced. Otherwise, a new entry is created.

        Args:
            candles: List of Candle objects to upsert.

        Returns:
            Number of candles processed (inserted + updated).

        Example:
            count = repo.upsert_candles([candle1, candle2])
            # count == 2
        """
        count = 0
        for candle in candles:
            key = (candle.symbol, candle.interval.value, candle.timestamp.isoformat())
            self._store[key] = candle
            count += 1
        return count

    def query_candles(self, query: MarketDataQuery) -> MarketDataPage:
        """
        Query candles with filtering, ordering, and cursor-based pagination.

        Filters by symbol and interval (required), with optional time range
        (start/end inclusive) and cursor (timestamp strictly after).
        Results are ordered by timestamp ascending.

        Args:
            query: MarketDataQuery with filter and pagination parameters.

        Returns:
            MarketDataPage with filtered candles, total count, and pagination cursor.

        Example:
            page = repo.query_candles(
                MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1, limit=10)
            )
        """
        # Filter candles matching symbol and interval
        filtered = [
            c
            for c in self._store.values()
            if c.symbol == query.symbol and c.interval == query.interval
        ]

        # Apply time range filters
        if query.start is not None:
            filtered = [c for c in filtered if c.timestamp >= query.start]
        if query.end is not None:
            filtered = [c for c in filtered if c.timestamp <= query.end]

        # Apply cursor (timestamp strictly after cursor value)
        if query.cursor is not None:
            cursor_ts = datetime.fromisoformat(query.cursor)
            filtered = [c for c in filtered if c.timestamp > cursor_ts]

        # Sort by timestamp ascending
        filtered.sort(key=lambda c: c.timestamp)

        total_count = len(filtered)
        has_more = total_count > query.limit
        page_candles = filtered[: query.limit]

        next_cursor: str | None = None
        if has_more and page_candles:
            next_cursor = page_candles[-1].timestamp.isoformat()

        return MarketDataPage(
            candles=page_candles,
            total_count=total_count,
            has_more=has_more,
            next_cursor=next_cursor,
        )

    def get_latest_candle(self, symbol: str, interval: CandleInterval) -> Candle | None:
        """
        Retrieve the most recent candle for a given symbol and interval.

        Args:
            symbol: Ticker symbol.
            interval: Candle interval.

        Returns:
            The most recent Candle, or None if no candles exist.

        Example:
            latest = repo.get_latest_candle("AAPL", CandleInterval.D1)
        """
        matching = [
            c for c in self._store.values() if c.symbol == symbol and c.interval == interval
        ]
        if not matching:
            return None
        return max(matching, key=lambda c: c.timestamp)

    def detect_gaps(
        self,
        symbol: str,
        interval: CandleInterval,
        start: datetime,
        end: datetime,
    ) -> list[DataGap]:
        """
        Detect gaps in candle data within a time range.

        Compares consecutive candle timestamps. A gap is reported when the
        time between consecutive candles exceeds 1.5× the expected interval
        duration.

        Args:
            symbol: Ticker symbol.
            interval: Candle interval.
            start: Start of scan range.
            end: End of scan range.

        Returns:
            List of DataGap objects for detected gaps.

        Example:
            gaps = repo.detect_gaps("AAPL", CandleInterval.M1, start, end)
        """
        matching = sorted(
            [
                c
                for c in self._store.values()
                if c.symbol == symbol
                and c.interval == interval
                and c.timestamp >= start
                and c.timestamp <= end
            ],
            key=lambda c: c.timestamp,
        )

        if len(matching) < 2:
            return []

        expected_seconds = INTERVAL_SECONDS[interval]
        # Tolerance factor: gap must be > 1.5× expected interval to count
        threshold_seconds = expected_seconds * 1.5

        gaps: list[DataGap] = []
        now = datetime.now(timezone.utc)

        for i in range(1, len(matching)):
            prev = matching[i - 1]
            curr = matching[i]
            delta = (curr.timestamp - prev.timestamp).total_seconds()
            if delta > threshold_seconds:
                gaps.append(
                    DataGap(
                        symbol=symbol,
                        interval=interval,
                        gap_start=prev.timestamp,
                        gap_end=curr.timestamp,
                        detected_at=now,
                    )
                )

        return gaps

    def delete_candles(self, symbol: str, interval: CandleInterval, before: datetime) -> int:
        """
        Delete candles older than the specified timestamp.

        Args:
            symbol: Ticker symbol.
            interval: Candle interval.
            before: Delete candles with timestamp strictly before this value.

        Returns:
            Number of rows deleted.

        Example:
            deleted = repo.delete_candles("AAPL", CandleInterval.M1, cutoff)
        """
        keys_to_delete = [
            key
            for key, candle in self._store.items()
            if candle.symbol == symbol and candle.interval == interval and candle.timestamp < before
        ]
        for key in keys_to_delete:
            del self._store[key]
        return len(keys_to_delete)

    # ------------------------------------------------------------------
    # Introspection helpers (test-only)
    # ------------------------------------------------------------------

    def get_all(self) -> list[Candle]:
        """
        Return all candles in the store, ordered by timestamp ascending.

        Returns:
            List of all Candle objects.
        """
        return sorted(self._store.values(), key=lambda c: c.timestamp)

    def count(self) -> int:
        """
        Return the total number of candles in the store.

        Returns:
            Integer count.
        """
        return len(self._store)

    def clear(self) -> None:
        """Remove all candles from the store."""
        self._store.clear()
