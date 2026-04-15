"""
Market data contracts for OHLCV candlestick storage and retrieval.

Responsibilities:
- Define Pydantic schemas for candles, intervals, queries, and pagination.
- Define data gap tracking contracts for monitoring data quality.
- Provide value objects consumed by the market data repository, collector,
  indicator engine, and research engine.

Does NOT:
- Contain I/O, database queries, or network calls.
- Contain indicator calculation logic.
- Know about specific data providers (Alpaca, Schwab, etc.).

Dependencies:
- pydantic: BaseModel, Field
- datetime, decimal: standard library types
- enum: standard library

Error conditions:
- Pydantic ValidationError raised on invalid field values.

Example:
    from libs.contracts.market_data import Candle, CandleInterval, MarketDataQuery

    candle = Candle(
        symbol="AAPL",
        interval=CandleInterval.D1,
        open=Decimal("174.50"),
        high=Decimal("176.25"),
        low=Decimal("173.80"),
        close=Decimal("175.90"),
        volume=58_000_000,
        timestamp=datetime(2026, 4, 10, 0, 0, tzinfo=timezone.utc),
    )

    query = MarketDataQuery(
        symbol="AAPL",
        interval=CandleInterval.D1,
        start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 4, 10, tzinfo=timezone.utc),
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Candle interval enum
# ---------------------------------------------------------------------------


class CandleInterval(str, Enum):  # noqa: UP042 — Python 3.10 compatibility (no StrEnum)
    """
    Supported candlestick time intervals.

    Values are string representations used in API requests and database storage.
    The naming convention follows common financial data conventions:
    M = minutes, H = hours, D = days.

    Example:
        CandleInterval.M1   # 1-minute candles
        CandleInterval.D1   # Daily candles
    """

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    D1 = "1d"


# ---------------------------------------------------------------------------
# Interval duration mapping (used for gap detection)
# ---------------------------------------------------------------------------

#: Mapping from interval to the expected number of seconds between consecutive
#: candles. Used by gap detection logic to identify missing data points.
#: Market hours are NOT accounted for here — gap detection callers must filter
#: for trading hours before comparing against these expected durations.
INTERVAL_SECONDS: dict[CandleInterval, int] = {
    CandleInterval.M1: 60,
    CandleInterval.M5: 300,
    CandleInterval.M15: 900,
    CandleInterval.H1: 3600,
    CandleInterval.D1: 86400,
}


# ---------------------------------------------------------------------------
# Candle — the core OHLCV data point
# ---------------------------------------------------------------------------


class Candle(BaseModel):
    """
    A single OHLCV candlestick data point.

    Represents one bar of market data for a specific symbol and time interval.
    All prices are stored as Decimal for exact financial arithmetic (no
    floating-point rounding errors on aggregation).

    Attributes:
        symbol: Ticker symbol (e.g., "AAPL", "SPY"). Uppercased.
        interval: Candle time interval (1m, 5m, 15m, 1h, 1d).
        open: Opening price for the interval.
        high: Highest price during the interval.
        low: Lowest price during the interval.
        close: Closing price for the interval.
        volume: Total shares/contracts traded during the interval.
        vwap: Volume-weighted average price (optional; not all providers supply it).
        trade_count: Number of individual trades in the interval (optional).
        timestamp: UTC timestamp of the candle's opening time.

    Example:
        candle = Candle(
            symbol="AAPL",
            interval=CandleInterval.D1,
            open=Decimal("174.50"),
            high=Decimal("176.25"),
            low=Decimal("173.80"),
            close=Decimal("175.90"),
            volume=58_000_000,
            timestamp=datetime(2026, 4, 10, tzinfo=timezone.utc),
        )
    """

    model_config = {"frozen": True}

    symbol: str = Field(..., min_length=1, max_length=10, description="Ticker symbol (e.g., AAPL)")
    interval: CandleInterval = Field(..., description="Candle time interval")
    open: Decimal = Field(..., ge=0, description="Opening price")
    high: Decimal = Field(..., ge=0, description="Highest price in interval")
    low: Decimal = Field(..., ge=0, description="Lowest price in interval")
    close: Decimal = Field(..., ge=0, description="Closing price")
    volume: int = Field(..., ge=0, description="Total volume traded")
    vwap: Decimal | None = Field(default=None, ge=0, description="Volume-weighted average price")
    trade_count: int | None = Field(default=None, ge=0, description="Number of trades in interval")
    timestamp: datetime = Field(..., description="UTC timestamp of candle open")


# ---------------------------------------------------------------------------
# TickData — future tick-level data (schema placeholder)
# ---------------------------------------------------------------------------


class TickData(BaseModel):
    """
    A single tick (trade) record for future tick-level data support.

    Represents one executed trade at a specific price and size. Not currently
    stored in the candle pipeline but defined here so downstream consumers
    can reference a stable contract when tick support is added.

    Attributes:
        symbol: Ticker symbol.
        price: Execution price.
        size: Number of shares/contracts in the trade.
        timestamp: UTC timestamp of the trade.
        exchange: Exchange/venue where the trade occurred (e.g., "IEX", "NASDAQ").

    Example:
        tick = TickData(
            symbol="AAPL",
            price=Decimal("175.42"),
            size=100,
            timestamp=datetime(2026, 4, 10, 14, 30, 15, tzinfo=timezone.utc),
            exchange="IEX",
        )
    """

    model_config = {"frozen": True}

    symbol: str = Field(..., min_length=1, max_length=10, description="Ticker symbol")
    price: Decimal = Field(..., ge=0, description="Trade price")
    size: int = Field(..., ge=0, description="Trade size (shares/contracts)")
    timestamp: datetime = Field(..., description="UTC timestamp of the trade")
    exchange: str = Field(..., min_length=1, max_length=20, description="Exchange/venue identifier")


# ---------------------------------------------------------------------------
# DataGap — detected gap in candle data
# ---------------------------------------------------------------------------


class DataGap(BaseModel):
    """
    A detected gap in the candle data for a given symbol and interval.

    Gap detection compares consecutive candle timestamps against the expected
    interval duration. When the actual gap exceeds the expected duration (with
    tolerance for market close periods), a DataGap record is created.

    Attributes:
        symbol: Ticker symbol with the data gap.
        interval: Candle interval where the gap was detected.
        gap_start: Timestamp of the last candle before the gap.
        gap_end: Timestamp of the first candle after the gap.
        detected_at: When the gap was detected.

    Example:
        gap = DataGap(
            symbol="AAPL",
            interval=CandleInterval.M1,
            gap_start=datetime(2026, 4, 10, 14, 30, tzinfo=timezone.utc),
            gap_end=datetime(2026, 4, 10, 14, 35, tzinfo=timezone.utc),
            detected_at=datetime(2026, 4, 10, 15, 0, tzinfo=timezone.utc),
        )
    """

    model_config = {"frozen": True}

    symbol: str = Field(..., min_length=1, max_length=10, description="Ticker symbol")
    interval: CandleInterval = Field(..., description="Candle interval where the gap was detected")
    gap_start: datetime = Field(..., description="Timestamp of last candle before gap")
    gap_end: datetime = Field(..., description="Timestamp of first candle after gap")
    detected_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the gap was detected",
    )


# ---------------------------------------------------------------------------
# MarketDataQuery — query parameters for candle retrieval
# ---------------------------------------------------------------------------


class MarketDataQuery(BaseModel):
    """
    Query parameters for retrieving candle data from the market data repository.

    Supports time-range filtering, pagination via cursor, and result limiting.
    The cursor is an opaque string (ISO-8601 timestamp of the last candle
    returned in the previous page) enabling efficient keyset pagination.

    Attributes:
        symbol: Ticker symbol to query.
        interval: Candle interval to query.
        start: Start of the time range (inclusive). Optional; omit for no lower bound.
        end: End of the time range (inclusive). Optional; omit for no upper bound.
        limit: Maximum number of candles to return per page (default 1000, max 10000).
        cursor: Opaque pagination cursor from a previous MarketDataPage.next_cursor.

    Example:
        query = MarketDataQuery(
            symbol="AAPL",
            interval=CandleInterval.D1,
            start=datetime(2025, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 4, 10, tzinfo=timezone.utc),
            limit=500,
        )
    """

    symbol: str = Field(..., min_length=1, max_length=10, description="Ticker symbol")
    interval: CandleInterval = Field(..., description="Candle interval")
    start: datetime | None = Field(default=None, description="Start of time range (inclusive)")
    end: datetime | None = Field(default=None, description="End of time range (inclusive)")
    limit: int = Field(default=1000, ge=1, le=10000, description="Max candles per page")
    cursor: str | None = Field(default=None, description="Pagination cursor from previous page")


# ---------------------------------------------------------------------------
# MarketDataPage — paginated response
# ---------------------------------------------------------------------------


class MarketDataPage(BaseModel):
    """
    Paginated response from a market data candle query.

    Contains the candle results and metadata for cursor-based pagination.
    Clients should check has_more and pass next_cursor to the next query
    to retrieve subsequent pages.

    Attributes:
        candles: List of candle records for this page.
        total_count: Total number of candles matching the query (across all pages).
        has_more: True if additional pages exist beyond this one.
        next_cursor: Opaque cursor to pass as MarketDataQuery.cursor for the next page.
            None when has_more is False.

    Example:
        page = MarketDataPage(
            candles=[candle1, candle2],
            total_count=1500,
            has_more=True,
            next_cursor="2025-06-15T00:00:00+00:00",
        )
    """

    candles: list[Candle] = Field(default_factory=list, description="Candle records for this page")
    total_count: int = Field(..., ge=0, description="Total candles matching the query")
    has_more: bool = Field(..., description="Whether more pages exist")
    next_cursor: str | None = Field(default=None, description="Cursor for the next page")
