"""
Mock signal repository for unit testing.

Responsibilities:
- Provide an in-memory implementation of SignalRepositoryInterface.
- Support introspection for test assertions.
- Maintain behavioural parity with the SQL implementation.

Does NOT:
- Access any external storage.
- Contain business logic.

Dependencies:
- libs.contracts.interfaces.signal_repository.SignalRepositoryInterface
- libs.contracts.signal: Signal, SignalEvaluation, SignalStats

Example:
    repo = MockSignalRepository()
    repo.save_signal(signal)
    assert repo.signal_count() == 1
"""

from __future__ import annotations

from datetime import datetime, timezone

from libs.contracts.interfaces.signal_repository import SignalRepositoryInterface
from libs.contracts.signal import (
    Signal,
    SignalDirection,
    SignalEvaluation,
    SignalStats,
    SignalStrength,
)


class MockSignalRepository(SignalRepositoryInterface):
    """
    In-memory implementation of SignalRepositoryInterface for unit testing.

    Responsibilities:
    - Store signals and evaluations in memory.
    - Provide introspection helpers for test assertions.

    Does NOT:
    - Persist data across test runs.

    Example:
        repo = MockSignalRepository()
        repo.save_signal(signal)
        assert repo.signal_count() == 1
    """

    def __init__(self) -> None:
        self._signals: dict[str, Signal] = {}
        self._evaluations: list[SignalEvaluation] = []

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    def save_signal(self, signal: Signal) -> Signal:
        """
        Persist a trading signal in memory.

        Args:
            signal: The signal to persist.

        Returns:
            The persisted signal (unchanged).
        """
        self._signals[signal.signal_id] = signal
        return signal

    def save_evaluation(self, evaluation: SignalEvaluation) -> SignalEvaluation:
        """
        Persist a signal evaluation in memory.

        Args:
            evaluation: The evaluation to persist.

        Returns:
            The persisted evaluation (unchanged).
        """
        self._evaluations.append(evaluation)
        return evaluation

    def find_signals(
        self,
        strategy_id: str,
        symbol: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[Signal]:
        """
        Query signals by strategy, symbol, and time range.

        Args:
            strategy_id: Strategy ID to filter by.
            symbol: Optional symbol filter (case-insensitive).
            since: Only return signals generated after this time.
            limit: Maximum number of results.

        Returns:
            List of matching signals, ordered by generated_at descending.
        """
        results = [s for s in self._signals.values() if s.strategy_id == strategy_id]

        if symbol is not None:
            norm = symbol.upper()
            results = [s for s in results if s.symbol == norm]

        if since is not None:
            results = [s for s in results if s.generated_at > since]

        # Sort by generated_at descending (newest first)
        results.sort(key=lambda s: s.generated_at, reverse=True)

        return results[:limit]

    def find_evaluations(self, signal_id: str) -> list[SignalEvaluation]:
        """
        Find all evaluations for a specific signal.

        Args:
            signal_id: Signal ID to look up.

        Returns:
            List of evaluations for the signal.
        """
        return [e for e in self._evaluations if e.signal.signal_id == signal_id]

    def get_signal_stats(
        self,
        strategy_id: str,
        since: datetime,
    ) -> SignalStats:
        """
        Compute aggregated signal statistics for a strategy.

        Args:
            strategy_id: Strategy to aggregate.
            since: Start of the statistics window.

        Returns:
            SignalStats with counts and averages.
        """
        matching = [
            s
            for s in self._signals.values()
            if s.strategy_id == strategy_id and s.generated_at > since
        ]

        matching_evals = [
            e
            for e in self._evaluations
            if e.signal.strategy_id == strategy_id and e.signal.generated_at > since
        ]

        total = len(matching)
        approved = sum(1 for e in matching_evals if e.approved)
        rejected = sum(1 for e in matching_evals if not e.approved)

        long_count = sum(1 for s in matching if s.direction == SignalDirection.LONG)
        short_count = sum(1 for s in matching if s.direction == SignalDirection.SHORT)
        flat_count = sum(1 for s in matching if s.direction == SignalDirection.FLAT)

        strong_count = sum(1 for s in matching if s.strength == SignalStrength.STRONG)
        moderate_count = sum(1 for s in matching if s.strength == SignalStrength.MODERATE)
        weak_count = sum(1 for s in matching if s.strength == SignalStrength.WEAK)

        avg_conf = sum(s.confidence for s in matching) / total if total > 0 else 0.0

        now = datetime.now(tz=timezone.utc)
        return SignalStats(
            strategy_id=strategy_id,
            total_signals=total,
            approved_signals=approved,
            rejected_signals=rejected,
            long_signals=long_count,
            short_signals=short_count,
            flat_signals=flat_count,
            strong_signals=strong_count,
            moderate_signals=moderate_count,
            weak_signals=weak_count,
            avg_confidence=avg_conf,
            since=since,
            until=now,
        )

    # ------------------------------------------------------------------
    # Introspection helpers for tests
    # ------------------------------------------------------------------

    def signal_count(self) -> int:
        """Return total number of stored signals."""
        return len(self._signals)

    def evaluation_count(self) -> int:
        """Return total number of stored evaluations."""
        return len(self._evaluations)

    def get_all_signals(self) -> list[Signal]:
        """Return all stored signals."""
        return list(self._signals.values())

    def get_all_evaluations(self) -> list[SignalEvaluation]:
        """Return all stored evaluations."""
        return list(self._evaluations)

    def clear(self) -> None:
        """Remove all stored signals and evaluations."""
        self._signals.clear()
        self._evaluations.clear()
