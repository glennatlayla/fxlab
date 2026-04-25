"""
Rolling-extremes indicators (M1.B3) — rolling max/min over configurable windows.

Responsibilities:
- RollingHighCalculator: rolling maximum of the ``high`` column over
  ``length_bars``.
- RollingLowCalculator: rolling minimum of the ``low`` column over
  ``length_bars``.
- RollingMaxCalculator: rolling maximum of a configurable ``source`` column
  (default ``close``) over ``length_bars``.
- RollingMinCalculator: rolling minimum of a configurable ``source`` column
  (default ``close``) over ``length_bars``.

All four behave exactly like ``pandas.Series.rolling(length_bars).max()`` /
``.min()``: the first ``length_bars - 1`` outputs are NaN, and if
``length_bars`` exceeds the input length the entire output is NaN.

Used by:
- FX_TimeSeriesMomentum_Breakout_D1 (Donchian-style breakout via
  ``rolling_high`` / ``rolling_low``).
- FX_MTF_DailyTrend_H1Pullback (swing high/low for Fibonacci retracement
  via ``rolling_max`` / ``rolling_min`` on close or other source columns).

Does NOT:
- Access databases, files, or external services.
- Depend on pandas at runtime (math is implemented in numpy; pandas is only
  used as the reference oracle in unit tests).
- Mutate state across calls — every calculator is stateless.

Dependencies:
- numpy: window reductions.
- libs.contracts.indicator: IndicatorInfo, IndicatorParam (metadata model).
- libs.indicators (deferred): module-bottom self-registration into
  ``default_registry``. The import is at the bottom of the file to avoid
  the circular import that would otherwise occur because the package
  ``__init__`` imports concrete calculators while constructing the registry.

Error conditions:
- Returns an all-NaN array (without raising) when the input is shorter than
  ``length_bars`` or ``length_bars`` < 1.

Example:
    from libs.indicators.rolling_extremes import RollingHighCalculator

    calc = RollingHighCalculator()
    out = calc.calculate(o, h, l, c, v, t, length_bars=20)
    # out[i] == max(high[i - 19 : i + 1]) for i >= 19, NaN before that.

Registry names (canonical, uppercase):
- ROLLING_HIGH
- ROLLING_LOW
- ROLLING_MAX
- ROLLING_MIN
"""

from __future__ import annotations

from typing import Any

import numpy as np

from libs.contracts.indicator import IndicatorInfo, IndicatorParam


def _rolling_extreme(values: np.ndarray, length_bars: int, op: str) -> np.ndarray:
    """
    Compute a rolling extreme (max or min) over ``length_bars`` matching
    ``pandas.Series.rolling(length_bars).max()`` / ``.min()`` exactly.

    Edge-case behaviour intentionally matches pandas:
    - Output length equals input length.
    - First ``length_bars - 1`` positions are NaN (insufficient lookback).
    - If ``length_bars`` exceeds ``len(values)`` the entire output is NaN.
    - If ``length_bars < 1`` (defensive — registry constraints prevent this),
      the entire output is NaN.

    Args:
        values: 1-D float64 array of input values.
        length_bars: Window length in bars (>= 1).
        op: Either ``"max"`` or ``"min"``.

    Returns:
        np.ndarray of the same length as ``values`` (float64).

    Raises:
        ValueError: If ``op`` is not ``"max"`` or ``"min"``.
    """
    if op not in ("max", "min"):
        raise ValueError(f"op must be 'max' or 'min', got {op!r}")

    n = len(values)
    out = np.full(n, np.nan, dtype=np.float64)

    if length_bars < 1 or length_bars > n:
        return out

    reducer = np.max if op == "max" else np.min
    for i in range(length_bars - 1, n):
        # Inclusive end index; window covers i - length_bars + 1 .. i.
        out[i] = reducer(values[i - length_bars + 1 : i + 1])

    return out


# Map source-column names to OHLCV positions for RollingMax / RollingMin.
_SOURCE_COLUMNS: dict[str, int] = {
    "open": 0,
    "high": 1,
    "low": 2,
    "close": 3,
    "volume": 4,
}


def _select_source(
    source: str,
    open_arr: np.ndarray,
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    close_arr: np.ndarray,
    volume_arr: np.ndarray,
) -> np.ndarray:
    """
    Return the OHLCV array indicated by ``source``.

    Args:
        source: Column name; one of "open", "high", "low", "close", "volume".
            Comparison is case-insensitive and ignores surrounding whitespace.
        open_arr, high_arr, low_arr, close_arr, volume_arr: Input arrays.

    Returns:
        The selected array.

    Raises:
        ValueError: If ``source`` is not a recognised OHLCV column name.
    """
    key = source.lower().strip()
    if key not in _SOURCE_COLUMNS:
        raise ValueError(f"source must be one of {sorted(_SOURCE_COLUMNS)}, got {source!r}")
    return (open_arr, high_arr, low_arr, close_arr, volume_arr)[_SOURCE_COLUMNS[key]]


