"""
MACD Momentum signal strategy — histogram-based momentum and crossover detection.

Responsibilities:
- Detect MACD histogram turning positive (from ≤0 to >0) for LONG signals.
- Detect MACD histogram turning negative (from ≥0 to <0) for SHORT signals.
- Classify signal strength based on magnitude of histogram value.
- Classify confidence based on histogram magnitude relative to strong threshold.
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
- Returns None if required MACD indicator is missing.
- Returns None if histogram contains fewer than 2 valid data points.
- Returns None if either of the last two histogram values is NaN.
- Returns None if no histogram momentum change is detected.

Example:
    strategy = MACDMomentumStrategy(
        deployment_id="deploy-001",
        fast_period=12,
        slow_period=26,
        signal_period=9,
        strong_histogram=1.0,
        moderate_histogram=0.3,
    )
    # Required indicators: MACD with components (macd_line, signal_line, histogram)
    requests = strategy.required_indicators()
    # In evaluate, histogram turning positive (after being ≤0) generates LONG ENTRY.
    # Histogram turning negative (after being ≥0) generates SHORT ENTRY.
    # Strength depends on absolute histogram magnitude.
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


class MACDMomentumStrategy(SignalStrategyInterface):
    """
    Signal strategy that detects MACD histogram momentum changes.

    Generates LONG signals when the MACD histogram turns positive
    (transitions from ≤0 to >0) and SHORT signals when it turns negative
    (transitions from ≥0 to <0). Signal strength and confidence are
    determined by the absolute magnitude of the histogram value at the
    signal time, compared against configurable thresholds.

    Responsibilities:
    - Detect histogram momentum changes (positive/negative transitions).
    - Compute signal strength and confidence based on histogram magnitude.
    - Classify signals as ENTRY or EXIT based on current position.
    - Declare required indicators (MACD) via required_indicators().
    - Return None if insufficient data or no valid momentum change.

    Does NOT:
    - Execute trades or manage positions.
    - Evaluate risk gates.
    - Persist signals.

    Dependencies:
    - Injected: deployment_id (set in constructor).
    - Computed: fast_period, slow_period, signal_period, thresholds.
    - External: numpy for array operations.

    Raises:
    - ValueError: If fast_period >= slow_period.
    - ValueError: If thresholds are non-positive.

    Example:
        strategy = MACDMomentumStrategy(
            deployment_id="d1",
            fast_period=12,
            slow_period=26,
            signal_period=9,
        )
        signal = strategy.evaluate(
            "AAPL", candles, indicators, None, correlation_id="c1"
        )
        if signal:
            # signal.direction is LONG (histogram positive) or SHORT (histogram negative)
            # signal.signal_type is ENTRY or EXIT
    """

    def __init__(
        self,
        *,
        deployment_id: str,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
        strong_histogram: float = 1.0,
        moderate_histogram: float = 0.3,
        supported_symbols: list[str] | None = None,
    ) -> None:
        """
        Initialize the MACD Momentum strategy.

        Args:
            deployment_id: Deployment context identifier (required).
            fast_period: Period for fast EMA in MACD (default: 12).
            slow_period: Period for slow EMA in MACD (default: 26).
            signal_period: Period for signal line EMA (default: 9).
            strong_histogram: Absolute histogram threshold for STRONG strength (default: 1.0).
                Signals with |histogram| >= this value are STRONG.
            moderate_histogram: Absolute histogram threshold for MODERATE strength (default: 0.3).
                Signals with |histogram| >= this value are MODERATE; below are WEAK.
            supported_symbols: List of symbols this strategy can trade (default: empty = all).

        Raises:
            ValueError: If fast_period >= slow_period.
            ValueError: If thresholds are not positive.

        Example:
            strategy = MACDMomentumStrategy(
                deployment_id="deploy-001",
                fast_period=12,
                slow_period=26,
                signal_period=9,
                strong_histogram=1.0,
            )
        """
        if fast_period >= slow_period:
            raise ValueError(
                f"fast_period ({fast_period}) must be less than slow_period ({slow_period})"
            )
        if strong_histogram <= 0 or moderate_histogram <= 0:
            raise ValueError("Thresholds must be positive")

        self._deployment_id = deployment_id
        self._fast_period = fast_period
        self._slow_period = slow_period
        self._signal_period = signal_period
        self._strong_histogram = strong_histogram
        self._moderate_histogram = moderate_histogram
        self._supported_symbols = supported_symbols or []

    @property
    def strategy_id(self) -> str:
        """Unique identifier for this strategy."""
        return "macd-momentum"

    @property
    def name(self) -> str:
        """Human-readable name for this strategy."""
        return "MACD Momentum"

    @property
    def supported_symbols(self) -> list[str]:
        """List of symbols this strategy can trade (empty = all)."""
        return self._supported_symbols

    def required_indicators(self) -> list[IndicatorRequest]:
        """
        Declare which indicators this strategy needs computed.

        Returns:
            List with a single IndicatorRequest for MACD with the configured
            fast_period, slow_period, and signal_period parameters.

        Example:
            reqs = strategy.required_indicators()
            # [
            #   IndicatorRequest(
            #       indicator_name="MACD",
            #       params={"fast_period": 12, "slow_period": 26, "signal_period": 9}
            #   )
            # ]
        """
        return [
            IndicatorRequest(
                indicator_name="MACD",
                params={
                    "fast_period": self._fast_period,
                    "slow_period": self._slow_period,
                    "signal_period": self._signal_period,
                },
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

        Detects MACD histogram momentum changes:
        - LONG when histogram transitions from ≤0 to >0 (positive momentum).
        - SHORT when histogram transitions from ≥0 to <0 (negative momentum).
        Returns None if insufficient data, missing indicators, or no momentum change.

        Args:
            symbol: Ticker symbol being evaluated (e.g. "AAPL").
            candles: Recent candle data for the symbol.
            indicators: Pre-computed indicator results keyed by indicator name
                (expected key: "MACD" with components: "macd_line", "signal_line", "histogram").
            current_position: Current position snapshot for this symbol (None if flat).
            correlation_id: Request correlation ID for tracing (keyword-only).

        Returns:
            A Signal if a valid histogram momentum change is detected, None otherwise.

        Raises:
            KeyError: If the required MACD indicator is not in indicators dict.

        Example:
            signal = strategy.evaluate(
                "AAPL", candles, indicators, None, correlation_id="c1"
            )
            if signal:
                # signal.direction is LONG or SHORT
                # signal.signal_type is ENTRY or EXIT
        """
        logger.debug(
            "Evaluating MACD momentum",
            symbol=symbol,
            candle_count=len(candles),
            has_position=current_position is not None,
            correlation_id=correlation_id,
        )

        # Retrieve the MACD result (multi-output indicator).
        try:
            macd_result = indicators["MACD"]
        except KeyError as e:
            logger.warning(
                "Missing required MACD indicator",
                symbol=symbol,
                missing=str(e),
                available=list(indicators.keys()),
            )
            return None

        # Extract the histogram component.
        try:
            histogram = macd_result.get_component("histogram")
        except KeyError as e:
            logger.warning(
                "MACD result missing histogram component",
                symbol=symbol,
                error=str(e),
                available=list(macd_result.components.keys()),
            )
            return None

        # Check that we have at least 2 valid histogram values (to detect momentum change).
        if len(histogram) < 2:
            logger.debug(
                "Insufficient MACD histogram data",
                symbol=symbol,
                histogram_len=len(histogram),
            )
            return None

        # Extract the last two histogram values.
        hist_prev = histogram[-2]
        hist_curr = histogram[-1]

        # If either value is NaN, we cannot determine a valid signal.
        if math.isnan(hist_prev) or math.isnan(hist_curr):
            logger.debug(
                "NaN values in MACD histogram",
                symbol=symbol,
                hist_prev=hist_prev,
                hist_curr=hist_curr,
            )
            return None

        # Detect histogram turning positive: hist_prev <= 0 AND hist_curr > 0.
        turning_positive = hist_prev <= 0 and hist_curr > 0
        # Detect histogram turning negative: hist_prev >= 0 AND hist_curr < 0.
        turning_negative = hist_prev >= 0 and hist_curr < 0

        if not (turning_positive or turning_negative):
            logger.debug(
                "No MACD histogram momentum change detected",
                symbol=symbol,
                hist_prev=hist_prev,
                hist_curr=hist_curr,
            )
            return None

        # Determine signal direction and type.
        direction = SignalDirection.LONG if turning_positive else SignalDirection.SHORT

        # Compute signal type: EXIT if the direction opposes the current position.
        signal_type = SignalType.ENTRY
        # If holding a position and signal direction opposes it, it's an EXIT.
        if (
            current_position is not None
            and current_position.quantity != 0
            and (
                (direction == SignalDirection.LONG and current_position.quantity < 0)
                or (direction == SignalDirection.SHORT and current_position.quantity > 0)
            )
        ):
            signal_type = SignalType.EXIT

        # Compute signal strength and confidence from absolute histogram magnitude.
        abs_histogram = abs(hist_curr)

        if abs_histogram >= self._strong_histogram:
            strength = SignalStrength.STRONG
        elif abs_histogram >= self._moderate_histogram:
            strength = SignalStrength.MODERATE
        else:
            strength = SignalStrength.WEAK

        # Confidence: ratio of abs_histogram to strong threshold, clamped to [0.0, 1.0].
        confidence = (
            min(abs_histogram / self._strong_histogram, 1.0) if self._strong_histogram > 0 else 0.0
        )
        confidence = max(0.0, confidence)

        # Extract additional components for indicators_used.
        try:
            macd_line = macd_result.get_component("macd_line")
            signal_line = macd_result.get_component("signal_line")
            macd_line_value = float(macd_line[-1])
            signal_line_value = float(signal_line[-1])
        except KeyError:
            # If components are missing, use NaN placeholders
            macd_line_value = float("nan")
            signal_line_value = float("nan")

        # Build indicators_used dict with MACD components at signal time.
        indicators_used = {
            "macd_line": macd_line_value,
            "signal_line": signal_line_value,
            "histogram": float(hist_curr),
        }

        logger.info(
            "MACD momentum signal detected",
            symbol=symbol,
            direction=direction.value,
            signal_type=signal_type.value,
            strength=strength.value,
            confidence=confidence,
            histogram=hist_curr,
            abs_histogram=abs_histogram,
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
                "histogram_previous": float(hist_prev),
                "histogram_current": float(hist_curr),
                "momentum_type": "positive" if turning_positive else "negative",
                "macd_line": macd_line_value,
                "signal_line": signal_line_value,
            },
        )

        return signal
