"""
Indicator computation service — orchestrates candle fetching and indicator calculation.

Responsibilities:
- Fetch candle data from the market data repository for requested symbol/interval.
- Delegate indicator computation to the IndicatorEngine.
- List available indicators and provide metadata.
- Structured logging for compute requests.

Does NOT:
- Contain indicator math (delegated to IndicatorEngine).
- Handle HTTP request/response (that's the route layer).
- Manage database connections (injected via constructor).

Dependencies:
- libs.indicators.IndicatorEngine: indicator computation.
- libs.contracts.interfaces.market_data_repository.MarketDataRepositoryInterface: candle data.
- structlog: structured logging.

Error conditions:
- IndicatorNotFoundError: requested indicator not registered.
- NotFoundError: no candle data for symbol/interval.

Example:
    service = IndicatorService(engine=engine, market_data_repo=repo)
    result = service.compute_indicator("SMA", "AAPL", CandleInterval.D1, period=20)
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import structlog

from libs.contracts.errors import NotFoundError
from libs.contracts.indicator import IndicatorInfo, IndicatorRequest, IndicatorResult
from libs.contracts.market_data import CandleInterval, MarketDataQuery
from libs.indicators.engine import IndicatorEngine
from services.api.services.interfaces.indicator_service_interface import (
    IndicatorServiceInterface,
)

logger = structlog.get_logger(__name__)


class IndicatorService(IndicatorServiceInterface):
    """
    Production indicator computation service.

    Fetches candles from the market data repository, delegates computation
    to the IndicatorEngine, and returns results with metadata.

    Responsibilities:
    - Candle retrieval for indicator input data.
    - Single and batch indicator computation.
    - Available indicator listing.
    - Structured logging.

    Does NOT:
    - Contain indicator math.
    - Manage HTTP layer concerns.
    - Hold mutable state between requests.

    Dependencies:
    - IndicatorEngine: indicator calculation dispatch.
    - MarketDataRepositoryInterface: candle data access.

    Example:
        service = IndicatorService(engine=engine, market_data_repo=repo)
        result = service.compute_indicator("SMA", "AAPL", CandleInterval.D1, period=20)
    """

    def __init__(
        self,
        engine: IndicatorEngine,
        market_data_repo: Any,
    ) -> None:
        self._engine = engine
        self._repo = market_data_repo

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

        Fetches candles from the repository, delegates to the engine,
        and logs the computation.

        Args:
            indicator_name: Canonical indicator name.
            symbol: Ticker symbol.
            interval: Candle interval.
            start: Start of time range.
            end: End of time range.
            **params: Indicator-specific parameters.

        Returns:
            IndicatorResult with computed values.

        Raises:
            IndicatorNotFoundError: If indicator_name is not registered.
            NotFoundError: If no candle data exists.
        """
        t0 = time.monotonic()

        candles = self._fetch_candles(symbol, interval, start, end)
        if not candles:
            raise NotFoundError(
                f"No candle data for {symbol} at {interval.value}. "
                f"Ensure market data has been collected."
            )

        result = self._engine.compute(indicator_name, candles, **params)

        duration_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "indicator.computed",
            operation="indicator_compute",
            component="IndicatorService",
            indicator=indicator_name,
            symbol=symbol,
            interval=interval.value,
            candle_count=len(candles),
            duration_ms=round(duration_ms, 2),
            result="success",
        )

        return result

    def compute_batch(
        self,
        requests: list[IndicatorRequest],
        symbol: str,
        interval: CandleInterval,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, IndicatorResult]:
        """
        Compute multiple indicators for the same candle data.

        Args:
            requests: List of IndicatorRequest.
            symbol: Ticker symbol.
            interval: Candle interval.
            start: Start of time range.
            end: End of time range.

        Returns:
            Dict mapping indicator keys to results.

        Raises:
            IndicatorNotFoundError: If any indicator not registered.
            NotFoundError: If no candle data exists.
        """
        t0 = time.monotonic()

        candles = self._fetch_candles(symbol, interval, start, end)
        if not candles:
            raise NotFoundError(f"No candle data for {symbol} at {interval.value}.")

        results = self._engine.compute_batch(requests, candles)

        duration_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "indicator.batch_computed",
            operation="indicator_compute_batch",
            component="IndicatorService",
            indicators=[r.indicator_name for r in requests],
            symbol=symbol,
            interval=interval.value,
            candle_count=len(candles),
            indicator_count=len(requests),
            duration_ms=round(duration_ms, 2),
            result="success",
        )

        return results

    def list_available(self) -> list[IndicatorInfo]:
        """
        List all available indicators.

        Returns:
            Sorted list of IndicatorInfo.
        """
        return self._engine.registry.list_available()

    def get_indicator_info(self, name: str) -> IndicatorInfo:
        """
        Get detailed info for a specific indicator.

        Args:
            name: Indicator name (case-insensitive).

        Returns:
            IndicatorInfo for the named indicator.

        Raises:
            IndicatorNotFoundError: If not registered.
        """
        calculator = self._engine.registry.get(name)
        return calculator.info()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_candles(
        self,
        symbol: str,
        interval: CandleInterval,
        start: datetime | None,
        end: datetime | None,
    ) -> list[Any]:
        """
        Fetch candles from the market data repository.

        Args:
            symbol: Ticker symbol.
            interval: Candle interval.
            start: Start time.
            end: End time.

        Returns:
            List of Candle models ordered by ascending timestamp.
        """
        query = MarketDataQuery(
            symbol=symbol.upper(),
            interval=interval,
            start=start,
            end=end or datetime.now(timezone.utc),
            limit=10000,  # Fetch up to 10K candles for indicator computation
        )
        page = self._repo.query_candles(query)
        return page.candles
