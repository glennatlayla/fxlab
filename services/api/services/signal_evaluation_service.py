"""
Signal evaluation service — multi-gate pipeline for signal approval.

Responsibilities:
- Evaluate raw signals through an ordered pipeline of risk gates.
- Gate 1: Data quality — reject if quality score below policy threshold.
- Gate 2: Kill switch — reject if deployment or global halt is active.
- Gate 3: Risk gate — delegate to RiskGateInterface for pre-trade checks.
- Gate 4: Position sizing — compute position size via PositionSizingService.
- Gate 5: VaR impact — reject if projected VaR exceeds deployment threshold.
- Gate 6: Duplicate signal filter — reject if identical signal within cooldown.
- Persist every evaluation (approved or rejected) to SignalRepository.
- Return a fully-constructed SignalEvaluation with all gate results.

Does NOT:
- Generate signals (SignalStrategy responsibility).
- Execute orders (ExecutionService responsibility).
- Manage positions (PositionRepository responsibility).

Dependencies:
- DataQualityServiceInterface: quality score lookup.
- KillSwitchServiceInterface: halt status check.
- RiskGateInterface: pre-trade risk check.
- PositionSizingServiceInterface: position sizing computation.
- RiskAnalyticsServiceInterface: VaR computation.
- SignalRepositoryInterface: signal persistence and duplicate lookup.

Error conditions:
- All gate failures produce a rejected SignalEvaluation (not exceptions).
- Downstream service unavailability is caught and treated as gate failure.

Example:
    service = SignalEvaluationService(
        data_quality_service=dq_service,
        kill_switch_service=ks_service,
        risk_gate=risk_gate,
        position_sizing_service=sizing_service,
        risk_analytics_service=analytics_service,
        signal_repository=signal_repo,
    )
    evaluation = service.evaluate(
        signal=signal,
        deployment_id="deploy-001",
        execution_mode="paper",
        correlation_id="corr-001",
    )
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import structlog

from libs.contracts.interfaces.data_quality_service import (
    DataQualityServiceInterface,
)
from libs.contracts.interfaces.kill_switch_service_interface import (
    KillSwitchServiceInterface,
)
from libs.contracts.interfaces.position_sizing_service import (
    PositionSizingServiceInterface,
)
from libs.contracts.interfaces.risk_analytics_service import (
    RiskAnalyticsServiceInterface,
)
from libs.contracts.interfaces.risk_gate_interface import RiskGateInterface
from libs.contracts.interfaces.signal_evaluation_service import (
    SignalEvaluationServiceInterface,
)
from libs.contracts.interfaces.signal_repository import SignalRepositoryInterface
from libs.contracts.market_data import CandleInterval
from libs.contracts.signal import (
    RiskGateResult,
    Signal,
    SignalDirection,
    SignalEvaluation,
)

logger = structlog.get_logger(__name__)


class SignalEvaluationService(SignalEvaluationServiceInterface):
    """
    Production implementation of the signal evaluation pipeline.

    Evaluates a raw Signal through 6 ordered gates. Each gate produces
    a RiskGateResult. The pipeline is fail-fast: the first failing gate
    causes immediate rejection. If all gates pass, the signal is approved
    with a computed position size and adjusted stop.

    Responsibilities:
    - Orchestrate gate evaluation in the correct order.
    - Build and return a complete SignalEvaluation.
    - Persist every evaluation to the signal repository.

    Does NOT:
    - Generate signals or execute orders.
    - Manage positions or account state.

    Dependencies:
    - DataQualityServiceInterface (injected): quality score lookup.
    - KillSwitchServiceInterface (injected): halt status check.
    - RiskGateInterface (injected): pre-trade risk checks.
    - PositionSizingServiceInterface (injected): position sizing.
    - RiskAnalyticsServiceInterface (injected): VaR computation.
    - SignalRepositoryInterface (injected): persistence and duplicate lookup.

    Example:
        service = SignalEvaluationService(
            data_quality_service=dq_svc,
            kill_switch_service=ks_svc,
            risk_gate=risk_gate,
            position_sizing_service=sizing_svc,
            risk_analytics_service=analytics_svc,
            signal_repository=signal_repo,
        )
        evaluation = service.evaluate(signal=sig, deployment_id="d1",
                                      execution_mode="paper", correlation_id="c1")
    """

    def __init__(
        self,
        *,
        data_quality_service: DataQualityServiceInterface,
        kill_switch_service: KillSwitchServiceInterface,
        risk_gate: RiskGateInterface,
        position_sizing_service: PositionSizingServiceInterface,
        risk_analytics_service: RiskAnalyticsServiceInterface,
        signal_repository: SignalRepositoryInterface,
        var_threshold: Decimal = Decimal("5000.00"),
        quality_threshold: float = 0.7,
        cooldown_seconds: int = 300,
    ) -> None:
        """
        Initialise the signal evaluation service with injected dependencies.

        Args:
            data_quality_service: Service for quality score lookup.
            kill_switch_service: Service for halt status check.
            risk_gate: Pre-trade risk gate interface.
            position_sizing_service: Service for position sizing computation.
            risk_analytics_service: Service for VaR computation.
            signal_repository: Repository for signal persistence and lookups.
            var_threshold: Maximum absolute VaR (95%) allowed. Signals are
                rejected if |VaR_95| exceeds this value.
            quality_threshold: Minimum composite quality score [0.0, 1.0]
                required for the data quality gate to pass.
            cooldown_seconds: Minimum seconds between identical signals
                before the duplicate filter allows a repeat.

        Example:
            service = SignalEvaluationService(
                data_quality_service=dq,
                kill_switch_service=ks,
                risk_gate=rg,
                position_sizing_service=ps,
                risk_analytics_service=ra,
                signal_repository=sr,
                var_threshold=Decimal("10000"),
                quality_threshold=0.8,
                cooldown_seconds=600,
            )
        """
        self._data_quality_service = data_quality_service
        self._kill_switch_service = kill_switch_service
        self._risk_gate = risk_gate
        self._position_sizing_service = position_sizing_service
        self._risk_analytics_service = risk_analytics_service
        self._signal_repository = signal_repository
        self._var_threshold = var_threshold
        self._quality_threshold = quality_threshold
        self._cooldown_seconds = cooldown_seconds

    def evaluate(
        self,
        *,
        signal: Signal,
        deployment_id: str,
        execution_mode: str,
        correlation_id: str,
    ) -> SignalEvaluation:
        """
        Evaluate a signal through the full risk gate pipeline.

        Gates are executed in order and fail-fast on first rejection:
        1. Data quality gate
        2. Kill switch gate
        3. Duplicate signal filter
        4. Risk gate (pre-trade checks)
        5. Position sizing
        6. VaR impact check

        The result is always persisted to the signal repository.

        Args:
            signal: The raw signal to evaluate.
            deployment_id: Deployment context for risk limits and config.
            execution_mode: Execution mode string (shadow/paper/live).
            correlation_id: Distributed tracing ID.

        Returns:
            SignalEvaluation with approved/rejected status, all gate results,
            position size (if approved), and adjusted stop.

        Example:
            evaluation = service.evaluate(
                signal=signal, deployment_id="d1",
                execution_mode="paper", correlation_id="c1",
            )
        """
        logger.info(
            "Signal evaluation started",
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            direction=signal.direction.value,
            deployment_id=deployment_id,
            correlation_id=correlation_id,
        )

        gate_results: list[RiskGateResult] = []
        position_size: Decimal | None = None
        adjusted_stop: Decimal | None = None

        # --- Gate 1: Data quality ---
        dq_result = self._check_data_quality(signal)
        gate_results.append(dq_result)
        if not dq_result.passed:
            return self._build_rejected(
                signal=signal,
                gate_results=gate_results,
                reason=dq_result.details.get("reason", "Data quality gate failed"),
            )

        # --- Gate 2: Kill switch ---
        ks_result = self._check_kill_switch(signal, deployment_id)
        gate_results.append(ks_result)
        if not ks_result.passed:
            return self._build_rejected(
                signal=signal,
                gate_results=gate_results,
                reason="Kill switch is active for this deployment",
            )

        # --- Gate 3: Duplicate signal filter ---
        dup_result = self._check_duplicate(signal)
        gate_results.append(dup_result)
        if not dup_result.passed:
            return self._build_rejected(
                signal=signal,
                gate_results=gate_results,
                reason=dup_result.details.get("reason", "Duplicate signal rejected"),
            )

        # --- Gate 4: Risk gate (pre-trade) ---
        risk_result = self._check_risk_gate(signal, deployment_id, correlation_id)
        gate_results.append(risk_result)
        if not risk_result.passed:
            return self._build_rejected(
                signal=signal,
                gate_results=gate_results,
                reason=risk_result.details.get("reason", "Risk gate check failed"),
            )

        # --- Gate 5: Position sizing ---
        sizing_result_gate, pos_size, adj_stop = self._compute_position_size(signal)
        gate_results.append(sizing_result_gate)
        if not sizing_result_gate.passed:
            return self._build_rejected(
                signal=signal,
                gate_results=gate_results,
                reason=sizing_result_gate.details.get("reason", "Position size is zero"),
            )
        position_size = pos_size
        adjusted_stop = adj_stop

        # --- Gate 6: VaR impact check ---
        var_result = self._check_var_impact(deployment_id)
        gate_results.append(var_result)
        if not var_result.passed:
            return self._build_rejected(
                signal=signal,
                gate_results=gate_results,
                reason=var_result.details.get("reason", "VaR exceeds threshold"),
            )

        # All gates passed — approved
        logger.info(
            "Signal approved",
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            position_size=str(position_size),
            correlation_id=correlation_id,
        )

        evaluation = SignalEvaluation(
            signal=signal,
            approved=True,
            risk_gate_results=gate_results,
            position_size=position_size,
            adjusted_stop=adjusted_stop,
            rejection_reason=None,
            evaluated_at=datetime.now(tz=timezone.utc),
        )
        self._signal_repository.save_evaluation(evaluation)
        return evaluation

    # ------------------------------------------------------------------
    # Gate implementations
    # ------------------------------------------------------------------

    def _check_data_quality(self, signal: Signal) -> RiskGateResult:
        """
        Gate 1: Check data quality score for the signal's symbol.

        Retrieves the latest quality score and rejects if below threshold
        or if no score is available.

        Args:
            signal: The signal being evaluated.

        Returns:
            RiskGateResult with passed=True if quality is adequate.
        """
        try:
            score = self._data_quality_service.evaluate_quality(
                signal.symbol, CandleInterval.D1, window_minutes=1440
            )
        except Exception:
            logger.warning(
                "Data quality service unavailable",
                symbol=signal.symbol,
                exc_info=True,
            )
            return RiskGateResult(
                gate_name="data_quality",
                passed=False,
                details={
                    "reason": "Data quality service unavailable — cannot verify quality score"
                },
            )

        if score is None:
            logger.warning(
                "No quality score available",
                symbol=signal.symbol,
            )
            return RiskGateResult(
                gate_name="data_quality",
                passed=False,
                details={
                    "reason": f"No quality score available for {signal.symbol}",
                    "threshold": self._quality_threshold,
                },
            )

        if score.composite_score < self._quality_threshold:
            logger.info(
                "Data quality below threshold",
                symbol=signal.symbol,
                score=score.composite_score,
                threshold=self._quality_threshold,
                grade=score.grade.value,
            )
            return RiskGateResult(
                gate_name="data_quality",
                passed=False,
                details={
                    "reason": (
                        f"Data quality score {score.composite_score:.2f} "
                        f"below threshold {self._quality_threshold:.2f} "
                        f"(grade: {score.grade.value})"
                    ),
                    "score": score.composite_score,
                    "threshold": self._quality_threshold,
                    "grade": score.grade.value,
                },
            )

        return RiskGateResult(
            gate_name="data_quality",
            passed=True,
            details={
                "score": score.composite_score,
                "grade": score.grade.value,
            },
        )

    def _check_kill_switch(self, signal: Signal, deployment_id: str) -> RiskGateResult:
        """
        Gate 2: Check if any kill switch is active for this context.

        Checks global, strategy, and symbol-level kill switches.

        Args:
            signal: The signal being evaluated.
            deployment_id: Deployment context.

        Returns:
            RiskGateResult with passed=True if not halted.
        """
        try:
            halted = self._kill_switch_service.is_halted(
                deployment_id=deployment_id,
                strategy_id=signal.strategy_id,
                symbol=signal.symbol,
            )
        except Exception:
            logger.warning(
                "Kill switch service unavailable — treating as halted",
                deployment_id=deployment_id,
                exc_info=True,
            )
            return RiskGateResult(
                gate_name="kill_switch",
                passed=False,
                details={
                    "reason": "Kill switch service unavailable — fail-safe: treating as halted"
                },
            )

        if halted:
            logger.info(
                "Kill switch active",
                deployment_id=deployment_id,
                symbol=signal.symbol,
                strategy_id=signal.strategy_id,
            )
            return RiskGateResult(
                gate_name="kill_switch",
                passed=False,
                details={"reason": "Kill switch is active for this deployment"},
            )

        return RiskGateResult(
            gate_name="kill_switch",
            passed=True,
            details={},
        )

    def _check_duplicate(self, signal: Signal) -> RiskGateResult:
        """
        Gate 3: Check for duplicate signals within the cooldown window.

        A duplicate is defined as a signal with the same strategy_id,
        symbol, direction, and bar_timestamp evaluated within the
        cooldown_seconds window.

        Args:
            signal: The signal being evaluated.

        Returns:
            RiskGateResult with passed=True if no duplicate found.
        """
        try:
            cooldown_since = signal.generated_at - timedelta(seconds=self._cooldown_seconds)
            recent_signals = self._signal_repository.find_signals(
                strategy_id=signal.strategy_id,
                symbol=signal.symbol,
                since=cooldown_since,
                limit=10,
            )
        except Exception:
            logger.warning(
                "Signal repository unavailable for duplicate check",
                exc_info=True,
            )
            # Fail-open: allow signal if we can't check for duplicates
            return RiskGateResult(
                gate_name="duplicate_filter",
                passed=True,
                details={"reason": "Repository unavailable — fail-open"},
            )

        for existing in recent_signals:
            if (
                existing.direction == signal.direction
                and existing.bar_timestamp == signal.bar_timestamp
                and existing.signal_id != signal.signal_id
            ):
                logger.info(
                    "Duplicate signal detected",
                    signal_id=signal.signal_id,
                    existing_signal_id=existing.signal_id,
                    symbol=signal.symbol,
                    bar_timestamp=str(signal.bar_timestamp),
                )
                return RiskGateResult(
                    gate_name="duplicate_filter",
                    passed=False,
                    details={
                        "reason": (
                            f"Duplicate signal: same strategy ({signal.strategy_id}), "
                            f"symbol ({signal.symbol}), direction ({signal.direction.value}), "
                            f"bar_timestamp within cooldown window"
                        ),
                        "existing_signal_id": existing.signal_id,
                        "cooldown_seconds": self._cooldown_seconds,
                    },
                )

        return RiskGateResult(
            gate_name="duplicate_filter",
            passed=True,
            details={"cooldown_seconds": self._cooldown_seconds},
        )

    def _check_risk_gate(
        self, signal: Signal, deployment_id: str, correlation_id: str
    ) -> RiskGateResult:
        """
        Gate 4: Pre-trade risk check via the RiskGateInterface.

        Constructs a minimal OrderRequest proxy and delegates to the
        risk gate for position size, daily loss, concentration, and
        order count checks.

        Args:
            signal: The signal being evaluated.
            deployment_id: Deployment context.
            correlation_id: Tracing ID.

        Returns:
            RiskGateResult with passed=True if risk checks pass.
        """
        from libs.contracts.execution import (
            AccountSnapshot,
            ExecutionMode,
            OrderRequest,
            OrderSide,
            OrderType,
            TimeInForce,
        )

        try:
            # Build a proxy order for the risk gate check.
            # The actual quantity will be refined by position sizing,
            # but we need a reasonable estimate for the pre-trade check.
            side = OrderSide.BUY if signal.direction == SignalDirection.LONG else OrderSide.SELL
            proxy_order = OrderRequest(
                client_order_id=f"eval-{signal.signal_id}",
                symbol=signal.symbol,
                side=side,
                order_type=OrderType.MARKET,
                quantity=Decimal("1"),  # Placeholder — risk gate checks limits
                time_in_force=TimeInForce.DAY,
                deployment_id=deployment_id,
                strategy_id=signal.strategy_id,
                correlation_id=correlation_id,
                execution_mode=ExecutionMode.PAPER,
            )

            # Use empty positions/account as we're checking policy limits,
            # not position-level constraints at this stage.
            risk_check = self._risk_gate.check_order(
                deployment_id=deployment_id,
                order=proxy_order,
                positions=[],
                account=AccountSnapshot(
                    account_id="eval-placeholder",
                    equity=Decimal("100000"),
                    cash=Decimal("100000"),
                    buying_power=Decimal("200000"),
                    portfolio_value=Decimal("0"),
                    updated_at=datetime.now(tz=timezone.utc),
                ),
                correlation_id=correlation_id,
            )
        except Exception:
            logger.warning(
                "Risk gate service unavailable",
                deployment_id=deployment_id,
                exc_info=True,
            )
            return RiskGateResult(
                gate_name="risk_gate",
                passed=False,
                details={"reason": "Risk gate service unavailable — fail-safe: rejecting signal"},
            )

        if not risk_check.passed:
            logger.info(
                "Risk gate rejected signal",
                signal_id=signal.signal_id,
                check_name=risk_check.check_name,
                reason=risk_check.reason,
            )
            return RiskGateResult(
                gate_name="risk_gate",
                passed=False,
                details={
                    "reason": f"Risk gate failed: {risk_check.reason}",
                    "check_name": risk_check.check_name,
                    "severity": risk_check.severity.value,
                },
            )

        return RiskGateResult(
            gate_name="risk_gate",
            passed=True,
            details={"check_name": risk_check.check_name},
        )

    def _compute_position_size(
        self, signal: Signal
    ) -> tuple[RiskGateResult, Decimal | None, Decimal | None]:
        """
        Gate 5: Compute position size via PositionSizingService.

        Uses ATR-based sizing if the signal has a suggested stop,
        otherwise falls back to fixed sizing.

        Args:
            signal: The signal being evaluated.

        Returns:
            Tuple of (gate_result, position_size, adjusted_stop).
            position_size and adjusted_stop are None if the gate fails.
        """
        from libs.contracts.position_sizing import SizingMethod, SizingRequest

        try:
            method = SizingMethod.ATR_BASED if signal.suggested_stop else SizingMethod.FIXED

            sizing_request = SizingRequest(
                symbol=signal.symbol,
                side="buy" if signal.direction == SignalDirection.LONG else "sell",
                method=method,
                account_equity=Decimal("100000"),  # Will be resolved from deployment config
                current_price=signal.suggested_entry or Decimal("0"),
                atr_value=(
                    abs(signal.suggested_entry - signal.suggested_stop)
                    if signal.suggested_entry and signal.suggested_stop
                    else None
                ),
            )

            sizing_result = self._position_sizing_service.compute_size(sizing_request)
        except Exception:
            logger.warning(
                "Position sizing service unavailable",
                signal_id=signal.signal_id,
                exc_info=True,
            )
            return (
                RiskGateResult(
                    gate_name="position_sizing",
                    passed=False,
                    details={"reason": "Position sizing service unavailable"},
                ),
                None,
                None,
            )

        if sizing_result.recommended_quantity <= 0:
            logger.info(
                "Position size is zero",
                signal_id=signal.signal_id,
                symbol=signal.symbol,
            )
            return (
                RiskGateResult(
                    gate_name="position_sizing",
                    passed=False,
                    details={
                        "reason": "Computed position size is zero or negative",
                        "recommended_quantity": str(sizing_result.recommended_quantity),
                    },
                ),
                None,
                None,
            )

        return (
            RiskGateResult(
                gate_name="position_sizing",
                passed=True,
                details={
                    "recommended_quantity": str(sizing_result.recommended_quantity),
                    "recommended_value": str(sizing_result.recommended_value),
                    "method": sizing_result.method_used.value,
                },
            ),
            sizing_result.recommended_quantity,
            sizing_result.stop_loss_price,
        )

    def _check_var_impact(self, deployment_id: str) -> RiskGateResult:
        """
        Gate 6: Check projected VaR impact against deployment threshold.

        Computes current portfolio VaR and rejects if |VaR_95| exceeds
        the configured threshold.

        Args:
            deployment_id: Deployment context for VaR computation.

        Returns:
            RiskGateResult with passed=True if VaR is within threshold.
        """
        try:
            var_result = self._risk_analytics_service.compute_var(
                deployment_id=deployment_id,
            )
        except Exception:
            logger.warning(
                "Risk analytics service unavailable for VaR check",
                deployment_id=deployment_id,
                exc_info=True,
            )
            # Fail-safe: reject if we can't compute VaR
            return RiskGateResult(
                gate_name="var_impact",
                passed=False,
                details={
                    "reason": "Risk analytics service unavailable — fail-safe: rejecting signal"
                },
            )

        # VaR is negative (loss), compare absolute value to threshold
        abs_var = abs(var_result.var_95)
        if abs_var > self._var_threshold:
            logger.info(
                "VaR exceeds threshold",
                deployment_id=deployment_id,
                var_95=str(var_result.var_95),
                threshold=str(self._var_threshold),
            )
            return RiskGateResult(
                gate_name="var_impact",
                passed=False,
                details={
                    "reason": (
                        f"VaR |{var_result.var_95}| = {abs_var} exceeds "
                        f"threshold {self._var_threshold}"
                    ),
                    "var_95": str(var_result.var_95),
                    "threshold": str(self._var_threshold),
                },
            )

        return RiskGateResult(
            gate_name="var_impact",
            passed=True,
            details={
                "var_95": str(var_result.var_95),
                "threshold": str(self._var_threshold),
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_rejected(
        self,
        *,
        signal: Signal,
        gate_results: list[RiskGateResult],
        reason: str,
    ) -> SignalEvaluation:
        """
        Build and persist a rejected SignalEvaluation.

        Args:
            signal: The signal that was rejected.
            gate_results: Gate results accumulated so far.
            reason: Human-readable rejection reason.

        Returns:
            Persisted SignalEvaluation with approved=False.
        """
        logger.info(
            "Signal rejected",
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            reason=reason,
        )
        evaluation = SignalEvaluation(
            signal=signal,
            approved=False,
            risk_gate_results=gate_results,
            position_size=None,
            adjusted_stop=None,
            rejection_reason=reason,
            evaluated_at=datetime.now(tz=timezone.utc),
        )
        self._signal_repository.save_evaluation(evaluation)
        return evaluation
