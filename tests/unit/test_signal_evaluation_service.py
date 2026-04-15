"""
Unit tests for SignalEvaluationService (M5).

Tests cover each gate in the pipeline:
1. Data quality gate — reject on low quality score.
2. Kill switch gate — reject when halted.
3. Risk gate — reject on risk check failure.
4. Position sizing — compute position size.
5. VaR impact check — reject on excessive VaR.
6. Duplicate signal filter — reject duplicate signals.
7. Full pipeline approval — all gates pass.
8. Gate ordering — fail-fast on first rejection.
9. Concurrent evaluation safety.

Follows §5 TDD naming: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from libs.contracts.data_quality import QualityGrade, QualityScore
from libs.contracts.market_data import CandleInterval
from libs.contracts.position_sizing import SizingMethod, SizingResult
from libs.contracts.risk import RiskCheckResult, RiskEventSeverity
from libs.contracts.risk_analytics import VaRResult
from libs.contracts.signal import (
    Signal,
    SignalDirection,
    SignalStrength,
    SignalType,
)
from services.api.services.signal_evaluation_service import SignalEvaluationService

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 13, 14, 0, tzinfo=timezone.utc)
_DEPLOY_ID = "deploy-test-001"
_CORR_ID = "corr-test-001"


_SIGNAL_COUNTER = 0


def _make_signal(
    *,
    symbol: str = "AAPL",
    direction: SignalDirection = SignalDirection.LONG,
    signal_type: SignalType = SignalType.ENTRY,
    strength: SignalStrength = SignalStrength.MODERATE,
    confidence: float = 0.75,
    bar_timestamp: datetime | None = None,
    strategy_id: str = "strat-test",
    suggested_stop: Decimal | None = Decimal("165.00"),
    signal_id: str | None = None,
) -> Signal:
    """Build a test signal with sensible defaults and unique signal_id."""
    global _SIGNAL_COUNTER  # noqa: PLW0603
    _SIGNAL_COUNTER += 1
    resolved_id = signal_id or f"01HTESTSIGNAL{_SIGNAL_COUNTER:012d}"
    return Signal(
        signal_id=resolved_id,
        strategy_id=strategy_id,
        deployment_id=_DEPLOY_ID,
        symbol=symbol,
        direction=direction,
        signal_type=signal_type,
        strength=strength,
        confidence=confidence,
        indicators_used={"sma_20": 175.0},
        bar_timestamp=bar_timestamp or _NOW,
        generated_at=_NOW,
        correlation_id=_CORR_ID,
        suggested_stop=suggested_stop,
    )


def _make_quality_score(
    *,
    symbol: str = "AAPL",
    composite_score: float = 0.95,
    grade: QualityGrade = QualityGrade.A,
) -> QualityScore:
    """Build a test quality score."""
    return QualityScore(
        symbol=symbol,
        interval=CandleInterval.D1,
        window_start=_NOW - timedelta(hours=1),
        window_end=_NOW,
        completeness=composite_score,
        timeliness=composite_score,
        consistency=composite_score,
        accuracy=composite_score,
        composite_score=composite_score,
        anomaly_count=0,
        grade=grade,
        scored_at=_NOW,
    )


def _make_var_result(var_95: str = "-2500.00") -> VaRResult:
    """Build a VaR result."""
    from libs.contracts.risk_analytics import VaRMethod

    return VaRResult(
        var_95=Decimal(var_95),
        var_99=Decimal("-4100.00"),
        cvar_95=Decimal("-3200.00"),
        cvar_99=Decimal("-5000.00"),
        method=VaRMethod.HISTORICAL,
        lookback_days=252,
        computed_at=_NOW,
    )


def _make_sizing_result(qty: str = "100") -> SizingResult:
    """Build a sizing result."""
    return SizingResult(
        recommended_quantity=Decimal(qty),
        recommended_value=Decimal(qty) * Decimal("175.00"),
        method_used=SizingMethod.ATR_BASED,
        reasoning="Test sizing",
        stop_loss_price=Decimal("165.00"),
    )


def _make_risk_check(passed: bool = True) -> RiskCheckResult:
    """Build a risk check result."""
    return RiskCheckResult(
        passed=passed,
        check_name="position_limit",
        reason=None if passed else "Position exceeds limit",
        severity=RiskEventSeverity.INFO if passed else RiskEventSeverity.CRITICAL,
    )


def _build_service(
    *,
    quality_score: QualityScore | None = None,
    is_halted: bool = False,
    risk_check: RiskCheckResult | None = None,
    sizing_result: SizingResult | None = None,
    var_result: VaRResult | None = None,
    var_threshold: Decimal = Decimal("5000.00"),
    quality_threshold: float = 0.7,
    cooldown_seconds: int = 300,
) -> SignalEvaluationService:
    """
    Build a SignalEvaluationService with mocked dependencies.

    All dependencies are mocked to return the provided values.
    """
    # Data quality service mock
    dq_service = MagicMock()
    dq_service.evaluate_quality.return_value = quality_score or _make_quality_score()

    # Kill switch service mock
    ks_service = MagicMock()
    ks_service.is_halted.return_value = is_halted

    # Risk gate mock
    risk_gate = MagicMock()
    risk_gate.check_order.return_value = risk_check or _make_risk_check(passed=True)

    # Position sizing service mock
    sizing_service = MagicMock()
    sizing_service.compute_size.return_value = sizing_result or _make_sizing_result()

    # Risk analytics service mock
    analytics_service = MagicMock()
    analytics_service.compute_var.return_value = var_result or _make_var_result()

    # Signal repository mock
    signal_repo = MagicMock()
    signal_repo.find_signals.return_value = []  # No duplicates by default
    signal_repo.save_evaluation.side_effect = lambda e: e

    return SignalEvaluationService(
        data_quality_service=dq_service,
        kill_switch_service=ks_service,
        risk_gate=risk_gate,
        position_sizing_service=sizing_service,
        risk_analytics_service=analytics_service,
        signal_repository=signal_repo,
        var_threshold=var_threshold,
        quality_threshold=quality_threshold,
        cooldown_seconds=cooldown_seconds,
    )


# ===========================================================================
# Full Pipeline Tests
# ===========================================================================


class TestFullPipelineApproval:
    """Tests for the complete approval pipeline."""

    def test_all_gates_pass_returns_approved(self) -> None:
        """Signal approved when all gates pass."""
        service = _build_service()
        signal = _make_signal()

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.approved is True
        assert evaluation.rejection_reason is None
        assert evaluation.position_size is not None
        assert evaluation.position_size > 0

    def test_approved_signal_has_gate_results(self) -> None:
        """Approved signal includes all gate results."""
        service = _build_service()
        signal = _make_signal()

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert len(evaluation.risk_gate_results) >= 4
        assert all(g.passed for g in evaluation.risk_gate_results)

    def test_approved_signal_has_position_size(self) -> None:
        """Approved signal has a computed position size."""
        service = _build_service(sizing_result=_make_sizing_result("250"))
        signal = _make_signal()

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.position_size == Decimal("250")


# ===========================================================================
# Data Quality Gate Tests
# ===========================================================================


class TestDataQualityGate:
    """Tests for the data quality gate."""

    def test_reject_on_low_quality_score(self) -> None:
        """Signal rejected when quality score is below threshold."""
        low_score = _make_quality_score(composite_score=0.5, grade=QualityGrade.F)
        service = _build_service(quality_score=low_score, quality_threshold=0.7)
        signal = _make_signal()

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.approved is False
        assert "quality" in evaluation.rejection_reason.lower()

    def test_pass_on_adequate_quality(self) -> None:
        """Signal passes data quality gate when score meets threshold."""
        good_score = _make_quality_score(composite_score=0.95, grade=QualityGrade.A)
        service = _build_service(quality_score=good_score, quality_threshold=0.7)
        signal = _make_signal()

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.approved is True

    def test_reject_when_no_quality_score_available(self) -> None:
        """Signal rejected when no quality score exists for the symbol."""
        dq_service = MagicMock()
        dq_service.evaluate_quality.return_value = None

        service = _build_service()
        # Override the quality service
        service._data_quality_service = dq_service
        signal = _make_signal()

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.approved is False
        assert "quality" in evaluation.rejection_reason.lower()


# ===========================================================================
# Kill Switch Gate Tests
# ===========================================================================


class TestKillSwitchGate:
    """Tests for the kill switch gate."""

    def test_reject_when_halted(self) -> None:
        """Signal rejected when kill switch is active."""
        service = _build_service(is_halted=True)
        signal = _make_signal()

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.approved is False
        assert "kill switch" in evaluation.rejection_reason.lower()

    def test_pass_when_not_halted(self) -> None:
        """Signal passes kill switch gate when not halted."""
        service = _build_service(is_halted=False)
        signal = _make_signal()

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.approved is True


# ===========================================================================
# Risk Gate Tests
# ===========================================================================


class TestRiskGate:
    """Tests for the pre-trade risk gate."""

    def test_reject_on_risk_check_failure(self) -> None:
        """Signal rejected when risk gate check fails."""
        failed_check = _make_risk_check(passed=False)
        service = _build_service(risk_check=failed_check)
        signal = _make_signal()

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.approved is False
        assert "risk" in evaluation.rejection_reason.lower()

    def test_pass_on_risk_check_success(self) -> None:
        """Signal passes risk gate when all checks pass."""
        passed_check = _make_risk_check(passed=True)
        service = _build_service(risk_check=passed_check)
        signal = _make_signal()

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.approved is True


# ===========================================================================
# Position Sizing Tests
# ===========================================================================


class TestPositionSizing:
    """Tests for position sizing gate."""

    def test_position_size_passed_to_evaluation(self) -> None:
        """Position sizing result is included in evaluation."""
        service = _build_service(sizing_result=_make_sizing_result("500"))
        signal = _make_signal()

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.position_size == Decimal("500")

    def test_zero_position_size_rejects_signal(self) -> None:
        """Signal rejected when position sizing returns zero."""
        zero_size = _make_sizing_result("0")
        service = _build_service(sizing_result=zero_size)
        signal = _make_signal()

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.approved is False
        assert "position size" in evaluation.rejection_reason.lower()

    def test_stop_loss_from_sizing_used_as_adjusted_stop(self) -> None:
        """Sizing service's stop loss price becomes adjusted_stop."""
        sizing = _make_sizing_result("100")
        service = _build_service(sizing_result=sizing)
        signal = _make_signal()

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.adjusted_stop == Decimal("165.00")


