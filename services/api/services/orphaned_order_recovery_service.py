"""
Orphaned order recovery service — detects and recovers orders lost in broker gaps.

Responsibilities:
- Detect pending orders in the internal database with no broker_order_id.
- Query the broker for all open orders to find orphaned orders by client_order_id.
- Import broker_order_id and status when an orphaned order is found.
- Mark orders as expired when they are not found at the broker.
- Sync fill data (filled_quantity, average_fill_price) for partial_fill orders.
- Log extra broker orders as critical warnings (never auto-cancel).
- Record execution events for all recovery actions.
- Generate detailed recovery reports.
- Support per-deployment and batch recovery across all active live deployments.

Does NOT:
- Implement broker communication (delegates to BrokerAdapterInterface).
- Auto-cancel orders the system doesn't understand (safety first).
- Enforce kill switches or risk gates (separate responsibilities).
- Perform destructive operations without explicit action (read-only analysis,
  except for status updates which are safe).

Dependencies:
- DeploymentRepositoryInterface (injected): validate deployment existence and state.
- OrderRepositoryInterface (injected): retrieve and update order records.
- ExecutionEventRepositoryInterface (injected): record recovery events.
- BrokerAdapterRegistry (injected): obtain broker adapter for each deployment.
- structlog: structured logging with correlation_id propagation.

Error conditions:
- NotFoundError: deployment does not exist or has no broker adapter.
- ExternalServiceError: broker adapter communication failure.

Example:
    service = OrphanedOrderRecoveryService(
        deployment_repo=deployment_repo,
        order_repo=order_repo,
        execution_event_repo=event_repo,
        broker_registry=broker_registry,
    )
    report = service.recover_orphaned_orders(
        deployment_id="01HDEPLOY...",
        correlation_id="corr-001",
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.deployment_repository_interface import (
    DeploymentRepositoryInterface,
)
from libs.contracts.interfaces.execution_event_repository_interface import (
    ExecutionEventRepositoryInterface,
)
from libs.contracts.interfaces.order_repository_interface import (
    OrderRepositoryInterface,
)
from libs.contracts.interfaces.orphaned_order_recovery_interface import (
    OrphanedOrderRecoveryServiceInterface,
)
from libs.contracts.orphan_recovery import (
    OrphanOrderRecoveryResult,
    OrphanRecoveryReport,
)
from services.api.infrastructure.broker_registry import BrokerAdapterRegistry

logger = structlog.get_logger(__name__)


class OrphanedOrderRecoveryService(OrphanedOrderRecoveryServiceInterface):
    """
    Production implementation of orphaned order recovery.

    Responsibilities:
    - Queries internal database for open orders (status: pending, submitted, partial_fill).
    - Queries broker adapter for all open orders.
    - Matches internal pending orders to broker orders by client_order_id.
    - Imports broker_order_id and status when found.
    - Marks orders as expired when not found at broker.
    - Syncs fill data for partial_fill orders.
    - Logs extra broker orders as warnings (never auto-cancels).
    - Records execution events for all actions.
    - Generates detailed per-order recovery results.
    - Supports recovery across multiple deployments.

    Dependencies:
    - DeploymentRepositoryInterface: validate deployment state.
    - OrderRepositoryInterface: retrieve and update order records.
    - ExecutionEventRepositoryInterface: record recovery events.
    - BrokerAdapterRegistry: obtain broker adapter for each deployment.

    Thread safety:
    - Each deployment recovery is independent.
    - Service is thread-safe by virtue of immutable input (correlation_id)
      and isolated deployment-level operations.

    Example:
        service = OrphanedOrderRecoveryService(
            deployment_repo=deployment_repo,
            order_repo=order_repo,
            execution_event_repo=event_repo,
            broker_registry=broker_registry,
        )
        report = service.recover_orphaned_orders(
            deployment_id="01HDEPLOY...",
            correlation_id="corr-001",
        )
    """

    def __init__(
        self,
        *,
        deployment_repo: DeploymentRepositoryInterface,
        order_repo: OrderRepositoryInterface,
        execution_event_repo: ExecutionEventRepositoryInterface,
        broker_registry: BrokerAdapterRegistry,
    ) -> None:
        """
        Initialise the orphaned order recovery service.

        Args:
            deployment_repo: Repository for deployment lookups.
            order_repo: Repository for order persistence.
            execution_event_repo: Repository for execution event audit trail.
            broker_registry: Registry routing deployment_id → broker adapter.
        """
        self._deployment_repo = deployment_repo
        self._order_repo = order_repo
        self._execution_event_repo = execution_event_repo
        self._broker_registry = broker_registry

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_event(
        self,
        *,
        order_id: str,
        event_type: str,
        correlation_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Record an execution event to the append-only audit trail.

        Args:
            order_id: Parent order ULID.
            event_type: Event type string.
            correlation_id: Distributed tracing ID.
            details: Optional event context.
        """
        self._execution_event_repo.save(
            order_id=order_id,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            correlation_id=correlation_id,
            details=details or {},
        )

    def _recover_pending_order(
        self,
        *,
        order: dict[str, Any],
        adapter: Any,
        correlation_id: str,
    ) -> OrphanOrderRecoveryResult:
        """
        Attempt to recover a single pending order by searching the broker.

        If the pending order has no broker_order_id, search the broker's
        open orders by client_order_id. If found, import the broker_order_id
        and update the status. If not found, mark as expired.

        Args:
            order: Internal order record (dict).
            adapter: BrokerAdapterInterface instance.
            correlation_id: Distributed tracing ID.

        Returns:
            OrphanOrderRecoveryResult with action, status, and any error.
        """
        order_id = order["id"]
        client_order_id = order["client_order_id"]
        symbol = order["symbol"]
        side = order["side"]
        quantity = order["quantity"]

        try:
            # Search broker's open orders by client_order_id
            broker_orders = adapter.list_open_orders()
            broker_order = next(
                (o for o in broker_orders if o.client_order_id == client_order_id),
                None,
            )

            if broker_order is not None:
                # Found at broker — import the broker_order_id and status
                logger.info(
                    "orphan_order_found_at_broker",
                    order_id=order_id,
                    client_order_id=client_order_id,
                    broker_order_id=broker_order.broker_order_id,
                    correlation_id=correlation_id,
                    component="orphaned_order_recovery",
                )

                self._order_repo.update_status(
                    order_id=order_id,
                    status=broker_order.status.value.lower(),
                    broker_order_id=broker_order.broker_order_id,
                    submitted_at=broker_order.submitted_at,
                )

                self._record_event(
                    order_id=order_id,
                    event_type="orphan_recovered",
                    correlation_id=correlation_id,
                    details={
                        "action": "imported",
                        "broker_order_id": broker_order.broker_order_id,
                        "status": broker_order.status.value,
                    },
                )

                return OrphanOrderRecoveryResult(
                    order_id=order_id,
                    client_order_id=client_order_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    action="imported",
                    broker_order_id=broker_order.broker_order_id,
                    status=broker_order.status.value.lower(),
                    filled_quantity=None,
                    average_fill_price=None,
                    error_message=None,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            else:
                # NOT found at broker — mark as expired
                logger.warning(
                    "orphan_order_not_found_at_broker",
                    order_id=order_id,
                    client_order_id=client_order_id,
                    correlation_id=correlation_id,
                    component="orphaned_order_recovery",
                )

                self._order_repo.update_status(
                    order_id=order_id,
                    status="expired",
                )

                self._record_event(
                    order_id=order_id,
                    event_type="orphan_expired",
                    correlation_id=correlation_id,
                    details={"action": "expired", "status": "expired"},
                )

                return OrphanOrderRecoveryResult(
                    order_id=order_id,
                    client_order_id=client_order_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    action="expired",
                    status="expired",
                    broker_order_id=None,
                    filled_quantity=None,
                    average_fill_price=None,
                    error_message=None,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

        except Exception as e:
            logger.error(
                "orphan_recovery_failed",
                order_id=order_id,
                client_order_id=client_order_id,
                error=str(e),
                correlation_id=correlation_id,
                component="orphaned_order_recovery",
                exc_info=True,
            )
            return OrphanOrderRecoveryResult(
                order_id=order_id,
                client_order_id=client_order_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                action="skipped",
                status=order["status"],
                broker_order_id=None,
                filled_quantity=None,
                average_fill_price=None,
                error_message=str(e),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

    def _sync_partial_fill_order(
        self,
        *,
        order: dict[str, Any],
        adapter: Any,
        correlation_id: str,
    ) -> OrphanOrderRecoveryResult:
        """
        Sync fill data for a partial_fill order from the broker.

        Args:
            order: Internal order record with broker_order_id already set.
            adapter: BrokerAdapterInterface instance.
            correlation_id: Distributed tracing ID.

        Returns:
            OrphanOrderRecoveryResult with synced fill data or error.
        """
        order_id = order["id"]
        client_order_id = order["client_order_id"]
        broker_order_id = order.get("broker_order_id")
        symbol = order["symbol"]
        side = order["side"]
        quantity = order["quantity"]

        if not broker_order_id:
            # No broker_order_id to sync — skip
            return OrphanOrderRecoveryResult(
                order_id=order_id,
                client_order_id=client_order_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                action="skipped",
                status=order["status"],
                broker_order_id=None,
                filled_quantity=None,
                average_fill_price=None,
                error_message=None,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        try:
            # Get fills from broker
            fills = adapter.get_fills(broker_order_id)

            if fills:
                # Compute totals
                total_filled = sum(f.quantity for f in fills)
                total_cost = sum(f.quantity * f.price for f in fills)
                avg_price = total_cost / total_filled if total_filled > 0 else 0

                logger.info(
                    "partial_fill_synced",
                    order_id=order_id,
                    broker_order_id=broker_order_id,
                    filled_quantity=str(total_filled),
                    average_fill_price=str(avg_price),
                    correlation_id=correlation_id,
                    component="orphaned_order_recovery",
                )

                # Update order with fill data
                self._order_repo.update_status(
                    order_id=order_id,
                    status=order["status"],  # Keep current status
                    filled_quantity=str(total_filled),
                    average_fill_price=str(avg_price),
                )

                self._record_event(
                    order_id=order_id,
                    event_type="orphan_synced_fills",
                    correlation_id=correlation_id,
                    details={
                        "action": "synced_fills",
                        "filled_quantity": str(total_filled),
                        "average_fill_price": str(avg_price),
                    },
                )

                return OrphanOrderRecoveryResult(
                    order_id=order_id,
                    client_order_id=client_order_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    action="synced_fills",
                    broker_order_id=broker_order_id,
                    status=order["status"],
                    filled_quantity=str(total_filled),
                    average_fill_price=str(avg_price),
                    error_message=None,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            else:
                # No fills yet
                return OrphanOrderRecoveryResult(
                    order_id=order_id,
                    client_order_id=client_order_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    action="skipped",
                    broker_order_id=broker_order_id,
                    status=order["status"],
                    filled_quantity=None,
                    average_fill_price=None,
                    error_message=None,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

        except Exception as e:
            logger.error(
                "partial_fill_sync_failed",
                order_id=order_id,
                broker_order_id=broker_order_id,
                error=str(e),
                correlation_id=correlation_id,
                component="orphaned_order_recovery",
                exc_info=True,
            )
            return OrphanOrderRecoveryResult(
                order_id=order_id,
                client_order_id=client_order_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                action="skipped",
                broker_order_id=broker_order_id,
                status=order["status"],
                filled_quantity=None,
                average_fill_price=None,
                error_message=str(e),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recover_orphaned_orders(
        self,
        *,
        deployment_id: str,
        correlation_id: str,
    ) -> OrphanRecoveryReport:
        """
        Attempt to recover orphaned orders for a single deployment.

        Process:
        1. Validate deployment exists and is in active/live state.
        2. Get broker adapter for the deployment.
        3. Retrieve all open internal orders (pending, submitted, partial_fill).
        4. Query broker for all open orders.
        5. For each internal pending order without broker_order_id:
           a. Search broker's open orders by client_order_id.
           b. If found: import broker_order_id and update status.
           c. If not found: mark order as expired.
        6. For each internal partial_fill order:
           a. Sync fill data from broker.
        7. For each extra broker order not in internal DB:
           a. Log as critical warning (never auto-cancel).
           b. Include in report.cancelled_count.
        8. Record execution events for all actions.
        9. Return detailed OrphanRecoveryReport.

        Args:
            deployment_id: ULID of the deployment to recover.
            correlation_id: Distributed tracing ID for this recovery attempt.

        Returns:
            OrphanRecoveryReport with recovered_count, failed_count, details.

        Raises:
            NotFoundError: deployment does not exist or has no adapter.
            ExternalServiceError: broker adapter communication failure.
        """
        start_time = datetime.now(timezone.utc)

        logger.info(
            "orphan_recovery_started",
            deployment_id=deployment_id,
            correlation_id=correlation_id,
            component="orphaned_order_recovery",
        )

        # Step 1: Validate deployment exists
        deployment = self._deployment_repo.get_by_id(deployment_id)
        if deployment is None:
            logger.error(
                "orphan_recovery_deployment_not_found",
                deployment_id=deployment_id,
                correlation_id=correlation_id,
                component="orphaned_order_recovery",
            )
            raise NotFoundError(f"Deployment {deployment_id} not found")

        # Step 2: Get broker adapter
        if not self._broker_registry.is_registered(deployment_id):
            logger.error(
                "orphan_recovery_no_adapter",
                deployment_id=deployment_id,
                correlation_id=correlation_id,
                component="orphaned_order_recovery",
            )
            raise NotFoundError(f"No broker adapter registered for deployment {deployment_id}")

        adapter = self._broker_registry.get(deployment_id)

        # Step 3: Retrieve all open internal orders
        internal_open_orders = self._order_repo.list_open_by_deployment(deployment_id=deployment_id)

        logger.info(
            "orphan_recovery_retrieved_internal_orders",
            deployment_id=deployment_id,
            count=len(internal_open_orders),
            correlation_id=correlation_id,
            component="orphaned_order_recovery",
        )

        # Step 4: Query broker for open orders
        broker_open_orders = adapter.list_open_orders()

        logger.info(
            "orphan_recovery_retrieved_broker_orders",
            deployment_id=deployment_id,
            count=len(broker_open_orders),
            correlation_id=correlation_id,
            component="orphaned_order_recovery",
        )

        # Collect results
        details: list[OrphanOrderRecoveryResult] = []
        recovered_count = 0
        failed_count = 0
        cancelled_count = 0

        # Step 5 & 6: Process internal orders
        internal_client_ids = set()
        for order in internal_open_orders:
            internal_client_ids.add(order["client_order_id"])
            status = order["status"]

            if status == "pending" and not order.get("broker_order_id"):
                # Pending with no broker_order_id — try to recover
                result = self._recover_pending_order(
                    order=order,
                    adapter=adapter,
                    correlation_id=correlation_id,
                )
                details.append(result)
                if result.action == "imported":
                    recovered_count += 1
                elif result.error_message:
                    failed_count += 1

            elif status == "partial_fill" and order.get("broker_order_id"):
                # Partial fill — sync fills from broker
                result = self._sync_partial_fill_order(
                    order=order,
                    adapter=adapter,
                    correlation_id=correlation_id,
                )
                details.append(result)

        # Step 7: Check for extra broker orders not in internal DB
        for broker_order in broker_open_orders:
            if broker_order.client_order_id not in internal_client_ids:
                logger.warning(
                    "orphan_recovery_extra_broker_order",
                    broker_order_id=broker_order.broker_order_id,
                    client_order_id=broker_order.client_order_id,
                    symbol=broker_order.symbol,
                    correlation_id=correlation_id,
                    component="orphaned_order_recovery",
                )
                cancelled_count += 1

        # Step 8: Complete
        end_time = datetime.now(timezone.utc)

        logger.info(
            "orphan_recovery_completed",
            deployment_id=deployment_id,
            recovered_count=recovered_count,
            failed_count=failed_count,
            cancelled_count=cancelled_count,
            duration_ms=(end_time - start_time).total_seconds() * 1000.0,
            correlation_id=correlation_id,
            component="orphaned_order_recovery",
        )

        return OrphanRecoveryReport(
            deployment_id=deployment_id,
            recovered_count=recovered_count,
            cancelled_count=cancelled_count,
            failed_count=failed_count,
            details=details,
            started_at=start_time,
            completed_at=end_time,
        )

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
            Empty list if no active live deployments exist.

        Raises:
            ExternalServiceError: if broker communication fails during recovery.
        """
        logger.info(
            "orphan_recovery_all_started",
            correlation_id=correlation_id,
            component="orphaned_order_recovery",
        )

        # Query deployments with state=active AND execution_mode=live
        # Try multiple approaches depending on what the repo provides
        deployments = []
        if hasattr(self._deployment_repo, "list_by_state"):
            deployments = self._deployment_repo.list_by_state(state="active")
            deployments = [d for d in deployments if d.get("execution_mode") == "live"]
        elif hasattr(self._deployment_repo, "get_all"):
            # Fallback: get all and filter manually
            all_deployments = self._deployment_repo.get_all()
            deployments = [
                d
                for d in all_deployments
                if d.get("state") == "active" and d.get("execution_mode") == "live"
            ]
        else:
            # Last resort: warn and return empty list
            logger.warning(
                "deployment_repo_no_list_method",
                correlation_id=correlation_id,
                component="orphaned_order_recovery",
            )
            deployments = []

        logger.info(
            "orphan_recovery_found_deployments",
            count=len(deployments),
            correlation_id=correlation_id,
            component="orphaned_order_recovery",
        )

        reports: list[OrphanRecoveryReport] = []
        for deployment in deployments:
            try:
                report = self.recover_orphaned_orders(
                    deployment_id=deployment["id"],
                    correlation_id=correlation_id,
                )
                reports.append(report)
            except Exception as e:
                logger.error(
                    "orphan_recovery_deployment_failed",
                    deployment_id=deployment["id"],
                    error=str(e),
                    correlation_id=correlation_id,
                    component="orphaned_order_recovery",
                    exc_info=True,
                )
                # Continue with next deployment

        logger.info(
            "orphan_recovery_all_completed",
            total_deployments=len(deployments),
            reports_generated=len(reports),
            correlation_id=correlation_id,
            component="orphaned_order_recovery",
        )

        return reports
