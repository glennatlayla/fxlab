"""
Unit tests for rolling-extremes calculators (M1.B3).

Covers RollingHighCalculator, RollingLowCalculator, RollingMaxCalculator,
RollingMinCalculator. The acceptance bar in the milestone spec is exact
match against ``pandas.Series.rolling(N).max()`` / ``.min()`` (since the
operation is just a window reduction there is no floating-point tolerance).

For each calculator:
- Hand-computed 10-bar fixture with length=3 → assert exact match.
- 500 random bars vs ``pandas.Series.rolling(N).max()/.min()`` → assert
  exact equality (np.array_equal, NaNs in identical positions).
- Edge case: window > series length → all NaN.
- Edge case: NaN at start (first ``length_bars - 1`` outputs are NaN).

Plus:
- Registry wiring for all four registry names.
- Metadata via ``info()``.
- Source-column selection on RollingMax / RollingMin.
- Invalid source raises ValueError.

Naming convention: test_<unit>_<scenario>_<expected_outcome>.
"""

from __future__ import annotations

import numpy as np
import pytest

from libs.indicators import default_registry

# Importing the module also triggers self-registration into default_registry.
from libs.indicators.rolling_extremes import (
    RollingHighCalculator,
    RollingLowCalculator,
    RollingMaxCalculator,
    RollingMinCalculator,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _pandas_rolling_extreme(values: np.ndarray, length_bars: int, op: str) -> np.ndarray:
    """
    Reference oracle that reproduces ``pandas.Series(values).rolling(N).max()``
    (or ``.min()``) using only numpy. Used in lieu of importing pandas because
    pandas is not installed in the test environment, but the M1.B3 acceptance
    criterion is exact equality with pandas' rolling max/min.

    Behaviour matches pandas exactly for arrays without input NaNs:
    - First ``length_bars - 1`` outputs are NaN.
    - If ``length_bars`` exceeds ``len(values)`` the entire output is NaN.
    - Subsequent outputs are the max/min over the trailing window.

    Args:
        values: Input array (float64).
        length_bars: Window size (>= 1).
        op: ``"max"`` or ``"min"``.

    Returns:
        Reference output array matching pandas' rolling reduction.
    """
    n = len(values)
    out = np.full(n, np.nan, dtype=np.float64)
    if length_bars < 1 or length_bars > n:
        return out
    reducer = np.max if op == "max" else np.min
    for i in range(length_bars - 1, n):
        out[i] = reducer(values[i - length_bars + 1 : i + 1])
    return out


def _ohlcv_for(
    close: np.ndarray,
    *,
    open_arr: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    volume: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """
    Build a minimal OHLCV bundle for a calculator's ``calculate`` kwargs.

    Each non-close array defaults to ``close.copy()`` so tests that only care
    about a single column can pass that one and ignore the rest.
    """
    n = len(close)
    return {
        "open": close.copy() if open_arr is None else open_arr,
        "high": close.copy() if high is None else high,
        "low": close.copy() if low is None else low,
        "close": close,
        "volume": np.full(n, 1.0, dtype=np.float64) if volume is None else volume,
        "timestamps": np.arange(n, dtype=np.float64),
    }


# ---------------------------------------------------------------------------
# Hand-computed 10-bar fixture (length=3)
# ---------------------------------------------------------------------------
#
# Bars indexed 0..9. With length_bars=3 the first two outputs are NaN; from
# index 2 onward each output is the max/min over the trailing 3 bars.
#
# high (used by RollingHigh):
#   [10, 12, 11, 14, 13, 15, 12, 11, 16, 9]
#   max-windows from idx 2:
#     idx 2  max(10,12,11) = 12
#     idx 3  max(12,11,14) = 14
#     idx 4  max(11,14,13) = 14
#     idx 5  max(14,13,15) = 15
#     idx 6  max(13,15,12) = 15
#     idx 7  max(15,12,11) = 15
#     idx 8  max(12,11,16) = 16
#     idx 9  max(11,16,9)  = 16
#
# low (used by RollingLow):
#   [ 8,  9,  7, 10,  6, 11,  5, 12,  4, 13]
#   min-windows from idx 2:
#     idx 2  min(8, 9, 7)  = 7
#     idx 3  min(9, 7,10)  = 7
#     idx 4  min(7,10, 6)  = 6
#     idx 5  min(10,6,11)  = 6
#     idx 6  min(6,11, 5)  = 5
#     idx 7  min(11,5,12)  = 5
#     idx 8  min(5,12, 4)  = 4
#     idx 9  min(12,4,13)  = 4
#
# close (used by RollingMax / RollingMin with default source):
#   [9, 10, 8, 11, 7, 12, 6, 13, 5, 14]
#   max-windows from idx 2:
#     idx 2  max(9,10,8)  = 10
#     idx 3  max(10,8,11) = 11
#     idx 4  max(8,11,7)  = 11
#     idx 5  max(11,7,12) = 12
#     idx 6  max(7,12,6)  = 12
#     idx 7  max(12,6,13) = 13
#     idx 8  max(6,13,5)  = 13
#     idx 9  max(13,5,14) = 14
#   min-windows from idx 2:
#     idx 2  min(9,10,8)  = 8
#     idx 3  min(10,8,11) = 8
#     idx 4  min(8,11,7)  = 7
#     idx 5  min(11,7,12) = 7
#     idx 6  min(7,12,6)  = 6
#     idx 7  min(12,6,13) = 6
#     idx 8  min(6,13,5)  = 5
#     idx 9  min(13,5,14) = 5

_HIGH_10 = np.array([10.0, 12.0, 11.0, 14.0, 13.0, 15.0, 12.0, 11.0, 16.0, 9.0])
_LOW_10 = np.array([8.0, 9.0, 7.0, 10.0, 6.0, 11.0, 5.0, 12.0, 4.0, 13.0])
_CLOSE_10 = np.array([9.0, 10.0, 8.0, 11.0, 7.0, 12.0, 6.0, 13.0, 5.0, 14.0])

_EXPECTED_HIGH_LEN3 = np.array([np.nan, np.nan, 12.0, 14.0, 14.0, 15.0, 15.0, 15.0, 16.0, 16.0])
_EXPECTED_LOW_LEN3 = np.array([np.nan, np.nan, 7.0, 7.0, 6.0, 6.0, 5.0, 5.0, 4.0, 4.0])
_EXPECTED_CLOSE_MAX_LEN3 = np.array(
    [np.nan, np.nan, 10.0, 11.0, 11.0, 12.0, 12.0, 13.0, 13.0, 14.0]
)
_EXPECTED_CLOSE_MIN_LEN3 = np.array([np.nan, np.nan, 8.0, 8.0, 7.0, 7.0, 6.0, 6.0, 5.0, 5.0])


def _assert_array_equal_with_nan(a: np.ndarray, b: np.ndarray) -> None:
    """Element-wise equality including NaN positions (NaN == NaN here)."""
    assert a.shape == b.shape, f"shape mismatch: {a.shape} vs {b.shape}"
    assert np.array_equal(np.isnan(a), np.isnan(b)), "NaN mask differs"
    finite_mask = ~np.isnan(a)
    # Exact equality on non-NaN entries (no tolerance — max/min is bit-exact).
    assert np.array_equal(a[finite_mask], b[finite_mask]), (
        f"finite values differ: {a[finite_mask]} vs {b[finite_mask]}"
    )


# ---------------------------------------------------------------------------
# RollingHigh — hand-computed, pandas-parity, edges
# ---------------------------------------------------------------------------


def test_rolling_high_handcomputed_10bar_len3_matches_expected() -> None:
    out = RollingHighCalculator().calculate(**_ohlcv_for(_CLOSE_10, high=_HIGH_10), length_bars=3)
    _assert_array_equal_with_nan(out, _EXPECTED_HIGH_LEN3)


def test_rolling_high_500_random_bars_matches_pandas_rolling_max_exactly() -> None:
    rng = np.random.default_rng(seed=20260425)
    high = (1.10 + rng.standard_normal(500) * 0.005).astype(np.float64)
    length_bars = 20

    out = RollingHighCalculator().calculate(**_ohlcv_for(high, high=high), length_bars=length_bars)
    expected = _pandas_rolling_extreme(high, length_bars, "max")
    _assert_array_equal_with_nan(out, expected)


def test_rolling_high_window_larger_than_series_returns_all_nan() -> None:
    high = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    out = RollingHighCalculator().calculate(**_ohlcv_for(high, high=high), length_bars=10)
    assert out.shape == (5,)
    assert np.all(np.isnan(out))


def test_rolling_high_first_length_minus_one_outputs_are_nan() -> None:
    rng = np.random.default_rng(seed=11)
    high = rng.standard_normal(50).astype(np.float64) + 100.0
    length_bars = 14

    out = RollingHighCalculator().calculate(**_ohlcv_for(high, high=high), length_bars=length_bars)
    assert np.all(np.isnan(out[: length_bars - 1]))
    assert np.all(np.isfinite(out[length_bars - 1 :]))


# ---------------------------------------------------------------------------
# RollingLow — hand-computed, pandas-parity, edges
# ---------------------------------------------------------------------------


def test_rolling_low_handcomputed_10bar_len3_matches_expected() -> None:
    out = RollingLowCalculator().calculate(**_ohlcv_for(_CLOSE_10, low=_LOW_10), length_bars=3)
    _assert_array_equal_with_nan(out, _EXPECTED_LOW_LEN3)


def test_rolling_low_500_random_bars_matches_pandas_rolling_min_exactly() -> None:
    rng = np.random.default_rng(seed=20260426)
    low = (1.10 + rng.standard_normal(500) * 0.005).astype(np.float64)
    length_bars = 20

    out = RollingLowCalculator().calculate(**_ohlcv_for(low, low=low), length_bars=length_bars)
    expected = _pandas_rolling_extreme(low, length_bars, "min")
    _assert_array_equal_with_nan(out, expected)


def test_rolling_low_window_larger_than_series_returns_all_nan() -> None:
    low = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
    out = RollingLowCalculator().calculate(**_ohlcv_for(low, low=low), length_bars=10)
    assert out.shape == (5,)
    assert np.all(np.isnan(out))


def test_rolling_low_first_length_minus_one_outputs_are_nan() -> None:
    rng = np.random.default_rng(seed=22)
    low = rng.standard_normal(50).astype(np.float64) + 100.0
    length_bars = 14

    out = RollingLowCalculator().calculate(**_ohlcv_for(low, low=low), length_bars=length_bars)
    assert np.all(np.isnan(out[: length_bars - 1]))
    assert np.all(np.isfinite(out[length_bars - 1 :]))


# ---------------------------------------------------------------------------
# RollingMax — hand-computed (close), pandas-parity, edges, source selection
# ---------------------------------------------------------------------------


def test_rolling_max_handcomputed_10bar_len3_close_matches_expected() -> None:
    out = RollingMaxCalculator().calculate(
        **_ohlcv_for(_CLOSE_10), length_bars=3
    )  # default source = "close"
    _assert_array_equal_with_nan(out, _EXPECTED_CLOSE_MAX_LEN3)


def test_rolling_max_500_random_bars_matches_pandas_rolling_max_exactly() -> None:
    rng = np.random.default_rng(seed=20260427)
    close = (1.10 + rng.standard_normal(500) * 0.005).astype(np.float64)
    length_bars = 20

    out = RollingMaxCalculator().calculate(**_ohlcv_for(close), length_bars=length_bars)
    expected = _pandas_rolling_extreme(close, length_bars, "max")
    _assert_array_equal_with_nan(out, expected)


def test_rolling_max_window_larger_than_series_returns_all_nan() -> None:
    close = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    out = RollingMaxCalculator().calculate(**_ohlcv_for(close), length_bars=10)
    assert out.shape == (5,)
    assert np.all(np.isnan(out))


def test_rolling_max_first_length_minus_one_outputs_are_nan() -> None:
    rng = np.random.default_rng(seed=33)
    close = rng.standard_normal(50).astype(np.float64) + 100.0
    length_bars = 14

    out = RollingMaxCalculator().calculate(**_ohlcv_for(close), length_bars=length_bars)
    assert np.all(np.isnan(out[: length_bars - 1]))
    assert np.all(np.isfinite(out[length_bars - 1 :]))


@pytest.mark.parametrize("source", ["open", "high", "low", "close", "volume"])
def test_rolling_max_selects_configured_source_column(source: str) -> None:
    rng = np.random.default_rng(seed=44 + len(source))
    n = 100
    arrays = {
        "open": rng.standard_normal(n).astype(np.float64) + 100.0,
        "high": rng.standard_normal(n).astype(np.float64) + 110.0,
        "low": rng.standard_normal(n).astype(np.float64) + 90.0,
        "close": rng.standard_normal(n).astype(np.float64) + 100.0,
        "volume": rng.standard_normal(n).astype(np.float64) + 1000.0,
    }

    out = RollingMaxCalculator().calculate(
        open=arrays["open"],
        high=arrays["high"],
        low=arrays["low"],
        close=arrays["close"],
        volume=arrays["volume"],
        timestamps=np.arange(n, dtype=np.float64),
        length_bars=10,
        source=source,
    )
    expected = _pandas_rolling_extreme(arrays[source], 10, "max")
    _assert_array_equal_with_nan(out, expected)


def test_rolling_max_invalid_source_raises_value_error() -> None:
    close = np.arange(20, dtype=np.float64)
    with pytest.raises(ValueError, match="source must be one of"):
        RollingMaxCalculator().calculate(**_ohlcv_for(close), length_bars=5, source="not_a_column")


# ---------------------------------------------------------------------------
# RollingMin — hand-computed (close), pandas-parity, edges, source selection
# ---------------------------------------------------------------------------


def test_rolling_min_handcomputed_10bar_len3_close_matches_expected() -> None:
    out = RollingMinCalculator().calculate(
        **_ohlcv_for(_CLOSE_10), length_bars=3
    )  # default source = "close"
    _assert_array_equal_with_nan(out, _EXPECTED_CLOSE_MIN_LEN3)


def test_rolling_min_500_random_bars_matches_pandas_rolling_min_exactly() -> None:
    rng = np.random.default_rng(seed=20260428)
    close = (1.10 + rng.standard_normal(500) * 0.005).astype(np.float64)
    length_bars = 20

    out = RollingMinCalculator().calculate(**_ohlcv_for(close), length_bars=length_bars)
    expected = _pandas_rolling_extreme(close, length_bars, "min")
    _assert_array_equal_with_nan(out, expected)


def test_rolling_min_window_larger_than_series_returns_all_nan() -> None:
    close = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
    out = RollingMinCalculator().calculate(**_ohlcv_for(close), length_bars=10)
    assert out.shape == (5,)
    assert np.all(np.isnan(out))


def test_rolling_min_first_length_minus_one_outputs_are_nan() -> None:
    rng = np.random.default_rng(seed=55)
    close = rng.standard_normal(50).astype(np.float64) + 100.0
    length_bars = 14

    out = RollingMinCalculator().calculate(**_ohlcv_for(close), length_bars=length_bars)
    assert np.all(np.isnan(out[: length_bars - 1]))
    assert np.all(np.isfinite(out[length_bars - 1 :]))


@pytest.mark.parametrize("source", ["open", "high", "low", "close", "volume"])
def test_rolling_min_selects_configured_source_column(source: str) -> None:
    rng = np.random.default_rng(seed=66 + len(source))
    n = 100
    arrays = {
        "open": rng.standard_normal(n).astype(np.float64) + 100.0,
        "high": rng.standard_normal(n).astype(np.float64) + 110.0,
        "low": rng.standard_normal(n).astype(np.float64) + 90.0,
        "close": rng.standard_normal(n).astype(np.float64) + 100.0,
        "volume": rng.standard_normal(n).astype(np.float64) + 1000.0,
    }

    out = RollingMinCalculator().calculate(
        open=arrays["open"],
        high=arrays["high"],
        low=arrays["low"],
        close=arrays["close"],
        volume=arrays["volume"],
        timestamps=np.arange(n, dtype=np.float64),
        length_bars=10,
        source=source,
    )
    expected = _pandas_rolling_extreme(arrays[source], 10, "min")
    _assert_array_equal_with_nan(out, expected)


def test_rolling_min_invalid_source_raises_value_error() -> None:
    close = np.arange(20, dtype=np.float64)
    with pytest.raises(ValueError, match="source must be one of"):
        RollingMinCalculator().calculate(**_ohlcv_for(close), length_bars=5, source="not_a_column")


# ---------------------------------------------------------------------------
# Sweep window sizes against pandas (max + min) — guards against off-by-one
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("length_bars", [1, 2, 3, 5, 14, 20, 50])
def test_rolling_high_various_window_sizes_match_pandas_exactly(length_bars: int) -> None:
    rng = np.random.default_rng(seed=2000 + length_bars)
    high = (100.0 + rng.standard_normal(200)).astype(np.float64)
    out = RollingHighCalculator().calculate(**_ohlcv_for(high, high=high), length_bars=length_bars)
    expected = _pandas_rolling_extreme(high, length_bars, "max")
    _assert_array_equal_with_nan(out, expected)


@pytest.mark.parametrize("length_bars", [1, 2, 3, 5, 14, 20, 50])
def test_rolling_low_various_window_sizes_match_pandas_exactly(length_bars: int) -> None:
    rng = np.random.default_rng(seed=3000 + length_bars)
    low = (100.0 + rng.standard_normal(200)).astype(np.float64)
    out = RollingLowCalculator().calculate(**_ohlcv_for(low, low=low), length_bars=length_bars)
    expected = _pandas_rolling_extreme(low, length_bars, "min")
    _assert_array_equal_with_nan(out, expected)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_rolling_high_info_returns_expected_metadata() -> None:
    info = RollingHighCalculator().info()
    assert info.name == "ROLLING_HIGH"
    assert info.category == "volatility"
    assert info.output_names == ["value"]
    assert info.default_params == {"length_bars": 20}
    assert len(info.param_constraints) == 1
    p = info.param_constraints[0]
    assert p.name == "length_bars"
    assert p.default == 20
    assert p.min_value == 1
    assert p.param_type == "int"


def test_rolling_low_info_returns_expected_metadata() -> None:
    info = RollingLowCalculator().info()
    assert info.name == "ROLLING_LOW"
    assert info.category == "volatility"
    assert info.output_names == ["value"]
    assert info.default_params == {"length_bars": 20}


def test_rolling_max_info_returns_expected_metadata_including_source_param() -> None:
    info = RollingMaxCalculator().info()
    assert info.name == "ROLLING_MAX"
    assert info.category == "volatility"
    assert info.default_params == {"length_bars": 20, "source": "close"}
    names = sorted(p.name for p in info.param_constraints)
    assert names == ["length_bars", "source"]


def test_rolling_min_info_returns_expected_metadata_including_source_param() -> None:
    info = RollingMinCalculator().info()
    assert info.name == "ROLLING_MIN"
    assert info.category == "volatility"
    assert info.default_params == {"length_bars": 20, "source": "close"}
    names = sorted(p.name for p in info.param_constraints)
    assert names == ["length_bars", "source"]


# ---------------------------------------------------------------------------
# Registry wiring — module import self-registers all four names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("registry_name", "expected_cls"),
    [
        ("ROLLING_HIGH", RollingHighCalculator),
        ("ROLLING_LOW", RollingLowCalculator),
        ("ROLLING_MAX", RollingMaxCalculator),
        ("ROLLING_MIN", RollingMinCalculator),
    ],
)
def test_default_registry_has_rolling_extreme_registered(
    registry_name: str, expected_cls: type
) -> None:
    """Importing the module triggers self-registration in default_registry."""
    assert default_registry.has(registry_name), (
        f"{registry_name} must be registered in default_registry "
        f"(import libs.indicators.rolling_extremes triggers registration)."
    )
    calc = default_registry.get(registry_name)
    assert isinstance(calc, expected_cls)
