"""
Risk gate service interface (port).

Responsibilities:
- Define the abstract contract for pre-trade risk checking.
- Every order must pass through the risk gate before reaching any broker adapter.

Does NOT:
- Implement risk check logic (service responsibility).
- Persist risk events (delegates to repository).

Dependencies:
- libs.contracts.execution: OrderRequest, PositionSnapshot, AccountSnapshot.
- libs.contracts.risk: RiskCheckResult, RiskEvent, PreTradeRiskLimits.

Error conditions:
- NotFoundError: deployment_id does not have risk limits configured.

Example:
    gate: RiskGateInterface = RiskGateService(...)
    result = gate.check_order(
        deployment_id="01HDEPLOY...",
        order=order_request,
        positions=current_positions,
        account=account_snapshot,
        correlation_id="corr-001",
    )
    if not result.passed:
        # Reject order
        ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.execution import (
    AccountSnapshot,
    OrderRequest,
    PositionSnapshot,
)
from libs.contracts.risk import PreTradeRiskLimits, RiskCheckResult, RiskEvent


class RiskGateInterface(ABC):
    """
    Port interface for pre-trade risk gate.

    The risk gate is the mandatory checkpoint that every order must pass
    through before being routed to any broker adapter (shadow, paper, or live).

    Checks are ordered cheapest-first and fail-fast on first violation.

    Implementations:
    - RiskGateService — production implementation (M5)
    """

    @abstractmethod
    def check_order(
        self,
        *,
        deployment_id: str,
        order: OrderRequest,
        positions: list[PositionSnapshot],
        account: AccountSnapshot,
        correlation_id: str,
    ) -> RiskCheckResult:
        """
        Run all pre-trade risk checks on an order.

        Checks (in order, fail-fast):
        1. Order value limit
        2. Position size limit
        3. Concentration limit
        4. Open order count limit
        5. Daily loss limit

        Args:
            deployment_id: ULID of the deployment.
            order: The order to validate.
            positions: Current positions for the deployment.
            account: Current account snapshot.
            correlation_id: Distributed tracing ID.

        Returns:
            RiskCheckResult — passed=True if all checks pass,
            or the first failing check result.
        """
        ...

    @abstractmethod
    def set_risk_limits(
        self,
        *,
        deployment_id: str,
        limits: PreTradeRiskLimits,
    ) -> None:
        """
        Configure risk limits for a deployment.

        Args:
            deployment_id: ULID of the deployment.
            limits: Risk limits to apply.
        """
        ...

    @abstractmethod
    def get_risk_limits(
        self,
        *,
        deployment_id: str,
    ) -> PreTradeRiskLimits:
        """
        Get current risk limits for a deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            PreTradeRiskLimits for the deployment.

        Raises:
            NotFoundError: deployment has no risk limits configured.
        """
        ...

    @abstractmethod
    def get_risk_events(
        self,
        *,
        deployment_id: str,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[RiskEvent]:
        """
        Get risk events for a deployment.

        Args:
            deployment_id: ULID of the deployment.
            severity: Optional filter by severity level.
            limit: Maximum number of events to return.

        Returns:
            List of RiskEvent objects, most recent first.
        """
        ...

    @abstractmethod
    def enforce_order(
        self,
        *,
        deployment_id: str,
        order: OrderRequest,
        positions: list[PositionSnapshot],
        account: AccountSnapshot,
        correlation_id: str,
    ) -> None:
        """
        Enforce pre-trade risk checks — raise on failure.

        This is the structural enforcement method that execution services
        MUST call before submitting any order. Unlike check_order() which
        returns a result, enforce_order():
        1. Calls check_order() internally.
        2. Persists a RiskEvent for both pass and fail outcomes.
        3. Raises RiskGateRejectionError on failure (never returns a result).
        4. Returns silently on success.

        This design makes it impossible to accidentally ignore a failing
        risk check — the exception propagates unless explicitly caught.

        Args:
            deployment_id: ULID of the deployment.
            order: The order to validate.
            positions: Current positions for the deployment.
            account: Current account snapshot.
            correlation_id: Distributed tracing ID.

        Raises:
            RiskGateRejectionError: risk check failed — order must not
                be submitted. Includes check_name, severity, reason.
        """
        ...

    @abstractmethod
    def clear_risk_limits(
        self,
        *,
        deployment_id: str,
    ) -> None:
        """
        Remove risk limits for a deployment.

        Args:
            deployment_id: ULID of the deployment.

        Raises:
            NotFoundError: deployment has no risk limits configured.
        """
        ...
