"""
Unit tests for volume indicators (OBV, VWAP, ADL, MFI, CMF).

Validates correctness, boundary conditions, and edge cases.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from libs.indicators.volume import (
    ADLCalculator,
    CMFCalculator,
    MFICalculator,
    OBVCalculator,
    VWAPCalculator,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_CLOSE_20 = np.array(
    [
        100.0,
        102.0,
        101.0,
        103.0,
        104.0,
        103.5,
        105.0,
        106.0,
        105.5,
        107.0,
        108.0,
        107.5,
        109.0,
        110.0,
        109.5,
        111.0,
        112.0,
        111.5,
        113.0,
        114.0,
    ],
    dtype=np.float64,
)
_HIGH_20 = _CLOSE_20 + 1.5
_LOW_20 = _CLOSE_20 - 1.5
_OPEN_20 = _CLOSE_20 - 0.3
_VOLUME_20 = np.array(
    [
        1e6,
        1.2e6,
        0.8e6,
        1.5e6,
        1.1e6,
        0.9e6,
        1.3e6,
        1.4e6,
        1.0e6,
        1.6e6,
        1.2e6,
        0.7e6,
        1.5e6,
        1.8e6,
        0.6e6,
        1.4e6,
        1.7e6,
        0.9e6,
        1.3e6,
        1.5e6,
    ],
    dtype=np.float64,
)
_TS_20 = np.arange(20, dtype=np.float64)


def _call(calc: Any, **params: Any) -> Any:
    return calc.calculate(
        open=_OPEN_20,
        high=_HIGH_20,
        low=_LOW_20,
        close=_CLOSE_20,
        volume=_VOLUME_20,
        timestamps=_TS_20,
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
# OBV
# ---------------------------------------------------------------------------


class TestOBV:
    """Tests for OBVCalculator."""

    def test_obv_output_length(self) -> None:
        calc = OBVCalculator()
        result = _call(calc)
        assert len(result) == 20

    def test_obv_no_nan(self) -> None:
        """OBV should have no NaN values."""
        calc = OBVCalculator()
        result = _call(calc)
        assert not np.any(np.isnan(result))

    def test_obv_uptrend_increases(self) -> None:
        """In a pure uptrend, OBV should increase monotonically."""
        close = np.arange(100.0, 120.0, dtype=np.float64)
        volume = np.full(20, 1e6, dtype=np.float64)
        calc = OBVCalculator()
        result = _call_custom(calc, close=close, volume=volume)
        # Every value after first should be greater than previous
        assert np.all(np.diff(result[1:]) >= 0)

    def test_obv_flat_prices_zero(self) -> None:
        """Flat prices → all direction=0 → OBV stays at 0."""
        flat = np.full(20, 100.0, dtype=np.float64)
        calc = OBVCalculator()
        result = _call_custom(calc, close=flat)
        np.testing.assert_array_equal(result, np.zeros(20))

    def test_obv_info(self) -> None:
        calc = OBVCalculator()
        info = calc.info()
        assert info.name == "OBV"
        assert info.category == "volume"


# ---------------------------------------------------------------------------
# VWAP
# ---------------------------------------------------------------------------


class TestVWAP:
    """Tests for VWAPCalculator."""

    def test_vwap_output_length(self) -> None:
        calc = VWAPCalculator()
        result = _call(calc)
        assert len(result) == 20

    def test_vwap_no_nan(self) -> None:
        calc = VWAPCalculator()
        result = _call(calc)
        assert not np.any(np.isnan(result))

    def test_vwap_first_bar_equals_typical_price(self) -> None:
        """At index 0, VWAP = typical_price[0]."""
        calc = VWAPCalculator()
        result = _call(calc)
        tp0 = (_HIGH_20[0] + _LOW_20[0] + _CLOSE_20[0]) / 3.0
        np.testing.assert_almost_equal(result[0], tp0)

    def test_vwap_zero_volume_raises(self) -> None:
        """All-zero volume should raise ValueError."""
        calc = VWAPCalculator()
        close = np.array([100.0, 101.0, 102.0], dtype=np.float64)
        zero_vol = np.zeros(3, dtype=np.float64)
        with pytest.raises(ValueError, match="all volume values are zero"):
            _call_custom(calc, close=close, volume=zero_vol)

    def test_vwap_equal_volume_is_cumulative_tp_mean(self) -> None:
        """With equal volume bars, VWAP = running mean of typical prices."""
        n = 10
        close = np.arange(100.0, 110.0, dtype=np.float64)
        high = close + 1.0
        low = close - 1.0
        volume = np.full(n, 1e6, dtype=np.float64)
        calc = VWAPCalculator()
        result = _call_custom(calc, close=close, high=high, low=low, volume=volume)
        tp = (high + low + close) / 3.0
        expected_vwap = np.cumsum(tp) / np.arange(1, n + 1)
        np.testing.assert_array_almost_equal(result, expected_vwap)

    def test_vwap_info(self) -> None:
        calc = VWAPCalculator()
        assert calc.info().name == "VWAP"


# ---------------------------------------------------------------------------
# ADL
# ---------------------------------------------------------------------------


class TestADL:
    """Tests for ADLCalculator."""

    def test_adl_output_length(self) -> None:
        calc = ADLCalculator()
        result = _call(calc)
        assert len(result) == 20

    def test_adl_no_nan(self) -> None:
        calc = ADLCalculator()
        result = _call(calc)
        assert not np.any(np.isnan(result))

    def test_adl_close_at_high_positive_mfm(self) -> None:
        """When close = high, MFM = 1, ADL increases."""
        n = 10
        close = np.full(n, 110.0, dtype=np.float64)
        high = np.full(n, 110.0, dtype=np.float64)
        low = np.full(n, 100.0, dtype=np.float64)
        volume = np.full(n, 1e6, dtype=np.float64)
        calc = ADLCalculator()
        result = _call_custom(calc, close=close, high=high, low=low, volume=volume)
        # MFM = ((110-100) - (110-110)) / (110-100) = 1.0
        # ADL should increase by volume each bar
        assert np.all(np.diff(result) > 0)

    def test_adl_info(self) -> None:
        calc = ADLCalculator()
        assert calc.info().name == "ADL"


# ---------------------------------------------------------------------------
# MFI
# ---------------------------------------------------------------------------


class TestMFI:
    """Tests for MFICalculator."""

    def test_mfi_bounded_0_100(self) -> None:
        calc = MFICalculator()
        result = _call(calc, period=5)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0)
        assert np.all(valid <= 100)

    def test_mfi_nan_for_insufficient_lookback(self) -> None:
        calc = MFICalculator()
        result = _call(calc, period=14)
        assert np.all(np.isnan(result[:14]))

    def test_mfi_output_length(self) -> None:
        calc = MFICalculator()
        result = _call(calc, period=5)
        assert len(result) == 20

    def test_mfi_info(self) -> None:
        calc = MFICalculator()
        info = calc.info()
        assert info.name == "MFI"
        assert info.category == "volume"


# ---------------------------------------------------------------------------
# CMF
# ---------------------------------------------------------------------------


class TestCMF:
    """Tests for CMFCalculator."""

    def test_cmf_bounded_minus1_to_1(self) -> None:
        calc = CMFCalculator()
        result = _call(calc, period=10)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= -1.0)
        assert np.all(valid <= 1.0)

    def test_cmf_nan_for_insufficient_lookback(self) -> None:
        calc = CMFCalculator()
        result = _call(calc, period=10)
        assert np.all(np.isnan(result[:9]))

    def test_cmf_output_length(self) -> None:
        calc = CMFCalculator()
        result = _call(calc, period=10)
        assert len(result) == 20

    def test_cmf_close_at_high_positive(self) -> None:
        """When close = high consistently, CMF should be positive."""
        n = 20
        close = np.full(n, 110.0, dtype=np.float64)
        high = np.full(n, 110.0, dtype=np.float64)
        low = np.full(n, 100.0, dtype=np.float64)
        volume = np.full(n, 1e6, dtype=np.float64)
        calc = CMFCalculator()
        result = _call_custom(calc, close=close, high=high, low=low, volume=volume, period=5)
        valid = result[~np.isnan(result)]
        assert np.all(valid > 0)

    def test_cmf_info(self) -> None:
        calc = CMFCalculator()
        assert calc.info().name == "CMF"


# ---------------------------------------------------------------------------
# Default engine integration
# ---------------------------------------------------------------------------


class TestM6Registration:
    """Test that all M6 indicators are registered in the default engine."""

    def test_all_m6_indicators_registered(self) -> None:
        from libs.indicators import default_registry

        expected = {
            "BOLLINGER_BANDS",
            "ATR",
            "KELTNER",
            "DONCHIAN",
            "STDDEV",
            "HISTORICAL_VOLATILITY",
            "OBV",
            "VWAP",
            "ADL",
            "MFI",
            "CMF",
        }
        for name in expected:
            assert default_registry.has(name), f"{name} not registered"

    def test_default_registry_has_24_indicators(self) -> None:
        """13 from M5 + 11 from M6 = 24 total."""
        from libs.indicators import default_registry

        assert default_registry.count() == 24
