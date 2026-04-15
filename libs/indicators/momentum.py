"""
Momentum indicators — measure speed and magnitude of price changes.

Responsibilities:
- MACD: Moving Average Convergence Divergence (fast/slow EMA crossover).
- RSI: Relative Strength Index (overbought/oversold oscillator).
- Stochastic: %K and %D stochastic oscillator.
- StochasticRSI: Stochastic applied to RSI values.
- ROC: Rate of Change (percentage price change over period).
- MOM: Momentum (absolute price difference over period).
- Williams_R: Williams %R (inverse stochastic oscillator, -100 to 0).
- CCI: Commodity Channel Index (deviation from typical price mean).

Does NOT:
- Access databases, files, or external services.
- Manage registration (done at package init time).
- Hold any mutable state between calls.

Dependencies:
- numpy: all computation is vectorized.
- libs.indicators.trend._ema_array: shared EMA computation.
- libs.contracts.indicator: IndicatorInfo, IndicatorParam protocol types.

Error conditions:
- All indicators return NaN for positions with insufficient lookback.
- RSI output bounded [0, 100]; Stochastic %K/%D bounded [0, 100].

Example:
    calc = MACDCalculator()
    result = calc.calculate(o, h, l, c, v, t, fast_period=12, slow_period=26, signal_period=9)
    # result is dict with "macd_line", "signal_line", "histogram" keys
"""

from __future__ import annotations

from typing import Any

import numpy as np

from libs.contracts.indicator import IndicatorInfo, IndicatorParam
from libs.indicators.trend import _ema_array


