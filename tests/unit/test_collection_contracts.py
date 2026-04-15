"""
Unit tests for collection result Pydantic contracts.

Validates schema constraints and serialization for CollectionResult
and SymbolCollectionResult.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from libs.contracts.collection import CollectionResult, SymbolCollectionResult
from libs.contracts.market_data import CandleInterval, DataGap

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS = datetime(2026, 4, 10, 14, 30, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# SymbolCollectionResult
# ---------------------------------------------------------------------------


class TestSymbolCollectionResult:
    """SymbolCollectionResult Pydantic model validation tests."""

    def test_valid_success_result(self) -> None:
        result = SymbolCollectionResult(
            symbol="AAPL",
            interval=CandleInterval.D1,
            candles_collected=252,
            candles_persisted=252,
        )
        assert result.symbol == "AAPL"
        assert result.candles_collected == 252
        assert result.gaps_detected == []
        assert result.error is None

    def test_valid_failure_result(self) -> None:
        result = SymbolCollectionResult(
            symbol="AAPL",
            interval=CandleInterval.D1,
            candles_collected=0,
            candles_persisted=0,
            error="ExternalServiceError: API down",
        )
        assert result.error is not None

    def test_with_gaps(self) -> None:
        gap = DataGap(
            symbol="AAPL",
            interval=CandleInterval.M1,
            gap_start=_TS,
            gap_end=datetime(2026, 4, 10, 14, 35, tzinfo=timezone.utc),
        )
        result = SymbolCollectionResult(
            symbol="AAPL",
            interval=CandleInterval.M1,
            candles_collected=59,
            candles_persisted=59,
            gaps_detected=[gap],
        )
        assert len(result.gaps_detected) == 1

    def test_is_frozen(self) -> None:
        result = SymbolCollectionResult(
            symbol="AAPL",
            interval=CandleInterval.D1,
            candles_collected=10,
            candles_persisted=10,
        )
        with pytest.raises(ValidationError):
            result.symbol = "SPY"  # type: ignore[misc]

    def test_rejects_negative_candles_collected(self) -> None:
        with pytest.raises(ValidationError, match="candles_collected"):
            SymbolCollectionResult(
                symbol="AAPL",
                interval=CandleInterval.D1,
                candles_collected=-1,
                candles_persisted=0,
            )


# ---------------------------------------------------------------------------
# CollectionResult
# ---------------------------------------------------------------------------


class TestCollectionResult:
    """CollectionResult Pydantic model validation tests."""

    def test_empty_collection_result(self) -> None:
        result = CollectionResult(symbols_requested=[])
        assert result.total_candles_collected == 0
        assert result.symbols_succeeded == []
        assert result.symbols_failed == []
        assert result.started_at is not None

    def test_full_collection_result(self) -> None:
        result = CollectionResult(
            symbols_requested=["AAPL", "SPY"],
            symbols_succeeded=["AAPL", "SPY"],
            total_candles_collected=504,
            total_candles_persisted=504,
            total_gaps_detected=0,
        )
        assert len(result.symbols_requested) == 2
        assert result.total_candles_collected == 504

    def test_is_frozen(self) -> None:
        result = CollectionResult(symbols_requested=["AAPL"])
        with pytest.raises(ValidationError):
            result.total_candles_collected = 999  # type: ignore[misc]

    def test_serialization_round_trip(self) -> None:
        result = CollectionResult(
            symbols_requested=["AAPL"],
            symbols_succeeded=["AAPL"],
            total_candles_collected=100,
            total_candles_persisted=100,
        )
        data = result.model_dump()
        restored = CollectionResult(**data)
        assert restored.symbols_requested == result.symbols_requested
        assert restored.total_candles_collected == result.total_candles_collected
