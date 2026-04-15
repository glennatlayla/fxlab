"""
Composite Signal strategy — meta-strategy aggregating multiple sub-strategies.

Responsibilities:
- Aggregate signals from multiple sub-strategies with configurable weightings.
- Apply a quorum requirement: signal only if minimum number of sub-strategies agree.
- Filter signals by minimum confidence threshold.
- Determine majority direction by weighted voting of sub-strategy directions.
- Declare required indicators by aggregating and deduplicating sub-strategy requests.
- Return composite signal with metadata listing constituent sub-strategy IDs.

Does NOT:
- Manage positions or execute trades (service layer responsibility).
- Evaluate risk gates (service layer responsibility).
- Persist signals (repository layer responsibility).
- Implement individual trading strategies (delegated to sub-strategies).

Dependencies:
- libs.contracts.interfaces.signal_strategy: SignalStrategyInterface
- libs.contracts.market_data: Candle
- libs.contracts.indicator: IndicatorRequest, IndicatorResult
- libs.contracts.execution: PositionSnapshot
- libs.contracts.signal: Signal, SignalDirection, SignalStrength, SignalType
- services.worker.strategies._base: build_signal
- structlog: Debug logging (injected via get_logger)

Error conditions:
- Returns None if fewer than quorum sub-strategies produce signals.
- Returns None if weighted confidence falls below min_confidence threshold.
- Propagates any exceptions from sub-strategies to caller.

Example:
    sub_strategies = [
        BollingerBandBreakoutStrategy(...),
        StochasticMomentumStrategy(...),
        MovingAverageCrossoverStrategy(...),
    ]
    strategy = CompositeSignalStrategy(
        deployment_id="deploy-001",
        sub_strategies=sub_strategies,
        quorum=2,
        min_confidence=0.5,
    )
    # Signal only if at least 2 sub-strategies agree with confidence >= 0.5
    requests = strategy.required_indicators()
    # Returns deduplicated union of all sub-strategy indicators
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from libs.contracts.indicator import IndicatorRequest, IndicatorResult
from libs.contracts.interfaces.signal_strategy import SignalStrategyInterface
from libs.contracts.signal import (
    Signal,
    SignalDirection,
    SignalType,
)
from services.worker.strategies._base import build_signal

if TYPE_CHECKING:
    from libs.contracts.execution import PositionSnapshot
    from libs.contracts.market_data import Candle

logger = structlog.get_logger(__name__)


class CompositeSignalStrategy(SignalStrategyInterface):
    """
    Meta-strategy that aggregates signals from multiple sub-strategies.

    Evaluates multiple trading strategies in parallel and produces a composite
    signal only when a configurable quorum of sub-strategies agree on direction
    with sufficient confidence. Signals are weighted equally by default but can
    use custom weights to prioritize certain sub-strategies.

    Responsibilities:
    - Invoke all sub-strategies in parallel on the same market data.
    - Collect non-None signals from sub-strategies.
    - Apply quorum rule: require minimum number of agreeing signals.
    - Determine majority direction by weighted voting.
    - Filter constituent signals by majority direction.
    - Compute weighted average confidence.
    - Apply minimum confidence threshold.
    - Determine signal strength from strongest sub-signal.
    - Classify signals as ENTRY or EXIT based on current position.
    - Aggregate required indicators from all sub-strategies.
    - Return composite signal with sub-strategy metadata.

    Does NOT:
    - Execute trades or manage positions.
    - Evaluate risk gates.
    - Persist signals.
    - Implement individual trading logic.

    Dependencies:
    - Injected: deployment_id, sub_strategies, weights (optional), quorum, min_confidence.
    - Computed: majority direction via weighted voting, aggregate confidence.
    - External: sub-strategy interfaces.

    Raises:
    - ValueError: If sub_strategies is empty.
    - ValueError: If quorum > len(sub_strategies).
    - ValueError: If quorum < 1.
    - ValueError: If any weight is <= 0.
    - ValueError: If min_confidence not in [0.0, 1.0].

    Example:
        sub_strategies = [
            BollingerBandBreakoutStrategy(deployment_id="d1", ...),
            StochasticMomentumStrategy(deployment_id="d1", ...),
            MovingAverageCrossoverStrategy(deployment_id="d1", ...),
        ]
        strategy = CompositeSignalStrategy(
            deployment_id="d1",
            sub_strategies=sub_strategies,
            weights={"bollinger-breakout": 1.5, "stochastic-momentum": 1.0, "ma-crossover": 1.0},
            quorum=2,
            min_confidence=0.5,
        )
        signal = strategy.evaluate(
            "AAPL", candles, indicators, None, correlation_id="c1"
        )
        if signal:
            # Composite signal with metadata listing all voting sub-strategies
            print(f"Sub-strategies in vote: {signal.metadata['sub_strategy_ids']}")
    """

    def __init__(
        self,
        *,
        deployment_id: str,
        sub_strategies: list[SignalStrategyInterface],
        weights: dict[str, float] | None = None,
        quorum: int = 2,
        min_confidence: float = 0.5,
        supported_symbols: list[str] | None = None,
    ) -> None:
        """
        Initialize the Composite Signal strategy.

        Args:
            deployment_id: Deployment context identifier (required).
            sub_strategies: List of SignalStrategyInterface instances to aggregate.
                Must contain at least one strategy.
            weights: Optional dict mapping strategy_id to weight (default: equal weight).
                Used for weighted voting on direction and confidence. If not provided,
                all sub-strategies are weighted equally (1.0).
            quorum: Minimum number of sub-strategies that must agree to produce signal
                (default: 2). Must satisfy 1 <= quorum <= len(sub_strategies).
            min_confidence: Minimum weighted average confidence to produce signal
                (default: 0.5). Must be in [0.0, 1.0].
            supported_symbols: List of symbols this strategy can trade (default: empty = all).

        Raises:
            ValueError: If sub_strategies is empty.
            ValueError: If quorum < 1 or quorum > len(sub_strategies).
            ValueError: If min_confidence not in [0.0, 1.0].
            ValueError: If any weight is <= 0.

        Example:
            strategy = CompositeSignalStrategy(
                deployment_id="deploy-001",
                sub_strategies=[strat1, strat2, strat3],
                weights={"strat-a": 1.5, "strat-b": 1.0},
                quorum=2,
                min_confidence=0.6,
            )
        """
        if not sub_strategies:
            raise ValueError("sub_strategies must not be empty")
        if quorum < 1 or quorum > len(sub_strategies):
            raise ValueError(
                f"quorum ({quorum}) must satisfy "
                f"1 <= quorum <= len(sub_strategies) ({len(sub_strategies)})"
            )
        if not (0.0 <= min_confidence <= 1.0):
            raise ValueError(f"min_confidence ({min_confidence}) must be in [0.0, 1.0]")

        # Validate and normalize weights.
        normalized_weights: dict[str, float] = {}
        if weights:
            for strat_id, weight in weights.items():
                if weight <= 0:
                    raise ValueError(f"weight for {strat_id} ({weight}) must be > 0")
                normalized_weights[strat_id] = weight
        else:
            # Equal weight for all sub-strategies.
            for strat in sub_strategies:
                normalized_weights[strat.strategy_id] = 1.0

        self._deployment_id = deployment_id
        self._sub_strategies = sub_strategies
        self._weights = normalized_weights
        self._quorum = quorum
        self._min_confidence = min_confidence
        self._supported_symbols = supported_symbols or []

    @property
    def strategy_id(self) -> str:
        """Unique identifier for this strategy."""
        return "composite-signal"

    @property
    def name(self) -> str:
        """Human-readable name for this strategy."""
        return "Composite Signal"

    @property
    def supported_symbols(self) -> list[str]:
        """List of symbols this strategy can trade (empty = all)."""
        return self._supported_symbols

    def required_indicators(self) -> list[IndicatorRequest]:
        """
        Declare which indicators this strategy needs computed.

        Aggregates required indicators from all sub-strategies and deduplicates
        by (indicator_name, params) to avoid redundant computation.

        Returns:
            Deduplicated list of IndicatorRequest objects from all sub-strategies.

        Example:
            reqs = strategy.required_indicators()
            # Returns union of all sub-strategy indicator requirements,
            # with duplicates removed.
        """
        # Use a set to track (indicator_name, params tuple) for deduplication.
        seen = set()
        deduplicated_requests = []

        for sub_strat in self._sub_strategies:
            for request in sub_strat.required_indicators():
                # Convert params to a hashable tuple of (key, value) pairs.
                params_tuple = tuple(sorted(request.params.items()))
                key = (request.indicator_name, params_tuple)

                if key not in seen:
                    seen.add(key)
                    deduplicated_requests.append(request)

        return deduplicated_requests

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
        Evaluate market data via all sub-strategies and produce composite signal.

        Calls evaluate on each sub-strategy, collects non-None signals, applies
        quorum rule, determines majority direction via weighted voting, and filters
        to signals matching the majority. Returns None if quorum is not met or
        weighted confidence falls below threshold.

        Args:
            symbol: Ticker symbol being evaluated (e.g. "AAPL").
            candles: Recent candle data for the symbol.
            indicators: Pre-computed indicator results (shared across all sub-strategies).
            current_position: Current position snapshot for this symbol (None if flat).
            correlation_id: Request correlation ID for tracing (keyword-only).

        Returns:
            A composite Signal if quorum is met and confidence threshold passed,
            None otherwise.

        Raises:
            Any exception raised by a sub-strategy's evaluate method.

        Example:
            signal = strategy.evaluate(
                "AAPL", candles, indicators, None, correlation_id="c1"
            )
            if signal:
                # Composite signal with sub-strategy voting data in metadata
                sub_ids = signal.metadata["sub_strategy_ids"]
                voting_weights = signal.metadata["voting_weights"]
                print(f"Voted by: {sub_ids}")
        """
        logger.debug(
            "Evaluating composite signal with sub-strategies",
            symbol=symbol,
            candle_count=len(candles),
            num_sub_strategies=len(self._sub_strategies),
            quorum=self._quorum,
            correlation_id=correlation_id,
        )

        # Evaluate all sub-strategies in parallel.
        sub_signals = []
        for sub_strat in self._sub_strategies:
            try:
                sub_signal = sub_strat.evaluate(
                    symbol,
                    candles,
                    indicators,
                    current_position,
                    correlation_id=correlation_id,
                )
                if sub_signal is not None:
                    sub_signals.append(sub_signal)
                    logger.debug(
                        "Sub-strategy produced signal",
                        strategy_id=sub_strat.strategy_id,
                        direction=sub_signal.direction.value,
                        confidence=sub_signal.confidence,
                    )
            except Exception as e:
                logger.error(
                    "Sub-strategy evaluation failed",
                    strategy_id=sub_strat.strategy_id,
                    error=str(e),
                    correlation_id=correlation_id,
                )
                raise

        # Apply quorum rule.
        if len(sub_signals) < self._quorum:
            logger.debug(
                "Quorum not met",
                symbol=symbol,
                num_signals=len(sub_signals),
                quorum=self._quorum,
            )
            return None

        # Determine majority direction via weighted voting.
        direction_votes: dict[SignalDirection, float] = {
            SignalDirection.LONG: 0.0,
            SignalDirection.SHORT: 0.0,
            SignalDirection.FLAT: 0.0,
        }

        for sub_signal in sub_signals:
            weight = self._weights.get(sub_signal.strategy_id, 1.0)
            direction_votes[sub_signal.direction] += weight

        # Find direction(s) with maximum votes.
        max_votes = max(direction_votes.values())
        majority_directions = [d for d, v in direction_votes.items() if v == max_votes]

        # If tie, prefer LONG > SHORT > FLAT for consistent behavior.
        if len(majority_directions) > 1:
            if SignalDirection.LONG in majority_directions:
                majority_direction = SignalDirection.LONG
            elif SignalDirection.SHORT in majority_directions:
                majority_direction = SignalDirection.SHORT
            else:
                majority_direction = SignalDirection.FLAT
        else:
            majority_direction = majority_directions[0]

        logger.debug(
            "Majority direction determined",
            symbol=symbol,
            direction=majority_direction.value,
            direction_votes=direction_votes,
        )

        # Filter to signals matching majority direction.
        majority_signals = [s for s in sub_signals if s.direction == majority_direction]

        if not majority_signals:
            logger.debug(
                "No signals match majority direction",
                symbol=symbol,
                majority_direction=majority_direction.value,
            )
            return None

        # Compute weighted average confidence from majority signals.
        total_weight = 0.0
        weighted_confidence = 0.0
        voting_weights = {}

        for sub_signal in majority_signals:
            weight = self._weights.get(sub_signal.strategy_id, 1.0)
            weighted_confidence += sub_signal.confidence * weight
            total_weight += weight
            voting_weights[sub_signal.strategy_id] = weight

        avg_confidence = weighted_confidence / total_weight if total_weight > 0 else 0.0

        # Apply confidence threshold.
        if avg_confidence < self._min_confidence:
            logger.debug(
                "Weighted confidence below threshold",
                symbol=symbol,
                avg_confidence=avg_confidence,
                min_confidence=self._min_confidence,
            )
            return None

        # Determine signal strength from strongest sub-signal.
        strength_order = {"strong": 3, "moderate": 2, "weak": 1}
        strongest_signal = max(
            majority_signals,
            key=lambda s: strength_order.get(s.strength.value, 0),
        )
        strength = strongest_signal.strength

        # Determine signal type: EXIT if direction opposes current position.
        signal_type = SignalType.ENTRY
        if (
            current_position is not None
            and current_position.quantity != 0
            and (
                (majority_direction == SignalDirection.LONG and current_position.quantity < 0)
                or (majority_direction == SignalDirection.SHORT and current_position.quantity > 0)
            )
        ):
            signal_type = SignalType.EXIT

        # Build indicators_used from majority signals (union of keys).
        indicators_used = {}
        for sub_signal in majority_signals:
            indicators_used.update(sub_signal.indicators_used)

        # Build metadata with sub-strategy voting information.
        sub_strategy_ids = [s.strategy_id for s in majority_signals]
        metadata = {
            "num_sub_signals": len(sub_signals),
            "num_majority_signals": len(majority_signals),
            "sub_strategy_ids": sub_strategy_ids,
            "voting_weights": voting_weights,
            "direction_votes": {d.value: v for d, v in direction_votes.items()},
            "avg_confidence": avg_confidence,
        }

        logger.info(
            "Composite signal generated",
            symbol=symbol,
            direction=majority_direction.value,
            signal_type=signal_type.value,
            strength=strength.value,
            avg_confidence=avg_confidence,
            num_voting_strategies=len(majority_signals),
            sub_strategy_ids=sub_strategy_ids,
            correlation_id=correlation_id,
        )

        # Build and return the composite signal.
        signal = build_signal(
            strategy_id=self.strategy_id,
            deployment_id=self._deployment_id,
            symbol=symbol,
            direction=majority_direction,
            signal_type=signal_type,
            strength=strength,
            confidence=avg_confidence,
            indicators_used=indicators_used,
            bar_timestamp=candles[-1].timestamp,
            correlation_id=correlation_id,
            metadata=metadata,
        )

        return signal
