"""
Unit tests for RollingStddevCalculator (M1.B4).

Verifies:
- Sample-stddev semantics (ddof=1) — denominator N-1.
- Hand-computed correctness on a 5-bar fixture with length_bars=3.
- Numerical parity with numpy.std(window, ddof=1) on 500 random bars
  to within 1e-12 (the milestone's stated acceptance bar). Pandas would
  be a stronger third-party oracle but is not in the project's runtime
  deps; numpy is, and ``pandas.Series(...).rolling(N).std()`` is itself
  defined as the ddof=1 rolling reduction, so numpy is the equivalent
  reference.
- NaN-padding contract: first ``length_bars - 1`` outputs are NaN.
- Edge case: window > series length yields all-NaN output.
- Registry wiring: ROLLING_STDDEV is registered in default_registry and
  the registered instance is a RollingStddevCalculator.
- Metadata: get_info() returns ROLLING_STDDEV with the expected default.

Naming convention: test_<unit>_<scenario>_<expected_outcome>.
"""

from __future__ import annotations

import numpy as np
import pytest

from libs.indicators import default_registry
from libs.indicators.rolling_stddev import RollingStddevCalculator

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _ohlcv_for(close: np.ndarray) -> dict[str, np.ndarray]:
    """
    Build a minimal OHLCV bundle around the given close array.

    Other arrays are unused by RollingStddevCalculator but the protocol
    requires them. Using close itself for O/H/L keeps test data terse and
    leaves no possibility of accidentally feeding stale shape information.
    """
    n = len(close)
    return {
        "open": close.copy(),
        "high": close.copy(),
        "low": close.copy(),
        "close": close,
        "volume": np.full(n, 1.0, dtype=np.float64),
        "timestamps": np.arange(n, dtype=np.float64),
    }


# ---------------------------------------------------------------------------
# Hand-computed fixture: 5 bars, length_bars=3, ddof=1
# ---------------------------------------------------------------------------
#
# Window 1 — closes[0..2] = [10, 12, 14]
#   mean = 12; deviations = [-2, 0, 2]; sum_sq = 8; var = 8/(3-1) = 4
#   stddev = 2.0
#
# Window 2 — closes[1..3] = [12, 14, 11]
#   mean = 12.333…; deviations = [-0.333…, 1.666…, -1.333…]
#   sum_sq = 0.1111 + 2.7778 + 1.7778 = 4.6667
#   var = 4.6667 / 2 = 2.3333…; stddev = sqrt(2.3333…) = 1.527525231…
#
# Window 3 — closes[2..4] = [14, 11, 13]
#   mean = 12.666…; deviations = [1.333…, -1.666…, 0.333…]
#   sum_sq = 1.7778 + 2.7778 + 0.1111 = 4.6667
#   var = 2.3333…; stddev = 1.527525231…


def test_calculate_handcomputed_5bar_length3_matches_expected_to_1e12() -> None:
    close = np.array([10.0, 12.0, 14.0, 11.0, 13.0], dtype=np.float64)
    calc = RollingStddevCalculator()

    out = calc.calculate(**_ohlcv_for(close), length_bars=3)

    assert out.shape == (5,)
    assert np.isnan(out[0])
    assert np.isnan(out[1])

    # Compare against numpy ddof=1 — this is the milestone's acceptance oracle.
    expected_w1 = float(np.std(close[0:3], ddof=1))
    expected_w2 = float(np.std(close[1:4], ddof=1))
    expected_w3 = float(np.std(close[2:5], ddof=1))

    assert abs(out[2] - 2.0) <= 1e-12, "Window 1 must match the hand calc."
    assert abs(out[2] - expected_w1) <= 1e-12
    assert abs(out[3] - expected_w2) <= 1e-12
    assert abs(out[4] - expected_w3) <= 1e-12


