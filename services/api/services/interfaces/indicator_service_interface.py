"""
Indicator service interface — contract for indicator computation service.

Responsibilities:
- Define the abstract interface for computing technical indicators.
- Provide a clean boundary between the API routes and indicator engine.

Does NOT:
- Contain implementation logic.
- Import concrete dependencies.

Dependencies:
- libs.contracts.indicator: IndicatorResult, IndicatorRequest, IndicatorInfo.
- libs.contracts.market_data: CandleInterval.

Example:
    service: IndicatorServiceInterface = get_indicator_service()
    result = service.compute_indicator("SMA", "AAPL", CandleInterval.D1, period=20)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from libs.contracts.indicator import IndicatorInfo, IndicatorRequest, IndicatorResult
from libs.contracts.market_data import CandleInterval


class IndicatorServiceInterface(ABC):
    """
    Abstract interface for the indicator computation service.

    Implementations fetch candle data from the market data repository,
    delegate computation to the IndicatorEngine, and optionally cache
    results.

    Responsibilities:
    - Compute single or batch indicators for a given symbol and interval.
    - List available indicators with metadata.
    - Retrieve detailed info for a specific indicator.

    Does NOT:
    - Contain indicator math (delegated to IndicatorEngine).
    - Handle HTTP request/response (that's the route layer).
    """

    @abstractmethod
    def compute_indicator(
        self,
        indicator_name: str,
        symbol: str,
        interval: CandleInterval,
        start: datetime | None = None,
        end: datetime | None = None,
        **params: object,
    ) -> IndicatorResult:
        """
        Compute a single indicator for a symbol and interval.

        Args:
            indicator_name: Canonical indicator name (e.g. "SMA").
            symbol: Ticker symbol (e.g. "AAPL").
            interval: Candle interval.
            start: Start of time range (inclusive).
            end: End of time range (inclusive).
            **params: Indicator-specific parameters.

        Returns:
            IndicatorResult with computed values and timestamps.

        Raises:
            IndicatorNotFoundError: If indicator_name is not registered.
            NotFoundError: If no candle data exists for the symbol/interval.
        """

    @abstractmethod
    def compute_batch(
        self,
        requests: list[IndicatorRequest],
        symbol: str,
        interval: CandleInterval,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, IndicatorResult]:
        """
        Compute multiple indicators for the same symbol and interval.

        Args:
            requests: List of IndicatorRequest specifying indicators and params.
            symbol: Ticker symbol.
            interval: Candle interval.
            start: Start of time range.
            end: End of time range.

        Returns:
            Dict mapping indicator keys to IndicatorResult instances.

        Raises:
            IndicatorNotFoundError: If any requested indicator is not registered.
            NotFoundError: If no candle data exists.
        """

    @abstractmethod
    def list_available(self) -> list[IndicatorInfo]:
        """
        List all available indicators with metadata.

        Returns:
            List of IndicatorInfo, sorted by name.
        """

    @abstractmethod
    def get_indicator_info(self, name: str) -> IndicatorInfo:
        """
        Get detailed info for a specific indicator.

        Args:
            name: Indicator name (case-insensitive).

        Returns:
            IndicatorInfo for the named indicator.

        Raises:
            IndicatorNotFoundError: If name is not registered.
        """
