"""
Volatility indicators — measure price dispersion and range.

Responsibilities:
- BollingerBands: upper/lower bands based on SMA ± std_dev × σ.
- ATR: Average True Range — volatility from true range.
- Keltner: Keltner Channel — EMA ± multiplier × ATR.
- DonchianChannel: Highest high / lowest low over period.
- StandardDeviation: Rolling standard deviation of close prices.
- HistoricalVolatility: Annualized standard deviation of log returns.

Does NOT:
- Access databases, files, or external services.
- Manage registration (done at package init time).
- Hold any mutable state between calls.

Dependencies:
- numpy: all computation is vectorized.
- libs.indicators.trend: _ema_array for EMA computations.
- libs.contracts.indicator: IndicatorInfo, IndicatorParam.

Example:
    calc = BollingerBandsCalculator()
    result = calc.calculate(o, h, l, c, v, t, period=20, std_dev=2.0)
    # result is dict with "upper", "middle", "lower", "bandwidth", "percent_b"
"""

from __future__ import annotations

from typing import Any

import numpy as np

from libs.contracts.indicator import IndicatorInfo, IndicatorParam
from libs.indicators.trend import _ema_array


class BollingerBandsCalculator:
    """
    Bollinger Bands — SMA ± (std_dev × rolling standard deviation).

    Multi-output: upper, middle (SMA), lower, bandwidth, percent_b.

    Example:
        calc = BollingerBandsCalculator()
        result = calc.calculate(o, h, l, c, v, t, period=20, std_dev=2.0)
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
        Compute Bollinger Bands.

        Args:
            close: Close prices (float64).
            **params: period (20), std_dev (2.0).

        Returns:
            Dict with "upper", "middle", "lower", "bandwidth", "percent_b".
        """
        period: int = int(params.get("period", 20))
        std_mult: float = float(params.get("std_dev", 2.0))
        n = len(close)

        middle = np.full(n, np.nan, dtype=np.float64)
        std = np.full(n, np.nan, dtype=np.float64)

        if n >= period and period >= 1:
            # Compute SMA and rolling std using cumulative approach
            cumsum = np.cumsum(close)
            cumsum2 = np.cumsum(close**2)

            middle[period - 1] = cumsum[period - 1] / period
            middle[period:] = (cumsum[period:] - cumsum[:-period]) / period

            # Rolling variance: E[X²] - E[X]²
            mean_sq = np.full(n, np.nan, dtype=np.float64)
            mean_sq[period - 1] = cumsum2[period - 1] / period
            mean_sq[period:] = (cumsum2[period:] - cumsum2[:-period]) / period

            variance = mean_sq - middle**2
            # Clamp negative variance from floating point errors
            variance = np.maximum(variance, 0.0)
            std = np.sqrt(variance)

        upper = middle + std_mult * std
        lower = middle - std_mult * std

        # Bandwidth = (upper - lower) / middle
        with np.errstate(divide="ignore", invalid="ignore"):
            bandwidth = np.where(middle != 0, (upper - lower) / middle, np.nan)

        # %B = (close - lower) / (upper - lower)
        band_width_raw = upper - lower
        with np.errstate(divide="ignore", invalid="ignore"):
            percent_b = np.where(
                band_width_raw != 0,
                (close - lower) / band_width_raw,
                np.nan,
            )

        return {
            "upper": upper,
            "middle": middle,
            "lower": lower,
            "bandwidth": bandwidth,
            "percent_b": percent_b,
        }

    def info(self) -> IndicatorInfo:
        """Return Bollinger Bands metadata."""
        return IndicatorInfo(
            name="BOLLINGER_BANDS",
            description="Bollinger Bands — SMA ± std_dev × σ",
            category="volatility",
            output_names=["upper", "middle", "lower", "bandwidth", "percent_b"],
            default_params={"period": 20, "std_dev": 2.0},
            param_constraints=[
                IndicatorParam(
                    name="period", default=20, min_value=2, max_value=500, param_type="int"
                ),
                IndicatorParam(
                    name="std_dev", default=2.0, min_value=0.1, max_value=5.0, param_type="float"
                ),
            ],
        )


