"""
Trend indicators — moving averages for smoothing price data.

Responsibilities:
- SMA (Simple Moving Average): equal-weight rolling mean of close prices.
- EMA (Exponential Moving Average): Wilder-smoothed exponential average.
- WMA (Weighted Moving Average): linearly-weighted rolling average.
- DEMA (Double Exponential Moving Average): 2×EMA − EMA(EMA).
- TEMA (Triple Exponential Moving Average): 3×EMA − 3×EMA(EMA) + EMA(EMA(EMA)).

Does NOT:
- Access databases, files, or external services.
- Manage registration (done at package init time).
- Hold any mutable state between calls.

Dependencies:
- numpy: all computation is vectorized.
- libs.contracts.indicator: IndicatorInfo, IndicatorParam protocol types.

Error conditions:
- All indicators return NaN for positions with insufficient lookback.
- Period must be ≥ 1 (enforced via IndicatorParam constraints).

Example:
    calc = SMACalculator()
    result = calc.calculate(open, high, low, close, volume, timestamps, period=20)
    # result is np.ndarray of same length as close, with NaN for first 19 positions
"""

from __future__ import annotations

from typing import Any

import numpy as np

from libs.contracts.indicator import IndicatorInfo, IndicatorParam


def _ema_array(data: np.ndarray, period: int) -> np.ndarray:
    """
    Compute EMA using Wilder smoothing (alpha = 2/(period+1)).

    Finds the first window of ``period`` consecutive non-NaN values to use
    as the SMA seed. This allows chaining (e.g. EMA of EMA for DEMA/TEMA)
    where the input array contains leading NaNs from a prior EMA pass.

    Args:
        data: 1-D float64 input array (may contain leading NaNs).
        period: Lookback window.

    Returns:
        1-D float64 array of same length with EMA values.
    """
    n = len(data)
    result = np.full(n, np.nan, dtype=np.float64)
    if n < period or period < 1:
        return result

    alpha = 2.0 / (period + 1)

    # Find the first index where we have `period` consecutive non-NaN values
    seed_end = -1
    consecutive = 0
    for i in range(n):
        if np.isnan(data[i]):
            consecutive = 0
        else:
            consecutive += 1
            if consecutive >= period:
                seed_end = i
                break

    if seed_end < 0:
        return result  # Not enough non-NaN data

    seed_start = seed_end - period + 1
    result[seed_end] = np.mean(data[seed_start : seed_end + 1])

    # EMA propagation from seed onward
    for i in range(seed_end + 1, n):
        if np.isnan(data[i]):
            # Propagate previous EMA value when input is NaN
            result[i] = result[i - 1]
        else:
            result[i] = alpha * data[i] + (1.0 - alpha) * result[i - 1]

    return result


class SMACalculator:
    """
    Simple Moving Average — equal-weight rolling mean of close prices.

    Computes the arithmetic mean of the last ``period`` close prices at each
    position. Positions with fewer than ``period`` data points are NaN.

    Uses numpy cumsum for O(n) computation instead of naive rolling loops.

    Example:
        calc = SMACalculator()
        sma = calc.calculate(o, h, l, c, v, t, period=20)
    """

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
        """
        Compute SMA from close prices.

        Args:
            close: Close prices (float64).
            **params: period (int, default 20).

        Returns:
            np.ndarray with SMA values; NaN for insufficient lookback.
        """
        period: int = int(params.get("period", 20))
        n = len(close)
        result = np.full(n, np.nan, dtype=np.float64)
        if n < period or period < 1:
            return result

        # O(n) SMA via cumulative sum
        cumsum = np.cumsum(close)
        result[period - 1] = cumsum[period - 1] / period
        result[period:] = (cumsum[period:] - cumsum[:-period]) / period
        return result

    def info(self) -> IndicatorInfo:
        """Return SMA metadata."""
        return IndicatorInfo(
            name="SMA",
            description="Simple Moving Average — equal-weight rolling mean of close prices",
            category="trend",
            output_names=["value"],
            default_params={"period": 20},
            param_constraints=[
                IndicatorParam(
                    name="period", default=20, min_value=1, max_value=500, param_type="int"
                ),
            ],
        )


