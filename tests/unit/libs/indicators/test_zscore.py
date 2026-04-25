"""
Unit tests for libs.indicators.zscore.ZScoreCalculator.

Coverage:
- Hand-computed 5-bar fixture exercising the basic arithmetic.
- 500-bar synthetic series matching numpy's reference computation to
  within 1e-9 absolute tolerance (acceptance criterion from M1.B2).
- Std == 0 returns NaN at the affected positions and emits exactly one
  WARN log for the FIRST std==0 calculation.
- A second std==0 call on the same calculator instance MUST NOT emit a
  second WARN (the "log once per instance" contract).
- info() exposes the canonical metadata required by the registry.
- The module-level registration places "ZSCORE" into default_registry.
"""

from __future__ import annotations

import numpy as np
import pytest
import structlog

from libs.indicators.zscore import ZScoreCalculator


def _empty_ohlcv(n: int) -> dict[str, np.ndarray]:
    """Return zero-filled OHLCV arrays of length ``n``.

    The ZScore calculator never reads OHLCV directly — they are accepted
    only to satisfy the IndicatorCalculator protocol — so any aligned
    same-length arrays will do.
    """
    z = np.zeros(n, dtype=np.float64)
    return {
        "open": z,
        "high": z,
        "low": z,
        "close": z,
        "volume": z,
        "timestamps": np.arange(n, dtype=np.float64),
    }


def test_zscore_hand_computed_five_bar_fixture_matches_expected() -> None:
    """Hand-computed 5-bar arithmetic check.

    z = (value - mean) / std, evaluated element-wise. We pick simple
    integer values whose z-scores are exact in float64.
    """
    calc = ZScoreCalculator()
    value = np.array([10.0, 12.0, 14.0, 16.0, 18.0], dtype=np.float64)
    mean_source = np.array([10.0, 11.0, 12.0, 13.0, 14.0], dtype=np.float64)
    std_source = np.array([1.0, 1.0, 2.0, 2.0, 4.0], dtype=np.float64)
    expected = np.array([0.0, 1.0, 1.0, 1.5, 1.0], dtype=np.float64)

    result = calc.calculate(
        **_empty_ohlcv(5),
        value=value,
        mean_source=mean_source,
        std_source=std_source,
    )

    np.testing.assert_allclose(result, expected, atol=1e-12, rtol=0.0)


def test_zscore_500_bar_series_matches_numpy_reference_within_1e_minus_9() -> None:
    """Acceptance: 500-bar series matches numpy reference within 1e-9."""
    rng = np.random.default_rng(seed=20260425)
    n = 500
    value = rng.normal(loc=1.2345, scale=0.0125, size=n).astype(np.float64)

    # Reference rolling stats over a 20-bar window — emulates what an
    # upstream Bollinger / rolling-stddev indicator would feed in.
    window = 20
    mean_source = np.full(n, np.nan, dtype=np.float64)
    std_source = np.full(n, np.nan, dtype=np.float64)
    for i in range(window - 1, n):
        slice_ = value[i - window + 1 : i + 1]
        mean_source[i] = slice_.mean()
        # ddof=0 = population stddev; the IR's rolling_stddev contract
        # treats the choice as upstream-defined. Either is fine here as
        # long as the reference matches.
        std_source[i] = slice_.std(ddof=0)

    # Reference z-score: vanilla numpy, NaN-safe at warm-up positions.
    with np.errstate(divide="ignore", invalid="ignore"):
        expected = (value - mean_source) / std_source

    calc = ZScoreCalculator()
    result = calc.calculate(
        **_empty_ohlcv(n),
        value=value,
        mean_source=mean_source,
        std_source=std_source,
    )

    # Compare element-wise, treating NaNs as equal — both arrays share
    # the warm-up NaN region.
    assert result.shape == expected.shape
    nan_mask = np.isnan(expected)
    assert np.array_equal(np.isnan(result), nan_mask)
    np.testing.assert_allclose(
        result[~nan_mask],
        expected[~nan_mask],
        atol=1e-9,
        rtol=0.0,
    )


