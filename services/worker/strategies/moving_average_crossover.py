"""
Moving Average Crossover signal strategy — golden cross and death cross detection.

Responsibilities:
- Detect when a fast-period moving average crosses above (golden cross → LONG)
  or below (death cross → SHORT) a slow-period moving average.
- Support both SMA and EMA via configurable use_ema flag.
- Classify signal strength and confidence based on MA spread percentage.
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
- structlog: Debug logging (injected via get_logger)

Error conditions:
- Returns None if required indicators are missing or contain insufficient data.
- Returns None if the last two values of either MA are NaN.
- Returns None if no crossover is detected between the last two bars.

Example:
    strategy = MovingAverageCrossoverStrategy(
        deployment_id="deploy-001",
        fast_period=20,
        slow_period=50,
        use_ema=False,
        strong_threshold_pct=2.0,
        moderate_threshold_pct=0.5,
    )
    # Required indicators: SMA_20, SMA_50
    requests = strategy.required_indicators()
    # In evaluate, a golden cross (fast[-1] > slow[-1] and fast[-2] <= slow[-2])
    # generates a LONG ENTRY signal with strength and confidence based on spread.
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


class MovingAverageCrossoverStrategy(SignalStrategyInterface):
    """
    Signal strategy that detects moving average crossovers.

    Generates LONG signals on golden crosses (fast MA crosses above slow MA)
    and SHORT signals on death crosses (fast MA crosses below slow MA).
    Signal strength and confidence are computed from the percentage spread
    between the two moving averages at the crossover point.

    Responsibilities:
    - Detect golden and death crosses between fast and slow MAs.
    - Compute signal strength and confidence based on MA spread.
    - Classify signals as ENTRY or EXIT based on current position.
    - Declare required indicators (SMA or EMA pairs) via required_indicators().
    - Return None if insufficient data or no valid crossover.

    Does NOT:
    - Execute trades or manage positions.
    - Evaluate risk gates.
    - Persist signals.

    Dependencies:
    - Injected: deployment_id (set in constructor).
    - Computed: fast_period, slow_period, use_ema, thresholds.
    - External: numpy for array operations.

    Raises:
    - ValueError: If fast_period >= slow_period.
    - ValueError: If thresholds are non-positive.

    Example:
        strategy = MovingAverageCrossoverStrategy(
            deployment_id="d1",
            fast_period=20,
            slow_period=50,
            use_ema=False,
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
        fast_period: int = 20,
        slow_period: int = 50,
        use_ema: bool = False,
        strong_threshold_pct: float = 2.0,
        moderate_threshold_pct: float = 0.5,
        supported_symbols: list[str] | None = None,
    ) -> None:
        """
        Initialize the Moving Average Crossover strategy.

        Args:
            deployment_id: Deployment context identifier (required).
            fast_period: Period for fast-moving average (default: 20).
            slow_period: Period for slow-moving average (default: 50).
            use_ema: If True, use EMA; if False (default), use SMA.
            strong_threshold_pct: MA spread threshold for STRONG strength (default: 2.0).
                Signals with spread >= this pct are STRONG.
            moderate_threshold_pct: MA spread threshold for MODERATE strength (default: 0.5).
                Signals with spread >= this pct are MODERATE; below are WEAK.
            supported_symbols: List of symbols this strategy can trade (default: empty = all).

        Raises:
            ValueError: If fast_period >= slow_period.
            ValueError: If thresholds are not positive.

        Example:
            strategy = MovingAverageCrossoverStrategy(
                deployment_id="deploy-001",
                fast_period=10,
                slow_period=30,
                use_ema=True,
            )
        """
        if fast_period >= slow_period:
            raise ValueError(
                f"fast_period ({fast_period}) must be less than slow_period ({slow_period})"
            )
        if strong_threshold_pct <= 0 or moderate_threshold_pct <= 0:
            raise ValueError("Thresholds must be positive")

        self._deployment_id = deployment_id
        self._fast_period = fast_period
        self._slow_period = slow_period
        self._use_ema = use_ema
        self._strong_threshold_pct = strong_threshold_pct
        self._moderate_threshold_pct = moderate_threshold_pct
        self._supported_symbols = supported_symbols or []

    @property
    def strategy_id(self) -> str:
        """Unique identifier for this strategy."""
        return "ma-crossover"

    @property
    def name(self) -> str:
        """Human-readable name for this strategy."""
        return "Moving Average Crossover"

    @property
    def supported_symbols(self) -> list[str]:
        """List of symbols this strategy can trade (empty = all)."""
        return self._supported_symbols

    def required_indicators(self) -> list[IndicatorRequest]:
        """
        Declare which indicators this strategy needs computed.

        Returns:
            List of two IndicatorRequest objects: one for fast period,
            one for slow period. Both use SMA or EMA based on use_ema flag.

        Example:
            reqs = strategy.required_indicators()
            # [
            #   IndicatorRequest(indicator_name="SMA", params={"period": 20}),
            #   IndicatorRequest(indicator_name="SMA", params={"period": 50}),
            # ]
        """
        indicator_name = "EMA" if self._use_ema else "SMA"
        return [
            IndicatorRequest(
                indicator_name=indicator_name,
                params={"period": self._fast_period},
            ),
            IndicatorRequest(
                indicator_name=indicator_name,
                params={"period": self._slow_period},
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

        Detects golden crosses (fast > slow after fast <= slow) for LONG signals
        and death crosses (fast < slow after fast >= slow) for SHORT signals.
        Returns None if insufficient data, missing indicators, or no crossover.

        Args:
            symbol: Ticker symbol being evaluated (e.g. "AAPL").
            candles: Recent candle data for the symbol.
            indicators: Pre-computed indicator results keyed by indicator name
                (e.g. "SMA_20", "SMA_50" or "EMA_20", "EMA_50").
            current_position: Current position snapshot for this symbol (None if flat).
            correlation_id: Request correlation ID for tracing (keyword-only).

        Returns:
            A Signal if a valid crossover is detected, None otherwise.

        Raises:
            KeyError: If required indicators (SMA_* or EMA_*) are not in indicators dict.

        Example:
            signal = strategy.evaluate(
                "AAPL", candles, indicators, None, correlation_id="c1"
            )
            if signal:
                # signal.direction is LONG or SHORT
                # signal.signal_type is ENTRY or EXIT
        """
        logger.debug(
            "Evaluating MA crossover",
            symbol=symbol,
            candle_count=len(candles),
            has_position=current_position is not None,
            correlation_id=correlation_id,
        )

        # Build indicator keys based on whether we use EMA or SMA.
        ma_type = "EMA" if self._use_ema else "SMA"
        fast_key = f"{ma_type}_{self._fast_period}"
        slow_key = f"{ma_type}_{self._slow_period}"

        # Retrieve required indicator results.
        try:
            fast_result = indicators[fast_key]
            slow_result = indicators[slow_key]
        except KeyError as e:
            logger.warning(
                "Missing required indicators",
                symbol=symbol,
                missing=str(e),
                available=list(indicators.keys()),
            )
            return None

        fast_values = fast_result.values
        slow_values = slow_result.values

        # Check that we have at least 2 valid data points (to detect crossover).
        if len(fast_values) < 2 or len(slow_values) < 2:
            logger.debug(
                "Insufficient indicator data",
                symbol=symbol,
                fast_len=len(fast_values),
                slow_len=len(slow_values),
            )
            return None

        # Extract the last two values of each MA.
        fast_prev = fast_values[-2]
        fast_curr = fast_values[-1]
        slow_prev = slow_values[-2]
        slow_curr = slow_values[-1]

        # If any value is NaN, we cannot determine a valid signal.
        if (
            math.isnan(fast_prev)
            or math.isnan(fast_curr)
            or math.isnan(slow_prev)
            or math.isnan(slow_curr)
        ):
            logger.debug(
                "NaN values in indicator data",
                symbol=symbol,
                fast_prev=fast_prev,
                fast_curr=fast_curr,
                slow_prev=slow_prev,
                slow_curr=slow_curr,
            )
            return None

        # Detect crossover: golden cross (fast crosses above slow).
        golden_cross = fast_prev <= slow_prev and fast_curr > slow_curr
        # Detect crossover: death cross (fast crosses below slow).
        death_cross = fast_prev >= slow_prev and fast_curr < slow_curr

        if not (golden_cross or death_cross):
            logger.debug(
                "No crossover detected",
                symbol=symbol,
                fast_prev=fast_prev,
                fast_curr=fast_curr,
                slow_prev=slow_prev,
                slow_curr=slow_curr,
            )
            return None

        # Determine signal direction and type.
        direction = SignalDirection.LONG if golden_cross else SignalDirection.SHORT

        # Compute signal type: EXIT if the direction opposes the current position.
        signal_type = SignalType.ENTRY
        # If we're holding a position and the signal direction opposes it, it's an EXIT.
        if (
            current_position is not None
            and current_position.quantity != 0
            and (
                (direction == SignalDirection.LONG and current_position.quantity < 0)
                or (direction == SignalDirection.SHORT and current_position.quantity > 0)
            )
        ):
            signal_type = SignalType.EXIT

        # Compute signal strength and confidence from MA spread.
        spread = abs(fast_curr - slow_curr)
        spread_pct = (spread / slow_curr) * 100.0 if slow_curr != 0 else 0.0

        if spread_pct >= self._strong_threshold_pct:
            strength = SignalStrength.STRONG
        elif spread_pct >= self._moderate_threshold_pct:
            strength = SignalStrength.MODERATE
        else:
            strength = SignalStrength.WEAK

        # Confidence: ratio of spread to strong threshold, clamped to [0.0, 1.0].
        confidence = (
            min(spread_pct / self._strong_threshold_pct, 1.0)
            if self._strong_threshold_pct > 0
            else 0.0
        )
        confidence = max(0.0, confidence)

        # Build indicators_used dict with the MA values at signal time.
        indicators_used = {
            fast_key: float(fast_curr),
            slow_key: float(slow_curr),
        }

        logger.info(
            "MA crossover signal detected",
            symbol=symbol,
            direction=direction.value,
            signal_type=signal_type.value,
            strength=strength.value,
            confidence=confidence,
            spread_pct=spread_pct,
            correlation_id=correlation_id,
        )

        # Use build_signal helper to construct the Signal object.
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
                "fast_ma": float(fast_curr),
                "slow_ma": float(slow_curr),
                "spread_pct": spread_pct,
                "crossover_type": "golden_cross" if golden_cross else "death_cross",
            },
        )

        return signal
