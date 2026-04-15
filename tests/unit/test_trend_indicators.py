"""
Unit tests for trend indicators (SMA, EMA, WMA, DEMA, TEMA).

Validates correctness against manually computed reference values,
edge cases (insufficient data, single candle, flat prices), and
NaN handling for insufficient lookback periods.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from libs.indicators.trend import (
    DEMACalculator,
    EMACalculator,
    SMACalculator,
    TEMACalculator,
    WMACalculator,
    _ema_array,
)

# ---------------------------------------------------------------------------
# Shared test data — known reference values
# ---------------------------------------------------------------------------

# 10 close prices for a hypothetical stock
_CLOSE_10 = np.array(
    [44.0, 44.25, 44.50, 43.75, 44.50, 44.25, 44.00, 43.75, 44.25, 44.75],
    dtype=np.float64,
)

# Dummy OHLCV arrays (only close used by trend indicators)
_N = len(_CLOSE_10)
_OPEN = np.full(_N, 44.0, dtype=np.float64)
_HIGH = np.full(_N, 45.0, dtype=np.float64)
_LOW = np.full(_N, 43.0, dtype=np.float64)
_VOLUME = np.full(_N, 1_000_000.0, dtype=np.float64)
_TIMESTAMPS = np.arange(_N, dtype=np.float64)


def _call(calc: Any, close: np.ndarray = _CLOSE_10, **params: Any) -> np.ndarray:
    """Invoke a calculator with standard dummy OHLCV arrays."""
    n = len(close)
    return calc.calculate(
        open=np.full(n, 44.0, dtype=np.float64),
        high=np.full(n, 45.0, dtype=np.float64),
        low=np.full(n, 43.0, dtype=np.float64),
        close=close,
        volume=np.full(n, 1e6, dtype=np.float64),
        timestamps=np.arange(n, dtype=np.float64),
        **params,
    )


# ---------------------------------------------------------------------------
# _ema_array (shared helper)
# ---------------------------------------------------------------------------


class TestEmaArray:
    """Tests for the shared _ema_array helper."""

    def test_ema_seed_is_sma(self) -> None:
        """EMA seed (at index period-1) should equal SMA of first `period` values."""
        period = 5
        result = _ema_array(_CLOSE_10, period)
        expected_seed = np.mean(_CLOSE_10[:period])
        np.testing.assert_almost_equal(result[period - 1], expected_seed)

    def test_ema_nan_before_seed(self) -> None:
        period = 5
        result = _ema_array(_CLOSE_10, period)
        assert np.all(np.isnan(result[: period - 1]))

    def test_ema_no_nan_from_seed_onward(self) -> None:
        period = 5
        result = _ema_array(_CLOSE_10, period)
        assert not np.any(np.isnan(result[period - 1 :]))

    def test_ema_period_1_equals_input(self) -> None:
        """EMA with period 1 should equal the input (alpha=1)."""
        result = _ema_array(_CLOSE_10, 1)
        np.testing.assert_array_almost_equal(result, _CLOSE_10)

    def test_ema_insufficient_data_all_nan(self) -> None:
        short = np.array([1.0, 2.0], dtype=np.float64)
        result = _ema_array(short, 5)
        assert np.all(np.isnan(result))


# ---------------------------------------------------------------------------
# SMA
# ---------------------------------------------------------------------------


class TestSMA:
    """Tests for SMACalculator."""

    def test_sma_period_3_reference_values(self) -> None:
        """Manually computed SMA(3) for _CLOSE_10."""
        calc = SMACalculator()
        result = _call(calc, period=3)

        # SMA at index 2 = mean(44, 44.25, 44.5) = 44.25
        np.testing.assert_almost_equal(result[2], 44.25)
        # SMA at index 3 = mean(44.25, 44.5, 43.75) = 44.166...
        np.testing.assert_almost_equal(result[3], 44.1666666667, decimal=8)
        # First two should be NaN
        assert np.all(np.isnan(result[:2]))

    def test_sma_period_1_equals_close(self) -> None:
        calc = SMACalculator()
        result = _call(calc, period=1)
        np.testing.assert_array_almost_equal(result, _CLOSE_10)

    def test_sma_period_equals_length_single_value(self) -> None:
        calc = SMACalculator()
        result = _call(calc, period=_N)
        assert np.sum(~np.isnan(result)) == 1
        np.testing.assert_almost_equal(result[-1], np.mean(_CLOSE_10))

    def test_sma_period_exceeds_length_all_nan(self) -> None:
        calc = SMACalculator()
        result = _call(calc, period=_N + 1)
        assert np.all(np.isnan(result))

    def test_sma_flat_prices_returns_constant(self) -> None:
        flat = np.full(20, 100.0, dtype=np.float64)
        calc = SMACalculator()
        result = _call(calc, close=flat, period=5)
        valid = result[~np.isnan(result)]
        np.testing.assert_array_almost_equal(valid, np.full(len(valid), 100.0))

    def test_sma_output_length_matches_input(self) -> None:
        calc = SMACalculator()
        result = _call(calc, period=5)
        assert len(result) == _N

    def test_sma_info(self) -> None:
        calc = SMACalculator()
        info = calc.info()
        assert info.name == "SMA"
        assert info.category == "trend"
        assert info.default_params["period"] == 20


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------


class TestEMA:
    """Tests for EMACalculator."""

    def test_ema_seed_matches_sma(self) -> None:
        calc = EMACalculator()
        result = _call(calc, period=5)
        sma_seed = np.mean(_CLOSE_10[:5])
        np.testing.assert_almost_equal(result[4], sma_seed)

    def test_ema_nan_before_period(self) -> None:
        calc = EMACalculator()
        result = _call(calc, period=5)
        assert np.all(np.isnan(result[:4]))
        assert not np.isnan(result[4])

    def test_ema_responds_to_recent_prices(self) -> None:
        """EMA should weight recent prices more — if last price is high, EMA should be above SMA."""
        # Create data with a sharp up-move at the end
        data = np.array([10.0] * 20 + [20.0], dtype=np.float64)
        calc_sma = SMACalculator()
        calc_ema = EMACalculator()
        sma = _call(calc_sma, close=data, period=5)
        ema = _call(calc_ema, close=data, period=5)
        # At the last position, EMA should be higher than SMA
        assert ema[-1] > sma[-1]

    def test_ema_output_length(self) -> None:
        calc = EMACalculator()
        result = _call(calc, period=3)
        assert len(result) == _N

    def test_ema_info(self) -> None:
        calc = EMACalculator()
        info = calc.info()
        assert info.name == "EMA"
        assert info.category == "trend"


# ---------------------------------------------------------------------------
# WMA
# ---------------------------------------------------------------------------


class TestWMA:
    """Tests for WMACalculator."""

    def test_wma_period_3_reference(self) -> None:
        """WMA(3) at index 2: (44*1 + 44.25*2 + 44.5*3) / 6 = 44.3333..."""
        calc = WMACalculator()
        result = _call(calc, period=3)
        expected = (44.0 * 1 + 44.25 * 2 + 44.50 * 3) / 6.0
        np.testing.assert_almost_equal(result[2], expected, decimal=8)

    def test_wma_nan_before_period(self) -> None:
        calc = WMACalculator()
        result = _call(calc, period=5)
        assert np.all(np.isnan(result[:4]))

    def test_wma_period_1_equals_close(self) -> None:
        calc = WMACalculator()
        result = _call(calc, period=1)
        np.testing.assert_array_almost_equal(result, _CLOSE_10)

    def test_wma_weights_recent_more(self) -> None:
        """WMA should be closer to the most recent value than SMA."""
        data = np.array([10.0, 10.0, 10.0, 10.0, 20.0], dtype=np.float64)
        calc_wma = WMACalculator()
        calc_sma = SMACalculator()
        wma = _call(calc_wma, close=data, period=5)
        sma = _call(calc_sma, close=data, period=5)
        # WMA should be closer to 20 than SMA at last position
        assert wma[-1] > sma[-1]

    def test_wma_info(self) -> None:
        calc = WMACalculator()
        assert calc.info().name == "WMA"


# ---------------------------------------------------------------------------
# DEMA
# ---------------------------------------------------------------------------


class TestDEMA:
    """Tests for DEMACalculator."""

    def test_dema_less_lag_than_ema(self) -> None:
        """DEMA should react faster to a step change than EMA."""
        data = np.array([10.0] * 50 + [20.0] * 10, dtype=np.float64)
        calc_ema = EMACalculator()
        calc_dema = DEMACalculator()
        ema = _call(calc_ema, close=data, period=10)
        dema = _call(calc_dema, close=data, period=10)
        # After the step change, DEMA should be closer to 20 than EMA
        assert dema[-1] > ema[-1]

    def test_dema_nan_handling(self) -> None:
        # Use enough data for DEMA to produce non-NaN values (needs 2× period lookback)
        data = np.arange(1.0, 31.0, dtype=np.float64)
        calc = DEMACalculator()
        result = _call(calc, close=data, period=5)
        # First values should be NaN
        assert np.isnan(result[0])
        # Eventually should have non-NaN values
        assert not np.all(np.isnan(result))

    def test_dema_output_length(self) -> None:
        calc = DEMACalculator()
        result = _call(calc, period=3)
        assert len(result) == _N

    def test_dema_info(self) -> None:
        calc = DEMACalculator()
        assert calc.info().name == "DEMA"


# ---------------------------------------------------------------------------
# TEMA
# ---------------------------------------------------------------------------


class TestTEMA:
    """Tests for TEMACalculator."""

    def test_tema_reacts_faster_than_ema(self) -> None:
        """TEMA should converge to the new price level faster than plain EMA after a step change."""
        data = np.array([10.0] * 60 + [20.0] * 5, dtype=np.float64)
        calc_ema = EMACalculator()
        calc_tema = TEMACalculator()
        ema = _call(calc_ema, close=data, period=10)
        tema = _call(calc_tema, close=data, period=10)
        # TEMA should be closer to 20.0 (new level) than EMA right after the step
        # Check at the 3rd bar after step (index 62)
        assert tema[62] > ema[62]

    def test_tema_output_length(self) -> None:
        calc = TEMACalculator()
        result = _call(calc, period=3)
        assert len(result) == _N

    def test_tema_info(self) -> None:
        calc = TEMACalculator()
        assert calc.info().name == "TEMA"
        assert calc.info().category == "trend"


# ---------------------------------------------------------------------------
# Cross-indicator properties
# ---------------------------------------------------------------------------


class TestTrendProperties:
    """Property-based tests that apply to all trend indicators."""

    @pytest.mark.parametrize("CalcClass", [SMACalculator, EMACalculator, WMACalculator])
    def test_output_length_equals_input_length(self, CalcClass: type) -> None:
        calc = CalcClass()
        result = _call(calc, period=3)
        assert len(result) == _N

    @pytest.mark.parametrize("CalcClass", [SMACalculator, EMACalculator, WMACalculator])
    def test_flat_prices_return_constant(self, CalcClass: type) -> None:
        flat = np.full(50, 42.0, dtype=np.float64)
        calc = CalcClass()
        result = _call(calc, close=flat, period=5)
        valid = result[~np.isnan(result)]
        np.testing.assert_array_almost_equal(valid, np.full(len(valid), 42.0))

    @pytest.mark.parametrize("CalcClass", [SMACalculator, EMACalculator, WMACalculator])
    def test_single_candle_period_1_returns_value(self, CalcClass: type) -> None:
        single = np.array([100.0], dtype=np.float64)
        calc = CalcClass()
        result = _call(calc, close=single, period=1)
        np.testing.assert_almost_equal(result[0], 100.0)