class MACDCalculator:
    """
    MACD — Moving Average Convergence Divergence.

    Computes the difference between fast and slow EMA of close prices,
    a signal line (EMA of MACD), and a histogram (MACD − signal).

    Multi-output: returns dict with "macd_line", "signal_line", "histogram".

    Example:
        calc = MACDCalculator()
        result = calc.calculate(o, h, l, c, v, t, fast_period=12, slow_period=26, signal_period=9)
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
    ) -> dict[str, np.ndarray]:
        """
        Compute MACD, signal line, and histogram.

        Args:
            close: Close prices (float64).
            **params: fast_period (12), slow_period (26), signal_period (9).

        Returns:
            Dict with "macd_line", "signal_line", "histogram" arrays.
        """
        fast_period: int = int(params.get("fast_period", 12))
        slow_period: int = int(params.get("slow_period", 26))
        signal_period: int = int(params.get("signal_period", 9))

        fast_ema = _ema_array(close, fast_period)
        slow_ema = _ema_array(close, slow_period)
        macd_line = fast_ema - slow_ema
        signal_line = _ema_array(macd_line, signal_period)
        histogram = macd_line - signal_line

        return {
            "macd_line": macd_line,
            "signal_line": signal_line,
            "histogram": histogram,
        }

    def info(self) -> IndicatorInfo:
        """Return MACD metadata."""
        return IndicatorInfo(
            name="MACD",
            description="Moving Average Convergence Divergence",
            category="momentum",
            output_names=["macd_line", "signal_line", "histogram"],
            default_params={"fast_period": 12, "slow_period": 26, "signal_period": 9},
            param_constraints=[
                IndicatorParam(
                    name="fast_period", default=12, min_value=2, max_value=100, param_type="int"
                ),
                IndicatorParam(
                    name="slow_period", default=26, min_value=2, max_value=200, param_type="int"
                ),
                IndicatorParam(
                    name="signal_period", default=9, min_value=2, max_value=100, param_type="int"
                ),
            ],
        )


class RSICalculator:
    """
    RSI — Relative Strength Index (Wilder smoothing).

    Measures the magnitude of recent gains vs losses on a 0-100 scale.
    RSI > 70 is typically overbought; RSI < 30 is oversold.

    Uses Wilder's smoothing method (exponential moving average of
    gains and losses with alpha = 1/period).

    Example:
        calc = RSICalculator()
        rsi = calc.calculate(o, h, l, c, v, t, period=14)
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
        Compute RSI from close prices.

        Args:
            close: Close prices (float64).
            **params: period (int, default 14).

        Returns:
            np.ndarray with RSI values bounded [0, 100]; NaN for insufficient lookback.
        """
        period: int = int(params.get("period", 14))
        n = len(close)
        result = np.full(n, np.nan, dtype=np.float64)
        if n < period + 1 or period < 1:
            return result

        # Price changes
        deltas = np.diff(close)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        # First average gain/loss = SMA of first `period` changes
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        # Wilder smoothing: avg = (prev_avg * (period-1) + current) / period
        if avg_loss == 0:
            result[period] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[period] = 100.0 - (100.0 / (1.0 + rs))

        for i in range(period + 1, n):
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
            if avg_loss == 0:
                result[i] = 100.0
            else:
                rs = avg_gain / avg_loss
                result[i] = 100.0 - (100.0 / (1.0 + rs))

        return result

    def info(self) -> IndicatorInfo:
        """Return RSI metadata."""
        return IndicatorInfo(
            name="RSI",
            description="Relative Strength Index — momentum oscillator (0-100)",
            category="momentum",
            output_names=["value"],
            default_params={"period": 14},
            param_constraints=[
                IndicatorParam(
                    name="period", default=14, min_value=2, max_value=200, param_type="int"
                ),
            ],
        )


class StochasticCalculator:
    """
    Stochastic Oscillator — %K and %D lines.

    %K measures where close is relative to the high-low range over k_period.
    %D is the SMA of %K over d_period.
    smooth_k applies SMA smoothing to raw %K before computing %D.

    Output bounded [0, 100].

    Example:
        calc = StochasticCalculator()
        result = calc.calculate(o, h, l, c, v, t, k_period=14, d_period=3, smooth_k=3)
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
    ) -> dict[str, np.ndarray]:
        """
        Compute Stochastic %K and %D.

        Args:
            high: High prices (float64).
            low: Low prices (float64).
            close: Close prices (float64).
            **params: k_period (14), d_period (3), smooth_k (3).

        Returns:
            Dict with "percent_k" and "percent_d" arrays.
        """
        k_period: int = int(params.get("k_period", 14))
        d_period: int = int(params.get("d_period", 3))
        smooth_k: int = int(params.get("smooth_k", 3))

        n = len(close)
        raw_k = np.full(n, np.nan, dtype=np.float64)

        # Raw %K = (Close - Lowest Low) / (Highest High - Lowest Low) × 100
        for i in range(k_period - 1, n):
            h_max = np.max(high[i - k_period + 1 : i + 1])
            l_min = np.min(low[i - k_period + 1 : i + 1])
            hl_range = h_max - l_min
            if hl_range == 0:
                raw_k[i] = 50.0  # Flat price: midpoint
            else:
                raw_k[i] = ((close[i] - l_min) / hl_range) * 100.0

        # Smooth %K with SMA
        percent_k = self._sma_of(raw_k, smooth_k)

        # %D = SMA of smoothed %K
        percent_d = self._sma_of(percent_k, d_period)

        return {"percent_k": percent_k, "percent_d": percent_d}

    @staticmethod
    def _sma_of(data: np.ndarray, period: int) -> np.ndarray:
        """Compute SMA over a (possibly NaN-containing) array."""
        n = len(data)
        result = np.full(n, np.nan, dtype=np.float64)
        if period < 1:
            return result

        for i in range(n):
            window = data[max(0, i - period + 1) : i + 1]
            valid = window[~np.isnan(window)]
            if len(valid) >= period:
                result[i] = np.mean(valid)
        return result

    def info(self) -> IndicatorInfo:
        """Return Stochastic metadata."""
        return IndicatorInfo(
            name="STOCHASTIC",
            description="Stochastic Oscillator — %K and %D (0-100)",
            category="momentum",
            output_names=["percent_k", "percent_d"],
            default_params={"k_period": 14, "d_period": 3, "smooth_k": 3},
            param_constraints=[
                IndicatorParam(
                    name="k_period", default=14, min_value=2, max_value=200, param_type="int"
                ),
                IndicatorParam(
                    name="d_period", default=3, min_value=1, max_value=50, param_type="int"
                ),
                IndicatorParam(
                    name="smooth_k", default=3, min_value=1, max_value=50, param_type="int"
                ),
            ],
        )