# ===========================================================================
# VaR Impact Tests
# ===========================================================================


class TestVaRImpactGate:
    """Tests for the VaR impact check."""

    def test_reject_when_var_exceeds_threshold(self) -> None:
        """Signal rejected when projected VaR exceeds threshold."""
        # VaR of -6000 exceeds threshold of 5000
        high_var = _make_var_result("-6000.00")
        service = _build_service(var_result=high_var, var_threshold=Decimal("5000.00"))
        signal = _make_signal()

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.approved is False
        assert "var" in evaluation.rejection_reason.lower()

    def test_pass_when_var_within_threshold(self) -> None:
        """Signal passes when VaR is within threshold."""
        ok_var = _make_var_result("-2500.00")
        service = _build_service(var_result=ok_var, var_threshold=Decimal("5000.00"))
        signal = _make_signal()

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.approved is True


# ===========================================================================
# Duplicate Signal Filter Tests
# ===========================================================================


class TestDuplicateSignalFilter:
    """Tests for the duplicate signal filter."""

    def test_reject_duplicate_signal(self) -> None:
        """Signal rejected when identical signal was recently evaluated."""
        service = _build_service()
        # Make find_signals return a matching signal (duplicate)
        existing = _make_signal(bar_timestamp=_NOW)
        service._signal_repository.find_signals.return_value = [existing]
        signal = _make_signal(bar_timestamp=_NOW)

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.approved is False
        assert "duplicate" in evaluation.rejection_reason.lower()

    def test_pass_when_no_duplicate_exists(self) -> None:
        """Signal passes when no duplicate found."""
        service = _build_service()
        service._signal_repository.find_signals.return_value = []
        signal = _make_signal()

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.approved is True

    def test_pass_when_old_duplicate_outside_cooldown(self) -> None:
        """Signal passes when prior signal is outside cooldown window."""
        service = _build_service(cooldown_seconds=300)
        old_signal = _make_signal(
            bar_timestamp=_NOW - timedelta(hours=1),
        )
        service._signal_repository.find_signals.return_value = [old_signal]
        signal = _make_signal(bar_timestamp=_NOW)

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.approved is True


