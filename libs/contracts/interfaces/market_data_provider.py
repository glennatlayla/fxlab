"""
Market data provider interface for external data source adapters.

Responsibilities:
- Define the abstract contract for fetching OHLCV candlestick data from
  external market data APIs (Alpaca, Schwab, Polygon, etc.).
- Provide a uniform API that the market data collector service depends on,
  decoupling collection logic from specific provider implementations.

Does NOT:
- Persist data (that's the MarketDataRepositoryInterface's job).
- Compute indicators or analytics.
- Manage API credentials or HTTP connections (concrete adapters own that).

Dependencies:
- libs.contracts.market_data: Candle, CandleInterval contracts.
- datetime: Standard library time types.

Error conditions:
- ExternalServiceError: Raised by concrete implementations on API failure.
- TransientError: Raised on retriable failures (429, 5xx, timeout).
- AuthError: Raised on invalid credentials (401/403).

Example:
    provider: MarketDataProviderInterface = AlpacaMarketDataProvider(config)
    candles = provider.fetch_historical_bars(
        symbol="AAPL",
        interval=CandleInterval.D1,
        start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 4, 10, tzinfo=timezone.utc),
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from libs.contracts.market_data import Candle, CandleInterval


class MarketDataProviderInterface(ABC):
    """
    Abstract interface for external market data providers.

    Concrete implementations wrap a specific data vendor's REST API
    (Alpaca, Schwab, Polygon, etc.) and map vendor-specific bar formats
    to the canonical Candle contract.

    Responsibilities:
    - Fetch historical OHLCV bars for a symbol and interval.
    - Report which intervals the provider supports.
    - Identify the provider by name (for logging and diagnostics).

    Does NOT:
    - Persist candles (collector service handles that).
    - Manage rate limiting across multiple providers.
    - Handle real-time streaming (separate interface in M3).

    Dependencies:
    - External API client (injected in concrete implementation).

    Example:
        provider = AlpacaMarketDataProvider(config=config)
        bars = provider.fetch_historical_bars("AAPL", CandleInterval.D1, start, end)
        name = provider.get_provider_name()  # "alpaca"
    """

    @abstractmethod
    def fetch_historical_bars(
        self,
        symbol: str,
        interval: CandleInterval,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """
        Fetch historical OHLCV bars for a symbol within a time range.

        The provider handles pagination internally (e.g. Alpaca page_token)
        and returns the complete list of candles for the requested range.

        Args:
            symbol: Ticker symbol (e.g. "AAPL", "SPY"). Case-insensitive;
                provider normalises to its API's expected format.
            interval: Candle time interval to fetch.
            start: Start of the time range (inclusive), timezone-aware UTC.
            end: End of the time range (inclusive), timezone-aware UTC.

        Returns:
            List of Candle objects ordered by timestamp ascending.
            Empty list if no data exists for the range.

        Raises:
            ExternalServiceError: On unrecoverable API failure.
            TransientError: On retriable failure (429, 5xx, timeout).
            AuthError: On authentication or permission failure.
            ValidationError: If the interval is not supported by this provider.

        Example:
            candles = provider.fetch_historical_bars(
                "AAPL", CandleInterval.D1,
                datetime(2025, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            # len(candles) ≈ 252 (trading days in a year)
        """

    @abstractmethod
    def get_supported_intervals(self) -> list[CandleInterval]:
        """
        Return the list of candle intervals this provider supports.

        Returns:
            List of CandleInterval values the provider can fetch.

        Example:
            intervals = provider.get_supported_intervals()
            # [CandleInterval.M1, CandleInterval.D1, ...]
        """

    @abstractmethod
    def get_provider_name(self) -> str:
        """
        Return a stable, lowercase identifier for this provider.

        Used in logging, metrics labels, and diagnostics. Must be a
        short, ASCII-only string (e.g. "alpaca", "schwab", "polygon").

        Returns:
            Provider name string.

        Example:
            provider.get_provider_name()  # "alpaca"
        """