class ATRCalculator:
    """
    ATR — Average True Range.

    True Range = max(H-L, |H-prev_C|, |L-prev_C|).
    ATR = Wilder's smoothed average of True Range over period.

    Example:
        calc = ATRCalculator()
        atr = calc.calculate(o, h, l, c, v, t, period=14)
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
        Compute ATR.

        Args:
            high, low, close: Price arrays (float64).
            **params: period (int, default 14).

        Returns:
            np.ndarray with ATR values; NaN for insufficient lookback.
        """
        period: int = int(params.get("period", 14))
        n = len(close)
        result = np.full(n, np.nan, dtype=np.float64)
        if n < period + 1 or period < 1:
            return result

        # True Range
        tr = np.full(n, np.nan, dtype=np.float64)
        tr[0] = high[0] - low[0]
        for i in range(1, n):
            hl = high[i] - low[i]
            hc = abs(high[i] - close[i - 1])
            lc = abs(low[i] - close[i - 1])
            tr[i] = max(hl, hc, lc)

        # First ATR = SMA of first `period` true ranges (starting from index 1)
        result[period] = np.mean(tr[1 : period + 1])

        # Wilder smoothing: ATR = (prev_ATR * (period-1) + TR) / period
        for i in range(period + 1, n):
            result[i] = (result[i - 1] * (period - 1) + tr[i]) / period

        return result

    def info(self) -> IndicatorInfo:
        """Return ATR metadata."""
        return IndicatorInfo(
            name="ATR",
            description="Average True Range — volatility from true range",
            category="volatility",
            output_names=["value"],
            default_params={"period": 14},
            param_constraints=[
                IndicatorParam(
                    name="period", default=14, min_value=1, max_value=200, param_type="int"
                ),
            ],
        )


class KeltnerCalculator:
    """
    Keltner Channel — EMA ± (multiplier × ATR).

    Multi-output: upper, middle (EMA), lower.

    Example:
        calc = KeltnerCalculator()
        result = calc.calculate(o, h, l, c, v, t, period=20, atr_period=10, multiplier=1.5)
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
        Compute Keltner Channel.

        Args:
            high, low, close: Price arrays (float64).
            **params: period (20), atr_period (10), multiplier (1.5).

        Returns:
            Dict with "upper", "middle", "lower".
        """
        period: int = int(params.get("period", 20))
        atr_period: int = int(params.get("atr_period", 10))
        multiplier: float = float(params.get("multiplier", 1.5))

        middle = _ema_array(close, period)
        atr_calc = ATRCalculator()
        atr = atr_calc.calculate(open, high, low, close, volume, timestamps, period=atr_period)

        upper = middle + multiplier * atr
        lower = middle - multiplier * atr

        return {"upper": upper, "middle": middle, "lower": lower}

    def info(self) -> IndicatorInfo:
        """Return Keltner Channel metadata."""
        return IndicatorInfo(
            name="KELTNER",
            description="Keltner Channel — EMA ± multiplier × ATR",
            category="volatility",
            output_names=["upper", "middle", "lower"],
            default_params={"period": 20, "atr_period": 10, "multiplier": 1.5},
            param_constraints=[
                IndicatorParam(
                    name="period", default=20, min_value=2, max_value=200, param_type="int"
                ),
                IndicatorParam(
                    name="atr_period", default=10, min_value=1, max_value=200, param_type="int"
                ),
                IndicatorParam(
                    name="multiplier", default=1.5, min_value=0.1, max_value=5.0, param_type="float"
                ),
            ],
        )


class DonchianChannelCalculator:
    """
    Donchian Channel — highest high and lowest low over period.

    Multi-output: upper, lower, middle.

    Example:
        calc = DonchianChannelCalculator()
        result = calc.calculate(o, h, l, c, v, t, period=20)
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
        Compute Donchian Channel.

        Args:
            high, low: Price arrays (float64).
            **params: period (int, default 20).

        Returns:
            Dict with "upper", "lower", "middle".
        """
        period: int = int(params.get("period", 20))
        n = len(close)
        upper = np.full(n, np.nan, dtype=np.float64)
        lower = np.full(n, np.nan, dtype=np.float64)

        for i in range(period - 1, n):
            upper[i] = np.max(high[i - period + 1 : i + 1])
            lower[i] = np.min(low[i - period + 1 : i + 1])

        middle = (upper + lower) / 2.0

        return {"upper": upper, "lower": lower, "middle": middle}

    def info(self) -> IndicatorInfo:
        """Return Donchian Channel metadata."""
        return IndicatorInfo(
            name="DONCHIAN",
            description="Donchian Channel — highest high / lowest low over period",
            category="volatility",
            output_names=["upper", "lower", "middle"],
            default_params={"period": 20},
            param_constraints=[
                IndicatorParam(
                    name="period", default=20, min_value=2, max_value=200, param_type="int"
                ),
            ],
        )


