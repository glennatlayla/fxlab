"""
Orphaned order recovery service interface (port).

Responsibilities:
- Define the abstract contract for detecting and recovering orphaned orders.
- Orphaned orders are those that exist at the broker but not yet recorded
  in the internal database due to crashes after submission but before
  acknowledgment.
- Support recovery per-deployment and across all deployments.

Does NOT:
- Implement recovery logic.
- Know about specific broker APIs (Alpaca, Schwab, etc.).
- Perform I/O directly (delegates to repositories and broker adapters).
- Auto-cancel extra broker orders (safety: leaves it to operators).

Dependencies:
- OrphanRecoveryReport: from libs.contracts.orphan_recovery

Error conditions:
- NotFoundError: deployment does not exist or has no adapter.
- ExternalServiceError: broker adapter communication failure.

Example:
    repo: OrphanedOrderRecoveryServiceInterface = OrphanedOrderRecoveryService(...)
    report = repo.recover_orphaned_orders(
        deployment_id="01HDEPLOY...",
        correlation_id="corr-001",
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.orphan_recovery import OrphanRecoveryReport


class OrphanedOrderRecoveryServiceInterface(ABC):
    """
    Port interface for orphaned order recovery.

    Orphaned orders are those that exist at the broker with capital at risk
    but have not yet been recorded in the internal database. This occurs when:
    - System submits an order to the broker.
    - Broker acknowledges and creates the order with a broker_order_id.
    - System crashes before recording the broker_order_id internally.
    - On restart, the system knows nothing about the order.

    Recovery process:
    1. Retrieve all open internal orders (status in pending, submitted, partial_fill).
    2. Query the broker for all open orders at that deployment.
    3. For each internal pending order without a broker_order_id, search the
       broker's open orders by client_order_id to find and import it.
    4. For each internal partial_fill order, sync latest fill data from the broker.
    5. For each extra broker order not found internally, log as a critical warning
       and include in the report (but do NOT auto-cancel — safety first).
    6. Record execution events for each recovery action.
    7. Return a detailed report.

    Implementations:
    - OrphanedOrderRecoveryService: production implementation with real repos/adapters.

    Safety guarantees:
    - Never auto-cancels orders the system doesn't understand.
    - Records detailed execution events for audit trail.
    - Uses structured logging with correlation_id for tracing.
    - Reports all findings with per-order details.
    """

    @abstractmethod
    def recover_orphaned_orders(
        self,
        *,
        deployment_id: str,
        correlation_id: str,
    ) -> OrphanRecoveryReport:
        """
        Attempt to recover orphaned orders for a single deployment.

        Process:
        1. Validate deployment exists and has a broker adapter.
        2. Retrieve all open internal orders for the deployment.
        3. Query broker for all open orders.
        4. Match by client_order_id; import broker_order_id if found.
        5. Sync fill data for partial_fill orders.
        6. Log extra broker orders as critical warnings.
        7. Record execution events for all actions.
        8. Return detailed report.

        Args:
            deployment_id: ULID of the deployment to recover.
            correlation_id: Distributed tracing ID for this recovery attempt.

        Returns:
            OrphanRecoveryReport with recovered_count, failed_count, and
            per-order details.

        Raises:
            NotFoundError: deployment does not exist or has no broker adapter.
            ExternalServiceError: broker adapter communication failure.

        Example:
            report = service.recover_orphaned_orders(
                deployment_id="01HDEPLOY...",
                correlation_id="corr-001",
            )
            # report.recovered_count >= 0
            # report.failed_count >= 0
            # len(report.details) == recovered_count + failed_count + ...
        """
        ...

    @abstractmethod
    def recover_all_deployments(
        self,
        *,
        correlation_id: str,
    ) -> list[OrphanRecoveryReport]:
        """
        Attempt to recover orphaned orders across all active live deployments.

        Retrieves all deployments with state='active' and execution_mode='live',
        then runs recovery for each in sequence.

        Args:
            correlation_id: Distributed tracing ID for this batch recovery.

        Returns:
            List of OrphanRecoveryReport, one per deployment recovered.
            If no active live deployments exist, returns an empty list.

        Raises:
            ExternalServiceError: broker communication failure in recovery.
            NotFoundError: if a deployment exists but has no adapter
                (usually indicates misconfiguration).

        Example:
            reports = service.recover_all_deployments(correlation_id="corr-001")
            for report in reports:
                logger.info(f"Recovered {report.recovered_count} orders", ...)
        """
        ...
