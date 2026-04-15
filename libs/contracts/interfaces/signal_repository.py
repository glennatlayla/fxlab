"""
Signal repository interface (port).

Responsibilities:
- Define the abstract contract for persisting and querying trading signals
  and signal evaluations.
- Enable substitution of SQL and mock implementations without changing
  service code.

Does NOT:
- Generate signals or evaluate risk gates.
- Contain business logic.

Dependencies:
- libs.contracts.signal: Signal, SignalEvaluation, SignalStats

Error conditions:
- save_signal: implementors may raise on persistence failure.
- find_signals: returns empty list if no matches found.

Example:
    repo: SignalRepositoryInterface = MockSignalRepository()
    repo.save_signal(signal)
    signals = repo.find_signals(strategy_id="strat-sma-cross")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from libs.contracts.signal import Signal, SignalEvaluation, SignalStats


class SignalRepositoryInterface(ABC):
    """
    Port interface for signal persistence.

    Responsibilities:
    - Persist signal records for audit and analysis.
    - Persist signal evaluations for risk gate traceability.
    - Query signals with filtering by strategy, symbol, time range.
    - Compute aggregated signal statistics.

    Does NOT:
    - Generate signals (strategy responsibility).
    - Evaluate risk gates (service responsibility).

    Example:
        repo = SqlSignalRepository(session_factory)
        repo.save_signal(signal)
        signals = repo.find_signals(strategy_id="strat-sma-cross")
    """

    @abstractmethod
    def save_signal(self, signal: Signal) -> Signal:
        """
        Persist a trading signal.

        Args:
            signal: The signal to persist.

        Returns:
            The persisted signal (unchanged).

        Example:
            saved = repo.save_signal(signal)
        """

    @abstractmethod
    def save_evaluation(self, evaluation: SignalEvaluation) -> SignalEvaluation:
        """
        Persist a signal evaluation result.

        Args:
            evaluation: The evaluation to persist.

        Returns:
            The persisted evaluation (unchanged).

        Example:
            saved = repo.save_evaluation(evaluation)
        """

    @abstractmethod
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
            symbol: Optional symbol filter.
            since: Only return signals generated after this time.
            limit: Maximum number of results.

        Returns:
            List of matching signals, ordered by generated_at descending.

        Example:
            signals = repo.find_signals("strat-sma-cross", symbol="AAPL")
        """

    @abstractmethod
    def find_evaluations(self, signal_id: str) -> list[SignalEvaluation]:
        """
        Find all evaluations for a specific signal.

        Args:
            signal_id: Signal ID to look up evaluations for.

        Returns:
            List of evaluations for the signal.

        Example:
            evals = repo.find_evaluations("sig-001")
        """

    @abstractmethod
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

        Example:
            stats = repo.get_signal_stats("strat-sma-cross", since=cutoff)
        """
