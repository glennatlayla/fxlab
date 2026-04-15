"""
Mock market data provider for unit testing.

Responsibilities:
- Implement MarketDataProviderInterface with in-memory candle storage.
- Support programmable responses for testing collection service logic.
- Allow injection of errors for failure-mode testing.
- Provide introspection helpers for test assertions.

Does NOT:
- Make real API calls.
- Implement rate limiting or pagination.
- Persist data beyond the test session.

Dependencies:
- libs.contracts.interfaces.market_data_provider: Interface contract.
- libs.contracts.market_data: Candle, CandleInterval value objects.

Example:
    provider = MockMarketDataProvider()
    provider.set_bars("AAPL", CandleInterval.D1, candles)
    result = provider.fetch_historical_bars("AAPL", CandleInterval.D1, start, end)
    assert provider.fetch_count == 1
"""

from __future__ import annotations

from datetime import datetime

from libs.contracts.errors import ValidationError
from libs.contracts.interfaces.market_data_provider import (
    MarketDataProviderInterface,
)
from libs.contracts.market_data import Candle, CandleInterval


class MockMarketDataProvider(MarketDataProviderInterface):
    """
    In-memory mock implementation of MarketDataProviderInterface.

    Stores candles in a dict keyed by (symbol, interval). Supports
    programmable error injection via set_error() for testing failure modes.

    Responsibilities:
    - Return pre-loaded candles filtered by time range.
    - Raise injected errors for specific symbols.
    - Track fetch call count for assertion in tests.

    Does NOT:
    - Simulate rate limiting or pagination.
    - Validate API credentials.

    Example:
        mock = MockMarketDataProvider()
        mock.set_bars("AAPL", CandleInterval.D1, candles)
        bars = mock.fetch_historical_bars("AAPL", CandleInterval.D1, start, end)
        assert mock.fetch_count == 1
    """

    def __init__(self) -> None:
        self._bars: dict[tuple[str, str], list[Candle]] = {}
        self._errors: dict[str, Exception] = {}
        self._supported_intervals: list[CandleInterval] = list(CandleInterval)
        self._fetch_count: int = 0
        self._fetch_log: list[tuple[str, CandleInterval, datetime, datetime]] = []

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    def fetch_historical_bars(
        self,
        symbol: str,
        interval: CandleInterval,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """
        Return pre-loaded candles for the requested symbol and interval.

        Filters stored candles by the [start, end] time range.
        Raises any injected error for the symbol before returning data.

        Args:
            symbol: Ticker symbol.
            interval: Candle interval.
            start: Start of time range (inclusive).
            end: End of time range (inclusive).

        Returns:
            Filtered list of Candle objects.

        Raises:
            ExternalServiceError: If an error was injected for this symbol.
            ValidationError: If the interval is not in supported intervals.
        """
        self._fetch_count += 1
        self._fetch_log.append((symbol, interval, start, end))

        # Check for injected errors
        if symbol in self._errors:
            raise self._errors[symbol]

        # Validate interval
        if interval not in self._supported_intervals:
            raise ValidationError(
                f"Interval {interval.value} not supported by {self.get_provider_name()}"
            )

        key = (symbol.upper(), interval.value)
        all_bars = self._bars.get(key, [])

        # Filter by time range
        return [c for c in all_bars if start <= c.timestamp <= end]

    def get_supported_intervals(self) -> list[CandleInterval]:
        """Return configured supported intervals."""
        return list(self._supported_intervals)

    def get_provider_name(self) -> str:
        """Return 'mock' as the provider name."""
        return "mock"

    # ------------------------------------------------------------------
    # Test setup helpers
    # ------------------------------------------------------------------

    def set_bars(self, symbol: str, interval: CandleInterval, candles: list[Candle]) -> None:
        """
        Pre-load candles that will be returned by fetch_historical_bars.

        Args:
            symbol: Ticker symbol.
            interval: Candle interval.
            candles: Candles to store.
        """
        key = (symbol.upper(), interval.value)
        self._bars[key] = sorted(candles, key=lambda c: c.timestamp)

    def set_error(self, symbol: str, error: Exception) -> None:
        """
        Inject an error that will be raised when fetching the given symbol.

        Args:
            symbol: Ticker symbol that triggers the error.
            error: Exception to raise.
        """
        self._errors[symbol] = error

    def clear_error(self, symbol: str) -> None:
        """Remove injected error for a symbol."""
        self._errors.pop(symbol, None)

    def set_supported_intervals(self, intervals: list[CandleInterval]) -> None:
        """Override the list of supported intervals."""
        self._supported_intervals = list(intervals)

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    @property
    def fetch_count(self) -> int:
        """Number of times fetch_historical_bars was called."""
        return self._fetch_count

    @property
    def fetch_log(self) -> list[tuple[str, CandleInterval, datetime, datetime]]:
        """Log of all fetch calls: (symbol, interval, start, end)."""
        return list(self._fetch_log)

    def clear(self) -> None:
        """Reset all stored bars, errors, and counters."""
        self._bars.clear()
        self._errors.clear()
        self._fetch_count = 0
        self._fetch_log.clear()
        self._supported_intervals = list(CandleInterval)
