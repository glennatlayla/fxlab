"""
SQL repository for OHLCV market data candle storage and retrieval.

Responsibilities:
- Persist candle records via SQLAlchemy with bulk upsert semantics.
- Support cursor-based pagination for efficient large result set traversal.
- Detect data gaps by comparing consecutive candle timestamps.
- Manage data retention via time-based deletion.

Does NOT:
- Compute indicators or analytics (service layer responsibility).
- Know about specific data providers (Alpaca, Schwab, etc.).
- Manage database connections or transactions (caller responsibility).

Dependencies:
- SQLAlchemy Session (injected via constructor).
- libs.contracts.models.CandleRecord ORM model.
- libs.contracts.models.DataGapRecord ORM model.
- libs.contracts.market_data contracts.

Error conditions:
- ExternalServiceError: raised on database operation failure.

Example:
    db = next(get_db())
    repo = SqlMarketDataRepository(db=db)
    count = repo.upsert_candles([candle1, candle2])
    page = repo.query_candles(
        MarketDataQuery(symbol="AAPL", interval=CandleInterval.D1)
    )
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

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
from libs.contracts.models import CandleRecord

logger = logging.getLogger(__name__)


class SqlMarketDataRepository(MarketDataRepositoryInterface):
    """
    SQLAlchemy-backed implementation of MarketDataRepositoryInterface.

    Uses INSERT ... ON CONFLICT DO UPDATE for idempotent bulk upsert.
    Uses keyset (cursor-based) pagination for efficient large result sets
    without the offset-scan performance degradation of LIMIT/OFFSET.

    Responsibilities:
    - CRUD operations for CandleRecord ORM model.
    - Gap detection via timestamp comparison.
    - Data retention via time-based deletion.

    Does NOT:
    - Manage the SQLAlchemy Session lifecycle (caller responsibility).
    - Compute indicators or business metrics.

    Dependencies:
    - db: SQLAlchemy Session (injected via constructor).

    Example:
        repo = SqlMarketDataRepository(db=session)
        repo.upsert_candles([candle])
        page = repo.query_candles(query)
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    def upsert_candles(self, candles: list[Candle]) -> int:
        """
        Bulk upsert candle records using INSERT ... ON CONFLICT DO UPDATE.

        For SQLite, uses the sqlite dialect's insert().on_conflict_do_update().
        Processes candles in batches to avoid oversized SQL statements.

        Args:
            candles: List of Candle objects to upsert.

        Returns:
            Number of rows affected (inserted + updated).

        Raises:
            ExternalServiceError: If the database operation fails.

        Example:
            count = repo.upsert_candles(candles_list)
        """
        if not candles:
            return 0

        count = 0
        batch_size = 500

        for i in range(0, len(candles), batch_size):
            batch = candles[i : i + batch_size]
            values = [
                {
                    "symbol": c.symbol,
                    "interval": c.interval.value,
                    "timestamp": c.timestamp,
                    "open": str(c.open),
                    "high": str(c.high),
                    "low": str(c.low),
                    "close": str(c.close),
                    "volume": c.volume,
                    "vwap": str(c.vwap) if c.vwap is not None else None,
                    "trade_count": c.trade_count,
                }
                for c in batch
            ]

            stmt = sqlite_insert(CandleRecord).values(values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol", "interval", "timestamp"],
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "vwap": stmt.excluded.vwap,
                    "trade_count": stmt.excluded.trade_count,
                },
            )

            self._db.execute(stmt)
            count += len(batch)

        self._db.flush()

        logger.debug(
            "market_data.upsert_complete count=%d",
            count,
        )
        return count

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query_candles(self, query: MarketDataQuery) -> MarketDataPage:
        """
        Query candle records with filtering and cursor-based pagination.

        Uses keyset pagination (WHERE timestamp > cursor) instead of
        LIMIT/OFFSET for consistent performance on large datasets.

        Args:
            query: MarketDataQuery with filter and pagination parameters.

        Returns:
            MarketDataPage with candles, total count, pagination metadata.

        Example:
            page = repo.query_candles(query)
        """
        # Base filter: symbol + interval (always required)
        base_filter = [
            CandleRecord.symbol == query.symbol,
            CandleRecord.interval == query.interval.value,
        ]

        # Optional time range filters
        if query.start is not None:
            base_filter.append(CandleRecord.timestamp >= query.start)
        if query.end is not None:
            base_filter.append(CandleRecord.timestamp <= query.end)

        # Total count (before cursor and limit)
        count_stmt = select(func.count()).select_from(CandleRecord).where(*base_filter)
        total_count: int = self._db.execute(count_stmt).scalar() or 0

        # Apply cursor for pagination
        page_filter = list(base_filter)
        if query.cursor is not None:
            cursor_ts = datetime.fromisoformat(query.cursor)
            page_filter.append(CandleRecord.timestamp > cursor_ts)

        # Fetch limit + 1 to determine has_more
        fetch_limit = query.limit + 1
        data_stmt = (
            select(CandleRecord)
            .where(*page_filter)
            .order_by(CandleRecord.timestamp.asc())
            .limit(fetch_limit)
        )
        rows = list(self._db.execute(data_stmt).scalars().all())

        has_more = len(rows) > query.limit
        page_rows = rows[: query.limit]

        candles = [self._record_to_candle(r) for r in page_rows]

        next_cursor: str | None = None
        if has_more and page_rows:
            last_ts = page_rows[-1].timestamp
            # Ensure timezone-aware ISO format for cursor
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            next_cursor = last_ts.isoformat()

        return MarketDataPage(
            candles=candles,
            total_count=total_count,
            has_more=has_more,
            next_cursor=next_cursor,
        )

    # ------------------------------------------------------------------
    # Latest candle
    # ------------------------------------------------------------------

    def get_latest_candle(self, symbol: str, interval: CandleInterval) -> Candle | None:
        """
        Retrieve the most recent candle for a symbol and interval.

        Args:
            symbol: Ticker symbol.
            interval: Candle interval.

        Returns:
            Most recent Candle, or None if no data exists.

        Example:
            latest = repo.get_latest_candle("AAPL", CandleInterval.D1)
        """
        stmt = (
            select(CandleRecord)
            .where(
                CandleRecord.symbol == symbol,
                CandleRecord.interval == interval.value,
            )
            .order_by(CandleRecord.timestamp.desc())
            .limit(1)
        )
        row = self._db.execute(stmt).scalars().first()
        if row is None:
            return None
        return self._record_to_candle(row)

    # ------------------------------------------------------------------
    # Gap detection
    # ------------------------------------------------------------------

    def detect_gaps(
        self,
        symbol: str,
        interval: CandleInterval,
        start: datetime,
        end: datetime,
    ) -> list[DataGap]:
        """
        Detect gaps in candle data by comparing consecutive timestamps.

        Fetches all candles in the time range ordered by timestamp, then
        iterates pairwise to find gaps exceeding 1.5× the expected interval.

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
        stmt = (
            select(CandleRecord.timestamp)
            .where(
                CandleRecord.symbol == symbol,
                CandleRecord.interval == interval.value,
                CandleRecord.timestamp >= start,
                CandleRecord.timestamp <= end,
            )
            .order_by(CandleRecord.timestamp.asc())
        )
        timestamps = list(self._db.execute(stmt).scalars().all())

        if len(timestamps) < 2:
            return []

        expected_seconds = INTERVAL_SECONDS[interval]
        threshold_seconds = expected_seconds * 1.5

        now = datetime.now(timezone.utc)
        gaps: list[DataGap] = []

        for i in range(1, len(timestamps)):
            prev_ts = timestamps[i - 1]
            curr_ts = timestamps[i]
            delta = (curr_ts - prev_ts).total_seconds()
            if delta > threshold_seconds:
                gaps.append(
                    DataGap(
                        symbol=symbol,
                        interval=interval,
                        gap_start=prev_ts,
                        gap_end=curr_ts,
                        detected_at=now,
                    )
                )

        if gaps:
            logger.info(
                "market_data.gaps_detected symbol=%s interval=%s count=%d",
                symbol,
                interval.value,
                len(gaps),
            )

        return gaps

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

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
        stmt = delete(CandleRecord).where(
            CandleRecord.symbol == symbol,
            CandleRecord.interval == interval.value,
            CandleRecord.timestamp < before,
        )
        result = self._db.execute(stmt)
        self._db.flush()

        # SQLAlchemy 2.0: execute(delete()) returns a CursorResult exposing
        # rowcount, but the static return type is Result[Any] (which lacks the
        # attribute on stricter mypy + SQLAlchemy plugin versions). The runtime
        # type is always CursorResult for DML statements, so we read rowcount
        # via getattr with a typed fallback.
        deleted = getattr(result, "rowcount", 0)
        logger.debug(
            "market_data.delete_complete symbol=%s interval=%s deleted=%d",
            symbol,
            interval.value,
            deleted,
        )
        return deleted

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _record_to_candle(record: CandleRecord) -> Candle:
        """
        Convert a CandleRecord ORM instance to a Candle Pydantic model.

        Parses string price fields back to Decimal. Ensures timestamp is
        timezone-aware (UTC).

        Args:
            record: CandleRecord ORM instance.

        Returns:
            Candle Pydantic model.
        """
        ts = record.timestamp
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        return Candle(
            symbol=record.symbol,
            interval=CandleInterval(record.interval),
            open=Decimal(record.open),
            high=Decimal(record.high),
            low=Decimal(record.low),
            close=Decimal(record.close),
            volume=record.volume,
            vwap=Decimal(record.vwap) if record.vwap is not None else None,
            trade_count=record.trade_count,
            timestamp=ts,
        )