class StochasticRSICalculator:
    """
    StochasticRSI — Stochastic oscillator applied to RSI values.

    First computes RSI, then applies the stochastic formula to the RSI
    values. Useful for identifying overbought/oversold in RSI itself.

    Example:
        calc = StochasticRSICalculator()
        result = calc.calculate(o, h, l, c, v, t, rsi_period=14, stoch_period=14, k_period=3, d_period=3)
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
    ) -> dict[str, np.ndarray]:
        """
        Compute StochasticRSI %K and %D.

        Args:
            close: Close prices (float64).
            **params: rsi_period (14), stoch_period (14), k_period (3), d_period (3).

        Returns:
            Dict with "percent_k" and "percent_d" arrays.
        """
        rsi_period: int = int(params.get("rsi_period", 14))
        stoch_period: int = int(params.get("stoch_period", 14))
        k_period: int = int(params.get("k_period", 3))
        d_period: int = int(params.get("d_period", 3))

        n = len(close)
        rsi_calc = RSICalculator()
        rsi = rsi_calc.calculate(open, high, low, close, volume, timestamps, period=rsi_period)

        # Apply Stochastic formula to RSI values
        raw_k = np.full(n, np.nan, dtype=np.float64)
        for i in range(n):
            start = max(0, i - stoch_period + 1)
            window = rsi[start : i + 1]
            valid = window[~np.isnan(window)]
            if len(valid) >= stoch_period:
                rsi_min = np.min(valid)
                rsi_max = np.max(valid)
                rsi_range = rsi_max - rsi_min
                if rsi_range == 0:
                    raw_k[i] = 50.0
                else:
                    raw_k[i] = ((rsi[i] - rsi_min) / rsi_range) * 100.0

        # Smooth %K and %D
        percent_k = StochasticCalculator._sma_of(raw_k, k_period)
        percent_d = StochasticCalculator._sma_of(percent_k, d_period)

        return {"percent_k": percent_k, "percent_d": percent_d}

    def info(self) -> IndicatorInfo:
        """Return StochasticRSI metadata."""
        return IndicatorInfo(
            name="STOCHASTIC_RSI",
            description="Stochastic RSI — stochastic oscillator of RSI values (0-100)",
            category="momentum",
            output_names=["percent_k", "percent_d"],
            default_params={"rsi_period": 14, "stoch_period": 14, "k_period": 3, "d_period": 3},
            param_constraints=[
                IndicatorParam(
                    name="rsi_period", default=14, min_value=2, max_value=200, param_type="int"
                ),
                IndicatorParam(
                    name="stoch_period", default=14, min_value=2, max_value=200, param_type="int"
                ),
                IndicatorParam(
                    name="k_period", default=3, min_value=1, max_value=50, param_type="int"
                ),
                IndicatorParam(
                    name="d_period", default=3, min_value=1, max_value=50, param_type="int"
                ),
            ],
        )


class ROCCalculator:
    """
    Rate of Change — percentage price change over period.

    ROC = ((close[i] - close[i - period]) / close[i - period]) × 100

    Example:
        calc = ROCCalculator()
        roc = calc.calculate(o, h, l, c, v, t, period=12)
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
        Compute Rate of Change.

        Args:
            close: Close prices (float64).
            **params: period (int, default 12).

        Returns:
            np.ndarray with ROC percentage values; NaN for insufficient lookback.
        """
        period: int = int(params.get("period", 12))
        n = len(close)
        result = np.full(n, np.nan, dtype=np.float64)
        if n <= period or period < 1:
            return result

        # Vectorized: ROC[i] = (close[i] - close[i-period]) / close[i-period] * 100
        prev = close[:-period]
        curr = close[period:]
        # Avoid division by zero
        with np.errstate(divide="ignore", invalid="ignore"):
            roc_values = np.where(prev != 0, ((curr - prev) / prev) * 100.0, 0.0)
        result[period:] = roc_values

        return result

    def info(self) -> IndicatorInfo:
        """Return ROC metadata."""
        return IndicatorInfo(
            name="ROC",
            description="Rate of Change — percentage price change over period",
            category="momentum",
            output_names=["value"],
            default_params={"period": 12},
            param_constraints=[
                IndicatorParam(
                    name="period", default=12, min_value=1, max_value=200, param_type="int"
                ),
            ],
        )


class MOMCalculator:
    """
    Momentum — absolute price difference over period.

    MOM = close[i] - close[i - period]

    Example:
        calc = MOMCalculator()
        mom = calc.calculate(o, h, l, c, v, t, period=10)
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
        Compute Momentum.

        Args:
            close: Close prices (float64).
            **params: period (int, default 10).

        Returns:
            np.ndarray with momentum values; NaN for insufficient lookback.
        """
        period: int = int(params.get("period", 10))
        n = len(close)
        result = np.full(n, np.nan, dtype=np.float64)
        if n <= period or period < 1:
            return result

        result[period:] = close[period:] - close[:-period]
        return result

    def info(self) -> IndicatorInfo:
        """Return MOM metadata."""
        return IndicatorInfo(
            name="MOM",
            description="Momentum — absolute price difference over period",
            category="momentum",
            output_names=["value"],
            default_params={"period": 10},
            param_constraints=[
                IndicatorParam(
                    name="period", default=10, min_value=1, max_value=200, param_type="int"
                ),
            ],
        )


class WilliamsRCalculator:
    """
    Williams %R — inverse stochastic oscillator, range [-100, 0].

    %R = ((Highest High - Close) / (Highest High - Lowest Low)) × -100

    Readings near 0 indicate overbought; near -100 indicate oversold.

    Example:
        calc = WilliamsRCalculator()
        wr = calc.calculate(o, h, l, c, v, t, period=14)
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
        Compute Williams %R.

        Args:
            high, low, close: Price arrays (float64).
            **params: period (int, default 14).

        Returns:
            np.ndarray with Williams %R values [-100, 0]; NaN for insufficient lookback.
        """
        period: int = int(params.get("period", 14))
        n = len(close)
        result = np.full(n, np.nan, dtype=np.float64)
        if n < period or period < 1:
            return result

        for i in range(period - 1, n):
            h_max = np.max(high[i - period + 1 : i + 1])
            l_min = np.min(low[i - period + 1 : i + 1])
            hl_range = h_max - l_min
            if hl_range == 0:
                result[i] = -50.0  # Flat price: midpoint
            else:
                result[i] = ((h_max - close[i]) / hl_range) * -100.0

        return result

    def info(self) -> IndicatorInfo:
        """Return Williams %R metadata."""
        return IndicatorInfo(
            name="WILLIAMS_R",
            description="Williams %R — inverse stochastic oscillator (-100 to 0)",
            category="momentum",
            output_names=["value"],
            default_params={"period": 14},
            param_constraints=[
                IndicatorParam(
                    name="period", default=14, min_value=2, max_value=200, param_type="int"
                ),
            ],
        )


class CCICalculator:
    """
    CCI — Commodity Channel Index.

    Measures deviation of typical price from its SMA, scaled by mean
    absolute deviation. CCI = (TP - SMA(TP)) / (0.015 × MAD(TP))

    Typical Price (TP) = (High + Low + Close) / 3

    Example:
        calc = CCICalculator()
        cci = calc.calculate(o, h, l, c, v, t, period=20)
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
        Compute CCI.

        Args:
            high, low, close: Price arrays (float64).
            **params: period (int, default 20).

        Returns:
            np.ndarray with CCI values; NaN for insufficient lookback.
        """
        period: int = int(params.get("period", 20))
        n = len(close)
        result = np.full(n, np.nan, dtype=np.float64)
        if n < period or period < 1:
            return result

        # Typical price
        tp = (high + low + close) / 3.0

        for i in range(period - 1, n):
            window = tp[i - period + 1 : i + 1]
            sma = np.mean(window)
            mad = np.mean(np.abs(window - sma))
            if mad == 0:
                result[i] = 0.0
            else:
                result[i] = (tp[i] - sma) / (0.015 * mad)

        return result

    def info(self) -> IndicatorInfo:
        """Return CCI metadata."""
        return IndicatorInfo(
            name="CCI",
            description="Commodity Channel Index — deviation from typical price mean",
            category="momentum",
            output_names=["value"],
            default_params={"period": 20},
            param_constraints=[
                IndicatorParam(
                    name="period", default=20, min_value=2, max_value=200, param_type="int"
                ),
            ],
        )