class EMACalculator:
    """
    Exponential Moving Average — Wilder smoothing (alpha = 2/(period+1)).

    The EMA seed is the SMA of the first ``period`` close prices. Subsequent
    values apply exponential smoothing.

    Example:
        calc = EMACalculator()
        ema = calc.calculate(o, h, l, c, v, t, period=20)
    """

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
        """
        Compute EMA from close prices.

        Args:
            close: Close prices (float64).
            **params: period (int, default 20).

        Returns:
            np.ndarray with EMA values; NaN for insufficient lookback.
        """
        period: int = int(params.get("period", 20))
        return _ema_array(close, period)

    def info(self) -> IndicatorInfo:
        """Return EMA metadata."""
        return IndicatorInfo(
            name="EMA",
            description="Exponential Moving Average — Wilder smoothing",
            category="trend",
            output_names=["value"],
            default_params={"period": 20},
            param_constraints=[
                IndicatorParam(
                    name="period", default=20, min_value=1, max_value=500, param_type="int"
                ),
            ],
        )


class WMACalculator:
    """
    Weighted Moving Average — linearly-weighted rolling average.

    Weight at position i within the window is (i+1), so the most recent
    price has the highest weight.

    Example:
        calc = WMACalculator()
        wma = calc.calculate(o, h, l, c, v, t, period=20)
    """

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
        """
        Compute WMA from close prices.

        Args:
            close: Close prices (float64).
            **params: period (int, default 20).

        Returns:
            np.ndarray with WMA values; NaN for insufficient lookback.
        """
        period: int = int(params.get("period", 20))
        n = len(close)
        result = np.full(n, np.nan, dtype=np.float64)
        if n < period or period < 1:
            return result

        weights = np.arange(1, period + 1, dtype=np.float64)
        divisor = weights.sum()

        # Sliding dot product via stride tricks
        for i in range(period - 1, n):
            window = close[i - period + 1 : i + 1]
            result[i] = np.dot(window, weights) / divisor

        return result

    def info(self) -> IndicatorInfo:
        """Return WMA metadata."""
        return IndicatorInfo(
            name="WMA",
            description="Weighted Moving Average — linearly-weighted rolling average",
            category="trend",
            output_names=["value"],
            default_params={"period": 20},
            param_constraints=[
                IndicatorParam(
                    name="period", default=20, min_value=1, max_value=500, param_type="int"
                ),
            ],
        )


class DEMACalculator:
    """
    Double Exponential Moving Average: 2×EMA(close) − EMA(EMA(close)).

    Reduces lag compared to standard EMA by applying double smoothing.

    Example:
        calc = DEMACalculator()
        dema = calc.calculate(o, h, l, c, v, t, period=20)
    """

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
        """
        Compute DEMA from close prices.

        Args:
            close: Close prices (float64).
            **params: period (int, default 20).

        Returns:
            np.ndarray with DEMA values; NaN for insufficient lookback.
        """
        period: int = int(params.get("period", 20))
        ema1 = _ema_array(close, period)
        ema2 = _ema_array(ema1, period)
        return 2.0 * ema1 - ema2

    def info(self) -> IndicatorInfo:
        """Return DEMA metadata."""
        return IndicatorInfo(
            name="DEMA",
            description="Double Exponential Moving Average — reduced lag smoothing",
            category="trend",
            output_names=["value"],
            default_params={"period": 20},
            param_constraints=[
                IndicatorParam(
                    name="period", default=20, min_value=1, max_value=500, param_type="int"
                ),
            ],
        )


class TEMACalculator:
    """
    Triple Exponential Moving Average: 3×EMA − 3×EMA(EMA) + EMA(EMA(EMA)).

    Further reduces lag compared to DEMA.

    Example:
        calc = TEMACalculator()
        tema = calc.calculate(o, h, l, c, v, t, period=20)
    """

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
        """
        Compute TEMA from close prices.

        Args:
            close: Close prices (float64).
            **params: period (int, default 20).

        Returns:
            np.ndarray with TEMA values; NaN for insufficient lookback.
        """
        period: int = int(params.get("period", 20))
        ema1 = _ema_array(close, period)
        ema2 = _ema_array(ema1, period)
        ema3 = _ema_array(ema2, period)
        return 3.0 * ema1 - 3.0 * ema2 + ema3

    def info(self) -> IndicatorInfo:
        """Return TEMA metadata."""
        return IndicatorInfo(
            name="TEMA",
            description="Triple Exponential Moving Average — minimal lag smoothing",
            category="trend",
            output_names=["value"],
            default_params={"period": 20},
            param_constraints=[
                IndicatorParam(
                    name="period", default=20, min_value=1, max_value=500, param_type="int"
                ),
            ],
        )
