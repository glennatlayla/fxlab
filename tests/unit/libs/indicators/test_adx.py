"""
Unit tests for libs.indicators.adx.ADXCalculator.

Verifies:
- Hand-computed Wilder ADX fixture matches the implementation to 1e-6.
- 500 random bars produce values bounded [0, 100] with no NaN past warmup.
- 500 random bars match pandas-ta's adx() within 1e-6 (skipped if pandas-ta
  is not importable).
"""

from __future__ import annotations

import numpy as np
import pytest

from libs.contracts.indicator import IndicatorInfo
from libs.indicators.adx import ADXCalculator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_volume_timestamps(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Build placeholder volume/timestamps arrays (ADX ignores them)."""
    return np.zeros(n, dtype=np.float64), np.arange(n, dtype=np.float64)


def _reference_wilder_adx(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    length: int,
) -> dict[str, np.ndarray]:
    """
    Independent reference implementation of Wilder ADX for cross-checking.

    Re-derives the chain from scratch using a slightly different style
    (per-step accumulation in plain Python) so a copy-paste bug in the
    production module would surface as a numeric mismatch.
    """
    n = len(close)
    plus_di = np.full(n, np.nan, dtype=np.float64)
    minus_di = np.full(n, np.nan, dtype=np.float64)
    adx = np.full(n, np.nan, dtype=np.float64)

    if length < 1 or n < 2 * length + 1:
        return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}

    tr = [float("nan")] * n
    pdm = [float("nan")] * n
    mdm = [float("nan")] * n
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, hc, lc)
        up = high[i] - high[i - 1]
        dn = low[i - 1] - low[i]
        pdm[i] = up if (up > dn and up > 0.0) else 0.0
        mdm[i] = dn if (dn > up and dn > 0.0) else 0.0

    sm_tr = sum(tr[1 : length + 1])
    sm_pdm = sum(pdm[1 : length + 1])
    sm_mdm = sum(mdm[1 : length + 1])

    dx = [float("nan")] * n
    if sm_tr != 0.0:
        plus_di[length] = 100.0 * sm_pdm / sm_tr
        minus_di[length] = 100.0 * sm_mdm / sm_tr
        denom = plus_di[length] + minus_di[length]
        if denom != 0.0:
            dx[length] = 100.0 * abs(plus_di[length] - minus_di[length]) / denom

    for i in range(length + 1, n):
        sm_tr = sm_tr - sm_tr / length + tr[i]
        sm_pdm = sm_pdm - sm_pdm / length + pdm[i]
        sm_mdm = sm_mdm - sm_mdm / length + mdm[i]
        if sm_tr == 0.0:
            continue
        plus_di[i] = 100.0 * sm_pdm / sm_tr
        minus_di[i] = 100.0 * sm_mdm / sm_tr
        denom = plus_di[i] + minus_di[i]
        if denom == 0.0:
            continue
        dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / denom

    seed_index = 2 * length - 1
    seed_window = dx[length : seed_index + 1]
    if any(v != v for v in seed_window):  # NaN check
        return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}
    adx[seed_index] = sum(seed_window) / length
    for i in range(seed_index + 1, n):
        if dx[i] != dx[i]:  # NaN
            continue
        if adx[i - 1] != adx[i - 1]:
            continue
        adx[i] = (adx[i - 1] * (length - 1) + dx[i]) / length

    return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}


# ---------------------------------------------------------------------------
# Info / metadata
# ---------------------------------------------------------------------------


def test_info_returns_adx_metadata() -> None:
    calc = ADXCalculator()
    info = calc.info()
    assert isinstance(info, IndicatorInfo)
    assert info.name == "ADX"
    assert info.category == "momentum"
    assert info.output_names == ["adx", "plus_di", "minus_di"]
    assert info.default_params == {"length": 14}
    assert any(p.name == "length" for p in info.param_constraints)


# ---------------------------------------------------------------------------
# Hand-computed fixture
# ---------------------------------------------------------------------------


def test_adx_matches_handcomputed_reference_within_1e_minus_6() -> None:
    """30-bar OHLC fixture, length=5. Independent reference implementation."""
    rng = np.random.default_rng(seed=20260425)
    n = 30
    # Build a deterministic but realistic-looking OHLC series. Start at 1.10
    # (EURUSD-ish) and apply modest steps so True Range is non-trivial.
    base = 1.1000
    close = np.empty(n, dtype=np.float64)
    high = np.empty(n, dtype=np.float64)
    low = np.empty(n, dtype=np.float64)
    open_ = np.empty(n, dtype=np.float64)
    price = base
    for i in range(n):
        step = float(rng.normal(0.0, 0.0020))
        open_[i] = price
        price = price + step
        close[i] = price
        # Daily range +/- ~25 pips around the mid of open/close
        mid = (open_[i] + close[i]) / 2.0
        spread = float(abs(rng.normal(0.0, 0.0015))) + 0.0005
        high[i] = mid + spread
        low[i] = mid - spread

    length = 5
    volume, timestamps = _empty_volume_timestamps(n)

    calc = ADXCalculator()
    actual = calc.calculate(open_, high, low, close, volume, timestamps, length=length)
    expected = _reference_wilder_adx(high, low, close, length)

    for key in ("adx", "plus_di", "minus_di"):
        a = actual[key]
        e = np.asarray(expected[key], dtype=np.float64)
        assert a.shape == e.shape
        # Compare NaN-positions and value-positions separately.
        nan_mask = np.isnan(e)
        assert np.array_equal(np.isnan(a), nan_mask), (
            f"{key}: NaN positions diverge (impl vs reference)"
        )
        np.testing.assert_allclose(
            a[~nan_mask],
            e[~nan_mask],
            atol=1e-6,
            rtol=0.0,
            err_msg=f"{key} differs from hand-computed reference",
        )


def test_adx_warmup_window_is_nan_then_finite() -> None:
    """First 2*length-1 bars are NaN; ADX becomes finite at index 2*length-1."""
    rng = np.random.default_rng(seed=42)
    n = 60
    length = 14
    close = 1.10 + np.cumsum(rng.normal(0.0, 0.001, size=n))
    open_ = close + rng.normal(0.0, 0.0005, size=n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0.0, 0.0008, size=n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0.0, 0.0008, size=n))
    volume, timestamps = _empty_volume_timestamps(n)

    result = ADXCalculator().calculate(open_, high, low, close, volume, timestamps, length=length)
    adx = result["adx"]
    # All entries before the seed index must be NaN.
    seed_index = 2 * length - 1
    assert np.all(np.isnan(adx[:seed_index]))
    # Seed and subsequent values must be finite (random walk with no
    # zero-range bars).
    assert np.all(np.isfinite(adx[seed_index:]))


def test_adx_returns_all_nan_when_too_few_bars() -> None:
    """Less than 2*length+1 bars → all NaN, no exceptions."""
    n = 10
    length = 14
    o = np.linspace(1.0, 1.1, n)
    h = o + 0.01
    low = o - 0.01
    c = o + 0.005
    volume, timestamps = _empty_volume_timestamps(n)
    result = ADXCalculator().calculate(o, h, low, c, volume, timestamps, length=length)
    for key in ("adx", "plus_di", "minus_di"):
        assert result[key].shape == (n,)
        assert np.all(np.isnan(result[key]))


def test_adx_handles_flat_prices_without_crashing() -> None:
    """All-flat OHLC: smoothed TR = 0 → DI / DX / ADX must be NaN, not crash."""
    n = 50
    flat = np.full(n, 1.10, dtype=np.float64)
    volume, timestamps = _empty_volume_timestamps(n)
    result = ADXCalculator().calculate(flat, flat, flat, flat, volume, timestamps, length=14)
    # Division-by-zero in DI step is the Wilder-convention NaN path.
    assert np.all(np.isnan(result["adx"]))
    assert np.all(np.isnan(result["plus_di"]))
    assert np.all(np.isnan(result["minus_di"]))


# ---------------------------------------------------------------------------
# 500 random bars: bounds + no NaN past warmup
# ---------------------------------------------------------------------------


def test_adx_500_random_bars_bounded_and_no_nan_after_warmup() -> None:
    rng = np.random.default_rng(seed=20260425)
    n = 500
    length = 14
    # EURUSD-like daily walk
    returns = rng.normal(0.0, 0.005, size=n)
    close = 1.1000 + np.cumsum(returns)
    open_ = close + rng.normal(0.0, 0.001, size=n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0.0, 0.0015, size=n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0.0, 0.0015, size=n))
    volume, timestamps = _empty_volume_timestamps(n)

    result = ADXCalculator().calculate(open_, high, low, close, volume, timestamps, length=length)
    seed_index = 2 * length - 1

    for key in ("adx", "plus_di", "minus_di"):
        arr = result[key]
        assert arr.shape == (n,)
        # Warmup window must be NaN.
        assert np.all(np.isnan(arr[:seed_index])) if key == "adx" else True
        finite = arr[np.isfinite(arr)]
        assert finite.size > 0
        assert np.all(finite >= 0.0), f"{key} produced negative value"
        assert np.all(finite <= 100.0), f"{key} produced value > 100"

    # No NaN in ADX after the seed index for this well-conditioned series.
    assert np.all(np.isfinite(result["adx"][seed_index:]))


# ---------------------------------------------------------------------------
# Cross-check vs pandas-ta (skip if not installed)
# ---------------------------------------------------------------------------


def test_adx_matches_pandas_ta_within_1e_minus_6() -> None:
    pandas_ta = pytest.importorskip(
        "pandas_ta",
        reason="pandas-ta not installed in this environment; "
        "hand-computed reference test is the authoritative correctness check.",
    )
    import pandas as pd  # pandas is already a hard dep of the project

    rng = np.random.default_rng(seed=20260425)
    n = 500
    length = 14
    returns = rng.normal(0.0, 0.005, size=n)
    close = 1.1000 + np.cumsum(returns)
    open_ = close + rng.normal(0.0, 0.001, size=n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0.0, 0.0015, size=n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0.0, 0.0015, size=n))
    volume, timestamps = _empty_volume_timestamps(n)

    result = ADXCalculator().calculate(open_, high, low, close, volume, timestamps, length=length)

    df = pd.DataFrame({"high": high, "low": low, "close": close})
    pta = pandas_ta.adx(df["high"], df["low"], df["close"], length=length)
    # pandas-ta returns columns ADX_<n>, DMP_<n>, DMN_<n>
    ref_adx = pta[f"ADX_{length}"].to_numpy()
    ref_pdi = pta[f"DMP_{length}"].to_numpy()
    ref_mdi = pta[f"DMN_{length}"].to_numpy()

    # Compare on the intersection of finite positions in both arrays.
    for ours, theirs, name in (
        (result["adx"], ref_adx, "adx"),
        (result["plus_di"], ref_pdi, "plus_di"),
        (result["minus_di"], ref_mdi, "minus_di"),
    ):
        mask = np.isfinite(ours) & np.isfinite(theirs)
        assert mask.sum() > 0
        np.testing.assert_allclose(
            ours[mask],
            theirs[mask],
            atol=1e-6,
            rtol=0.0,
            err_msg=f"{name} disagrees with pandas-ta",
        )
