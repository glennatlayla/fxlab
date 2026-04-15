"""
Unit tests for MockSignalRepository (Phase 8 — M3).

Tests verify behavioural parity with what a SQL implementation would provide:
- Save and retrieve signals with filtering.
- Save and retrieve evaluations by signal ID.
- Signal statistics computation.
- Symbol normalization to uppercase.
- Time-range filtering (since parameter).
- Ordering by generated_at descending.
- Introspection helpers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from libs.contracts.mocks.mock_signal_repository import MockSignalRepository
from libs.contracts.signal import (
    RiskGateResult,
    Signal,
    SignalDirection,
    SignalEvaluation,
    SignalStrength,
    SignalType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 13, 14, 30, 0, tzinfo=timezone.utc)
_HOUR_AGO = _NOW - timedelta(hours=1)
_TWO_HOURS_AGO = _NOW - timedelta(hours=2)
_DAY_AGO = _NOW - timedelta(days=1)


def _make_signal(
    signal_id: str = "sig-001",
    strategy_id: str = "strat-sma",
    symbol: str = "AAPL",
    direction: SignalDirection = SignalDirection.LONG,
    strength: SignalStrength = SignalStrength.STRONG,
    confidence: float = 0.85,
    generated_at: datetime = _NOW,
) -> Signal:
    """Create a Signal with sensible defaults."""
    return Signal(
        signal_id=signal_id,
        strategy_id=strategy_id,
        deployment_id="deploy-001",
        symbol=symbol,
        direction=direction,
        signal_type=SignalType.ENTRY,
        strength=strength,
        confidence=confidence,
        bar_timestamp=generated_at,
        generated_at=generated_at,
        correlation_id="corr-001",
    )


def _make_evaluation(
    signal: Signal,
    approved: bool = True,
) -> SignalEvaluation:
    """Create a SignalEvaluation with sensible defaults."""
    return SignalEvaluation(
        signal=signal,
        approved=approved,
        risk_gate_results=[
            RiskGateResult(gate_name="test_gate", passed=approved),
        ],
        position_size=Decimal("500") if approved else None,
        rejection_reason=None if approved else "Gate failed",
        evaluated_at=_NOW,
    )


# ---------------------------------------------------------------------------
# Signal persistence tests
# ---------------------------------------------------------------------------


class TestSignalSaveAndFind:
    """Tests for signal save and retrieval."""

    def test_save_signal_returns_same_object(self) -> None:
        """save_signal returns the persisted signal unchanged."""
        repo = MockSignalRepository()
        signal = _make_signal()
        result = repo.save_signal(signal)
        assert result == signal

    def test_save_signal_increments_count(self) -> None:
        """Saving a signal increases the signal count."""
        repo = MockSignalRepository()
        assert repo.signal_count() == 0
        repo.save_signal(_make_signal())
        assert repo.signal_count() == 1

    def test_find_signals_by_strategy(self) -> None:
        """find_signals filters by strategy_id."""
        repo = MockSignalRepository()
        repo.save_signal(_make_signal(signal_id="s1", strategy_id="strat-sma"))
        repo.save_signal(_make_signal(signal_id="s2", strategy_id="strat-rsi"))

        results = repo.find_signals("strat-sma")
        assert len(results) == 1
        assert results[0].strategy_id == "strat-sma"

    def test_find_signals_by_symbol(self) -> None:
        """find_signals filters by symbol."""
        repo = MockSignalRepository()
        repo.save_signal(_make_signal(signal_id="s1", symbol="AAPL"))
        repo.save_signal(_make_signal(signal_id="s2", symbol="MSFT"))

        results = repo.find_signals("strat-sma", symbol="AAPL")
        assert len(results) == 1
        assert results[0].symbol == "AAPL"

    def test_find_signals_since_filter(self) -> None:
        """find_signals only returns signals after since."""
        repo = MockSignalRepository()
        repo.save_signal(_make_signal(signal_id="old", generated_at=_TWO_HOURS_AGO))
        repo.save_signal(_make_signal(signal_id="new", generated_at=_NOW))

        results = repo.find_signals("strat-sma", since=_HOUR_AGO)
        assert len(results) == 1
        assert results[0].signal_id == "new"

    def test_find_signals_ordered_by_generated_at_desc(self) -> None:
        """Results are ordered by generated_at descending."""
        repo = MockSignalRepository()
        t1 = _NOW - timedelta(minutes=30)
        t2 = _NOW - timedelta(minutes=15)
        t3 = _NOW
        repo.save_signal(_make_signal(signal_id="s1", generated_at=t1))
        repo.save_signal(_make_signal(signal_id="s3", generated_at=t3))
        repo.save_signal(_make_signal(signal_id="s2", generated_at=t2))

        results = repo.find_signals("strat-sma")
        assert [r.signal_id for r in results] == ["s3", "s2", "s1"]

    def test_find_signals_limit(self) -> None:
        """find_signals respects the limit parameter."""
        repo = MockSignalRepository()
        for i in range(10):
            repo.save_signal(
                _make_signal(
                    signal_id=f"s{i}",
                    generated_at=_NOW + timedelta(minutes=i),
                )
            )

        results = repo.find_signals("strat-sma", limit=3)
        assert len(results) == 3

    def test_find_signals_symbol_case_insensitive(self) -> None:
        """Symbol matching is case-insensitive."""
        repo = MockSignalRepository()
        repo.save_signal(_make_signal(signal_id="s1", symbol="aapl"))

        results = repo.find_signals("strat-sma", symbol="Aapl")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Evaluation persistence tests
# ---------------------------------------------------------------------------


class TestEvaluationSaveAndFind:
    """Tests for evaluation save and retrieval."""

    def test_save_evaluation_returns_same_object(self) -> None:
        """save_evaluation returns the persisted evaluation unchanged."""
        repo = MockSignalRepository()
        signal = _make_signal()
        repo.save_signal(signal)
        evaluation = _make_evaluation(signal)

        result = repo.save_evaluation(evaluation)
        assert result == evaluation

    def test_save_evaluation_increments_count(self) -> None:
        """Saving an evaluation increases the evaluation count."""
        repo = MockSignalRepository()
        signal = _make_signal()
        repo.save_signal(signal)

        assert repo.evaluation_count() == 0
        repo.save_evaluation(_make_evaluation(signal))
        assert repo.evaluation_count() == 1

    def test_find_evaluations_by_signal_id(self) -> None:
        """find_evaluations returns evaluations for a specific signal."""
        repo = MockSignalRepository()
        s1 = _make_signal(signal_id="s1")
        s2 = _make_signal(signal_id="s2")
        repo.save_signal(s1)
        repo.save_signal(s2)
        repo.save_evaluation(_make_evaluation(s1))
        repo.save_evaluation(_make_evaluation(s2))

        results = repo.find_evaluations("s1")
        assert len(results) == 1
        assert results[0].signal.signal_id == "s1"

    def test_find_evaluations_empty(self) -> None:
        """find_evaluations returns empty list for unknown signal."""
        repo = MockSignalRepository()
        results = repo.find_evaluations("nonexistent")
        assert results == []


# ---------------------------------------------------------------------------
# Signal stats tests
# ---------------------------------------------------------------------------


class TestSignalStats:
    """Tests for get_signal_stats computation."""

    def test_stats_counts(self) -> None:
        """Stats correctly count signals by direction and strength."""
        repo = MockSignalRepository()
        repo.save_signal(
            _make_signal(
                signal_id="s1", direction=SignalDirection.LONG, strength=SignalStrength.STRONG
            )
        )
        repo.save_signal(
            _make_signal(
                signal_id="s2", direction=SignalDirection.SHORT, strength=SignalStrength.MODERATE
            )
        )
        repo.save_signal(
            _make_signal(
                signal_id="s3", direction=SignalDirection.FLAT, strength=SignalStrength.WEAK
            )
        )

        stats = repo.get_signal_stats("strat-sma", since=_DAY_AGO)
        assert stats.total_signals == 3
        assert stats.long_signals == 1
        assert stats.short_signals == 1
        assert stats.flat_signals == 1
        assert stats.strong_signals == 1
        assert stats.moderate_signals == 1
        assert stats.weak_signals == 1

    def test_stats_approval_counts(self) -> None:
        """Stats correctly count approved/rejected evaluations."""
        repo = MockSignalRepository()
        s1 = _make_signal(signal_id="s1")
        s2 = _make_signal(signal_id="s2")
        repo.save_signal(s1)
        repo.save_signal(s2)
        repo.save_evaluation(_make_evaluation(s1, approved=True))
        repo.save_evaluation(_make_evaluation(s2, approved=False))

        stats = repo.get_signal_stats("strat-sma", since=_DAY_AGO)
        assert stats.approved_signals == 1
        assert stats.rejected_signals == 1

    def test_stats_avg_confidence(self) -> None:
        """Stats correctly compute average confidence."""
        repo = MockSignalRepository()
        repo.save_signal(_make_signal(signal_id="s1", confidence=0.80))
        repo.save_signal(_make_signal(signal_id="s2", confidence=0.60))

        stats = repo.get_signal_stats("strat-sma", since=_DAY_AGO)
        assert abs(stats.avg_confidence - 0.70) < 1e-9

    def test_stats_empty(self) -> None:
        """Stats for empty repo returns zeroes."""
        repo = MockSignalRepository()
        stats = repo.get_signal_stats("strat-sma", since=_DAY_AGO)
        assert stats.total_signals == 0
        assert stats.approved_signals == 0
        assert stats.avg_confidence == 0.0

    def test_stats_since_filter(self) -> None:
        """Stats respect the since filter."""
        repo = MockSignalRepository()
        repo.save_signal(_make_signal(signal_id="old", generated_at=_TWO_HOURS_AGO))
        repo.save_signal(_make_signal(signal_id="new", generated_at=_NOW))

        stats = repo.get_signal_stats("strat-sma", since=_HOUR_AGO)
        assert stats.total_signals == 1


# ---------------------------------------------------------------------------
# Introspection helper tests
# ---------------------------------------------------------------------------


class TestIntrospection:
    """Tests for mock introspection helpers."""

    def test_clear_removes_all(self) -> None:
        """clear() removes all signals and evaluations."""
        repo = MockSignalRepository()
        signal = _make_signal()
        repo.save_signal(signal)
        repo.save_evaluation(_make_evaluation(signal))

        repo.clear()
        assert repo.signal_count() == 0
        assert repo.evaluation_count() == 0

    def test_get_all_signals(self) -> None:
        """get_all_signals returns all stored signals."""
        repo = MockSignalRepository()
        repo.save_signal(_make_signal(signal_id="s1"))
        repo.save_signal(_make_signal(signal_id="s2"))
        assert len(repo.get_all_signals()) == 2

    def test_get_all_evaluations(self) -> None:
        """get_all_evaluations returns all stored evaluations."""
        repo = MockSignalRepository()
        s1 = _make_signal(signal_id="s1")
        repo.save_signal(s1)
        repo.save_evaluation(_make_evaluation(s1))
        repo.save_evaluation(_make_evaluation(s1, approved=False))
        assert len(repo.get_all_evaluations()) == 2
