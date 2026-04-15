"""
Market data repository interface (port).

Responsibilities:
- Define the abstract contract for OHLCV candle persistence and retrieval.
- Support bulk upsert for efficient data ingestion.
- Support cursor-based pagination for large result sets.
- Support gap detection for data quality monitoring.

Does NOT:
- Implement storage logic (SQL, filesystem, etc.).
- Contain business logic or indicator calculations.
- Know about specific data providers (Alpaca, Schwab, etc.).

Dependencies:
- None (pure interface).

Error conditions:
- NotFoundError: not raised by this interface (queries return empty results).
- ValidationError: raised if query parameters are invalid.

Example:
    repo: MarketDataRepositoryInterface = SqlMarketDataRepository(db=session)
    count = repo.upsert_candles(candles=[candle1, candle2, candle3])
    page = repo.query_candles(
        MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1)
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from libs.contracts.market_data import (
    Candle,
    CandleInterval,
    DataGap,
    MarketDataPage,
    MarketDataQuery,
)


class MarketDataRepositoryInterface(ABC):
    """
    Port interface for OHLCV candle persistence and retrieval.

    Responsibilities:
    - Bulk upsert of candle records (idempotent — duplicates update in place).
    - Paginated querying with time-range and cursor support.
    - Latest-candle lookup for live price display.
    - Gap detection for data quality monitoring.
    - Candle deletion for retention management.

    Does NOT:
    - Compute indicators or analytics.
    - Know about specific data providers.
    - Manage database connections or transactions (caller responsibility).

    Dependencies:
    - MarketDataQuery, MarketDataPage, Candle, CandleInterval, DataGap contracts.

    Example:
        repo = SqlMarketDataRepository(db=session)
        repo.upsert_candles([candle1, candle2])
        page = repo.query_candles(
            MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1, limit=500)
        )
    """

    @abstractmethod
    def upsert_candles(self, candles: list[Candle]) -> int:
        """
        Bulk upsert candle records into the store.

        If a candle with the same (symbol, interval, timestamp) already exists,
        it is updated with the new OHLCV values. Otherwise, a new record is
        inserted. This makes the operation idempotent — re-ingesting the same
        data does not create duplicates.

        Args:
            candles: List of Candle objects to upsert. May be empty (returns 0).

        Returns:
            Number of rows affected (inserted + updated).

        Raises:
            ExternalServiceError: If the database operation fails.

        Example:
            count = repo.upsert_candles([candle1, candle2])
            # count == 2
        """

    @abstractmethod
    def query_candles(self, query: MarketDataQuery) -> MarketDataPage:
        """
        Query candle records with filtering and cursor-based pagination.

        Returns candles ordered by timestamp ascending. When a cursor is
        provided, only candles with timestamp strictly after the cursor
        value are returned (keyset pagination).

        Args:
            query: Query parameters (symbol, interval, time range, limit, cursor).

        Returns:
            MarketDataPage with candles, total_count, has_more flag, and next_cursor.

        Raises:
            ExternalServiceError: If the database operation fails.

        Example:
            page = repo.query_candles(
                MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1, limit=100)
            )
            while page.has_more:
                page = repo.query_candles(
                    MarketDataQuery(
                        symbol="AAPL",
                        interval=CandleInterval.D1,
                        limit=100,
                        cursor=page.next_cursor,
                    )
                )
        """

    @abstractmethod
    def get_latest_candle(self, symbol: str, interval: CandleInterval) -> Candle | None:
        """
        Retrieve the most recent candle for a given symbol and interval.

        Used by the live dashboard to display current/last-known price.

        Args:
            symbol: Ticker symbol (e.g., "AAPL").
            interval: Candle interval (e.g., CandleInterval.D1).

        Returns:
            The most recent Candle, or None if no candles exist for this
            symbol/interval combination.

        Raises:
            ExternalServiceError: If the database operation fails.

        Example:
            latest = repo.get_latest_candle("AAPL", CandleInterval.D1)
            if latest:
                print(f"Last close: {latest.close}")
        """

    @abstractmethod
    def detect_gaps(
        self,
        symbol: str,
        interval: CandleInterval,
        start: datetime,
        end: datetime,
    ) -> list[DataGap]:
        """
        Detect gaps in the candle data for a symbol and interval within a time range.

        Compares consecutive candle timestamps against the expected interval
        duration. When the actual time difference between consecutive candles
        exceeds the expected duration by more than a tolerance factor (e.g., 1.5x),
        a DataGap is reported.

        Note: This method does NOT account for market close hours. Callers
        should interpret results in context (e.g., a gap from 16:00 to 09:30
        the next day is expected for US equities).

        Args:
            symbol: Ticker symbol to check.
            interval: Candle interval to check.
            start: Start of the time range to scan.
            end: End of the time range to scan.

        Returns:
            List of DataGap objects representing detected gaps. Empty list
            means no gaps found (or fewer than 2 candles in the range).

        Raises:
            ExternalServiceError: If the database operation fails.

        Example:
            gaps = repo.detect_gaps(
                "AAPL", CandleInterval.M1,
                start=datetime(2026, 4, 10, 14, 0, tzinfo=timezone.utc),
                end=datetime(2026, 4, 10, 15, 0, tzinfo=timezone.utc),
            )
            for gap in gaps:
                print(f"Gap: {gap.gap_start} → {gap.gap_end}")
        """

    @abstractmethod
    def delete_candles(self, symbol: str, interval: CandleInterval, before: datetime) -> int:
        """
        Delete candle records older than the specified timestamp.

        Used for data retention management. Deletes candles where
        timestamp < before for the given symbol and interval.

        Args:
            symbol: Ticker symbol.
            interval: Candle interval.
            before: Delete candles with timestamp strictly before this value.

        Returns:
            Number of rows deleted.

        Raises:
            ExternalServiceError: If the database operation fails.

        Example:
            deleted = repo.delete_candles(
                "AAPL", CandleInterval.M1,
                before=datetime(2025, 1, 1, tzinfo=timezone.utc),
            )
            print(f"Deleted {deleted} old 1-minute candles")
        """
