"""
Market data collection result contracts.

Responsibilities:
- Define the result contract for market data collection operations.
- Track per-symbol collection outcomes (candles collected, gaps detected).
- Provide aggregated summary for batch collection runs.

Does NOT:
- Contain I/O, database queries, or network calls.
- Contain collection logic (that's the collector service's job).

Dependencies:
- pydantic: BaseModel, Field.
- datetime: Standard library types.

Error conditions:
- Pydantic ValidationError raised on invalid field values.

Example:
    from libs.contracts.collection import CollectionResult, SymbolCollectionResult

    result = CollectionResult(
        symbols_requested=["AAPL", "SPY"],
        symbols_succeeded=["AAPL", "SPY"],
        symbols_failed=[],
        total_candles_collected=504,
        total_gaps_detected=0,
        symbol_results=[...],
    )
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from libs.contracts.market_data import CandleInterval, DataGap


class SymbolCollectionResult(BaseModel):
    """
    Collection result for a single symbol.

    Attributes:
        symbol: Ticker symbol that was collected.
        interval: Candle interval that was collected.
        candles_collected: Number of candles fetched from the provider.
        candles_persisted: Number of candles upserted to the repository.
        gaps_detected: List of data gaps found after collection.
        error: Error message if collection failed for this symbol, None on success.

    Example:
        result = SymbolCollectionResult(
            symbol="AAPL",
            interval=CandleInterval.D1,
            candles_collected=252,
            candles_persisted=252,
            gaps_detected=[],
        )
    """

    model_config = {"frozen": True}

    symbol: str = Field(..., min_length=1, max_length=10, description="Ticker symbol")
    interval: CandleInterval = Field(..., description="Candle interval collected")
    candles_collected: int = Field(..., ge=0, description="Candles fetched from provider")
    candles_persisted: int = Field(..., ge=0, description="Candles upserted to repository")
    gaps_detected: list[DataGap] = Field(
        default_factory=list, description="Gaps detected after collection"
    )
    error: str | None = Field(default=None, description="Error message if collection failed")


class CollectionResult(BaseModel):
    """
    Aggregated result from a market data collection run.

    Tracks which symbols succeeded, which failed, and the total candles
    collected across all symbols in the batch.

    Attributes:
        symbols_requested: All symbols that were requested for collection.
        symbols_succeeded: Symbols where collection completed successfully.
        symbols_failed: Symbols where collection encountered an error.
        total_candles_collected: Sum of candles fetched from the provider.
        total_candles_persisted: Sum of candles upserted to the repository.
        total_gaps_detected: Total number of data gaps found across all symbols.
        symbol_results: Per-symbol detailed results.
        started_at: When the collection run started.
        completed_at: When the collection run finished.

    Example:
        result = CollectionResult(
            symbols_requested=["AAPL", "SPY"],
            symbols_succeeded=["AAPL", "SPY"],
            symbols_failed=[],
            total_candles_collected=504,
            total_candles_persisted=504,
            total_gaps_detected=0,
            symbol_results=[...],
        )
    """

    model_config = {"frozen": True}

    symbols_requested: list[str] = Field(..., description="All requested symbols")
    symbols_succeeded: list[str] = Field(
        default_factory=list, description="Successfully collected symbols"
    )
    symbols_failed: list[str] = Field(default_factory=list, description="Failed symbols")
    total_candles_collected: int = Field(default=0, ge=0, description="Total candles fetched")
    total_candles_persisted: int = Field(default=0, ge=0, description="Total candles upserted")
    total_gaps_detected: int = Field(default=0, ge=0, description="Total gaps detected")
    symbol_results: list[SymbolCollectionResult] = Field(
        default_factory=list, description="Per-symbol results"
    )
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Collection run start time",
    )
    completed_at: datetime | None = Field(
        default=None, description="Collection run completion time"
    )
