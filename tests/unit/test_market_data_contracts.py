"""
Unit tests for market data Pydantic contracts.

Validates schema constraints, serialization, and edge cases for Candle,
CandleInterval, MarketDataQuery, MarketDataPage, TickData, and DataGap.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from libs.contracts.market_data import (
    Candle,
    CandleInterval,
    DataGap,
    MarketDataPage,
    MarketDataQuery,
    TickData,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS = datetime(2026, 4, 10, 14, 30, 0, tzinfo=timezone.utc)


def _make_candle(**overrides) -> Candle:
    """Create a valid Candle with sensible defaults, overriding any field."""
    defaults = {
        "symbol": "AAPL",
        "interval": CandleInterval.D1,
        "open": Decimal("174.50"),
        "high": Decimal("176.25"),
        "low": Decimal("173.80"),
        "close": Decimal("175.90"),
        "volume": 58_000_000,
        "timestamp": _TS,
    }
    defaults.update(overrides)
    return Candle(**defaults)


# ---------------------------------------------------------------------------
# CandleInterval
# ---------------------------------------------------------------------------


class TestCandleInterval:
    """CandleInterval enum value tests."""

    def test_interval_values_match_string_representation(self) -> None:
        assert CandleInterval.M1.value == "1m"
        assert CandleInterval.M5.value == "5m"
        assert CandleInterval.M15.value == "15m"
        assert CandleInterval.H1.value == "1h"
        assert CandleInterval.H4.value == "4h"
        assert CandleInterval.D1.value == "1d"

    def test_interval_count_is_six(self) -> None:
        # 6 intervals: M1, M5, M15, H1, H4, D1.
        # H4 was added on 2026-04-25 alongside the synthetic FX provider
        # that emits H4 bars natively. Update this count + the rationale
        # whenever a new interval lands.
        assert len(CandleInterval) == 6


# ---------------------------------------------------------------------------
# Candle
# ---------------------------------------------------------------------------


class TestCandle:
    """Candle Pydantic model validation tests."""

    def test_candle_valid_construction(self) -> None:
        candle = _make_candle()
        assert candle.symbol == "AAPL"
        assert candle.interval == CandleInterval.D1
        assert candle.open == Decimal("174.50")
        assert candle.high == Decimal("176.25")
        assert candle.low == Decimal("173.80")
        assert candle.close == Decimal("175.90")
        assert candle.volume == 58_000_000
        assert candle.vwap is None
        assert candle.trade_count is None
        assert candle.timestamp == _TS

    def test_candle_with_optional_fields(self) -> None:
        candle = _make_candle(
            vwap=Decimal("175.10"),
            trade_count=12_345,
        )
        assert candle.vwap == Decimal("175.10")
        assert candle.trade_count == 12_345

    def test_candle_is_frozen(self) -> None:
        candle = _make_candle()
        with pytest.raises(ValidationError):
            candle.close = Decimal("999.99")  # type: ignore[misc]

    def test_candle_rejects_empty_symbol(self) -> None:
        with pytest.raises(ValidationError, match="symbol"):
            _make_candle(symbol="")

    def test_candle_rejects_symbol_too_long(self) -> None:
        with pytest.raises(ValidationError, match="symbol"):
            _make_candle(symbol="A" * 11)

    def test_candle_rejects_negative_price(self) -> None:
        with pytest.raises(ValidationError, match="open"):
            _make_candle(open=Decimal("-1.00"))

    def test_candle_rejects_negative_volume(self) -> None:
        with pytest.raises(ValidationError, match="volume"):
            _make_candle(volume=-1)

    def test_candle_rejects_negative_vwap(self) -> None:
        with pytest.raises(ValidationError, match="vwap"):
            _make_candle(vwap=Decimal("-0.01"))

    def test_candle_allows_zero_price(self) -> None:
        """Zero is valid — some instruments can trade to zero."""
        candle = _make_candle(open=Decimal("0"), close=Decimal("0"))
        assert candle.open == Decimal("0")

    def test_candle_serialization_round_trip(self) -> None:
        candle = _make_candle(vwap=Decimal("175.10"))
        data = candle.model_dump()
        restored = Candle(**data)
        assert restored == candle


# ---------------------------------------------------------------------------
# TickData
# ---------------------------------------------------------------------------


class TestTickData:
    """TickData Pydantic model validation tests."""

    def test_tick_valid_construction(self) -> None:
        tick = TickData(
            symbol="AAPL",
            price=Decimal("175.42"),
            size=100,
            timestamp=_TS,
            exchange="IEX",
        )
        assert tick.symbol == "AAPL"
        assert tick.price == Decimal("175.42")
        assert tick.exchange == "IEX"

    def test_tick_is_frozen(self) -> None:
        tick = TickData(
            symbol="AAPL",
            price=Decimal("175.42"),
            size=100,
            timestamp=_TS,
            exchange="IEX",
        )
        with pytest.raises(ValidationError):
            tick.price = Decimal("999.99")  # type: ignore[misc]

    def test_tick_rejects_negative_size(self) -> None:
        with pytest.raises(ValidationError, match="size"):
            TickData(
                symbol="AAPL",
                price=Decimal("175.42"),
                size=-1,
                timestamp=_TS,
                exchange="IEX",
            )


# ---------------------------------------------------------------------------
# DataGap
# ---------------------------------------------------------------------------


class TestDataGap:
    """DataGap Pydantic model validation tests."""

    def test_data_gap_valid_construction(self) -> None:
        gap = DataGap(
            symbol="AAPL",
            interval=CandleInterval.M1,
            gap_start=datetime(2026, 4, 10, 14, 30, tzinfo=timezone.utc),
            gap_end=datetime(2026, 4, 10, 14, 35, tzinfo=timezone.utc),
        )
        assert gap.symbol == "AAPL"
        assert gap.interval == CandleInterval.M1
        assert gap.detected_at is not None  # auto-populated

    def test_data_gap_is_frozen(self) -> None:
        gap = DataGap(
            symbol="AAPL",
            interval=CandleInterval.M1,
            gap_start=_TS,
            gap_end=_TS,
        )
        with pytest.raises(ValidationError):
            gap.symbol = "SPY"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# MarketDataQuery
# ---------------------------------------------------------------------------


class TestMarketDataQuery:
    """MarketDataQuery Pydantic model validation tests."""

    def test_query_minimal_construction(self) -> None:
        query = MarketDataQuery(
            symbol="AAPL",
            interval=CandleInterval.D1,
        )
        assert query.symbol == "AAPL"
        assert query.interval == CandleInterval.D1
        assert query.start is None
        assert query.end is None
        assert query.limit == 1000
        assert query.cursor is None

    def test_query_full_construction(self) -> None:
        query = MarketDataQuery(
            symbol="SPY",
            interval=CandleInterval.M5,
            start=datetime(2025, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 4, 10, tzinfo=timezone.utc),
            limit=500,
            cursor="2025-06-15T00:00:00+00:00",
        )
        assert query.limit == 500
        assert query.cursor == "2025-06-15T00:00:00+00:00"

    def test_query_rejects_limit_zero(self) -> None:
        with pytest.raises(ValidationError, match="limit"):
            MarketDataQuery(
                symbol="AAPL",
                interval=CandleInterval.D1,
                limit=0,
            )

    def test_query_rejects_limit_exceeding_max(self) -> None:
        with pytest.raises(ValidationError, match="limit"):
            MarketDataQuery(
                symbol="AAPL",
                interval=CandleInterval.D1,
                limit=10001,
            )

    def test_query_rejects_empty_symbol(self) -> None:
        with pytest.raises(ValidationError, match="symbol"):
            MarketDataQuery(symbol="", interval=CandleInterval.D1)


# ---------------------------------------------------------------------------
# MarketDataPage
# ---------------------------------------------------------------------------


class TestMarketDataPage:
    """MarketDataPage Pydantic model validation tests."""

    def test_page_empty_result(self) -> None:
        page = MarketDataPage(
            candles=[],
            total_count=0,
            has_more=False,
        )
        assert page.candles == []
        assert page.total_count == 0
        assert page.has_more is False
        assert page.next_cursor is None

    def test_page_with_results_and_cursor(self) -> None:
        candle = _make_candle()
        page = MarketDataPage(
            candles=[candle],
            total_count=100,
            has_more=True,
            next_cursor="2026-04-10T14:30:00+00:00",
        )
        assert len(page.candles) == 1
        assert page.has_more is True
        assert page.next_cursor is not None

    def test_page_rejects_negative_total_count(self) -> None:
        with pytest.raises(ValidationError, match="total_count"):
            MarketDataPage(
                candles=[],
                total_count=-1,
                has_more=False,
            )