def test_calculate_500_random_bars_matches_numpy_ddof1_within_1e12() -> None:
    """Milestone acceptance test — 500 bars vs numpy.std(..., ddof=1).

    pandas.Series(arr).rolling(N).std() is defined as the ddof=1 rolling
    reduction, so numpy is the equivalent oracle and is already a runtime
    dependency. Computing the per-window numpy reference explicitly keeps
    the test reproducible without adding a pandas requirement.
    """
    rng = np.random.default_rng(seed=20260425)
    # Anchor around 1.10 to mimic an EURUSD-style mid; magnitudes that
    # exercise floating-point cancellation paths in cumulative-sum stddev.
    close = (1.10 + rng.standard_normal(500) * 0.005).astype(np.float64)
    length_bars = 20
    n = len(close)

    calc = RollingStddevCalculator()
    out = calc.calculate(**_ohlcv_for(close), length_bars=length_bars)

    expected = np.full(n, np.nan, dtype=np.float64)
    for i in range(length_bars - 1, n):
        expected[i] = np.std(close[i - length_bars + 1 : i + 1], ddof=1)

    # Both arrays should have NaN in identical positions (first N-1).
    assert np.array_equal(np.isnan(out), np.isnan(expected))

    valid = ~np.isnan(out)
    diff = np.abs(out[valid] - expected[valid])
    assert diff.max() <= 1e-12, (
        f"max |out - numpy ddof=1| = {diff.max():.3e} exceeds 1e-12 acceptance bar"
    )


def test_calculate_first_length_minus_one_outputs_are_nan() -> None:
    rng = np.random.default_rng(seed=7)
    close = rng.standard_normal(50).astype(np.float64) + 100.0
    length_bars = 14

    out = RollingStddevCalculator().calculate(**_ohlcv_for(close), length_bars=length_bars)

    # First (length_bars - 1) entries must be NaN; entry at index length_bars-1
    # must be a finite sample stddev.
    assert np.all(np.isnan(out[: length_bars - 1]))
    assert np.isfinite(out[length_bars - 1])
    assert np.all(np.isfinite(out[length_bars - 1 :]))


def test_calculate_window_larger_than_series_returns_all_nan() -> None:
    close = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)
    out = RollingStddevCalculator().calculate(**_ohlcv_for(close), length_bars=10)

    assert out.shape == (5,)
    assert np.all(np.isnan(out))


def test_calculate_length_bars_below_two_returns_all_nan() -> None:
    """length_bars < 2 leaves N - 1 == 0; sample stddev undefined."""
    close = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)
    out = RollingStddevCalculator().calculate(**_ohlcv_for(close), length_bars=1)

    assert np.all(np.isnan(out))


def test_calculate_constant_input_returns_zero_after_window_fills() -> None:
    """Constant series → stddev exactly 0.0 (no negative variance leak)."""
    close = np.full(20, 1.2345, dtype=np.float64)
    out = RollingStddevCalculator().calculate(**_ohlcv_for(close), length_bars=5)

    # First 4 are NaN; remainder should be exactly zero.
    assert np.all(np.isnan(out[:4]))
    assert np.allclose(out[4:], 0.0, atol=0.0)


def test_get_info_returns_rolling_stddev_metadata() -> None:
    info = RollingStddevCalculator().get_info()

    assert info.name == "ROLLING_STDDEV"
    assert info.category == "volatility"
    assert info.output_names == ["value"]
    assert info.default_params == {"length_bars": 20}
    assert len(info.param_constraints) == 1

    param = info.param_constraints[0]
    assert param.name == "length_bars"
    assert param.default == 20
    assert param.min_value == 2
    assert param.param_type == "int"


def test_default_registry_has_rolling_stddev_registered() -> None:
    """Module import must wire ROLLING_STDDEV into the default registry."""
    assert default_registry.has("ROLLING_STDDEV"), (
        "ROLLING_STDDEV must be registered in default_registry "
        "(import libs.indicators.rolling_stddev triggers registration)."
    )
    calc = default_registry.get("ROLLING_STDDEV")
    assert isinstance(calc, RollingStddevCalculator)


@pytest.mark.parametrize("length_bars", [2, 3, 5, 14, 20, 50])
def test_calculate_various_window_sizes_match_numpy_to_1e12(length_bars: int) -> None:
    """Sweep representative window sizes; numpy ddof=1 is the oracle."""
    rng = np.random.default_rng(seed=1234 + length_bars)
    close = (100.0 + rng.standard_normal(200)).astype(np.float64)

    out = RollingStddevCalculator().calculate(**_ohlcv_for(close), length_bars=length_bars)

    # Spot-check every valid index against numpy.std(window, ddof=1).
    for i in range(length_bars - 1, len(close)):
        expected = float(np.std(close[i - length_bars + 1 : i + 1], ddof=1))
        assert abs(out[i] - expected) <= 1e-12, (
            f"length={length_bars} idx={i}: got {out[i]}, expected {expected}"
        )
