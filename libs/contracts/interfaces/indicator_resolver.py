"""
Indicator resolver interface (port) for backtest engine integration.

Responsibilities:
- Define the abstract contract for resolving indicator values during backtesting.
- Serve as the dependency injection target for the research engine.

Does NOT:
- Implement resolution logic (IndicatorResolver implementation responsibility).
- Fetch market data (delegates to MarketDataRepositoryInterface).
- Compute indicators (delegates to IndicatorEngine).

Dependencies:
- None (pure interface).

Error conditions:
- IndicatorNotFoundError: unknown indicator name.
- ValidationError: insufficient data for indicator computation.

Example:
    resolver: IndicatorResolverInterface = IndicatorResolver(...)
    values = resolver.resolve("MACD", "AAPL", start, end, fast=12, slow=26, signal=9)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal


class IndicatorResolverInterface(ABC):
    """
    Port interface for resolving indicator values from historical data.

    Responsibilities:
    - Resolve indicator values for a symbol over a date range.
    - Cache computed results within a backtest run.
    - Handle lookback buffer automatically.

    Does NOT:
    - Execute trades or manage positions.
    - Persist results (caller responsibility).
    """

    @abstractmethod
    def resolve(
        self,
        indicator_name: str,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "1d",
        **params: int | float,
    ) -> list[Decimal | None]:
        """
        Resolve indicator values for a symbol over a date range.

        Fetches candle data (including lookback buffer), computes the
        indicator, and returns values aligned to the date range bars.

        Args:
            indicator_name: Name of the indicator (e.g., "SMA", "MACD").
            symbol: Instrument ticker.
            start: Start of the evaluation period.
            end: End of the evaluation period.
            interval: Candle interval (default "1d").
            **params: Indicator-specific parameters (e.g., period=20).

        Returns:
            List of indicator values, one per bar in the date range.
            None values indicate insufficient lookback data.

        Raises:
            IndicatorNotFoundError: If the indicator is not registered.
        """
        ...

    @abstractmethod
    def resolve_at_bar(
        self,
        indicator_name: str,
        symbol: str,
        bar_timestamp: datetime,
        interval: str = "1d",
        lookback_bars: int = 300,
        **params: int | float,
    ) -> Decimal | None:
        """
        Resolve a single indicator value at a specific bar timestamp.

        Args:
            indicator_name: Name of the indicator.
            symbol: Instrument ticker.
            bar_timestamp: Target bar timestamp.
            interval: Candle interval.
            lookback_bars: Number of bars to fetch for computation.
            **params: Indicator-specific parameters.

        Returns:
            Indicator value at the bar, or None if insufficient data.

        Raises:
            IndicatorNotFoundError: If the indicator is not registered.
        """
        ...

    @abstractmethod
    def clear_cache(self) -> None:
        """Clear the internal indicator result cache."""
        ...

    @abstractmethod
    def get_cache_stats(self) -> dict[str, int]:
        """
        Return cache statistics.

        Returns:
            Dict with 'hits', 'misses', 'size' keys.
        """
        ...
