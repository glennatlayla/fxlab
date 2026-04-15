"""
Volume indicators — measure buying/selling pressure via volume analysis.

Responsibilities:
- OBV: On-Balance Volume — cumulative volume direction indicator.
- VWAP: Volume-Weighted Average Price — intraday fair value.
- ADL: Accumulation/Distribution Line — volume-weighted close position.
- MFI: Money Flow Index — volume-weighted RSI (0-100).
- CMF: Chaikin Money Flow — money flow volume over period.

Does NOT:
- Access databases, files, or external services.
- Manage registration (done at package init time).
- Hold any mutable state between calls.

Dependencies:
- numpy: all computation is vectorized.
- libs.contracts.indicator: IndicatorInfo, IndicatorParam.

Error conditions:
- All indicators return NaN for insufficient lookback where applicable.
- VWAP raises ValueError if volume is all-zero.

Example:
    calc = OBVCalculator()
    obv = calc.calculate(o, h, l, c, v, t)
"""

from __future__ import annotations

from typing import Any

import numpy as np

from libs.contracts.indicator import IndicatorInfo, IndicatorParam


class OBVCalculator:
    """
    OBV — On-Balance Volume.

    Cumulative volume where volume is added on up-close days and
    subtracted on down-close days. OBV confirms price trends.

    Example:
        calc = OBVCalculator()
        obv = calc.calculate(o, h, l, c, v, t)
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
        Compute On-Balance Volume.

        Args:
            close: Close prices (float64).
            volume: Trade volumes (float64).

        Returns:
            np.ndarray with OBV values (no NaN — starts at 0).
        """
        n = len(close)
        result = np.zeros(n, dtype=np.float64)
        if n < 2:
            return result

        # Direction: +1 if close up, -1 if close down, 0 if unchanged
        direction = np.zeros(n, dtype=np.float64)
        direction[1:] = np.sign(close[1:] - close[:-1])

        # OBV = cumulative sum of (direction * volume)
        signed_volume = direction * volume
        result = np.cumsum(signed_volume)

        return result

    def info(self) -> IndicatorInfo:
        """Return OBV metadata."""
        return IndicatorInfo(
            name="OBV",
            description="On-Balance Volume — cumulative volume direction indicator",
            category="volume",
            output_names=["value"],
            default_params={},
        )


class VWAPCalculator:
    """
    VWAP — Volume-Weighted Average Price.

    Cumulative VWAP: sum(typical_price × volume) / sum(volume).
    Typical Price = (High + Low + Close) / 3.

    Example:
        calc = VWAPCalculator()
        vwap = calc.calculate(o, h, l, c, v, t)
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
        Compute VWAP.

        Args:
            high, low, close: Price arrays (float64).
            volume: Trade volumes (float64).

        Returns:
            np.ndarray with VWAP values.

        Raises:
            ValueError: If all volume values are zero.
        """
        if np.all(volume == 0):
            raise ValueError(
                "Cannot compute VWAP: all volume values are zero. "
                "VWAP requires non-zero volume data."
            )

        tp = (high + low + close) / 3.0
        cum_tp_vol = np.cumsum(tp * volume)
        cum_vol = np.cumsum(volume)

        with np.errstate(divide="ignore", invalid="ignore"):
            result = np.where(cum_vol != 0, cum_tp_vol / cum_vol, np.nan)

        return result

    def info(self) -> IndicatorInfo:
        """Return VWAP metadata."""
        return IndicatorInfo(
            name="VWAP",
            description="Volume-Weighted Average Price — intraday fair value",
            category="volume",
            output_names=["value"],
            default_params={},
        )


class ADLCalculator:
    """
    ADL — Accumulation/Distribution Line.

    ADL = cumsum(MFM × volume), where:
    MFM (Money Flow Multiplier) = ((Close - Low) - (High - Close)) / (High - Low)

    Example:
        calc = ADLCalculator()
        adl = calc.calculate(o, h, l, c, v, t)
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
        Compute Accumulation/Distribution Line.

        Args:
            high, low, close: Price arrays (float64).
            volume: Trade volumes (float64).

        Returns:
            np.ndarray with ADL values.
        """
        hl_range = high - low

        # Money Flow Multiplier: ((Close - Low) - (High - Close)) / (High - Low)
        with np.errstate(divide="ignore", invalid="ignore"):
            mfm = np.where(
                hl_range != 0,
                ((close - low) - (high - close)) / hl_range,
                0.0,
            )

        # Money Flow Volume
        mfv = mfm * volume

        # ADL = cumulative sum
        return np.cumsum(mfv)

    def info(self) -> IndicatorInfo:
        """Return ADL metadata."""
        return IndicatorInfo(
            name="ADL",
            description="Accumulation/Distribution Line — volume-weighted close position",
            category="volume",
            output_names=["value"],
            default_params={},
        )


