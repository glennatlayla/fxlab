"""
Unit tests for the indicator calculation engine.

Validates OHLCV extraction, single/batch computation dispatch,
result wrapping, error handling, and key disambiguation.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import numpy as np
import pytest

from libs.contracts.errors import IndicatorNotFoundError
from libs.contracts.indicator import (
    IndicatorInfo,
    IndicatorRequest,
    IndicatorResult,
)
from libs.contracts.market_data import Candle, CandleInterval
from libs.indicators.engine import IndicatorEngine
from libs.indicators.registry import IndicatorRegistry

# ---------------------------------------------------------------------------
# Helpers — stub calculators and candle factories
# ---------------------------------------------------------------------------

_BASE_TS = datetime(2026, 1, 2, 14, 30, 0, tzinfo=timezone.utc)


def _make_candles(n: int = 5) -> list[Candle]:
    """Create n candles with ascending prices and timestamps."""
    candles = []
    for i in range(n):
        candles.append(
            Candle(
                symbol="TEST",
                interval=CandleInterval.D1,
                open=Decimal(f"{100 + i}.00"),
                high=Decimal(f"{102 + i}.00"),
                low=Decimal(f"{99 + i}.00"),
                close=Decimal(f"{101 + i}.00"),
                volume=1_000_000 + i * 100_000,
                timestamp=datetime(2026, 1, 2 + i, 14, 30, 0, tzinfo=timezone.utc),
            )
        )
    return candles


class _EchoCloseCalculator:
    """Returns the close array unchanged — for testing dispatch."""

    def calculate(
        self,
        open: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        timestamps: np.ndarray,
        **params: Any,
    ) -> np.ndarray:
        return close.copy()

    def info(self) -> IndicatorInfo:
        return IndicatorInfo(name="ECHO_CLOSE", category="test")


class _MultiOutputCalculator:
    """Returns a dict of named arrays — for testing multi-output wrapping."""

    def calculate(
        self,
        open: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        timestamps: np.ndarray,
        **params: Any,
    ) -> dict[str, np.ndarray]:
        return {
            "upper": high.copy(),
            "lower": low.copy(),
            "middle": close.copy(),
        }

    def info(self) -> IndicatorInfo:
        return IndicatorInfo(
            name="MULTI",
            category="test",
            output_names=["upper", "lower", "middle"],
        )


class _ParamEchoCalculator:
    """Returns close * period — for testing parameter passthrough."""

    def calculate(
        self,
        open: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        timestamps: np.ndarray,
        **params: Any,
    ) -> np.ndarray:
        period = params.get("period", 1)
        return close * period

    def info(self) -> IndicatorInfo:
        return IndicatorInfo(
            name="PARAM_ECHO",
            category="test",
            default_params={"period": 1},
        )


def _make_engine() -> tuple[IndicatorEngine, IndicatorRegistry]:
    """Create engine with test calculators registered."""
    registry = IndicatorRegistry()
    registry.register("ECHO_CLOSE", _EchoCloseCalculator())
    registry.register("MULTI", _MultiOutputCalculator())
    registry.register("PARAM_ECHO", _ParamEchoCalculator())
    return IndicatorEngine(registry), registry


# ---------------------------------------------------------------------------
# OHLCV extraction
# ---------------------------------------------------------------------------


class TestOHLCVExtraction:
    """Tests for _extract_ohlcv static method."""

    def test_extraction_produces_correct_arrays(self) -> None:
        candles = _make_candles(3)
        ohlcv = IndicatorEngine._extract_ohlcv(candles)

        assert ohlcv["open"].dtype == np.float64
        assert len(ohlcv["open"]) == 3
        np.testing.assert_array_almost_equal(ohlcv["close"], [101.0, 102.0, 103.0])
        np.testing.assert_array_almost_equal(ohlcv["volume"], [1_000_000, 1_100_000, 1_200_000])

    def test_extraction_preserves_order(self) -> None:
        candles = _make_candles(5)
        ohlcv = IndicatorEngine._extract_ohlcv(candles)
        # Timestamps should be monotonically increasing
        assert np.all(np.diff(ohlcv["timestamps"]) > 0)

    def test_extraction_all_keys_present(self) -> None:
        candles = _make_candles(1)
        ohlcv = IndicatorEngine._extract_ohlcv(candles)
        assert set(ohlcv.keys()) == {"open", "high", "low", "close", "volume", "timestamps"}


# ---------------------------------------------------------------------------
# Single compute
# ---------------------------------------------------------------------------


class TestEngineCompute:
    """Tests for compute() single-indicator dispatch."""

    def test_compute_single_output(self) -> None:
        engine, _ = _make_engine()
        candles = _make_candles(5)
        result = engine.compute("ECHO_CLOSE", candles)

        assert isinstance(result, IndicatorResult)
        assert result.indicator_name == "ECHO_CLOSE"
        assert result.is_multi_output is False
        assert len(result.values) == 5
        np.testing.assert_array_almost_equal(result.values, [101.0, 102.0, 103.0, 104.0, 105.0])

    def test_compute_multi_output(self) -> None:
        engine, _ = _make_engine()
        candles = _make_candles(3)
        result = engine.compute("MULTI", candles)

        assert result.is_multi_output is True
        assert result.values is None
        assert set(result.components.keys()) == {"upper", "lower", "middle"}
        np.testing.assert_array_almost_equal(result.get_component("upper"), [102.0, 103.0, 104.0])

    def test_compute_passes_params(self) -> None:
        engine, _ = _make_engine()
        candles = _make_candles(3)
        result = engine.compute("PARAM_ECHO", candles, period=10)

        np.testing.assert_array_almost_equal(result.values, [1010.0, 1020.0, 1030.0])
        assert result.metadata["period"] == 10

    def test_compute_case_insensitive(self) -> None:
        engine, _ = _make_engine()
        candles = _make_candles(2)
        result = engine.compute("echo_close", candles)
        assert result.indicator_name == "ECHO_CLOSE"

    def test_compute_unregistered_raises_not_found(self) -> None:
        engine, _ = _make_engine()
        candles = _make_candles(2)
        with pytest.raises(IndicatorNotFoundError, match="UNKNOWN"):
            engine.compute("UNKNOWN", candles)

    def test_compute_empty_candles_raises_value_error(self) -> None:
        engine, _ = _make_engine()
        with pytest.raises(ValueError, match="empty"):
            engine.compute("ECHO_CLOSE", [])

    def test_compute_timestamps_aligned(self) -> None:
        engine, _ = _make_engine()
        candles = _make_candles(4)
        result = engine.compute("ECHO_CLOSE", candles)
        assert len(result.timestamps) == 4
        assert np.all(np.diff(result.timestamps) > 0)


# ---------------------------------------------------------------------------
# Batch compute
# ---------------------------------------------------------------------------


class TestEngineBatchCompute:
    """Tests for compute_batch() multi-indicator dispatch."""

    def test_batch_compute_multiple_indicators(self) -> None:
        engine, _ = _make_engine()
        candles = _make_candles(5)
        requests = [
            IndicatorRequest(indicator_name="ECHO_CLOSE"),
            IndicatorRequest(indicator_name="PARAM_ECHO", params={"period": 2}),
        ]
        results = engine.compute_batch(requests, candles)

        assert "ECHO_CLOSE" in results
        assert "PARAM_ECHO" in results
        np.testing.assert_array_almost_equal(
            results["ECHO_CLOSE"].values,
            [101.0, 102.0, 103.0, 104.0, 105.0],
        )
        np.testing.assert_array_almost_equal(
            results["PARAM_ECHO"].values,
            [202.0, 204.0, 206.0, 208.0, 210.0],
        )

    def test_batch_compute_same_indicator_different_params(self) -> None:
        """Duplicate indicator names get disambiguated keys."""
        engine, _ = _make_engine()
        candles = _make_candles(3)
        requests = [
            IndicatorRequest(indicator_name="PARAM_ECHO", params={"period": 2}),
            IndicatorRequest(indicator_name="PARAM_ECHO", params={"period": 5}),
        ]
        results = engine.compute_batch(requests, candles)

        assert len(results) == 2
        # First gets plain key, second gets disambiguated key
        assert "PARAM_ECHO" in results
        keys = list(results.keys())
        assert any("period=5" in k or k != "PARAM_ECHO" for k in keys)

    def test_batch_compute_empty_candles_raises_value_error(self) -> None:
        engine, _ = _make_engine()
        with pytest.raises(ValueError, match="empty"):
            engine.compute_batch([IndicatorRequest(indicator_name="ECHO_CLOSE")], [])

    def test_batch_compute_empty_requests_raises_value_error(self) -> None:
        engine, _ = _make_engine()
        candles = _make_candles(3)
        with pytest.raises(ValueError, match="No indicator requests"):
            engine.compute_batch([], candles)

    def test_batch_compute_unregistered_raises_not_found(self) -> None:
        engine, _ = _make_engine()
        candles = _make_candles(3)
        with pytest.raises(IndicatorNotFoundError):
            engine.compute_batch([IndicatorRequest(indicator_name="NOPE")], candles)

    def test_batch_compute_with_multi_output(self) -> None:
        engine, _ = _make_engine()
        candles = _make_candles(3)
        requests = [
            IndicatorRequest(indicator_name="MULTI"),
            IndicatorRequest(indicator_name="ECHO_CLOSE"),
        ]
        results = engine.compute_batch(requests, candles)
        assert results["MULTI"].is_multi_output is True
        assert results["ECHO_CLOSE"].is_multi_output is False


# ---------------------------------------------------------------------------
# Engine properties
# ---------------------------------------------------------------------------


class TestEngineProperties:
    """Tests for engine property accessors."""

    def test_registry_property(self) -> None:
        engine, registry = _make_engine()
        assert engine.registry is registry
