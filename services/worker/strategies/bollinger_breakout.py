"""
Bollinger Bands Breakout signal strategy — volatility-based entry detection.

Responsibilities:
- Detect when price breaks above the upper Bollinger Band (LONG) or below
  the lower Bollinger Band (SHORT).
- Filter false breakouts with volume confirmation: current volume must exceed
  the average volume by a configurable multiplier.
- Classify signal strength and confidence based on how far price extends
  beyond the band relative to the band width.
- Detect EXIT signals when the signal direction opposes an existing position.
- Handle NaN values gracefully (return None if insufficient data).

Does NOT:
- Manage positions or execute trades (service layer responsibility).
- Evaluate risk gates (service layer responsibility).
- Persist signals (repository layer responsibility).

Dependencies:
- libs.contracts.interfaces.signal_strategy: SignalStrategyInterface
- libs.contracts.market_data: Candle
- libs.contracts.indicator: IndicatorRequest, IndicatorResult
- libs.contracts.execution: PositionSnapshot
- libs.contracts.signal: Signal, SignalDirection, SignalStrength, SignalType
- services.worker.strategies._base: build_signal
- numpy: Array operations and NaN handling
- math: NaN detection
- structlog: Debug logging (injected via get_logger)

Error conditions:
- Returns None if required BBANDS indicator is missing.
- Returns None if any band value at [-1] is NaN.
- Returns None if volume confirmation fails.
- Returns None if price is inside the bands (no breakout).

Example:
    strategy = BollingerBandBreakoutStrategy(
        deployment_id="deploy-001",
        bb_period=20,
        bb_std=2.0,
        volume_multiplier=1.5,
        volume_lookback=20,
    )
    # Required indicators: BBANDS with period=20, std_dev=2.0
    requests = strategy.required_indicators()
    # In evaluate, a breakout above upper band with volume confirmation
    # generates a LONG ENTRY signal with strength/confidence based on
    # distance from band relative to band width.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import structlog

from libs.contracts.indicator import IndicatorRequest, IndicatorResult
from libs.contracts.interfaces.signal_strategy import SignalStrategyInterface
from libs.contracts.signal import (
    Signal,
    SignalDirection,
    SignalStrength,
    SignalType,
)
from services.worker.strategies._base import build_signal

if TYPE_CHECKING:
    from libs.contracts.execution import PositionSnapshot
    from libs.contracts.market_data import Candle

logger = structlog.get_logger(__name__)


class BollingerBandBreakoutStrategy(SignalStrategyInterface):
    """
    Signal strategy that detects price breakouts from Bollinger Bands.

    Generates LONG signals when price breaks above the upper band and generates
    SHORT signals when price breaks below the lower band. Both cases require
    volume confirmation: current volume must exceed a configurable multiple
    of recent average volume.

    Signal strength and confidence are computed from how far price extends
    beyond the band as a percentage of the band width (distance between upper
    and lower bands).

    Responsibilities:
    - Detect price breakouts above/below Bollinger Bands.
    - Verify breakouts with volume confirmation.
    - Compute signal strength and confidence from band distance.
    - Classify signals as ENTRY or EXIT based on current position.
    - Declare required indicators (BBANDS) via required_indicators().
    - Return None if insufficient data, volume not confirmed, or no breakout.

    Does NOT:
    - Execute trades or manage positions.
    - Evaluate risk gates.
    - Persist signals.

    Dependencies:
    - Injected: deployment_id, bb_period, bb_std, volume_multiplier, volume_lookback.
    - Computed: band distance, volume averages, signal strength/confidence.
    - External: numpy for array operations.

    Raises:
    - ValueError: If bb_period < 2 or bb_std <= 0.
    - ValueError: If volume_multiplier <= 0 or volume_lookback < 1.

    Example:
        strategy = BollingerBandBreakoutStrategy(
            deployment_id="d1",
            bb_period=20,
            bb_std=2.0,
            volume_multiplier=1.5,
            volume_lookback=20,
        )
        signal = strategy.evaluate(
            "AAPL", candles, indicators, None, correlation_id="c1"
        )
        if signal:
            print(f"Generated {signal.direction} {signal.strength} signal")
    """

    def __init__(
        self,
        *,
        deployment_id: str,
        bb_period: int = 20,
        bb_std: float = 2.0,
        volume_multiplier: float = 1.5,
        volume_lookback: int = 20,
        supported_symbols: list[str] | None = None,
    ) -> None:
        """
        Initialize the Bollinger Band Breakout strategy.

        Args:
            deployment_id: Deployment context identifier (required).
            bb_period: Period for Bollinger Bands calculation (default: 20).
            bb_std: Standard deviation multiplier for bands (default: 2.0).
            volume_multiplier: Required volume multiplier vs recent average (default: 1.5).
                Current volume must exceed avg_volume * this multiplier.
            volume_lookback: Number of recent candles for volume average (default: 20).
            supported_symbols: List of symbols this strategy can trade (default: empty = all).

        Raises:
            ValueError: If bb_period < 2 or bb_std <= 0.
            ValueError: If volume_multiplier <= 0 or volume_lookback < 1.

        Example:
            strategy = BollingerBandBreakoutStrategy(
                deployment_id="deploy-001",
                bb_period=20,
                bb_std=2.0,
                volume_multiplier=1.5,
            )
        """
        if bb_period < 2:
            raise ValueError(f"bb_period ({bb_period}) must be >= 2")
        if bb_std <= 0:
            raise ValueError(f"bb_std ({bb_std}) must be > 0")
        if volume_multiplier <= 0:
            raise ValueError(f"volume_multiplier ({volume_multiplier}) must be > 0")
        if volume_lookback < 1:
            raise ValueError(f"volume_lookback ({volume_lookback}) must be >= 1")

        self._deployment_id = deployment_id
        self._bb_period = bb_period
        self._bb_std = bb_std
        self._volume_multiplier = volume_multiplier
        self._volume_lookback = volume_lookback
        self._supported_symbols = supported_symbols or []

    @property
    def strategy_id(self) -> str:
        """Unique identifier for this strategy."""
        return "bollinger-breakout"

    @property
    def name(self) -> str:
        """Human-readable name for this strategy."""
        return "Bollinger Band Breakout"

    @property
    def supported_symbols(self) -> list[str]:
        """List of symbols this strategy can trade (empty = all)."""
        return self._supported_symbols

    def required_indicators(self) -> list[IndicatorRequest]:
        """
        Declare which indicators this strategy needs computed.

        Returns:
            List with a single IndicatorRequest for BBANDS with configured
            period and std_dev parameters. BBANDS is a multi-output indicator
            that returns "upper", "middle", "lower" components.

        Example:
            reqs = strategy.required_indicators()
            # [
            #   IndicatorRequest(
            #       indicator_name="BBANDS",
            #       params={"period": 20, "std_dev": 2.0}
            #   )
            # ]
        """
        return [
            IndicatorRequest(
                indicator_name="BBANDS",
                params={"period": self._bb_period, "std_dev": self._bb_std},
            )
        ]

    def evaluate(
        self,
        symbol: str,
        candles: list[Candle],
        indicators: dict[str, IndicatorResult],
        current_position: PositionSnapshot | None,
        *,
        correlation_id: str,
    ) -> Signal | None:
        """
        Evaluate market data and indicators, optionally produce a signal.

        Detects price breakouts above the upper Bollinger Band (LONG) or below
        the lower band (SHORT) with volume confirmation. Returns None if
        insufficient data, missing indicators, no breakout, or volume not
        confirmed.

        Args:
            symbol: Ticker symbol being evaluated (e.g. "AAPL").
            candles: Recent candle data for the symbol.
            indicators: Pre-computed indicator results keyed by indicator name
                (e.g. "BBANDS_20").
            current_position: Current position snapshot for this symbol (None if flat).
            correlation_id: Request correlation ID for tracing (keyword-only).

        Returns:
            A Signal if a valid breakout with volume confirmation is detected,
            None otherwise.

        Raises:
            KeyError: If the required BBANDS indicator is not in indicators dict.

        Example:
            signal = strategy.evaluate(
                "AAPL", candles, indicators, None, correlation_id="c1"
            )
            if signal:
                # signal.direction is LONG or SHORT
                # signal.signal_type is ENTRY or EXIT
                # signal.strength is based on distance from band
        """
        logger.debug(
            "Evaluating Bollinger Band breakout",
            symbol=symbol,
            candle_count=len(candles),
            has_position=current_position is not None,
            correlation_id=correlation_id,
        )

        # Build the indicator key.
        bb_key = f"BBANDS_{self._bb_period}"

        # Retrieve required BBANDS result (multi-output indicator).
        try:
            bb_result = indicators[bb_key]
        except KeyError as e:
            logger.warning(
                "Missing required BBANDS indicator",
                symbol=symbol,
                missing=str(e),
                available=list(indicators.keys()),
            )
            return None

        # Extract the band components from the multi-output result.
        try:
            upper = bb_result.get_component("upper")
            middle = bb_result.get_component("middle")
            lower = bb_result.get_component("lower")
        except KeyError as e:
            logger.warning(
                "Missing BBANDS component",
                symbol=symbol,
                error=str(e),
            )
            return None

        # Ensure we have sufficient data points.
        if len(upper) < 1 or len(lower) < 1:
            logger.debug(
                "Insufficient BBANDS data",
                symbol=symbol,
                upper_len=len(upper),
                lower_len=len(lower),
            )
            return None

        # Get the current band values at [-1].
        upper_curr = upper[-1]
        lower_curr = lower[-1]

        # Check for NaN values in band data.
        if math.isnan(upper_curr) or math.isnan(lower_curr):
            logger.debug(
                "NaN values in band data",
                symbol=symbol,
                upper_curr=upper_curr,
                lower_curr=lower_curr,
            )
            return None

        # Get the current close price.
        if len(candles) < 1:
            logger.debug("No candles available", symbol=symbol)
            return None

        close_curr = float(candles[-1].close)

        # Determine if we have a breakout.
        breakout_direction = None
        if close_curr > upper_curr:
            breakout_direction = SignalDirection.LONG
        elif close_curr < lower_curr:
            breakout_direction = SignalDirection.SHORT

        if breakout_direction is None:
            logger.debug(
                "No breakout detected; price inside bands",
                symbol=symbol,
                close=close_curr,
                upper=upper_curr,
                lower=lower_curr,
            )
            return None

        # Calculate average volume from the lookback window.
        volume_lookback = min(self._volume_lookback, len(candles))
        if volume_lookback < 1:
            logger.debug("No candles for volume lookback", symbol=symbol)
            return None

        avg_volume = sum(c.volume for c in candles[-volume_lookback:]) / volume_lookback

        current_volume = float(candles[-1].volume)

        # Confirm with volume: current volume must exceed threshold.
        required_volume = avg_volume * self._volume_multiplier
        if current_volume < required_volume:
            logger.debug(
                "Volume confirmation failed",
                symbol=symbol,
                current_volume=current_volume,
                required_volume=required_volume,
                avg_volume=avg_volume,
            )
            return None

        # Compute signal strength and confidence based on distance from band.
        band_width = upper_curr - lower_curr
        if band_width <= 0:
            logger.debug(
                "Invalid band width",
                symbol=symbol,
                upper=upper_curr,
                lower=lower_curr,
            )
            return None

        if breakout_direction == SignalDirection.LONG:
            distance_from_band = close_curr - upper_curr
        else:  # SHORT
            distance_from_band = lower_curr - close_curr

        distance_pct = (distance_from_band / band_width) * 100.0

        # Strength: STRONG > 0.5%, MODERATE > 0.2%, else WEAK.
        if distance_pct > 0.5:
            strength = SignalStrength.STRONG
        elif distance_pct > 0.2:
            strength = SignalStrength.MODERATE
        else:
            strength = SignalStrength.WEAK

        # Confidence: ratio of distance to band width, clamped to [0.0, 1.0].
        confidence = min(distance_from_band / band_width, 1.0)
        confidence = max(0.0, confidence)

        # Determine signal type: EXIT if direction opposes current position.
        signal_type = SignalType.ENTRY
        if (
            current_position is not None
            and current_position.quantity != 0
            and (
                (breakout_direction == SignalDirection.LONG and current_position.quantity < 0)
                or (breakout_direction == SignalDirection.SHORT and current_position.quantity > 0)
            )
        ):
            signal_type = SignalType.EXIT

        # Build indicators_used dict.
        indicators_used = {
            "upper": float(upper_curr),
            "middle": float(middle[-1]) if not math.isnan(middle[-1]) else 0.0,
            "lower": float(lower_curr),
            "close": close_curr,
        }

        logger.info(
            "Bollinger Band breakout signal detected",
            symbol=symbol,
            direction=breakout_direction.value,
            signal_type=signal_type.value,
            strength=strength.value,
            confidence=confidence,
            distance_pct=distance_pct,
            volume_multiplier=current_volume / avg_volume,
            correlation_id=correlation_id,
        )

        # Build and return the signal.
        signal = build_signal(
            strategy_id=self.strategy_id,
            deployment_id=self._deployment_id,
            symbol=symbol,
            direction=breakout_direction,
            signal_type=signal_type,
            strength=strength,
            confidence=confidence,
            indicators_used=indicators_used,
            bar_timestamp=candles[-1].timestamp,
            correlation_id=correlation_id,
            metadata={
                "upper_band": float(upper_curr),
                "lower_band": float(lower_curr),
                "band_width": float(band_width),
                "distance_pct": distance_pct,
                "current_volume": current_volume,
                "avg_volume": avg_volume,
                "volume_multiplier": current_volume / avg_volume,
                "breakout_type": (
                    "above_upper" if breakout_direction == SignalDirection.LONG else "below_lower"
                ),
            },
        )

        return signal
