"""
Signal evaluation service interface (port).

Responsibilities:
- Define the abstract contract for signal evaluation through risk gates.
- Each raw signal passes through a multi-gate pipeline before approval.

Does NOT:
- Implement gate logic (concrete service responsibility).
- Persist evaluations (delegates to SignalRepositoryInterface).
- Generate signals (SignalStrategyInterface responsibility).

Dependencies:
- libs.contracts.signal: Signal, SignalEvaluation

Error conditions:
- ExternalServiceError: if any downstream service is unavailable.

Example:
    service: SignalEvaluationServiceInterface = SignalEvaluationService(...)
    evaluation = service.evaluate(signal, deployment_config)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.signal import Signal, SignalEvaluation


class SignalEvaluationServiceInterface(ABC):
    """
    Port interface for the signal evaluation pipeline.

    The pipeline evaluates a raw Signal through ordered gates:
    1. Data quality gate
    2. Kill switch gate
    3. Risk gate
    4. Position sizing
    5. VaR impact check
    6. Duplicate signal filter

    A signal is approved only if all gates pass.

    Responsibilities:
    - Orchestrate signal evaluation through all risk gates.
    - Return a fully-constructed SignalEvaluation with gate results.

    Does NOT:
    - Generate signals.
    - Execute orders.
    - Persist results (caller may choose to persist).

    Example:
        evaluation = service.evaluate(
            signal=signal,
            deployment_id="deploy-001",
            execution_mode=ExecutionMode.PAPER,
            correlation_id="corr-001",
        )
        if evaluation.approved:
            # proceed to execution
            ...
    """

    @abstractmethod
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

        Gates are executed in order and fail-fast on first rejection.
        If all gates pass, the signal is approved with computed position
        size and adjusted stop.

        Args:
            signal: The raw signal to evaluate.
            deployment_id: Deployment context for risk limits and config.
            execution_mode: Execution mode string (shadow/paper/live).
            correlation_id: Distributed tracing ID.

        Returns:
            SignalEvaluation with approved/rejected status, gate results,
            position size, and adjusted stop.

        Example:
            evaluation = service.evaluate(
                signal=signal,
                deployment_id="deploy-001",
                execution_mode="paper",
                correlation_id="corr-001",
            )
        """