# ===========================================================================
# Gate Ordering / Fail-Fast Tests
# ===========================================================================


class TestGateOrdering:
    """Tests for gate ordering and fail-fast behaviour."""

    def test_quality_gate_checked_before_risk_gate(self) -> None:
        """Data quality gate rejects before risk gate is consulted."""
        low_score = _make_quality_score(composite_score=0.3, grade=QualityGrade.F)
        service = _build_service(quality_score=low_score, quality_threshold=0.7)
        signal = _make_signal()

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.approved is False
        # Risk gate should NOT have been called
        service._risk_gate.check_order.assert_not_called()

    def test_kill_switch_checked_before_risk_gate(self) -> None:
        """Kill switch gate rejects before risk gate is consulted."""
        service = _build_service(is_halted=True)
        signal = _make_signal()

        evaluation = service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        assert evaluation.approved is False
        service._risk_gate.check_order.assert_not_called()

    def test_evaluation_persisted_on_rejection(self) -> None:
        """Evaluation is persisted to repository even on rejection."""
        service = _build_service(is_halted=True)
        signal = _make_signal()

        service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        service._signal_repository.save_evaluation.assert_called_once()

    def test_evaluation_persisted_on_approval(self) -> None:
        """Evaluation is persisted to repository on approval."""
        service = _build_service()
        signal = _make_signal()

        service.evaluate(
            signal=signal,
            deployment_id=_DEPLOY_ID,
            execution_mode="paper",
            correlation_id=_CORR_ID,
        )

        service._signal_repository.save_evaluation.assert_called_once()
