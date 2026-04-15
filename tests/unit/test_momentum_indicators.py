"""
Unit tests for momentum indicators (MACD, RSI, Stochastic, StochasticRSI,
ROC, MOM, Williams_R, CCI).

Validates correctness against reference values, boundary conditions,
and edge cases.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from typing import Any

import numpy as np

from libs.indicators.momentum import (
    CCICalculator,
    MACDCalculator,
    MOMCalculator,
    ROCCalculator,
    RSICalculator,
    StochasticCalculator,
    StochasticRSICalculator,
    WilliamsRCalculator,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

# 30 close prices with realistic price action (uptrend with noise)
_CLOSE_30 = np.array(
    [
        100.0,
        101.5,
        100.8,
        102.0,
        103.5,
        102.8,
        104.0,
        105.5,
        104.8,
        106.0,
        107.5,
        106.8,
        108.0,
        109.5,
        108.8,
        110.0,
        111.5,
        110.8,
        112.0,
        113.5,
        112.8,
        114.0,
        115.5,
        114.8,
        116.0,
        117.5,
        116.8,
        118.0,
        119.5,
        118.8,
    ],
    dtype=np.float64,
)
_HIGH_30 = _CLOSE_30 + 1.0
_LOW_30 = _CLOSE_30 - 1.0
_OPEN_30 = _CLOSE_30 - 0.5
_VOLUME_30 = np.full(30, 1_000_000.0, dtype=np.float64)
_TS_30 = np.arange(30, dtype=np.float64)


def _call(calc: Any, **params: Any) -> Any:
    """Invoke calculator with 30-bar test data."""
    return calc.calculate(
        open=_OPEN_30,
        high=_HIGH_30,
        low=_LOW_30,
        close=_CLOSE_30,
        volume=_VOLUME_30,
        timestamps=_TS_30,
        **params,
    )


def _call_custom(
    calc: Any,
    close: np.ndarray,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    volume: np.ndarray | None = None,
    **params: Any,
) -> Any:
    """Invoke calculator with custom arrays."""
    n = len(close)
    if high is None:
        high = close + 1.0
    if low is None:
        low = close - 1.0
    if volume is None:
        volume = np.full(n, 1e6, dtype=np.float64)
    return calc.calculate(
        open=close - 0.5,
        high=high,
        low=low,
        close=close,
        volume=volume,
        timestamps=np.arange(n, dtype=np.float64),
        **params,
    )


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


class TestMACD:
    """Tests for MACDCalculator."""

    def test_macd_returns_three_components(self) -> None:
        calc = MACDCalculator()
        result = _call(calc)
        assert isinstance(result, dict)
        assert set(result.keys()) == {"macd_line", "signal_line", "histogram"}

    def test_macd_output_lengths_match(self) -> None:
        calc = MACDCalculator()
        result = _call(calc)
        assert len(result["macd_line"]) == 30
        assert len(result["signal_line"]) == 30
        assert len(result["histogram"]) == 30

    def test_macd_histogram_is_difference(self) -> None:
        """histogram = macd_line - signal_line"""
        calc = MACDCalculator()
        result = _call(calc)
        valid = ~np.isnan(result["macd_line"]) & ~np.isnan(result["signal_line"])
        np.testing.assert_array_almost_equal(
            result["histogram"][valid],
            result["macd_line"][valid] - result["signal_line"][valid],
        )

    def test_macd_uptrend_positive(self) -> None:
        """In an uptrend, MACD line should eventually become positive."""
        calc = MACDCalculator()
        result = _call(calc, fast_period=5, slow_period=10, signal_period=3)
        valid_macd = result["macd_line"][~np.isnan(result["macd_line"])]
        # At least some positive values in an uptrend
        assert np.any(valid_macd > 0)

    def test_macd_info(self) -> None:
        calc = MACDCalculator()
        info = calc.info()
        assert info.name == "MACD"
        assert info.category == "momentum"
        assert len(info.output_names) == 3


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------


class TestRSI:
    """Tests for RSICalculator."""

    def test_rsi_bounded_0_100(self) -> None:
        calc = RSICalculator()
        result = _call(calc, period=14)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0.0)
        assert np.all(valid <= 100.0)

    def test_rsi_nan_for_insufficient_lookback(self) -> None:
        calc = RSICalculator()
        result = _call(calc, period=14)
        # First `period` values should be NaN (need period+1 prices for period changes)
        assert np.all(np.isnan(result[:14]))

    def test_rsi_all_gains_returns_100(self) -> None:
        """Monotonically increasing prices → RSI = 100."""
        close = np.arange(1, 21, dtype=np.float64)
        calc = RSICalculator()
        result = _call_custom(calc, close=close, period=5)
        valid = result[~np.isnan(result)]
        np.testing.assert_array_almost_equal(valid, np.full(len(valid), 100.0))

    def test_rsi_all_losses_returns_0(self) -> None:
        """Monotonically decreasing prices → RSI = 0."""
        close = np.arange(20, 0, -1, dtype=np.float64)
        calc = RSICalculator()
        result = _call_custom(calc, close=close, period=5)
        valid = result[~np.isnan(result)]
        np.testing.assert_array_almost_equal(valid, np.full(len(valid), 0.0))

    def test_rsi_uptrend_above_50(self) -> None:
        """In a strong uptrend, RSI should be above 50."""
        calc = RSICalculator()
        result = _call(calc, period=14)
        valid = result[~np.isnan(result)]
        # Last values in uptrend should be > 50
        assert valid[-1] > 50.0

    def test_rsi_output_length(self) -> None:
        calc = RSICalculator()
        result = _call(calc, period=14)
        assert len(result) == 30

    def test_rsi_info(self) -> None:
        calc = RSICalculator()
        info = calc.info()
        assert info.name == "RSI"
        assert info.default_params["period"] == 14


# ---------------------------------------------------------------------------
# Stochastic
# ---------------------------------------------------------------------------


class TestStochastic:
    """Tests for StochasticCalculator."""

    def test_stochastic_returns_two_components(self) -> None:
        calc = StochasticCalculator()
        result = _call(calc)
        assert isinstance(result, dict)
        assert set(result.keys()) == {"percent_k", "percent_d"}

    def test_stochastic_bounded_0_100(self) -> None:
        calc = StochasticCalculator()
        result = _call(calc, k_period=5, d_period=3, smooth_k=1)
        for key in ("percent_k", "percent_d"):
            valid = result[key][~np.isnan(result[key])]
            if len(valid) > 0:
                assert np.all(valid >= 0.0), f"{key} has values < 0"
                assert np.all(valid <= 100.0), f"{key} has values > 100"

    def test_stochastic_close_at_high_returns_100(self) -> None:
        """When close equals the highest high, %K should be 100."""
        n = 20
        high = np.full(n, 110.0, dtype=np.float64)
        low = np.full(n, 90.0, dtype=np.float64)
        close = np.full(n, 110.0, dtype=np.float64)  # Close at high
        calc = StochasticCalculator()
        result = _call_custom(
            calc, close=close, high=high, low=low, k_period=5, d_period=3, smooth_k=1
        )
        valid_k = result["percent_k"][~np.isnan(result["percent_k"])]
        if len(valid_k) > 0:
            np.testing.assert_array_almost_equal(valid_k, np.full(len(valid_k), 100.0))

    def test_stochastic_output_length(self) -> None:
        calc = StochasticCalculator()
        result = _call(calc)
        assert len(result["percent_k"]) == 30
        assert len(result["percent_d"]) == 30

    def test_stochastic_info(self) -> None:
        calc = StochasticCalculator()
        info = calc.info()
        assert info.name == "STOCHASTIC"
        assert len(info.output_names) == 2


# ---------------------------------------------------------------------------
# StochasticRSI
# ---------------------------------------------------------------------------


class TestStochasticRSI:
    """Tests for StochasticRSICalculator."""

    def test_stochrsi_returns_two_components(self) -> None:
        calc = StochasticRSICalculator()
        result = _call(calc, rsi_period=5, stoch_period=5, k_period=3, d_period=3)
        assert isinstance(result, dict)
        assert "percent_k" in result
        assert "percent_d" in result

    def test_stochrsi_bounded_0_100(self) -> None:
        calc = StochasticRSICalculator()
        result = _call(calc, rsi_period=5, stoch_period=5, k_period=3, d_period=3)
        for key in ("percent_k", "percent_d"):
            valid = result[key][~np.isnan(result[key])]
            if len(valid) > 0:
                assert np.all(valid >= 0.0)
                assert np.all(valid <= 100.0)

    def test_stochrsi_output_length(self) -> None:
        calc = StochasticRSICalculator()
        result = _call(calc, rsi_period=5, stoch_period=5, k_period=3, d_period=3)
        assert len(result["percent_k"]) == 30

    def test_stochrsi_info(self) -> None:
        calc = StochasticRSICalculator()
        info = calc.info()
        assert info.name == "STOCHASTIC_RSI"


# ---------------------------------------------------------------------------
# ROC
# ---------------------------------------------------------------------------


class TestROC:
    """Tests for ROCCalculator."""

    def test_roc_reference_values(self) -> None:
        """ROC(1) = ((close[i] - close[i-1]) / close[i-1]) * 100."""
        calc = ROCCalculator()
        result = _call(calc, period=1)
        # ROC at index 1 = (101.5 - 100.0) / 100.0 * 100 = 1.5
        np.testing.assert_almost_equal(result[1], 1.5)

    def test_roc_nan_for_insufficient_lookback(self) -> None:
        calc = ROCCalculator()
        result = _call(calc, period=5)
        assert np.all(np.isnan(result[:5]))

    def test_roc_flat_prices_returns_zero(self) -> None:
        flat = np.full(20, 100.0, dtype=np.float64)
        calc = ROCCalculator()
        result = _call_custom(calc, close=flat, period=5)
        valid = result[~np.isnan(result)]
        np.testing.assert_array_almost_equal(valid, np.zeros(len(valid)))

    def test_roc_output_length(self) -> None:
        calc = ROCCalculator()
        result = _call(calc, period=5)
        assert len(result) == 30

    def test_roc_info(self) -> None:
        calc = ROCCalculator()
        assert calc.info().name == "ROC"


# ---------------------------------------------------------------------------
# MOM
# ---------------------------------------------------------------------------


class TestMOM:
    """Tests for MOMCalculator."""

    def test_mom_reference_values(self) -> None:
        """MOM(1) = close[i] - close[i-1]."""
        calc = MOMCalculator()
        result = _call(calc, period=1)
        # MOM at index 1 = 101.5 - 100.0 = 1.5
        np.testing.assert_almost_equal(result[1], 1.5)

    def test_mom_nan_for_insufficient_lookback(self) -> None:
        calc = MOMCalculator()
        result = _call(calc, period=5)
        assert np.all(np.isnan(result[:5]))

    def test_mom_uptrend_positive(self) -> None:
        calc = MOMCalculator()
        result = _call(calc, period=5)
        valid = result[~np.isnan(result)]
        # In a steady uptrend, most MOM values should be positive
        assert np.mean(valid > 0) > 0.5

    def test_mom_output_length(self) -> None:
        calc = MOMCalculator()
        result = _call(calc, period=10)
        assert len(result) == 30

    def test_mom_info(self) -> None:
        calc = MOMCalculator()
        assert calc.info().name == "MOM"


# ---------------------------------------------------------------------------
# Williams %R
# ---------------------------------------------------------------------------


class TestWilliamsR:
    """Tests for WilliamsRCalculator."""

    def test_williams_r_bounded_minus100_to_0(self) -> None:
        calc = WilliamsRCalculator()
        result = _call(calc, period=14)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= -100.0)
        assert np.all(valid <= 0.0)

    def test_williams_r_close_at_high_returns_0(self) -> None:
        """When close = highest high, Williams %R should be 0."""
        n = 20
        high = np.full(n, 110.0, dtype=np.float64)
        low = np.full(n, 90.0, dtype=np.float64)
        close = np.full(n, 110.0, dtype=np.float64)
        calc = WilliamsRCalculator()
        result = _call_custom(calc, close=close, high=high, low=low, period=5)
        valid = result[~np.isnan(result)]
        np.testing.assert_array_almost_equal(valid, np.zeros(len(valid)))

    def test_williams_r_close_at_low_returns_minus100(self) -> None:
        """When close = lowest low, Williams %R should be -100."""
        n = 20
        high = np.full(n, 110.0, dtype=np.float64)
        low = np.full(n, 90.0, dtype=np.float64)
        close = np.full(n, 90.0, dtype=np.float64)
        calc = WilliamsRCalculator()
        result = _call_custom(calc, close=close, high=high, low=low, period=5)
        valid = result[~np.isnan(result)]
        np.testing.assert_array_almost_equal(valid, np.full(len(valid), -100.0))

    def test_williams_r_nan_for_insufficient_lookback(self) -> None:
        calc = WilliamsRCalculator()
        result = _call(calc, period=14)
        assert np.all(np.isnan(result[:13]))

    def test_williams_r_info(self) -> None:
        calc = WilliamsRCalculator()
        assert calc.info().name == "WILLIAMS_R"


# ---------------------------------------------------------------------------
# CCI
# ---------------------------------------------------------------------------


class TestCCI:
    """Tests for CCICalculator."""

    def test_cci_output_length(self) -> None:
        calc = CCICalculator()
        result = _call(calc, period=5)
        assert len(result) == 30

    def test_cci_nan_for_insufficient_lookback(self) -> None:
        calc = CCICalculator()
        result = _call(calc, period=10)
        assert np.all(np.isnan(result[:9]))

    def test_cci_flat_prices_returns_zero(self) -> None:
        """Flat typical prices → CCI = 0 (no deviation)."""
        n = 20
        flat_close = np.full(n, 100.0, dtype=np.float64)
        flat_high = np.full(n, 100.0, dtype=np.float64)
        flat_low = np.full(n, 100.0, dtype=np.float64)
        calc = CCICalculator()
        result = _call_custom(calc, close=flat_close, high=flat_high, low=flat_low, period=5)
        valid = result[~np.isnan(result)]
        np.testing.assert_array_almost_equal(valid, np.zeros(len(valid)))

    def test_cci_positive_in_uptrend(self) -> None:
        """CCI should be positive when price is above its SMA of typical price."""
        calc = CCICalculator()
        result = _call(calc, period=5)
        valid = result[~np.isnan(result)]
        # In an uptrend, last values should tend positive
        assert valid[-1] > 0

    def test_cci_info(self) -> None:
        calc = CCICalculator()
        info = calc.info()
        assert info.name == "CCI"
        assert info.category == "momentum"


# ---------------------------------------------------------------------------
# Default engine integration
# ---------------------------------------------------------------------------


class TestDefaultEngineRegistration:
    """Test that all M5 indicators are registered in the default engine."""

    def test_all_m5_indicators_registered(self) -> None:
        from libs.indicators import default_registry

        expected = {
            "SMA",
            "EMA",
            "WMA",
            "DEMA",
            "TEMA",
            "MACD",
            "RSI",
            "STOCHASTIC",
            "STOCHASTIC_RSI",
            "ROC",
            "MOM",
            "WILLIAMS_R",
            "CCI",
        }
        for name in expected:
            assert default_registry.has(name), f"{name} not registered"

    def test_default_registry_has_at_least_13_m5_indicators(self) -> None:
        from libs.indicators import default_registry

        # M5 registers 13; M6 adds 11 more = 24 total
        assert default_registry.count() >= 13