def test_zscore_zero_std_returns_nan_and_warns_once() -> None:
    """Std == 0 → NaN at that position AND exactly one WARN emitted.

    structlog routes through processors rather than stdlib logging, so
    we use ``structlog.testing.capture_logs`` to intercept events.
    """
    calc = ZScoreCalculator()
    value = np.array([10.0, 12.0, 14.0], dtype=np.float64)
    mean_source = np.array([10.0, 11.0, 12.0], dtype=np.float64)
    std_source = np.array([1.0, 0.0, 2.0], dtype=np.float64)

    with structlog.testing.capture_logs() as captured:
        result = calc.calculate(
            **_empty_ohlcv(3),
            value=value,
            mean_source=mean_source,
            std_source=std_source,
        )

    assert np.isnan(result[1])
    # Non-zero-std positions still computed normally.
    assert result[0] == pytest.approx(0.0)
    assert result[2] == pytest.approx(1.0)

    warn_records = [r for r in captured if r["log_level"] == "warning"]
    assert len(warn_records) == 1, (
        f"Expected exactly one WARN on first std==0; got {len(warn_records)}"
    )
    # Sanity: the structured event identifies the std_source / zero condition.
    assert "std_source" in warn_records[0]["event"].lower()
    assert warn_records[0]["operation"] == "zscore_calculate"
    assert warn_records[0]["zero_count"] == 1


def test_zscore_zero_std_subsequent_call_does_not_warn_again() -> None:
    """A second std==0 calculation on the SAME instance must NOT warn."""
    calc = ZScoreCalculator()
    value = np.array([10.0, 12.0], dtype=np.float64)
    mean_source = np.array([10.0, 11.0], dtype=np.float64)
    std_source = np.array([0.0, 0.0], dtype=np.float64)

    # First call — consume the one allowed warning.
    with structlog.testing.capture_logs() as first_captured:
        first = calc.calculate(
            **_empty_ohlcv(2),
            value=value,
            mean_source=mean_source,
            std_source=std_source,
        )
    assert np.isnan(first).all()
    first_warns = [r for r in first_captured if r["log_level"] == "warning"]
    assert len(first_warns) == 1

    # Second call with std==0 — must NOT warn again.
    with structlog.testing.capture_logs() as second_captured:
        second = calc.calculate(
            **_empty_ohlcv(2),
            value=value,
            mean_source=mean_source,
            std_source=std_source,
        )
    assert np.isnan(second).all()
    second_warns = [r for r in second_captured if r["log_level"] == "warning"]
    assert len(second_warns) == 0, (
        "ZScoreCalculator must warn AT MOST ONCE per instance; "
        f"got {len(second_warns)} WARNs on the second call"
    )


def test_zscore_mismatched_shapes_raises_value_error() -> None:
    """value / mean_source / std_source must all be the same length."""
    calc = ZScoreCalculator()
    with pytest.raises(ValueError, match="same shape"):
        calc.calculate(
            **_empty_ohlcv(3),
            value=np.array([1.0, 2.0, 3.0]),
            mean_source=np.array([1.0, 2.0]),
            std_source=np.array([1.0, 1.0, 1.0]),
        )


def test_zscore_info_returns_expected_metadata() -> None:
    """info() exposes the canonical name, category, and param schema."""
    info = ZScoreCalculator().info()
    assert info.name == "ZSCORE"
    assert info.category == "momentum"
    assert info.output_names == ["value"]
    param_names = {p.name for p in info.param_constraints}
    assert {"value", "mean_source", "std_source"}.issubset(param_names)


def test_zscore_registered_in_default_registry() -> None:
    """Importing the module must register ZSCORE in default_registry."""
    # Importing the module is enough — the bottom-of-module register call
    # runs at import time. Re-import is safe because pytest caches.
    import libs.indicators.zscore  # noqa: F401  (import-for-side-effect)
    from libs.indicators import default_registry

    assert default_registry.has("ZSCORE")
    calc = default_registry.get("ZSCORE")
    assert isinstance(calc, ZScoreCalculator)
