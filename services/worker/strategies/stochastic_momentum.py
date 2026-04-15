"""
Stochastic Momentum signal strategy — crossover-based momentum entry detection.

Responsibilities:
- Detect Stochastic %K crossovers with the %D signal line for momentum trades.
- Filter signals using RSI to ensure consistent directional momentum.
- Classify signal strength and confidence based on the %K-%D divergence.
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
- math: NaN detection
- structlog: Debug logging (injected via get_logger)

Error conditions:
- Returns None if required STOCH or RSI indicators are missing.
- Returns None if any indicator value is NaN.
- Returns None if we lack sufficient data for crossover detection (at least 2 prior values).
- Returns None if no valid crossover is detected.
- Returns None if RSI filter conditions are not met.

Example:
    strategy = StochasticMomentumStrategy(
        deployment_id="deploy-001",
        stoch_period=14,
        stoch_k=3,
        stoch_d=3,
        rsi_period=14,
        oversold_zone=20.0,
        overbought_zone=80.0,
        rsi_long_filter=40.0,
        rsi_short_filter=60.0,
    )
    # Required indicators: STOCH and RSI with configured parameters
    requests = strategy.required_indicators()
    # In evaluate, a %K crossover above %D in the oversold zone with RSI < 40
    # generates a LONG ENTRY signal with strength/confidence based on K-D divergence.
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


class StochasticMomentumStrategy(SignalStrategyInterface):
    """
    Signal strategy that detects momentum shifts via Stochastic %K/%D crossovers.

    Generates LONG signals when %K crosses above %D in the oversold zone
    (configurable, typically < 20), and SHORT signals when %K crosses below %D
    in the overbought zone (configurable, typically > 80). Both signals are
    further filtered by RSI to confirm directional momentum.

    Signal strength and confidence are computed from the magnitude of the %K-%D
    divergence (difference between %K and %D values).

    Responsibilities:
    - Detect Stochastic %K/%D crossovers (bullish and bearish).
    - Filter crossovers by overbought/oversold zones.
    - Confirm direction with RSI thresholds.
    - Compute signal strength and confidence from K-D divergence.
    - Classify signals as ENTRY or EXIT based on current position.
    - Declare required indicators (STOCH and RSI) via required_indicators().
    - Return None if insufficient data or filter conditions not met.

    Does NOT:
    - Execute trades or manage positions.
    - Evaluate risk gates.
    - Persist signals.

    Dependencies:
    - Injected: deployment_id, stoch_period, stoch_k, stoch_d, rsi_period,
      oversold_zone, overbought_zone, rsi_long_filter, rsi_short_filter.
    - Computed: K-D divergence, RSI confirmation.
    - External: structlog for logging.

    Raises:
    - ValueError: If stoch_period < 1, stoch_k < 1, or stoch_d < 1.
    - ValueError: If rsi_period < 1.
    - ValueError: If zone thresholds are outside [0, 100].
    - ValueError: If rsi_long_filter >= rsi_short_filter.

    Example:
        strategy = StochasticMomentumStrategy(
            deployment_id="d1",
            stoch_period=14,
            oversold_zone=20.0,
            overbought_zone=80.0,
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
        stoch_period: int = 14,
        stoch_k: int = 3,
        stoch_d: int = 3,
        rsi_period: int = 14,
        oversold_zone: float = 20.0,
        overbought_zone: float = 80.0,
        rsi_long_filter: float = 40.0,
        rsi_short_filter: float = 60.0,
        supported_symbols: list[str] | None = None,
    ) -> None:
        """
        Initialize the Stochastic Momentum strategy.

        Args:
            deployment_id: Deployment context identifier (required).
            stoch_period: Period for Stochastic calculation (default: 14).
            stoch_k: Smoothing period for %K line (default: 3).
            stoch_d: Smoothing period for %D line (default: 3).
            rsi_period: Period for RSI calculation (default: 14).
            oversold_zone: Threshold for oversold zone, 0-100 (default: 20.0).
                LONG signals triggered when %K < this and crosses above %D.
            overbought_zone: Threshold for overbought zone, 0-100 (default: 80.0).
                SHORT signals triggered when %K > this and crosses below %D.
            rsi_long_filter: Maximum RSI for LONG signals (default: 40.0).
                Confirms LONG when RSI[-1] < this threshold.
            rsi_short_filter: Minimum RSI for SHORT signals (default: 60.0).
                Confirms SHORT when RSI[-1] > this threshold.
            supported_symbols: List of symbols this strategy can trade (default: empty = all).

        Raises:
            ValueError: If stoch_period < 1, stoch_k < 1, or stoch_d < 1.
            ValueError: If rsi_period < 1.
            ValueError: If zone thresholds are outside [0, 100].
            ValueError: If rsi_long_filter >= rsi_short_filter.

        Example:
            strategy = StochasticMomentumStrategy(
                deployment_id="deploy-001",
                stoch_period=14,
                oversold_zone=20.0,
                overbought_zone=80.0,
            )
        """
        if stoch_period < 1:
            raise ValueError(f"stoch_period ({stoch_period}) must be >= 1")
        if stoch_k < 1:
            raise ValueError(f"stoch_k ({stoch_k}) must be >= 1")
        if stoch_d < 1:
            raise ValueError(f"stoch_d ({stoch_d}) must be >= 1")
        if rsi_period < 1:
            raise ValueError(f"rsi_period ({rsi_period}) must be >= 1")
        if not (0 <= oversold_zone <= 100):
            raise ValueError(f"oversold_zone ({oversold_zone}) must be in [0, 100]")
        if not (0 <= overbought_zone <= 100):
            raise ValueError(f"overbought_zone ({overbought_zone}) must be in [0, 100]")
        if rsi_long_filter >= rsi_short_filter:
            raise ValueError(
                f"rsi_long_filter ({rsi_long_filter}) must be < "
                f"rsi_short_filter ({rsi_short_filter})"
            )

        self._deployment_id = deployment_id
        self._stoch_period = stoch_period
        self._stoch_k = stoch_k
        self._stoch_d = stoch_d
        self._rsi_period = rsi_period
        self._oversold_zone = oversold_zone
        self._overbought_zone = overbought_zone
        self._rsi_long_filter = rsi_long_filter
        self._rsi_short_filter = rsi_short_filter
        self._supported_symbols = supported_symbols or []

    @property
    def strategy_id(self) -> str:
        """Unique identifier for this strategy."""
        return "stochastic-momentum"

    @property
    def name(self) -> str:
        """Human-readable name for this strategy."""
        return "Stochastic Momentum"

    @property
    def supported_symbols(self) -> list[str]:
        """List of symbols this strategy can trade (empty = all)."""
        return self._supported_symbols

    def required_indicators(self) -> list[IndicatorRequest]:
        """
        Declare which indicators this strategy needs computed.

        Returns:
            List with two IndicatorRequests: one for STOCH (with k and d smoothing),
            one for RSI. Both are multi-output indicators.

        Example:
            reqs = strategy.required_indicators()
            # [
            #   IndicatorRequest(
            #       indicator_name="STOCH",
            #       params={"period": 14, "k_period": 3, "d_period": 3}
            #   ),
            #   IndicatorRequest(
            #       indicator_name="RSI",
            #       params={"period": 14}
            #   )
            # ]
        """
        return [
            IndicatorRequest(
                indicator_name="STOCH",
                params={
                    "period": self._stoch_period,
                    "k_period": self._stoch_k,
                    "d_period": self._stoch_d,
                },
            ),
            IndicatorRequest(
                indicator_name="RSI",
                params={"period": self._rsi_period},
            ),
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

        Detects Stochastic %K/%D crossovers in oversold/overbought zones,
        confirmed by RSI thresholds. Returns None if insufficient data,
        missing indicators, or filter conditions not met.

        Args:
            symbol: Ticker symbol being evaluated (e.g. "AAPL").
            candles: Recent candle data for the symbol.
            indicators: Pre-computed indicator results keyed by indicator name
                (e.g. "STOCH_14", "RSI_14").
            current_position: Current position snapshot for this symbol (None if flat).
            correlation_id: Request correlation ID for tracing (keyword-only).

        Returns:
            A Signal if a valid crossover with RSI confirmation is detected,
            None otherwise.

        Raises:
            KeyError: If required STOCH or RSI indicators are not in indicators dict.

        Example:
            signal = strategy.evaluate(
                "AAPL", candles, indicators, None, correlation_id="c1"
            )
            if signal:
                # signal.direction is LONG or SHORT
                # signal.signal_type is ENTRY or EXIT
                # signal.strength is based on K-D divergence
        """
        logger.debug(
            "Evaluating Stochastic momentum",
            symbol=symbol,
            candle_count=len(candles),
            has_position=current_position is not None,
            correlation_id=correlation_id,
        )

        # Build indicator keys.
        stoch_key = f"STOCH_{self._stoch_period}"
        rsi_key = f"RSI_{self._rsi_period}"

        # Retrieve required indicator results.
        try:
            stoch_result = indicators[stoch_key]
            rsi_result = indicators[rsi_key]
        except KeyError as e:
            logger.warning(
                "Missing required indicators",
                symbol=symbol,
                missing=str(e),
                available=list(indicators.keys()),
            )
            return None

        # Extract K and D components from STOCH (multi-output).
        try:
            k = stoch_result.get_component("k")
            d = stoch_result.get_component("d")
        except KeyError as e:
            logger.warning(
                "Missing STOCH component",
                symbol=symbol,
                error=str(e),
            )
            return None

        # Get RSI values (single-output indicator).
        rsi = rsi_result.values

        # Ensure we have at least 2 values for crossover detection.
        if len(k) < 2 or len(d) < 2 or len(rsi) < 1:
            logger.debug(
                "Insufficient indicator data",
                symbol=symbol,
                k_len=len(k),
                d_len=len(d),
                rsi_len=len(rsi),
            )
            return None

        # Extract the last two values of K and D for crossover detection.
        k_prev = k[-2]
        k_curr = k[-1]
        d_prev = d[-2]
        d_curr = d[-1]
        rsi_curr = rsi[-1]

        # Check for NaN values.
        if (
            math.isnan(k_prev)
            or math.isnan(k_curr)
            or math.isnan(d_prev)
            or math.isnan(d_curr)
            or math.isnan(rsi_curr)
        ):
            logger.debug(
                "NaN values in indicator data",
                symbol=symbol,
                k_prev=k_prev,
                k_curr=k_curr,
                d_prev=d_prev,
                d_curr=d_curr,
                rsi_curr=rsi_curr,
            )
            return None

        # Detect crossovers:
        # LONG: K crosses above D (k_prev <= d_prev AND k_curr > d_curr)
        # SHORT: K crosses below D (k_prev >= d_prev AND k_curr < d_curr)
        long_crossover = k_prev <= d_prev and k_curr > d_curr
        short_crossover = k_prev >= d_prev and k_curr < d_curr

        # Determine signal direction.
        direction = None
        if long_crossover:
            direction = SignalDirection.LONG
            # LONG crossover must be in oversold zone and RSI < rsi_long_filter.
            if k_curr >= self._oversold_zone or rsi_curr >= self._rsi_long_filter:
                logger.debug(
                    "LONG crossover failed filter conditions",
                    symbol=symbol,
                    k_curr=k_curr,
                    oversold_zone=self._oversold_zone,
                    rsi_curr=rsi_curr,
                    rsi_long_filter=self._rsi_long_filter,
                )
                return None
        elif short_crossover:
            direction = SignalDirection.SHORT
            # SHORT crossover must be in overbought zone and RSI > rsi_short_filter.
            if k_curr <= self._overbought_zone or rsi_curr <= self._rsi_short_filter:
                logger.debug(
                    "SHORT crossover failed filter conditions",
                    symbol=symbol,
                    k_curr=k_curr,
                    overbought_zone=self._overbought_zone,
                    rsi_curr=rsi_curr,
                    rsi_short_filter=self._rsi_short_filter,
                )
                return None
        else:
            logger.debug(
                "No crossover detected",
                symbol=symbol,
                k_prev=k_prev,
                k_curr=k_curr,
                d_prev=d_prev,
                d_curr=d_curr,
            )
            return None

        # Determine signal type: EXIT if direction opposes current position.
        signal_type = SignalType.ENTRY
        if (
            current_position is not None
            and current_position.quantity != 0
            and (
                (direction == SignalDirection.LONG and current_position.quantity < 0)
                or (direction == SignalDirection.SHORT and current_position.quantity > 0)
            )
        ):
            signal_type = SignalType.EXIT

        # Compute signal strength and confidence from K-D divergence.
        k_d_divergence = abs(k_curr - d_curr)

        # Strength: STRONG > 10, MODERATE > 5, else WEAK.
        if k_d_divergence > 10:
            strength = SignalStrength.STRONG
        elif k_d_divergence > 5:
            strength = SignalStrength.MODERATE
        else:
            strength = SignalStrength.WEAK

        # Confidence: ratio of divergence to 20 (max typical divergence), clamped.
        confidence = min(k_d_divergence / 20.0, 1.0)
        confidence = max(0.0, confidence)

        # Build indicators_used dict.
        indicators_used = {
            "k": float(k_curr),
            "d": float(d_curr),
            "rsi": float(rsi_curr),
        }

        logger.info(
            "Stochastic momentum signal detected",
            symbol=symbol,
            direction=direction.value,
            signal_type=signal_type.value,
            strength=strength.value,
            confidence=confidence,
            k_d_divergence=k_d_divergence,
            rsi_curr=rsi_curr,
            correlation_id=correlation_id,
        )

        # Build and return the signal.
        signal = build_signal(
            strategy_id=self.strategy_id,
            deployment_id=self._deployment_id,
            symbol=symbol,
            direction=direction,
            signal_type=signal_type,
            strength=strength,
            confidence=confidence,
            indicators_used=indicators_used,
            bar_timestamp=candles[-1].timestamp,
            correlation_id=correlation_id,
            metadata={
                "k_value": float(k_curr),
                "d_value": float(d_curr),
                "k_d_divergence": float(k_d_divergence),
                "rsi_value": float(rsi_curr),
                "crossover_type": ("k_above_d" if long_crossover else "k_below_d"),
                "zone": ("oversold" if long_crossover else "overbought"),
            },
        )

        return signal
