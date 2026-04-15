"""
Data freshness validation service for market data staleness detection.

Responsibilities:
- Implement DataFreshnessGateInterface for checking candle staleness.
- Calculate candle age vs staleness thresholds.
- Apply interval-based and absolute cap logic.
- Return structured freshness check results with logging.
- Remain stateless and deterministic.

Does NOT:
- Persist data or maintain state across calls.
- Know about specific data feeds or providers.
- Make external calls (no I/O, pure computation).

Dependencies (injected or imported):
- datetime: standard library for UTC time.
- structlog: logging for debugging and warnings.
- libs.contracts: DataFreshnessPolicy, FreshnessCheckResult, Candle, INTERVAL_SECONDS.

Error conditions:
- All errors treated as data rejection (fail-safe).

Example:
    gate = DataFreshnessGate()
    policy = DataFreshnessPolicy(
        max_staleness_multiplier=3.0,
        absolute_max_staleness_seconds=600,
        action_on_stale="reject",
    )
    result = gate.check_freshness(candle, policy)
    if result.action == "accepted":
        signal = strategy.evaluate(...)
    else:
        logger.warning(f"Data staleness gate: {result.action}", extra={...})
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog

from libs.contracts.data_freshness import DataFreshnessPolicy, FreshnessCheckResult
from libs.contracts.interfaces.data_freshness_gate_interface import (
    DataFreshnessGateInterface,
)
from libs.contracts.market_data import INTERVAL_SECONDS

if TYPE_CHECKING:
    from libs.contracts.market_data import Candle

logger = structlog.get_logger(__name__)


class DataFreshnessGate(DataFreshnessGateInterface):
    """
    Stateless service for validating market data freshness.

    Checks if a candle's age exceeds the staleness threshold defined by a
    freshness policy. The threshold is the minimum of:
    1. Interval-based: INTERVAL_SECONDS[candle.interval] * policy.max_staleness_multiplier
    2. Absolute cap: policy.absolute_max_staleness_seconds

    All calculations use UTC time. The service is thread-safe and has no
    internal mutable state.

    Example:
        gate = DataFreshnessGate()
        policy = DataFreshnessPolicy()  # defaults: multiplier=3.0, max=600s
        result = gate.check_freshness(candle, policy)

        if result.is_fresh:
            logger.info("Candle is fresh", age_seconds=result.age_seconds)
        else:
            logger.warning("Candle is stale", age_seconds=result.age_seconds)
    """

    def check_freshness(self, candle: Candle, policy: DataFreshnessPolicy) -> FreshnessCheckResult:
        """
        Check if a candle is fresh according to the given policy.

        Calculates:
        1. Current UTC time (via _get_current_time).
        2. Candle age = now - candle.timestamp.
        3. Interval-based threshold = INTERVAL_SECONDS[candle.interval] * multiplier.
        4. Effective threshold = min(interval_threshold, absolute_max_staleness).
        5. Freshness = age <= threshold.
        6. Action = "accepted" if fresh, else policy.action_on_stale.

        Args:
            candle: The market data candle to check.
            policy: The freshness policy defining acceptable staleness.

        Returns:
            FreshnessCheckResult with all required fields.

        Example:
            now = datetime(2026, 4, 13, 15, 30, 0, tzinfo=timezone.utc)
            candle = Candle(
                symbol="AAPL",
                interval=CandleInterval.M1,
                ...,
                timestamp=datetime(2026, 4, 13, 15, 29, 30, tzinfo=timezone.utc),
            )
            policy = DataFreshnessPolicy()
            result = gate.check_freshness(candle, policy)
            # result.age_seconds == 30.0
            # result.max_allowed_seconds == 180.0
            # result.is_fresh == True
            # result.action == "accepted"
        """
        now = self._get_current_time()

        # Calculate age in seconds.
        age_timedelta = now - candle.timestamp
        age_seconds = age_timedelta.total_seconds()

        # Calculate interval-based threshold.
        interval_seconds = INTERVAL_SECONDS.get(candle.interval, 60)
        interval_threshold = interval_seconds * policy.max_staleness_multiplier

        # Apply absolute cap: use the smaller threshold.
        max_allowed_seconds = min(interval_threshold, float(policy.absolute_max_staleness_seconds))

        # Determine freshness.
        is_fresh = age_seconds <= max_allowed_seconds

        # Determine action based on freshness and policy.
        if is_fresh:
            action = "accepted"
        elif policy.action_on_stale == "reject":
            action = "rejected"
        else:  # policy.action_on_stale == "warn"
            action = "warned"

        result = FreshnessCheckResult(
            symbol=candle.symbol,
            candle_timestamp=candle.timestamp,
            checked_at=now,
            age_seconds=age_seconds,
            max_allowed_seconds=max_allowed_seconds,
            is_fresh=is_fresh,
            action=action,  # type: ignore[arg-type]
        )

        # Log the result at appropriate level.
        if is_fresh:
            logger.debug(
                "Candle freshness check passed",
                symbol=candle.symbol,
                interval=candle.interval.value,
                age_seconds=age_seconds,
                max_allowed_seconds=max_allowed_seconds,
            )
        elif action == "rejected":
            logger.warning(
                "Candle freshness check rejected (stale data)",
                symbol=candle.symbol,
                interval=candle.interval.value,
                age_seconds=age_seconds,
                max_allowed_seconds=max_allowed_seconds,
            )
        else:  # action == "warned"
            logger.warning(
                "Candle freshness check warned (stale data in warn mode)",
                symbol=candle.symbol,
                interval=candle.interval.value,
                age_seconds=age_seconds,
                max_allowed_seconds=max_allowed_seconds,
            )

        return result

    def is_fresh(self, candle: Candle, policy: DataFreshnessPolicy) -> bool:
        """
        Quick boolean check: is the candle fresh according to policy?

        Convenience method that returns True if the candle's age is within
        the staleness threshold, False otherwise.

        Args:
            candle: The market data candle to check.
            policy: The freshness policy defining acceptable staleness.

        Returns:
            True if age_seconds <= max_allowed_seconds, False otherwise.

        Example:
            gate = DataFreshnessGate()
            if gate.is_fresh(candle, policy):
                signal = strategy.evaluate(candles, indicators, position)
        """
        result = self.check_freshness(candle, policy)
        return result.is_fresh

    def _get_current_time(self) -> datetime:
        """
        Get the current UTC time.

        Can be overridden in tests to inject a fixed time for deterministic testing.

        Returns:
            Current UTC time with timezone info.
        """
        return datetime.now(timezone.utc)