class RollingHighCalculator:
    """
    Rolling maximum of the ``high`` column over ``length_bars``.

    Output matches ``pandas.Series(high).rolling(length_bars).max()`` exactly.
    Used by Donchian-style breakout strategies that need the highest high
    over the configured lookback window.

    Example:
        calc = RollingHighCalculator()
        out = calc.calculate(o, h, l, c, v, t, length_bars=20)
    """

    def calculate(
        self,
        open: np.ndarray,  # noqa: A002 — protocol-mandated parameter name
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        timestamps: np.ndarray,
        **params: Any,
    ) -> np.ndarray:
        """
        Compute the rolling maximum of ``high`` over ``length_bars``.

        Args:
            high: High prices (float64). Other OHLCV arrays are accepted for
                protocol compliance but unused.
            **params: ``length_bars`` (int, default 20).

        Returns:
            np.ndarray of rolling maxima; NaN where lookback is insufficient.

        Example:
            out = calc.calculate(o, h, l, c, v, t, length_bars=3)
            # out[0..1] == NaN; out[2] == max(h[0..2]); out[3] == max(h[1..3]); ...
        """
        length_bars = int(params.get("length_bars", 20))
        return _rolling_extreme(high, length_bars, "max")

    def info(self) -> IndicatorInfo:
        """Return RollingHigh metadata."""
        return IndicatorInfo(
            name="ROLLING_HIGH",
            description="Rolling maximum of the high column over length_bars",
            category="volatility",
            output_names=["value"],
            default_params={"length_bars": 20},
            param_constraints=[
                IndicatorParam(
                    name="length_bars",
                    description="Window size in bars",
                    default=20,
                    min_value=1,
                    max_value=100_000,
                    param_type="int",
                ),
            ],
        )


class RollingLowCalculator:
    """
    Rolling minimum of the ``low`` column over ``length_bars``.

    Output matches ``pandas.Series(low).rolling(length_bars).min()`` exactly.
    Used by Donchian-style breakout strategies that need the lowest low
    over the configured lookback window.

    Example:
        calc = RollingLowCalculator()
        out = calc.calculate(o, h, l, c, v, t, length_bars=20)
    """

    def calculate(
        self,
        open: np.ndarray,  # noqa: A002
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        timestamps: np.ndarray,
        **params: Any,
    ) -> np.ndarray:
        """
        Compute the rolling minimum of ``low`` over ``length_bars``.

        Args:
            low: Low prices (float64). Other OHLCV arrays are accepted for
                protocol compliance but unused.
            **params: ``length_bars`` (int, default 20).

        Returns:
            np.ndarray of rolling minima; NaN where lookback is insufficient.

        Example:
            out = calc.calculate(o, h, l, c, v, t, length_bars=3)
            # out[0..1] == NaN; out[2] == min(l[0..2]); out[3] == min(l[1..3]); ...
        """
        length_bars = int(params.get("length_bars", 20))
        return _rolling_extreme(low, length_bars, "min")

    def info(self) -> IndicatorInfo:
        """Return RollingLow metadata."""
        return IndicatorInfo(
            name="ROLLING_LOW",
            description="Rolling minimum of the low column over length_bars",
            category="volatility",
            output_names=["value"],
            default_params={"length_bars": 20},
            param_constraints=[
                IndicatorParam(
                    name="length_bars",
                    description="Window size in bars",
                    default=20,
                    min_value=1,
                    max_value=100_000,
                    param_type="int",
                ),
            ],
        )


