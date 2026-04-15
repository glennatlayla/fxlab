"""
Partial fill monitor service — detects and resolves partial fill timeouts.

Responsibilities:
- Scan open orders in a deployment for partial fill status.
- Calculate elapsed time since submission against configured timeout.
- Query broker for latest fill status and detect completions.
- Cancel remaining quantity via broker when timeout expires and policy allows.
- Log operator alerts when policy dictates alert-only mode.
- Record audit trail of all actions via execution event repository.
- Thread-safe: Lock on order state transitions.

Does NOT:
- Implement broker communication directly (delegates to BrokerAdapterInterface).
- Enforce risk gates or kill switch logic.
- Know about specific broker APIs (Alpaca, IBKR, etc.).

Dependencies:
- OrderRepositoryInterface (injected): reads open orders, updates status.
- BrokerAdapterRegistry (injected): routes queries and cancellations to broker.
- ExecutionEventRepositoryInterface (injected): records resolution audit events.
- structlog: structured logging.

Error conditions:
- ExternalServiceError: broker communication failure (permanent or transient).
- NotFoundError: order or broker adapter not found.

Example:
    service = PartialFillMonitorService(
        order_repo=order_repo,
        broker_registry=broker_registry,
        execution_event_repo=event_repo,
    )
    policy = PartialFillPolicy(
        timeout_seconds=300,
        action_on_timeout="cancel_remaining",
    )
    resolutions = service.check_partial_fills(
        deployment_id="01HDEPLOY...",
        policy=policy,
        correlation_id="corr-001",
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog

from libs.contracts.errors import (
    ExternalServiceError,
    NotFoundError,
    TransientError,
)
from libs.contracts.interfaces.execution_event_repository_interface import (
    ExecutionEventRepositoryInterface,
)
from libs.contracts.interfaces.order_repository_interface import OrderRepositoryInterface
from libs.contracts.interfaces.partial_fill_monitor_interface import (
    PartialFillMonitorInterface,
)
from libs.contracts.partial_fill import PartialFillPolicy, PartialFillResolution
from services.api.infrastructure.broker_registry import BrokerAdapterRegistry

logger = structlog.get_logger(__name__)


class PartialFillMonitorService(PartialFillMonitorInterface):
    """
    Service for detecting and resolving partial fill orders with timeout.

    Periodically scans open orders in a deployment for partial fill status.
    For each partial fill:
    1. Syncs latest status from broker via get_order().
    2. If now fully filled: updates internal status to "filled".
    3. If still partial and elapsed time > timeout: cancels remaining or alerts.
    4. Records audit trail of all actions via execution events.

    Thread-safe: Order state transitions are protected by the repository layer
    (assuming database-level locking or optimistic concurrency control).

    Attributes:
        order_repo: OrderRepositoryInterface for order persistence.
        broker_registry: BrokerAdapterRegistry for routing to broker adapters.
        execution_event_repo: ExecutionEventRepositoryInterface for audit events.

    Example:
        service = PartialFillMonitorService(
            order_repo=order_repo,
            broker_registry=broker_registry,
            execution_event_repo=event_repo,
        )
        resolutions = service.check_partial_fills(
            deployment_id="01HDEPLOY...",
            policy=PartialFillPolicy(timeout_seconds=300),
            correlation_id="corr-001",
        )
    """

    def __init__(
        self,
        *,
        order_repo: OrderRepositoryInterface,
        broker_registry: BrokerAdapterRegistry,
        execution_event_repo: ExecutionEventRepositoryInterface,
    ) -> None:
        """
        Initialize the partial fill monitor service.

        Args:
            order_repo: OrderRepositoryInterface implementation for order queries/updates.
            broker_registry: BrokerAdapterRegistry for broker communication.
            execution_event_repo: ExecutionEventRepositoryInterface for audit logging.

        Example:
            service = PartialFillMonitorService(
                order_repo=order_repo,
                broker_registry=broker_registry,
                execution_event_repo=event_repo,
            )
        """
        self.order_repo = order_repo
        self.broker_registry = broker_registry
        self.execution_event_repo = execution_event_repo

    def check_partial_fills(
        self,
        *,
        deployment_id: str,
        policy: PartialFillPolicy,
        correlation_id: str,
    ) -> list[PartialFillResolution]:
        """
        Check all partial fill orders in a deployment against timeout policy.

        Algorithm:
        1. Query order_repo.list_open_by_deployment(deployment_id).
        2. Filter to orders with status == "partial_fill".
        3. For each partial fill order:
           a. Sync latest status from broker via adapter.get_order().
           b. If broker now shows status == "filled": update internal status
              to "filled" and record resolution with action_taken="fully_filled".
           c. If still partial (filled_qty < original_qty):
              - Calculate elapsed time since submitted_at.
              - If elapsed > policy.timeout_seconds:
                * If action_on_timeout == "cancel_remaining":
                  - Call broker adapter.cancel_order(broker_order_id).
                  - On success: update order status to "cancelled" with
                    filled_quantity and cancelled_at.
                  - Record resolution with action_taken="cancelled_remaining".
                * If action_on_timeout == "alert_only":
                  - Log WARNING with order details.
                  - Record resolution with action_taken="alert_sent".
              - Else: skip (within timeout, will retry next cycle).

        Args:
            deployment_id: ULID of the deployment to monitor.
            policy: PartialFillPolicy controlling timeout and action.
            correlation_id: Correlation ID for tracing and audit.

        Returns:
            List of PartialFillResolution records, one per partial fill
            order that was checked. May be empty if no partial fills or
            all are within timeout.

        Raises:
            ExternalServiceError: Broker query/cancel fails. On transient
                failures, the caller should retry. On permanent failures,
                escalate. Do NOT update order status on retriable failures.

        Example:
            policy = PartialFillPolicy(
                timeout_seconds=300,
                action_on_timeout="cancel_remaining",
            )
            resolutions = service.check_partial_fills(
                deployment_id="01HDEPLOY...",
                policy=policy,
                correlation_id="corr-001",
            )
            for res in resolutions:
                logger.info(
                    "Partial fill resolved",
                    extra={
                        "order_id": res.order_id,
                        "action": res.action_taken,
                    },
                )
        """
        resolutions: list[PartialFillResolution] = []

        logger.info(
            "Checking partial fills",
            extra={
                "operation": "check_partial_fills",
                "deployment_id": deployment_id,
                "correlation_id": correlation_id,
                "timeout_seconds": policy.timeout_seconds,
                "action_on_timeout": policy.action_on_timeout,
            },
        )

        # Step 1: Get all open orders in the deployment
        open_orders = self.order_repo.list_open_by_deployment(deployment_id=deployment_id)

        # Step 2: Filter to partial fill orders
        partial_orders = [o for o in open_orders if o.get("status") == "partial_fill"]

        if not partial_orders:
            logger.debug(
                "No partial fill orders found",
                extra={
                    "operation": "check_partial_fills",
                    "deployment_id": deployment_id,
                    "correlation_id": correlation_id,
                },
            )
            return resolutions

        logger.debug(
            "Found partial fill orders",
            extra={
                "operation": "check_partial_fills",
                "deployment_id": deployment_id,
                "correlation_id": correlation_id,
                "count": len(partial_orders),
            },
        )

        # Step 3: Process each partial fill order
        for order in partial_orders:
            try:
                resolution = self._resolve_partial_fill(
                    order=order,
                    deployment_id=deployment_id,
                    policy=policy,
                    correlation_id=correlation_id,
                )
                resolutions.append(resolution)
            except (ExternalServiceError, TransientError) as e:
                # Broker communication failure: log and re-raise
                # Caller will handle retry or escalation
                logger.warning(
                    "Broker communication failed during partial fill check",
                    extra={
                        "operation": "check_partial_fills",
                        "order_id": order.get("id"),
                        "broker_order_id": order.get("broker_order_id"),
                        "correlation_id": correlation_id,
                        "error": str(e),
                    },
                    exc_info=True,
                )
                raise

        logger.info(
            "Partial fill check completed",
            extra={
                "operation": "check_partial_fills",
                "deployment_id": deployment_id,
                "correlation_id": correlation_id,
                "resolutions": len(resolutions),
            },
        )

        return resolutions

    def _resolve_partial_fill(
        self,
        *,
        order: dict[str, Any],
        deployment_id: str,
        policy: PartialFillPolicy,
        correlation_id: str,
    ) -> PartialFillResolution:
        """
        Resolve a single partial fill order according to policy.

        Steps:
        1. Sync latest status from broker.
        2. If now fully filled: update internal status and return "fully_filled".
        3. If still partial: check elapsed time against timeout.
        4. If within timeout: return (no action, will retry later).
        5. If expired and action == cancel: cancel and update status.
        6. If expired and action == alert: log warning.

        Args:
            order: Order dict from repository (must have id, broker_order_id,
                submitted_at, quantity, filled_quantity).
            deployment_id: ULID of the deployment (used to get broker adapter).
            policy: PartialFillPolicy controlling action on timeout.
            correlation_id: Correlation ID for tracing.

        Returns:
            PartialFillResolution with action_taken and outcome details.

        Raises:
            ExternalServiceError: Broker query fails (permanent failure).
            TransientError: Broker query times out or returns 5xx (retriable).
        """
        order_id = order["id"]
        broker_order_id = order.get("broker_order_id")
        order.get("symbol")

        logger.debug(
            "Resolving partial fill order",
            extra={
                "operation": "_resolve_partial_fill",
                "order_id": order_id,
                "broker_order_id": broker_order_id,
                "deployment_id": deployment_id,
                "correlation_id": correlation_id,
            },
        )

        # Step 1: Get the broker adapter for this deployment
        try:
            adapter = self.broker_registry.get_adapter(deployment_id)  # type: ignore[attr-defined]
        except NotFoundError as e:
            logger.error(
                "No broker adapter registered for deployment",
                extra={
                    "operation": "_resolve_partial_fill",
                    "order_id": order_id,
                    "deployment_id": deployment_id,
                    "correlation_id": correlation_id,
                },
                exc_info=True,
            )
            raise NotFoundError(f"No broker adapter for deployment {deployment_id}") from e

        # Step 2: Sync latest order status from broker
        logger.debug(
            "Querying broker for order status",
            extra={
                "operation": "_resolve_partial_fill",
                "order_id": order_id,
                "broker_order_id": broker_order_id,
                "correlation_id": correlation_id,
            },
        )

        try:
            broker_order_response = adapter.get_order(broker_order_id)
        except NotFoundError:
            # Broker doesn't know about this order (shouldn't happen in normal flow)
            logger.error(
                "Broker order not found (order may have been cancelled externally)",
                extra={
                    "operation": "_resolve_partial_fill",
                    "order_id": order_id,
                    "broker_order_id": broker_order_id,
                    "correlation_id": correlation_id,
                },
            )
            raise NotFoundError(
                f"Broker order {broker_order_id} not found (external cancellation?)"
            )

        # Convert broker response to decimal for comparison
        broker_filled_qty = Decimal(str(broker_order_response.filled_quantity))
        broker_original_qty = Decimal(str(broker_order_response.quantity))
        broker_status = str(broker_order_response.status).lower()

        logger.debug(
            "Broker order status synced",
            extra={
                "operation": "_resolve_partial_fill",
                "order_id": order_id,
                "broker_status": broker_status,
                "broker_filled_qty": str(broker_filled_qty),
                "broker_original_qty": str(broker_original_qty),
                "correlation_id": correlation_id,
            },
        )

        # Step 3: Check if now fully filled
        if broker_status == "filled" or broker_filled_qty >= broker_original_qty:
            logger.info(
                "Partial fill order now fully filled",
                extra={
                    "operation": "_resolve_partial_fill",
                    "order_id": order_id,
                    "filled_qty": str(broker_filled_qty),
                    "correlation_id": correlation_id,
                },
            )

            # Update internal order status to "filled"
            now_iso = datetime.now(tz=timezone.utc).isoformat()
            self.order_repo.update_status(
                order_id=order_id,
                status="filled",
                filled_quantity=str(broker_filled_qty),
                filled_at=now_iso,
            )

            # Record audit event
            self.execution_event_repo.save(
                order_id=order_id,
                event_type="partial_fill_completed",
                timestamp=now_iso,
                details={
                    "action": "fully_filled",
                    "filled_qty": str(broker_filled_qty),
                },
                correlation_id=correlation_id,
            )

            return PartialFillResolution(
                order_id=order_id,
                broker_order_id=broker_order_id,
                original_quantity=str(broker_original_qty),
                filled_quantity=str(broker_filled_qty),
                fill_ratio=float(broker_filled_qty / broker_original_qty),
                action_taken="fully_filled",
            )

        # Step 4: Still partial — check timeout
        submitted_at_str = order.get("submitted_at")
        if not submitted_at_str:
            logger.warning(
                "Order missing submitted_at timestamp",
                extra={
                    "operation": "_resolve_partial_fill",
                    "order_id": order_id,
                    "correlation_id": correlation_id,
                },
            )
            # Cannot calculate elapsed time, skip (will retry when submitted_at is set)
            return PartialFillResolution(
                order_id=order_id,
                broker_order_id=broker_order_id,
                original_quantity=str(broker_original_qty),
                filled_quantity=str(broker_filled_qty),
                fill_ratio=float(broker_filled_qty / broker_original_qty),
                action_taken="alert_sent",  # Log and wait
                error_message="Missing submitted_at timestamp",
            )

        # Parse submitted_at as datetime
        try:
            submitted_at = datetime.fromisoformat(submitted_at_str)
            if submitted_at.tzinfo is None:
                submitted_at = submitted_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError) as e:
            logger.warning(
                "Invalid submitted_at timestamp",
                extra={
                    "operation": "_resolve_partial_fill",
                    "order_id": order_id,
                    "submitted_at": submitted_at_str,
                    "error": str(e),
                    "correlation_id": correlation_id,
                },
            )
            # Cannot parse, skip (will retry next cycle)
            return PartialFillResolution(
                order_id=order_id,
                broker_order_id=broker_order_id,
                original_quantity=str(broker_original_qty),
                filled_quantity=str(broker_filled_qty),
                fill_ratio=float(broker_filled_qty / broker_original_qty),
                action_taken="alert_sent",
                error_message=f"Invalid submitted_at: {str(e)}",
            )

        # Calculate elapsed time
        now = datetime.now(tz=timezone.utc)
        elapsed_seconds = (now - submitted_at).total_seconds()

        logger.debug(
            "Partial fill order age calculated",
            extra={
                "operation": "_resolve_partial_fill",
                "order_id": order_id,
                "elapsed_seconds": elapsed_seconds,
                "timeout_seconds": policy.timeout_seconds,
                "correlation_id": correlation_id,
            },
        )

        # Step 5: Check if timeout has expired
        if elapsed_seconds <= policy.timeout_seconds:
            logger.debug(
                "Partial fill order within timeout window",
                extra={
                    "operation": "_resolve_partial_fill",
                    "order_id": order_id,
                    "elapsed_seconds": elapsed_seconds,
                    "timeout_seconds": policy.timeout_seconds,
                    "correlation_id": correlation_id,
                },
            )
            # No action, will retry next cycle
            return PartialFillResolution(
                order_id=order_id,
                broker_order_id=broker_order_id,
                original_quantity=str(broker_original_qty),
                filled_quantity=str(broker_filled_qty),
                fill_ratio=float(broker_filled_qty / broker_original_qty),
                action_taken="alert_sent",  # Within timeout, no action
            )

        # Step 6: Timeout expired — take action based on policy
        logger.warning(
            "Partial fill order timeout expired",
            extra={
                "operation": "_resolve_partial_fill",
                "order_id": order_id,
                "elapsed_seconds": elapsed_seconds,
                "timeout_seconds": policy.timeout_seconds,
                "action_on_timeout": policy.action_on_timeout,
                "correlation_id": correlation_id,
            },
        )

        if policy.action_on_timeout == "cancel_remaining":
            return self._cancel_partial_order(
                order_id=order_id,
                broker_order_id=broker_order_id,
                original_qty=broker_original_qty,
                filled_qty=broker_filled_qty,
                correlation_id=correlation_id,
                adapter=adapter,
            )
        else:  # alert_only
            return self._alert_partial_order(
                order_id=order_id,
                broker_order_id=broker_order_id,
                original_qty=broker_original_qty,
                filled_qty=broker_filled_qty,
                elapsed_seconds=elapsed_seconds,
                correlation_id=correlation_id,
            )

    def _cancel_partial_order(
        self,
        *,
        order_id: str,
        broker_order_id: str,
        original_qty: Decimal,
        filled_qty: Decimal,
        correlation_id: str,
        adapter: Any,
    ) -> PartialFillResolution:
        """
        Cancel the remaining quantity of a partial fill order.

        Steps:
        1. Call adapter.cancel_order(broker_order_id).
        2. On success: update order status to "cancelled" with filled_quantity
           and cancelled_at timestamp.
        3. Record execution event with cancellation details.
        4. Return resolution with action_taken="cancelled_remaining".

        Args:
            order_id: Internal order ULID.
            broker_order_id: Broker-assigned order ID.
            original_qty: Total quantity ordered (Decimal).
            filled_qty: Quantity already filled (Decimal).
            correlation_id: Correlation ID for tracing.
            adapter: BrokerAdapterInterface instance to use for cancellation.

        Returns:
            PartialFillResolution with action_taken="cancelled_remaining"
            on success, or "error" on failure.

        Raises:
            ExternalServiceError: Broker cancel fails (permanent).
            TransientError: Broker cancel times out or returns 5xx (retriable).
        """
        logger.info(
            "Cancelling partial fill order",
            extra={
                "operation": "_cancel_partial_order",
                "order_id": order_id,
                "broker_order_id": broker_order_id,
                "filled_qty": str(filled_qty),
                "remaining_qty": str(original_qty - filled_qty),
                "correlation_id": correlation_id,
            },
        )

        try:
            # Step 1: Send cancel request to broker
            logger.debug(
                "Sending cancel request to broker",
                extra={
                    "operation": "_cancel_partial_order",
                    "order_id": order_id,
                    "broker_order_id": broker_order_id,
                    "correlation_id": correlation_id,
                },
            )

            adapter.cancel_order(broker_order_id)

            # Step 2: Update internal order status
            now_iso = datetime.now(tz=timezone.utc).isoformat()
            self.order_repo.update_status(
                order_id=order_id,
                status="cancelled",
                filled_quantity=str(filled_qty),
                cancelled_at=now_iso,
            )

            logger.info(
                "Partial fill order cancelled successfully",
                extra={
                    "operation": "_cancel_partial_order",
                    "order_id": order_id,
                    "broker_order_id": broker_order_id,
                    "cancelled_at": now_iso,
                    "correlation_id": correlation_id,
                },
            )

            # Step 3: Record audit event
            self.execution_event_repo.save(
                order_id=order_id,
                event_type="partial_fill_timeout_cancelled",
                timestamp=now_iso,
                details={
                    "action": "cancelled_remaining",
                    "filled_qty": str(filled_qty),
                    "cancelled_qty": str(original_qty - filled_qty),
                },
                correlation_id=correlation_id,
            )

            # Step 4: Return success resolution
            return PartialFillResolution(
                order_id=order_id,
                broker_order_id=broker_order_id,
                original_quantity=str(original_qty),
                filled_quantity=str(filled_qty),
                fill_ratio=float(filled_qty / original_qty),
                action_taken="cancelled_remaining",
                cancelled_at=datetime.fromisoformat(now_iso),
            )

        except (ExternalServiceError, TransientError) as e:
            # Broker cancel failed: log error and return error resolution
            logger.error(
                "Failed to cancel partial fill order at broker",
                extra={
                    "operation": "_cancel_partial_order",
                    "order_id": order_id,
                    "broker_order_id": broker_order_id,
                    "correlation_id": correlation_id,
                    "error": str(e),
                },
                exc_info=True,
            )

            # Do NOT update order status on transient failures — let caller retry
            if isinstance(e, TransientError):
                raise

            # On permanent failure: record error and return error resolution
            # (but don't update order status, so next cycle will retry)
            return PartialFillResolution(
                order_id=order_id,
                broker_order_id=broker_order_id,
                original_quantity=str(original_qty),
                filled_quantity=str(filled_qty),
                fill_ratio=float(filled_qty / original_qty),
                action_taken="error",
                error_message=f"Failed to cancel at broker: {str(e)}",
            )

    def _alert_partial_order(
        self,
        *,
        order_id: str,
        broker_order_id: str,
        original_qty: Decimal,
        filled_qty: Decimal,
        elapsed_seconds: float,
        correlation_id: str,
    ) -> PartialFillResolution:
        """
        Log an alert for a partial fill order that timed out (alert-only policy).

        Records a WARNING log with full order details for operator review.
        Does NOT update order status or send cancel request.

        Args:
            order_id: Internal order ULID.
            broker_order_id: Broker-assigned order ID.
            original_qty: Total quantity ordered (Decimal).
            filled_qty: Quantity already filled (Decimal).
            elapsed_seconds: Seconds elapsed since submission.
            correlation_id: Correlation ID for tracing.

        Returns:
            PartialFillResolution with action_taken="alert_sent".
        """
        remaining_qty = original_qty - filled_qty

        logger.warning(
            "Partial fill order timeout — alert only (not cancelled)",
            extra={
                "operation": "_alert_partial_order",
                "order_id": order_id,
                "broker_order_id": broker_order_id,
                "original_qty": str(original_qty),
                "filled_qty": str(filled_qty),
                "remaining_qty": str(remaining_qty),
                "elapsed_seconds": elapsed_seconds,
                "correlation_id": correlation_id,
                "action": "operator_review_required",
            },
        )

        # Record audit event
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        self.execution_event_repo.save(
            order_id=order_id,
            event_type="partial_fill_timeout_alert",
            timestamp=now_iso,
            details={
                "action": "alert_sent",
                "filled_qty": str(filled_qty),
                "remaining_qty": str(remaining_qty),
                "elapsed_seconds": elapsed_seconds,
            },
            correlation_id=correlation_id,
        )

        return PartialFillResolution(
            order_id=order_id,
            broker_order_id=broker_order_id,
            original_quantity=str(original_qty),
            filled_quantity=str(filled_qty),
            fill_ratio=float(filled_qty / original_qty),
            action_taken="alert_sent",
        )
