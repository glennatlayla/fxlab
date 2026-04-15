"""
Unit tests for signal contracts (Phase 8 — M3).

Tests verify enum values, model creation, validation, frozen semantics,
and default values for all signal domain objects.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from libs.contracts.signal import (
    RiskGateResult,
    Signal,
    SignalDirection,
    SignalEvaluation,
    SignalStats,
    SignalStrength,
    SignalType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 13, 14, 30, 0, tzinfo=timezone.utc)
_HOUR_AGO = _NOW - timedelta(hours=1)


def _make_signal(
    signal_id: str = "01HTEST0000000000000000001",
    symbol: str = "AAPL",
    direction: SignalDirection = SignalDirection.LONG,
    signal_type: SignalType = SignalType.ENTRY,
    strength: SignalStrength = SignalStrength.STRONG,
    confidence: float = 0.85,
) -> Signal:
    """Create a Signal with sensible defaults."""
    return Signal(
        signal_id=signal_id,
        strategy_id="strat-sma-cross",
        deployment_id="deploy-001",
        symbol=symbol,
        direction=direction,
        signal_type=signal_type,
        strength=strength,
        confidence=confidence,
        indicators_used={"sma_fast": 175.50, "sma_slow": 170.20},
        bar_timestamp=_NOW,
        generated_at=_NOW,
        correlation_id="corr-001",
    )


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestSignalDirection:
    """Tests for SignalDirection enum."""

    def test_all_directions_present(self) -> None:
        """All three signal directions are defined."""
        assert len(SignalDirection) == 3

    def test_direction_values(self) -> None:
        """Direction enum values match expected strings."""
        assert SignalDirection.LONG.value == "long"
        assert SignalDirection.SHORT.value == "short"
        assert SignalDirection.FLAT.value == "flat"


class TestSignalStrength:
    """Tests for SignalStrength enum."""

    def test_all_strengths_present(self) -> None:
        """All three signal strengths are defined."""
        assert len(SignalStrength) == 3

    def test_strength_values(self) -> None:
        """Strength enum values match expected strings."""
        assert SignalStrength.STRONG.value == "strong"
        assert SignalStrength.MODERATE.value == "moderate"
        assert SignalStrength.WEAK.value == "weak"


class TestSignalType:
    """Tests for SignalType enum."""

    def test_all_types_present(self) -> None:
        """All five signal types are defined."""
        assert len(SignalType) == 5

    def test_type_values(self) -> None:
        """Type enum values match expected strings."""
        assert SignalType.ENTRY.value == "entry"
        assert SignalType.EXIT.value == "exit"
        assert SignalType.SCALE_IN.value == "scale_in"
        assert SignalType.SCALE_OUT.value == "scale_out"
        assert SignalType.STOP_ADJUSTMENT.value == "stop_adjustment"


# ---------------------------------------------------------------------------
# Signal model tests
# ---------------------------------------------------------------------------


class TestSignal:
    """Tests for Signal domain model."""

    def test_valid_signal_creation(self) -> None:
        """Signal can be created with valid fields."""
        signal = _make_signal()
        assert signal.signal_id == "01HTEST0000000000000000001"
        assert signal.strategy_id == "strat-sma-cross"
        assert signal.symbol == "AAPL"
        assert signal.direction == SignalDirection.LONG
        assert signal.signal_type == SignalType.ENTRY
        assert signal.strength == SignalStrength.STRONG
        assert signal.confidence == 0.85

    def test_symbol_normalized_to_uppercase(self) -> None:
        """Symbol is normalized to uppercase."""
        signal = _make_signal(symbol="aapl")
        assert signal.symbol == "AAPL"

    def test_frozen_model(self) -> None:
        """Signal is frozen (immutable)."""
        signal = _make_signal()
        with pytest.raises(ValidationError):
            signal.confidence = 0.50  # type: ignore[misc]

    def test_optional_price_fields_default_none(self) -> None:
        """Optional price fields default to None."""
        signal = _make_signal()
        assert signal.suggested_entry is None
        assert signal.suggested_stop is None
        assert signal.suggested_target is None

    def test_price_fields_accept_decimal(self) -> None:
        """Price fields accept Decimal values."""
        signal = Signal(
            signal_id="01HTEST0000000000000000002",
            strategy_id="strat-rsi",
            deployment_id="deploy-002",
            symbol="MSFT",
            direction=SignalDirection.LONG,
            signal_type=SignalType.ENTRY,
            strength=SignalStrength.MODERATE,
            suggested_entry=Decimal("175.50"),
            suggested_stop=Decimal("170.00"),
            suggested_target=Decimal("185.00"),
            confidence=0.70,
            bar_timestamp=_NOW,
            generated_at=_NOW,
            correlation_id="corr-002",
        )
        assert signal.suggested_entry == Decimal("175.50")
        assert signal.suggested_stop == Decimal("170.00")
        assert signal.suggested_target == Decimal("185.00")

    def test_confidence_below_zero_rejected(self) -> None:
        """Confidence below 0.0 is rejected."""
        with pytest.raises(ValidationError):
            _make_signal(confidence=-0.1)

    def test_confidence_above_one_rejected(self) -> None:
        """Confidence above 1.0 is rejected."""
        with pytest.raises(ValidationError):
            _make_signal(confidence=1.1)

    def test_confidence_at_boundaries(self) -> None:
        """Confidence at 0.0 and 1.0 are valid."""
        s0 = _make_signal(signal_id="01HTEST0000000000000000003", confidence=0.0)
        assert s0.confidence == 0.0
        s1 = _make_signal(signal_id="01HTEST0000000000000000004", confidence=1.0)
        assert s1.confidence == 1.0

    def test_empty_symbol_rejected(self) -> None:
        """Empty symbol is rejected."""
        with pytest.raises(ValidationError):
            _make_signal(symbol="")

    def test_default_metadata_empty(self) -> None:
        """Metadata defaults to empty dict."""
        signal = _make_signal()
        assert signal.metadata == {}

    def test_indicators_used_stored(self) -> None:
        """Indicators used at signal time are stored."""
        signal = _make_signal()
        assert "sma_fast" in signal.indicators_used
        assert signal.indicators_used["sma_fast"] == 175.50


# ---------------------------------------------------------------------------
# RiskGateResult tests
# ---------------------------------------------------------------------------


class TestRiskGateResult:
    """Tests for RiskGateResult model."""

    def test_valid_creation(self) -> None:
        """RiskGateResult can be created with valid fields."""
        result = RiskGateResult(
            gate_name="max_position_size",
            passed=True,
            details={"max_allowed": 1000, "requested": 500},
        )
        assert result.gate_name == "max_position_size"
        assert result.passed is True

    def test_frozen_model(self) -> None:
        """RiskGateResult is frozen."""
        result = RiskGateResult(gate_name="test", passed=True)
        with pytest.raises(ValidationError):
            result.passed = False  # type: ignore[misc]

    def test_default_details_empty(self) -> None:
        """Details defaults to empty dict."""
        result = RiskGateResult(gate_name="test", passed=False)
        assert result.details == {}


# ---------------------------------------------------------------------------
# SignalEvaluation tests
# ---------------------------------------------------------------------------


class TestSignalEvaluation:
    """Tests for SignalEvaluation model."""

    def test_approved_evaluation(self) -> None:
        """Approved evaluation has correct fields."""
        signal = _make_signal()
        gate = RiskGateResult(gate_name="drawdown", passed=True)
        evaluation = SignalEvaluation(
            signal=signal,
            approved=True,
            risk_gate_results=[gate],
            position_size=Decimal("500"),
            adjusted_stop=Decimal("168.50"),
            rejection_reason=None,
            evaluated_at=_NOW,
        )
        assert evaluation.approved is True
        assert evaluation.position_size == Decimal("500")
        assert evaluation.rejection_reason is None

    def test_rejected_evaluation(self) -> None:
        """Rejected evaluation captures rejection reason."""
        signal = _make_signal()
        gate = RiskGateResult(
            gate_name="max_drawdown",
            passed=False,
            details={"current": 0.12, "max": 0.10},
        )
        evaluation = SignalEvaluation(
            signal=signal,
            approved=False,
            risk_gate_results=[gate],
            position_size=None,
            adjusted_stop=None,
            rejection_reason="Max drawdown exceeded",
            evaluated_at=_NOW,
        )
        assert evaluation.approved is False
        assert evaluation.rejection_reason == "Max drawdown exceeded"
        assert evaluation.position_size is None

    def test_frozen_model(self) -> None:
        """SignalEvaluation is frozen."""
        signal = _make_signal()
        evaluation = SignalEvaluation(
            signal=signal,
            approved=True,
            evaluated_at=_NOW,
        )
        with pytest.raises(ValidationError):
            evaluation.approved = False  # type: ignore[misc]

    def test_multiple_gate_results(self) -> None:
        """Evaluation can hold multiple gate results."""
        signal = _make_signal()
        gates = [
            RiskGateResult(gate_name="position_size", passed=True),
            RiskGateResult(gate_name="drawdown", passed=True),
            RiskGateResult(gate_name="volatility", passed=False),
        ]
        evaluation = SignalEvaluation(
            signal=signal,
            approved=False,
            risk_gate_results=gates,
            rejection_reason="Volatility gate failed",
            evaluated_at=_NOW,
        )
        assert len(evaluation.risk_gate_results) == 3


# ---------------------------------------------------------------------------
# SignalStats tests
# ---------------------------------------------------------------------------


class TestSignalStats:
    """Tests for SignalStats model."""

    def test_valid_stats_creation(self) -> None:
        """SignalStats can be created with valid fields."""
        stats = SignalStats(
            strategy_id="strat-sma-cross",
            total_signals=100,
            approved_signals=80,
            rejected_signals=20,
            long_signals=55,
            short_signals=40,
            flat_signals=5,
            strong_signals=30,
            moderate_signals=50,
            weak_signals=20,
            avg_confidence=0.72,
            since=_HOUR_AGO,
            until=_NOW,
        )
        assert stats.total_signals == 100
        assert stats.approved_signals == 80
        assert stats.avg_confidence == 0.72

    def test_negative_count_rejected(self) -> None:
        """Negative signal counts are rejected."""
        with pytest.raises(ValidationError):
            SignalStats(
                strategy_id="strat",
                total_signals=-1,
                approved_signals=0,
                rejected_signals=0,
                since=_HOUR_AGO,
                until=_NOW,
            )

    def test_default_direction_counts_zero(self) -> None:
        """Direction and strength counts default to zero."""
        stats = SignalStats(
            strategy_id="strat",
            total_signals=0,
            approved_signals=0,
            rejected_signals=0,
            since=_HOUR_AGO,
            until=_NOW,
        )
        assert stats.long_signals == 0
        assert stats.short_signals == 0
        assert stats.flat_signals == 0
        assert stats.strong_signals == 0
        assert stats.moderate_signals == 0
        assert stats.weak_signals == 0
        assert stats.avg_confidence == 0.0
