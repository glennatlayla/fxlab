"""
Partial fill monitor interface (port).

Responsibilities:
- Define the abstract contract for partial fill timeout monitoring.
- Specify the algorithm for checking, resolving, and auditing partial fills.
- Enable substitution of real and mock implementations without changing
  calling code.

Does NOT:
- Implement monitoring logic (service layer responsibility).
- Know about specific broker APIs or implementations.
- Contain business logic for timeout calculation.

Dependencies:
- libs.contracts.partial_fill: PartialFillPolicy, PartialFillResolution
- libs.contracts.errors: ExternalServiceError

Error conditions:
- ExternalServiceError: raised when broker communication fails.

Example:
    monitor: PartialFillMonitorInterface = PartialFillMonitorService(...)
    resolutions = monitor.check_partial_fills(
        deployment_id="01HDEPLOY...",
        policy=PartialFillPolicy(timeout_seconds=300),
        correlation_id="corr-abc",
    )
    for res in resolutions:
        logger.info("Partial fill resolved", extra={"action": res.action_taken})
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.partial_fill import PartialFillPolicy, PartialFillResolution


class PartialFillMonitorInterface(ABC):
    """
    Port interface for partial fill monitoring and timeout resolution.

    Responsibilities:
    - Scan open orders for partial fill status.
    - Calculate elapsed time since submission.
    - Decide whether to cancel remaining, alert, or wait.
    - Sync latest status from broker to detect completions.
    - Record audit trail of all actions taken.

    Does NOT:
    - Enforce risk policies or safety gates (separate responsibility).
    - Know about specific broker APIs.
    - Manage deployment state or lifecycle.
    """

    @abstractmethod
    def check_partial_fills(
        self,
        *,
        deployment_id: str,
        policy: PartialFillPolicy,
        correlation_id: str,
    ) -> list[PartialFillResolution]:
        """
        Check all open orders in a deployment for partial fill timeout.

        For each order with status "partial_fill":
        1. Sync latest status from broker via get_order().
        2. If broker says fully filled: update internal status, record resolution.
        3. If still partial and elapsed time > policy.timeout_seconds:
           - If action_on_timeout == "cancel_remaining":
             * Call broker cancel_order() for the broker_order_id.
             * Update internal order status to "cancelled".
             * Record filled_quantity and cancelled_at.
           - If action_on_timeout == "alert_only":
             * Log a WARNING with order details.
             * Record resolution with action_taken="alert_sent".
        4. If still partial but within timeout: skip (will retry next cycle).

        Args:
            deployment_id: ULID of the deployment to monitor.
            policy: PartialFillPolicy controlling timeout and action behaviour.
            correlation_id: Correlation ID for distributed tracing and audit.

        Returns:
            List of PartialFillResolution records documenting all actions taken
            during this check cycle. May be empty if no partial fills detected
            or all partial fills are within timeout.

        Raises:
            ExternalServiceError: Broker communication fails (transient or permanent).
                Caller should retry on TransientError, escalate on permanent failure.
                Do NOT update order status on retriable failures.

        Example:
            policy = PartialFillPolicy(
                timeout_seconds=300,
                action_on_timeout="cancel_remaining",
            )
            resolutions = monitor.check_partial_fills(
                deployment_id="01HDEPLOY...",
                policy=policy,
                correlation_id="corr-abc",
            )
            # resolutions contains one entry per partial fill order checked,
            # with action_taken indicating what was done (if anything).
        """
        ...
