"""
Interface for market data freshness validation.

Responsibilities:
- Define the contract for data freshness gate implementations.
- Specify methods for checking candle staleness against a policy.

Does NOT:
- Implement freshness logic (concrete service responsibility).
- Know about specific clock implementations or time providers.

Implementations:
- DataFreshnessGate: Production implementation (stdlib datetime.now(UTC)).
- MockDataFreshnessGate: In-memory test double with injectable time.

Example:
    from libs.contracts.interfaces.data_freshness_gate_interface import (
        DataFreshnessGateInterface,
    )
    from libs.contracts.data_freshness import DataFreshnessPolicy

    gate: DataFreshnessGateInterface = DataFreshnessGate()
    policy = DataFreshnessPolicy()
    result = gate.check_freshness(candle, policy)
    if not result.is_fresh:
        logger.warning("Stale data — skipping signal generation")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from libs.contracts.data_freshness import DataFreshnessPolicy, FreshnessCheckResult
    from libs.contracts.market_data import Candle


class DataFreshnessGateInterface(ABC):
    """
    Abstract interface for validating market data freshness.

    Implementations must check candle age against a freshness policy and
    return a structured result indicating whether the data is acceptable
    for signal generation.

    All methods are stateless and deterministic given the same inputs.

    Example:
        gate = DataFreshnessGate()
        policy = DataFreshnessPolicy(
            max_staleness_multiplier=3.0,
            absolute_max_staleness_seconds=600,
            action_on_stale="reject",
        )
        result = gate.check_freshness(candle, policy)
        if result.is_fresh:
            # Proceed with signal generation
            signal = strategy.evaluate(...)
        else:
            # Log rejection or warning based on result.action
            logger.warning(f"Stale candle: {result.age_seconds}s old")
    """

    @abstractmethod
    def check_freshness(self, candle: Candle, policy: DataFreshnessPolicy) -> FreshnessCheckResult:
        """
        Check if a candle is fresh according to the given policy.

        Calculates the age of the candle (current UTC time - candle.timestamp)
        and compares it against interval-based and absolute staleness thresholds.

        Args:
            candle: The market data candle to check.
            policy: The freshness policy defining acceptable staleness.

        Returns:
            FreshnessCheckResult with is_fresh, age_seconds, max_allowed_seconds,
            and action (accepted/rejected/warned).

        Raises:
            None — all errors are captured in the result's action field.
            If a calculation error occurs, treat it as a policy rejection.

        Example:
            result = gate.check_freshness(candle, policy)
            if result.action == "accepted":
                signal = strategy.evaluate(...)
            elif result.action == "rejected":
                logger.warning(f"Stale data rejected: {result.age_seconds}s old")
            else:  # "warned"
                signal = strategy.evaluate(...)
                logger.warning(f"Stale data warning: {result.age_seconds}s old")
        """

    @abstractmethod
    def is_fresh(self, candle: Candle, policy: DataFreshnessPolicy) -> bool:
        """
        Quick boolean check: is the candle fresh according to policy?

        Convenience method that returns True if check_freshness() would return
        a result with is_fresh=True, False otherwise.

        Args:
            candle: The market data candle to check.
            policy: The freshness policy defining acceptable staleness.

        Returns:
            True if the candle is fresh, False if stale.

        Example:
            if gate.is_fresh(candle, policy):
                signal = strategy.evaluate(candles, indicators, position)
        """