class StandardDeviationCalculator:
    """
    Rolling standard deviation of close prices.

    Example:
        calc = StandardDeviationCalculator()
        std = calc.calculate(o, h, l, c, v, t, period=20)
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
        Compute rolling standard deviation.

        Args:
            close: Close prices (float64).
            **params: period (int, default 20).

        Returns:
            np.ndarray with standard deviation values; NaN for insufficient lookback.
        """
        period: int = int(params.get("period", 20))
        n = len(close)
        result = np.full(n, np.nan, dtype=np.float64)
        if n < period or period < 2:
            return result

        # Use cumulative sums for O(n) computation
        cumsum = np.cumsum(close)
        cumsum2 = np.cumsum(close**2)

        mean = np.full(n, np.nan, dtype=np.float64)
        mean[period - 1] = cumsum[period - 1] / period
        mean[period:] = (cumsum[period:] - cumsum[:-period]) / period

        mean_sq = np.full(n, np.nan, dtype=np.float64)
        mean_sq[period - 1] = cumsum2[period - 1] / period
        mean_sq[period:] = (cumsum2[period:] - cumsum2[:-period]) / period

        variance = mean_sq - mean**2
        variance = np.maximum(variance, 0.0)
        result = np.sqrt(variance)

        return result

    def info(self) -> IndicatorInfo:
        """Return StandardDeviation metadata."""
        return IndicatorInfo(
            name="STDDEV",
            description="Rolling standard deviation of close prices",
            category="volatility",
            output_names=["value"],
            default_params={"period": 20},
            param_constraints=[
                IndicatorParam(
                    name="period", default=20, min_value=2, max_value=500, param_type="int"
                ),
            ],
        )


class HistoricalVolatilityCalculator:
    """
    Historical Volatility — annualized standard deviation of log returns.

    HV = std(log(close[i]/close[i-1])) × √(trading_days_per_year)

    Example:
        calc = HistoricalVolatilityCalculator()
        hv = calc.calculate(o, h, l, c, v, t, period=20, annualize=True)
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
        Compute historical volatility.

        Args:
            close: Close prices (float64).
            **params: period (20), annualize (True), trading_days (252).

        Returns:
            np.ndarray with HV values; NaN for insufficient lookback.
        """
        period: int = int(params.get("period", 20))
        annualize: bool = bool(params.get("annualize", True))
        trading_days: int = int(params.get("trading_days", 252))

        n = len(close)
        result = np.full(n, np.nan, dtype=np.float64)
        if n < period + 1 or period < 2:
            return result

        # Log returns
        with np.errstate(divide="ignore", invalid="ignore"):
            log_returns = np.where(
                close[:-1] > 0,
                np.log(close[1:] / close[:-1]),
                0.0,
            )

        # Rolling std of log returns
        for i in range(period, n):
            window = log_returns[i - period : i]
            result[i] = np.std(window, ddof=1)

        if annualize:
            result *= np.sqrt(trading_days)

        return result

    def info(self) -> IndicatorInfo:
        """Return HistoricalVolatility metadata."""
        return IndicatorInfo(
            name="HISTORICAL_VOLATILITY",
            description="Historical Volatility — annualized std dev of log returns",
            category="volatility",
            output_names=["value"],
            default_params={"period": 20, "annualize": True, "trading_days": 252},
            param_constraints=[
                IndicatorParam(
                    name="period", default=20, min_value=2, max_value=500, param_type="int"
                ),
                IndicatorParam(name="annualize", default=True, param_type="bool"),
                IndicatorParam(
                    name="trading_days", default=252, min_value=1, max_value=365, param_type="int"
                ),
            ],
        )
