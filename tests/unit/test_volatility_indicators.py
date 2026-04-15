"""
Unit tests for volatility indicators (BollingerBands, ATR, Keltner,
DonchianChannel, StandardDeviation, HistoricalVolatility).

Validates correctness, boundary conditions, and edge cases.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from typing import Any

import numpy as np

from libs.indicators.volatility import (
    ATRCalculator,
    BollingerBandsCalculator,
    DonchianChannelCalculator,
    HistoricalVolatilityCalculator,
    KeltnerCalculator,
    StandardDeviationCalculator,
)

# ---------------------------------------------------------------------------
# Shared test data — 30 bars with realistic price action
# ---------------------------------------------------------------------------

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
_HIGH_30 = _CLOSE_30 + 1.5
_LOW_30 = _CLOSE_30 - 1.5
_OPEN_30 = _CLOSE_30 - 0.3
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
# Bollinger Bands
# ---------------------------------------------------------------------------


class TestBollingerBands:
    """Tests for BollingerBandsCalculator."""

    def test_returns_five_components(self) -> None:
        calc = BollingerBandsCalculator()
        result = _call(calc, period=10, std_dev=2.0)
        assert set(result.keys()) == {"upper", "middle", "lower", "bandwidth", "percent_b"}

    def test_upper_above_middle_above_lower(self) -> None:
        calc = BollingerBandsCalculator()
        result = _call(calc, period=10, std_dev=2.0)
        valid = ~np.isnan(result["middle"])
        assert np.all(result["upper"][valid] >= result["middle"][valid])
        assert np.all(result["middle"][valid] >= result["lower"][valid])

    def test_flat_prices_bands_converge(self) -> None:
        """Flat prices → std dev = 0 → upper = middle = lower."""
        flat = np.full(30, 100.0, dtype=np.float64)
        calc = BollingerBandsCalculator()
        result = _call_custom(calc, close=flat, period=10)
        valid = ~np.isnan(result["middle"])
        np.testing.assert_array_almost_equal(result["upper"][valid], result["middle"][valid])
        np.testing.assert_array_almost_equal(result["lower"][valid], result["middle"][valid])

    def test_output_length(self) -> None:
        calc = BollingerBandsCalculator()
        result = _call(calc, period=10)
        for key in result:
            assert len(result[key]) == 30

    def test_info(self) -> None:
        calc = BollingerBandsCalculator()
        info = calc.info()
        assert info.name == "BOLLINGER_BANDS"
        assert info.category == "volatility"
        assert len(info.output_names) == 5


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------


class TestATR:
    """Tests for ATRCalculator."""

    def test_atr_always_non_negative(self) -> None:
        calc = ATRCalculator()
        result = _call(calc, period=5)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0)

    def test_atr_nan_for_insufficient_lookback(self) -> None:
        calc = ATRCalculator()
        result = _call(calc, period=14)
        assert np.all(np.isnan(result[:14]))

    def test_atr_flat_prices_equals_hl_range(self) -> None:
        """When prices are flat, TR = H - L consistently."""
        n = 30
        close = np.full(n, 100.0, dtype=np.float64)
        high = np.full(n, 102.0, dtype=np.float64)
        low = np.full(n, 98.0, dtype=np.float64)
        calc = ATRCalculator()
        result = _call_custom(calc, close=close, high=high, low=low, period=5)
        valid = result[~np.isnan(result)]
        # ATR should be close to 4.0 (H-L = 4)
        np.testing.assert_array_almost_equal(valid, np.full(len(valid), 4.0), decimal=1)

    def test_atr_output_length(self) -> None:
        calc = ATRCalculator()
        result = _call(calc, period=5)
        assert len(result) == 30

    def test_atr_info(self) -> None:
        calc = ATRCalculator()
        assert calc.info().name == "ATR"


# ---------------------------------------------------------------------------
# Keltner
# ---------------------------------------------------------------------------


class TestKeltner:
    """Tests for KeltnerCalculator."""

    def test_returns_three_components(self) -> None:
        calc = KeltnerCalculator()
        result = _call(calc, period=10, atr_period=5, multiplier=1.5)
        assert set(result.keys()) == {"upper", "middle", "lower"}

    def test_upper_above_lower(self) -> None:
        calc = KeltnerCalculator()
        result = _call(calc, period=10, atr_period=5, multiplier=1.5)
        valid = ~np.isnan(result["upper"]) & ~np.isnan(result["lower"])
        assert np.all(result["upper"][valid] >= result["lower"][valid])

    def test_output_length(self) -> None:
        calc = KeltnerCalculator()
        result = _call(calc, period=10, atr_period=5)
        for key in result:
            assert len(result[key]) == 30

    def test_info(self) -> None:
        calc = KeltnerCalculator()
        assert calc.info().name == "KELTNER"


# ---------------------------------------------------------------------------
# Donchian Channel
# ---------------------------------------------------------------------------


class TestDonchian:
    """Tests for DonchianChannelCalculator."""

    def test_returns_three_components(self) -> None:
        calc = DonchianChannelCalculator()
        result = _call(calc, period=10)
        assert set(result.keys()) == {"upper", "lower", "middle"}

    def test_upper_is_highest_high(self) -> None:
        calc = DonchianChannelCalculator()
        result = _call(calc, period=5)
        # At index 4, upper should be max of _HIGH_30[0:5]
        expected_upper = np.max(_HIGH_30[0:5])
        np.testing.assert_almost_equal(result["upper"][4], expected_upper)

    def test_lower_is_lowest_low(self) -> None:
        calc = DonchianChannelCalculator()
        result = _call(calc, period=5)
        expected_lower = np.min(_LOW_30[0:5])
        np.testing.assert_almost_equal(result["lower"][4], expected_lower)

    def test_middle_is_average(self) -> None:
        calc = DonchianChannelCalculator()
        result = _call(calc, period=5)
        valid = ~np.isnan(result["middle"])
        np.testing.assert_array_almost_equal(
            result["middle"][valid],
            (result["upper"][valid] + result["lower"][valid]) / 2.0,
        )

    def test_info(self) -> None:
        calc = DonchianChannelCalculator()
        assert calc.info().name == "DONCHIAN"


# ---------------------------------------------------------------------------
# Standard Deviation
# ---------------------------------------------------------------------------


class TestStandardDeviation:
    """Tests for StandardDeviationCalculator."""

    def test_flat_prices_zero_std(self) -> None:
        flat = np.full(30, 42.0, dtype=np.float64)
        calc = StandardDeviationCalculator()
        result = _call_custom(calc, close=flat, period=10)
        valid = result[~np.isnan(result)]
        np.testing.assert_array_almost_equal(valid, np.zeros(len(valid)))

    def test_std_non_negative(self) -> None:
        calc = StandardDeviationCalculator()
        result = _call(calc, period=10)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0)

    def test_std_output_length(self) -> None:
        calc = StandardDeviationCalculator()
        result = _call(calc, period=10)
        assert len(result) == 30

    def test_info(self) -> None:
        calc = StandardDeviationCalculator()
        assert calc.info().name == "STDDEV"


# ---------------------------------------------------------------------------
# Historical Volatility
# ---------------------------------------------------------------------------


class TestHistoricalVolatility:
    """Tests for HistoricalVolatilityCalculator."""

    def test_hv_non_negative(self) -> None:
        calc = HistoricalVolatilityCalculator()
        result = _call(calc, period=10)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0)

    def test_hv_flat_prices_zero(self) -> None:
        flat = np.full(30, 100.0, dtype=np.float64)
        calc = HistoricalVolatilityCalculator()
        result = _call_custom(calc, close=flat, period=10)
        valid = result[~np.isnan(result)]
        np.testing.assert_array_almost_equal(valid, np.zeros(len(valid)))

    def test_hv_annualized_larger(self) -> None:
        """Annualized HV should be larger than non-annualized."""
        calc = HistoricalVolatilityCalculator()
        hv_ann = _call(calc, period=10, annualize=True)
        hv_raw = _call(calc, period=10, annualize=False)
        valid = ~np.isnan(hv_ann) & ~np.isnan(hv_raw) & (hv_raw > 0)
        assert np.all(hv_ann[valid] > hv_raw[valid])

    def test_hv_output_length(self) -> None:
        calc = HistoricalVolatilityCalculator()
        result = _call(calc, period=10)
        assert len(result) == 30

    def test_info(self) -> None:
        calc = HistoricalVolatilityCalculator()
        assert calc.info().name == "HISTORICAL_VOLATILITY"
