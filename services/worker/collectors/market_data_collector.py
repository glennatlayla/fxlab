"""
Market data collector service for orchestrating data collection pipelines.

Responsibilities:
- Orchestrate fetching OHLCV bars from a MarketDataProviderInterface and
  persisting them via a MarketDataRepositoryInterface.
- Batch symbols into configurable chunks for controlled resource usage.
- Detect data gaps after collection and report them in the result.
- Isolate per-symbol failures so one failing symbol does not block others.
- Emit structured log events for monitoring collection progress.

Does NOT:
- Make HTTP calls directly (delegates to provider).
- Own database connections (delegates to repository).
- Implement rate limiting (provider is responsible for per-request pacing).
- Schedule itself (Celery tasks handle scheduling in market_data_tasks.py).

Dependencies:
- MarketDataProviderInterface: Fetches bars from external API.
- MarketDataRepositoryInterface: Persists candles and detects gaps.
- structlog: Structured logging.

Error conditions:
- Per-symbol errors are captured in CollectionResult.symbols_failed.
- The service does NOT raise exceptions — all failures are reported
  in the return value so the caller can decide on retry policy.

Example:
    collector = MarketDataCollectorService(
        provider=alpaca_provider,
        repository=sql_repo,
        chunk_size=10,
    )
    result = collector.collect(
        symbols=["AAPL", "SPY", "QQQ"],
        interval=CandleInterval.D1,
        start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 4, 10, tzinfo=timezone.utc),
    )
    print(f"Collected {result.total_candles_collected} candles")
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from libs.contracts.collection import (
    CollectionResult,
    SymbolCollectionResult,
)
from libs.contracts.interfaces.market_data_provider import (
    MarketDataProviderInterface,
)
from libs.contracts.interfaces.market_data_repository import (
    MarketDataRepositoryInterface,
)
from libs.contracts.market_data import CandleInterval, DataGap

logger = structlog.get_logger(__name__)

#: Default number of symbols to process per batch.
_DEFAULT_CHUNK_SIZE = 10


class MarketDataCollectorService:
    """
    Orchestrates market data collection from a provider to a repository.

    Processes symbols in configurable chunks, isolating failures per symbol
    so one failing ticker does not prevent others from being collected.
    After persisting candles, runs gap detection on the collected range
    to identify missing data points.

    Responsibilities:
    - Fetch bars from provider for each symbol.
    - Upsert fetched candles into the repository.
    - Run gap detection on the collected range.
    - Aggregate per-symbol results into a CollectionResult.
    - Log progress at each stage.

    Does NOT:
    - Manage scheduling or retry policy (Celery tasks handle that).
    - Rate-limit API calls (provider handles per-request pacing).
    - Manage database transactions (repository handles flush/commit).

    Dependencies:
    - provider: MarketDataProviderInterface (injected).
    - repository: MarketDataRepositoryInterface (injected).

    Example:
        collector = MarketDataCollectorService(provider=p, repository=r)
        result = collector.collect(["AAPL"], CandleInterval.D1, start, end)
    """

    def __init__(
        self,
        provider: MarketDataProviderInterface,
        repository: MarketDataRepositoryInterface,
        *,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._chunk_size = chunk_size

    def collect(
        self,
        symbols: list[str],
        interval: CandleInterval,
        start: datetime,
        end: datetime,
    ) -> CollectionResult:
        """
        Collect market data for a list of symbols within a time range.

        Processes symbols in chunks of chunk_size. For each symbol:
        1. Fetch bars from provider.
        2. Upsert candles to repository.
        3. Detect gaps in the collected range.
        4. Record per-symbol result.

        Any exception during a symbol's processing is caught and recorded
        as a failure — the remaining symbols continue processing.

        Args:
            symbols: List of ticker symbols to collect.
            interval: Candle interval to fetch.
            start: Start of time range (inclusive), timezone-aware UTC.
            end: End of time range (inclusive), timezone-aware UTC.

        Returns:
            CollectionResult with aggregated and per-symbol details.
            Never raises — all errors are captured in the result.

        Example:
            result = collector.collect(["AAPL", "SPY"], CandleInterval.D1, start, end)
            assert result.total_candles_collected > 0
        """
        started_at = datetime.now(timezone.utc)

        logger.info(
            "collector.run_start",
            symbols_count=len(symbols),
            interval=interval.value,
            start=start.isoformat(),
            end=end.isoformat(),
            chunk_size=self._chunk_size,
            provider=self._provider.get_provider_name(),
        )

        symbol_results: list[SymbolCollectionResult] = []
        succeeded: list[str] = []
        failed: list[str] = []
        total_collected = 0
        total_persisted = 0
        total_gaps = 0

        # Process in chunks
        for chunk_start in range(0, max(len(symbols), 1), self._chunk_size):
            chunk = symbols[chunk_start : chunk_start + self._chunk_size]
            if not chunk:
                break

            for symbol in chunk:
                sym_result = self._collect_symbol(symbol, interval, start, end)
                symbol_results.append(sym_result)

                if sym_result.error is None:
                    succeeded.append(symbol)
                    total_collected += sym_result.candles_collected
                    total_persisted += sym_result.candles_persisted
                    total_gaps += len(sym_result.gaps_detected)
                else:
                    failed.append(symbol)

        completed_at = datetime.now(timezone.utc)

        logger.info(
            "collector.run_complete",
            symbols_requested=len(symbols),
            symbols_succeeded=len(succeeded),
            symbols_failed=len(failed),
            total_candles_collected=total_collected,
            total_candles_persisted=total_persisted,
            total_gaps_detected=total_gaps,
            duration_ms=int((completed_at - started_at).total_seconds() * 1000),
        )

        return CollectionResult(
            symbols_requested=list(symbols),
            symbols_succeeded=succeeded,
            symbols_failed=failed,
            total_candles_collected=total_collected,
            total_candles_persisted=total_persisted,
            total_gaps_detected=total_gaps,
            symbol_results=symbol_results,
            started_at=started_at,
            completed_at=completed_at,
        )

    def _collect_symbol(
        self,
        symbol: str,
        interval: CandleInterval,
        start: datetime,
        end: datetime,
    ) -> SymbolCollectionResult:
        """
        Collect data for a single symbol. Catches all exceptions.

        Args:
            symbol: Ticker symbol to collect.
            interval: Candle interval.
            start: Start of time range.
            end: End of time range.

        Returns:
            SymbolCollectionResult — error field is set if collection failed.
        """
        try:
            # Step 1: Fetch from provider
            logger.debug(
                "collector.symbol_fetch_start",
                symbol=symbol,
                interval=interval.value,
            )
            candles = self._provider.fetch_historical_bars(symbol, interval, start, end)
            candles_collected = len(candles)

            # Step 2: Upsert to repository
            candles_persisted = 0
            if candles:
                candles_persisted = self._repository.upsert_candles(candles)

            # Step 3: Detect gaps
            gaps: list[DataGap] = []
            if candles_persisted > 0:
                gaps = self._repository.detect_gaps(symbol, interval, start, end)
                if gaps:
                    logger.warning(
                        "collector.gaps_detected",
                        symbol=symbol,
                        interval=interval.value,
                        gap_count=len(gaps),
                    )

            logger.info(
                "collector.symbol_complete",
                symbol=symbol,
                interval=interval.value,
                candles_collected=candles_collected,
                candles_persisted=candles_persisted,
                gaps_detected=len(gaps),
            )

            return SymbolCollectionResult(
                symbol=symbol,
                interval=interval,
                candles_collected=candles_collected,
                candles_persisted=candles_persisted,
                gaps_detected=gaps,
            )

        except Exception as exc:
            logger.error(
                "collector.symbol_failed",
                symbol=symbol,
                interval=interval.value,
                error_type=type(exc).__name__,
                error_message=str(exc),
                exc_info=True,
            )
            return SymbolCollectionResult(
                symbol=symbol,
                interval=interval,
                candles_collected=0,
                candles_persisted=0,
                error=f"{type(exc).__name__}: {exc}",
            )