class MFICalculator:
    """
    MFI — Money Flow Index.

    Volume-weighted RSI based on typical price. Bounded [0, 100].
    MFI > 80 is overbought; MFI < 20 is oversold.

    Example:
        calc = MFICalculator()
        mfi = calc.calculate(o, h, l, c, v, t, period=14)
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
        Compute Money Flow Index.

        Args:
            high, low, close: Price arrays (float64).
            volume: Trade volumes (float64).
            **params: period (int, default 14).

        Returns:
            np.ndarray with MFI values bounded [0, 100]; NaN for insufficient lookback.
        """
        period: int = int(params.get("period", 14))
        n = len(close)
        result = np.full(n, np.nan, dtype=np.float64)
        if n < period + 1 or period < 1:
            return result

        # Typical price
        tp = (high + low + close) / 3.0

        # Raw money flow
        raw_mf = tp * volume

        # Positive/negative money flow based on TP direction
        pos_mf = np.zeros(n, dtype=np.float64)
        neg_mf = np.zeros(n, dtype=np.float64)
        for i in range(1, n):
            if tp[i] > tp[i - 1]:
                pos_mf[i] = raw_mf[i]
            elif tp[i] < tp[i - 1]:
                neg_mf[i] = raw_mf[i]

        # Rolling sums
        for i in range(period, n):
            pos_sum = np.sum(pos_mf[i - period + 1 : i + 1])
            neg_sum = np.sum(neg_mf[i - period + 1 : i + 1])
            if neg_sum == 0:
                result[i] = 100.0
            else:
                mf_ratio = pos_sum / neg_sum
                result[i] = 100.0 - (100.0 / (1.0 + mf_ratio))

        return result

    def info(self) -> IndicatorInfo:
        """Return MFI metadata."""
        return IndicatorInfo(
            name="MFI",
            description="Money Flow Index — volume-weighted RSI (0-100)",
            category="volume",
            output_names=["value"],
            default_params={"period": 14},
            param_constraints=[
                IndicatorParam(
                    name="period", default=14, min_value=2, max_value=200, param_type="int"
                ),
            ],
        )


class CMFCalculator:
    """
    CMF — Chaikin Money Flow.

    CMF = sum(MFV, period) / sum(volume, period).
    Bounded approximately [-1, 1].

    Example:
        calc = CMFCalculator()
        cmf = calc.calculate(o, h, l, c, v, t, period=20)
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
        Compute Chaikin Money Flow.

        Args:
            high, low, close: Price arrays (float64).
            volume: Trade volumes (float64).
            **params: period (int, default 20).

        Returns:
            np.ndarray with CMF values; NaN for insufficient lookback.
        """
        period: int = int(params.get("period", 20))
        n = len(close)
        result = np.full(n, np.nan, dtype=np.float64)
        if n < period or period < 1:
            return result

        # Money Flow Multiplier
        hl_range = high - low
        with np.errstate(divide="ignore", invalid="ignore"):
            mfm = np.where(
                hl_range != 0,
                ((close - low) - (high - close)) / hl_range,
                0.0,
            )

        # Money Flow Volume
        mfv = mfm * volume

        # Rolling sums
        cum_mfv = np.cumsum(mfv)
        cum_vol = np.cumsum(volume)

        for i in range(period - 1, n):
            start = i - period + 1
            mfv_sum = cum_mfv[i] - (cum_mfv[start - 1] if start > 0 else 0)
            vol_sum = cum_vol[i] - (cum_vol[start - 1] if start > 0 else 0)
            if vol_sum != 0:
                result[i] = mfv_sum / vol_sum
            else:
                result[i] = 0.0

        return result

    def info(self) -> IndicatorInfo:
        """Return CMF metadata."""
        return IndicatorInfo(
            name="CMF",
            description="Chaikin Money Flow — money flow volume over period",
            category="volume",
            output_names=["value"],
            default_params={"period": 20},
            param_constraints=[
                IndicatorParam(
                    name="period", default=20, min_value=2, max_value=200, param_type="int"
                ),
            ],
        )
