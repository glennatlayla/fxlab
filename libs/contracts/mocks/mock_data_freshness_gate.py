"""
In-memory mock implementation of DataFreshnessGateInterface.

Used in unit tests to provide fast, deterministic freshness checks with
injectable time for time-travel testing.

Responsibilities:
- Implement DataFreshnessGateInterface with configurable mock behavior.
- Support time injection (freeze time at a specific UTC instant).
- Mirror the production DataFreshnessGate interface exactly.
- Provide introspection helpers for test assertions.

Does NOT:
- Persist data across process restarts.
- Perform actual I/O or logging.

Example:
    gate = MockDataFreshnessGate()
    gate.set_current_time(datetime(2026, 4, 13, 15, 30, 0, tzinfo=timezone.utc))

    candle = Candle(
        symbol="AAPL",
        interval=CandleInterval.M1,
        ...,
        timestamp=datetime(2026, 4, 13, 15, 29, 30, tzinfo=timezone.utc),
    )
    policy = DataFreshnessPolicy()

    result = gate.check_freshness(candle, policy)
    assert result.is_fresh is True
    assert result.age_seconds == 30.0

    # Introspection: check what was checked
    checks = gate.get_checks()
    assert len(checks) == 1
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from libs.contracts.data_freshness import DataFreshnessPolicy, FreshnessCheckResult
from libs.contracts.interfaces.data_freshness_gate_interface import (
    DataFreshnessGateInterface,
)
from libs.contracts.market_data import INTERVAL_SECONDS

if TYPE_CHECKING:
    from libs.contracts.market_data import Candle


class MockDataFreshnessGate(DataFreshnessGateInterface):
    """
    In-memory mock for DataFreshnessGateInterface with time injection.

    Provides deterministic freshness checks for testing, with the ability to
    freeze time at a specific instant for repeatable test behavior.

    All results are stored for test introspection and assertion.

    Example:
        gate = MockDataFreshnessGate()
        gate.set_current_time(test_now)
        result = gate.check_freshness(candle, policy)
        assert gate.get_check_count() == 1
    """

    def __init__(self) -> None:
        """Initialize the mock with current UTC time and empty check history."""
        self._current_time = datetime.now(timezone.utc)
        self._checks: list[FreshnessCheckResult] = []

    def set_current_time(self, now: datetime) -> None:
        """
        Set the time to be used for all subsequent freshness checks.

        Args:
            now: The fixed UTC time to use. Must have tzinfo=timezone.utc.

        Example:
            gate.set_current_time(datetime(2026, 4, 13, 15, 30, 0, tzinfo=timezone.utc))
        """
        self._current_time = now

    def get_current_time(self) -> datetime:
        """
        Get the currently set mock time.

        Returns:
            The fixed UTC time previously set, or current UTC if never set.
        """
        return self._current_time

    def check_freshness(self, candle: Candle, policy: DataFreshnessPolicy) -> FreshnessCheckResult:
        """
        Check if a candle is fresh according to the given policy.

        Identical implementation to the production DataFreshnessGate, but using
        the mock's injected time via _current_time instead of datetime.now().

        Args:
            candle: The market data candle to check.
            policy: The freshness policy defining acceptable staleness.

        Returns:
            FreshnessCheckResult with all required fields.
        """
        now = self._current_time

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

        # Record the check for introspection.
        self._checks.append(result)

        return result

    def is_fresh(self, candle: Candle, policy: DataFreshnessPolicy) -> bool:
        """
        Quick boolean check: is the candle fresh according to policy?

        Args:
            candle: The market data candle to check.
            policy: The freshness policy defining acceptable staleness.

        Returns:
            True if fresh, False otherwise.
        """
        result = self.check_freshness(candle, policy)
        return result.is_fresh

    # -----------------------------------------------------------------------
    # Introspection helpers for test assertions
    # -----------------------------------------------------------------------

    def get_checks(self) -> list[FreshnessCheckResult]:
        """
        Get all recorded freshness checks in order.

        Returns:
            List of all FreshnessCheckResult objects from calls to check_freshness().

        Example:
            gate.check_freshness(candle1, policy)
            gate.check_freshness(candle2, policy)
            assert len(gate.get_checks()) == 2
        """
        return list(self._checks)

    def get_check_count(self) -> int:
        """
        Get the number of freshness checks performed.

        Returns:
            Count of check_freshness() calls.

        Example:
            assert gate.get_check_count() == 3
        """
        return len(self._checks)

    def get_last_check(self) -> FreshnessCheckResult | None:
        """
        Get the most recent freshness check result.

        Returns:
            The last FreshnessCheckResult, or None if no checks performed.

        Example:
            result = gate.get_last_check()
            if result:
                assert result.is_fresh is True
        """
        return self._checks[-1] if self._checks else None

    def get_accepted_checks(self) -> list[FreshnessCheckResult]:
        """
        Get all freshness checks with action='accepted'.

        Returns:
            Subset of checks where action == "accepted".
        """
        return [c for c in self._checks if c.action == "accepted"]

    def get_rejected_checks(self) -> list[FreshnessCheckResult]:
        """
        Get all freshness checks with action='rejected'.

        Returns:
            Subset of checks where action == "rejected".
        """
        return [c for c in self._checks if c.action == "rejected"]

    def get_warned_checks(self) -> list[FreshnessCheckResult]:
        """
        Get all freshness checks with action='warned'.

        Returns:
            Subset of checks where action == "warned".
        """
        return [c for c in self._checks if c.action == "warned"]

    def clear(self) -> None:
        """Clear all recorded checks."""
        self._checks.clear()
