"""
Unit tests for MarketDataProviderInterface mock implementation.

Validates the mock provider behaves correctly as a stand-in for real
providers, ensuring the collector service tests exercise realistic
provider behaviour.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from libs.contracts.errors import ExternalServiceError, ValidationError
from libs.contracts.market_data import Candle, CandleInterval
from libs.contracts.mocks.mock_market_data_provider import MockMarketDataProvider

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


# ---------------------------------------------------------------------------
# MockMarketDataProvider tests
# ---------------------------------------------------------------------------


class TestMockProviderFetchBars:
    """Tests for MockMarketDataProvider.fetch_historical_bars()."""

    def test_returns_empty_list_when_no_bars_loaded(self) -> None:
        provider = MockMarketDataProvider()
        result = provider.fetch_historical_bars(
            "AAPL", CandleInterval.D1, _BASE_TS, _BASE_TS + timedelta(days=30)
        )
        assert result == []

    def test_returns_loaded_bars_within_time_range(self) -> None:
        provider = MockMarketDataProvider()
        candles = _make_daily_candles(count=10)
        provider.set_bars("AAPL", CandleInterval.D1, candles)

        result = provider.fetch_historical_bars(
            "AAPL",
            CandleInterval.D1,
            _BASE_TS + timedelta(days=3),
            _BASE_TS + timedelta(days=6),
        )
        assert len(result) == 4  # days 3, 4, 5, 6

    def test_returns_all_bars_when_range_covers_full_set(self) -> None:
        provider = MockMarketDataProvider()
        candles = _make_daily_candles(count=5)
        provider.set_bars("AAPL", CandleInterval.D1, candles)

        result = provider.fetch_historical_bars(
            "AAPL",
            CandleInterval.D1,
            _BASE_TS - timedelta(days=1),
            _BASE_TS + timedelta(days=100),
        )
        assert len(result) == 5

    def test_filters_by_symbol(self) -> None:
        provider = MockMarketDataProvider()
        aapl = _make_daily_candles(symbol="AAPL", count=5)
        spy = _make_daily_candles(symbol="SPY", count=3)
        provider.set_bars("AAPL", CandleInterval.D1, aapl)
        provider.set_bars("SPY", CandleInterval.D1, spy)

        result = provider.fetch_historical_bars(
            "AAPL", CandleInterval.D1, _BASE_TS, _BASE_TS + timedelta(days=100)
        )
        assert len(result) == 5
        assert all(c.symbol == "AAPL" for c in result)

    def test_raises_injected_error(self) -> None:
        provider = MockMarketDataProvider()
        provider.set_error("AAPL", ExternalServiceError("Alpaca is down"))

        with pytest.raises(ExternalServiceError, match="Alpaca is down"):
            provider.fetch_historical_bars(
                "AAPL", CandleInterval.D1, _BASE_TS, _BASE_TS + timedelta(days=1)
            )

    def test_raises_validation_error_for_unsupported_interval(self) -> None:
        provider = MockMarketDataProvider()
        provider.set_supported_intervals([CandleInterval.D1])

        with pytest.raises(ValidationError, match="not supported"):
            provider.fetch_historical_bars(
                "AAPL", CandleInterval.M1, _BASE_TS, _BASE_TS + timedelta(days=1)
            )

    def test_increments_fetch_count(self) -> None:
        provider = MockMarketDataProvider()
        assert provider.fetch_count == 0

        provider.fetch_historical_bars(
            "AAPL", CandleInterval.D1, _BASE_TS, _BASE_TS + timedelta(days=1)
        )
        assert provider.fetch_count == 1

        provider.fetch_historical_bars(
            "SPY", CandleInterval.D1, _BASE_TS, _BASE_TS + timedelta(days=1)
        )
        assert provider.fetch_count == 2

    def test_records_fetch_log(self) -> None:
        provider = MockMarketDataProvider()
        start = _BASE_TS
        end = _BASE_TS + timedelta(days=5)
        provider.fetch_historical_bars("AAPL", CandleInterval.D1, start, end)

        assert len(provider.fetch_log) == 1
        assert provider.fetch_log[0] == ("AAPL", CandleInterval.D1, start, end)


class TestMockProviderMetadata:
    """Tests for provider metadata methods."""

    def test_get_provider_name_returns_mock(self) -> None:
        provider = MockMarketDataProvider()
        assert provider.get_provider_name() == "mock"

    def test_get_supported_intervals_returns_all_by_default(self) -> None:
        provider = MockMarketDataProvider()
        intervals = provider.get_supported_intervals()
        assert set(intervals) == set(CandleInterval)

    def test_set_supported_intervals_overrides_defaults(self) -> None:
        provider = MockMarketDataProvider()
        provider.set_supported_intervals([CandleInterval.D1, CandleInterval.H1])
        intervals = provider.get_supported_intervals()
        assert intervals == [CandleInterval.D1, CandleInterval.H1]


class TestMockProviderIntrospection:
    """Tests for mock introspection helpers."""

    def test_clear_resets_all_state(self) -> None:
        provider = MockMarketDataProvider()
        provider.set_bars("AAPL", CandleInterval.D1, _make_daily_candles(count=3))
        provider.set_error("SPY", ExternalServiceError("test"))
        provider.fetch_historical_bars(
            "AAPL", CandleInterval.D1, _BASE_TS, _BASE_TS + timedelta(days=100)
        )

        provider.clear()

        assert provider.fetch_count == 0
        assert provider.fetch_log == []
        result = provider.fetch_historical_bars(
            "AAPL", CandleInterval.D1, _BASE_TS, _BASE_TS + timedelta(days=100)
        )
        assert result == []
        # SPY error should be cleared
        result = provider.fetch_historical_bars(
            "SPY", CandleInterval.D1, _BASE_TS, _BASE_TS + timedelta(days=100)
        )
        assert result == []

    def test_clear_error_removes_single_symbol_error(self) -> None:
        provider = MockMarketDataProvider()
        provider.set_error("AAPL", ExternalServiceError("test"))
        provider.clear_error("AAPL")

        # Should not raise
        result = provider.fetch_historical_bars(
            "AAPL", CandleInterval.D1, _BASE_TS, _BASE_TS + timedelta(days=1)
        )
        assert result == []