class RollingMaxCalculator:
    """
    Rolling maximum of a configurable ``source`` column over ``length_bars``.

    The default source is ``close``; callers may also select ``open``,
    ``high``, ``low``, or ``volume``. Output matches
    ``pandas.Series(source).rolling(length_bars).max()`` exactly.

    Used by FX_MTF_DailyTrend_H1Pullback for swing-high detection
    (Fibonacci retracement reference levels).

    Example:
        calc = RollingMaxCalculator()
        out = calc.calculate(o, h, l, c, v, t, length_bars=20, source="close")
    """

    def calculate(
        self,
        open: np.ndarray,  # noqa: A002
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        timestamps: np.ndarray,
        **params: Any,
    ) -> np.ndarray:
        """
        Compute the rolling maximum of ``source`` over ``length_bars``.

        Args:
            open, high, low, close, volume: OHLCV arrays (float64).
            **params: ``length_bars`` (int, default 20),
                ``source`` (str, default ``"close"``).

        Returns:
            np.ndarray of rolling maxima; NaN where lookback is insufficient.

        Raises:
            ValueError: If ``source`` is not one of open/high/low/close/volume.
        """
        length_bars = int(params.get("length_bars", 20))
        source = str(params.get("source", "close"))
        values = _select_source(source, open, high, low, close, volume)
        return _rolling_extreme(values, length_bars, "max")

    def info(self) -> IndicatorInfo:
        """Return RollingMax metadata."""
        return IndicatorInfo(
            name="ROLLING_MAX",
            description="Rolling maximum of a configurable source column",
            category="volatility",
            output_names=["value"],
            default_params={"length_bars": 20, "source": "close"},
            param_constraints=[
                IndicatorParam(
                    name="length_bars",
                    description="Window size in bars",
                    default=20,
                    min_value=1,
                    max_value=100_000,
                    param_type="int",
                ),
                IndicatorParam(
                    name="source",
                    description="OHLCV column: open, high, low, close, or volume",
                    default="close",
                    param_type="str",
                ),
            ],
        )


class RollingMinCalculator:
    """
    Rolling minimum of a configurable ``source`` column over ``length_bars``.

    The default source is ``close``; callers may also select ``open``,
    ``high``, ``low``, or ``volume``. Output matches
    ``pandas.Series(source).rolling(length_bars).min()`` exactly.

    Used by FX_MTF_DailyTrend_H1Pullback for swing-low detection
    (Fibonacci retracement reference levels).

    Example:
        calc = RollingMinCalculator()
        out = calc.calculate(o, h, l, c, v, t, length_bars=20, source="close")
    """

    def calculate(
        self,
        open: np.ndarray,  # noqa: A002
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        timestamps: np.ndarray,
        **params: Any,
    ) -> np.ndarray:
        """
        Compute the rolling minimum of ``source`` over ``length_bars``.

        Args:
            open, high, low, close, volume: OHLCV arrays (float64).
            **params: ``length_bars`` (int, default 20),
                ``source`` (str, default ``"close"``).

        Returns:
            np.ndarray of rolling minima; NaN where lookback is insufficient.

        Raises:
            ValueError: If ``source`` is not one of open/high/low/close/volume.
        """
        length_bars = int(params.get("length_bars", 20))
        source = str(params.get("source", "close"))
        values = _select_source(source, open, high, low, close, volume)
        return _rolling_extreme(values, length_bars, "min")

    def info(self) -> IndicatorInfo:
        """Return RollingMin metadata."""
        return IndicatorInfo(
            name="ROLLING_MIN",
            description="Rolling minimum of a configurable source column",
            category="volatility",
            output_names=["value"],
            default_params={"length_bars": 20, "source": "close"},
            param_constraints=[
                IndicatorParam(
                    name="length_bars",
                    description="Window size in bars",
                    default=20,
                    min_value=1,
                    max_value=100_000,
                    param_type="int",
                ),
                IndicatorParam(
                    name="source",
                    description="OHLCV column: open, high, low, close, or volume",
                    default="close",
                    param_type="str",
                ),
            ],
        )


# ---------------------------------------------------------------------------
# Module-bottom self-registration into the default registry.
#
# Imported here (not at top of file) to avoid a circular import:
# ``libs.indicators.__init__`` imports concrete calculators to populate
# ``default_registry``, and that module is loaded before this one when
# the package is first imported. Deferring the import to module-execution
# end means by the time we touch ``default_registry`` the package init
# has finished (or, if this module is imported standalone, the init runs
# first as a side effect of ``from libs.indicators ...``).
#
# Note: ``libs/indicators/__init__.py`` does NOT currently import this
# module (per the M1.B3 task brief which forbids modifying it). Callers
# that need ROLLING_HIGH / ROLLING_LOW / ROLLING_MAX / ROLLING_MIN in
# the default registry must therefore ``import libs.indicators.rolling_extremes``
# explicitly. The expected production wiring is a one-line import in
# ``libs/indicators/__init__.py``; that step is owned by the integration
# milestone that touches __init__.py.
# ---------------------------------------------------------------------------
from libs.indicators import default_registry  # noqa: E402  (intentional late import)

if not default_registry.has("ROLLING_HIGH"):
    default_registry.register("ROLLING_HIGH", RollingHighCalculator())
if not default_registry.has("ROLLING_LOW"):
    default_registry.register("ROLLING_LOW", RollingLowCalculator())
if not default_registry.has("ROLLING_MAX"):
    default_registry.register("ROLLING_MAX", RollingMaxCalculator())
if not default_registry.has("ROLLING_MIN"):
    default_registry.register("ROLLING_MIN", RollingMinCalculator())
