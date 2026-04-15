"""
Live execution service interface (port).

Responsibilities:
- Define the abstract contract for live-mode order execution.
- Live mode routes orders through real broker adapters (Alpaca, Schwab, etc.)
  with mandatory pre-trade risk gate enforcement, kill switch pre-checks,
  and database persistence of all order lifecycle events.

Does NOT:
- Execute broker communication directly (delegates to BrokerAdapterInterface).
- Contain risk gate logic (delegates to RiskGateInterface).
- Contain kill switch logic (delegates to KillSwitchServiceInterface).
- Know about specific broker APIs.

Dependencies:
- libs.contracts.execution: OrderRequest, OrderResponse, PositionSnapshot,
  AccountSnapshot.

Error conditions:
- NotFoundError: deployment_id has no registered broker adapter.
- StateTransitionError: deployment is not in an executable live state.
- RiskGateRejectionError: order fails pre-trade risk checks.
- KillSwitchActiveError: trading is halted for this deployment/strategy/symbol.
- ExternalServiceError: broker communication failure.

Example:
    service: LiveExecutionServiceInterface = LiveExecutionService(...)
    resp = service.submit_live_order(
        deployment_id="01HDEPLOY...",
        request=order_request,
        correlation_id="corr-001",
    )
    orders = service.list_live_orders(deployment_id="01HDEPLOY...")
    positions = service.get_live_positions(deployment_id="01HDEPLOY...")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from libs.contracts.execution import (
    AccountSnapshot,
    OrderRequest,
    OrderResponse,
    PositionSnapshot,
)


class LiveExecutionServiceInterface(ABC):
    """
    Port interface for live-mode execution orchestration.

    Live execution follows the same signal → risk check → order lifecycle
    pipeline as paper/shadow, but routes through real broker adapters and
    enforces stricter safety checks:

    1. Kill switch pre-check (halts if active at any scope)
    2. Pre-trade risk gate enforcement (fail-fast on violation)
    3. Order persistence to database BEFORE broker submission
    4. Broker submission through real adapter
    5. Order status update with broker acknowledgment
    6. Execution event logging at every state transition

    Every order MUST be persisted to the database before broker submission.
    This guarantees recoverability if the process crashes after submission
    but before receiving the broker acknowledgment.

    Implementations:
    - LiveExecutionService — production implementation (Phase 6 M3)

    Thread safety:
    - Implementations must be safe for concurrent calls across different
      deployment_ids AND for concurrent calls within the same deployment_id.
      All order state transitions must be Lock-protected.
    """

    @abstractmethod
    def submit_live_order(
        self,
        *,
        deployment_id: str,
        request: OrderRequest,
        correlation_id: str,
    ) -> OrderResponse:
        """
        Submit a live order through a real broker adapter.

        Pipeline:
        1. Validate deployment state (active + live mode)
        2. Check kill switch (global, strategy, symbol scopes)
        3. Enforce pre-trade risk gate
        4. Persist order to database (status=pending)
        5. Submit to broker adapter
        6. Update order with broker acknowledgment (status=submitted)
        7. Record execution events

        Args:
            deployment_id: ULID of the deployment in live mode.
            request: Normalized order submission payload.
            correlation_id: Distributed tracing ID from the originating signal.

        Returns:
            OrderResponse with SUBMITTED status and broker_order_id.

        Raises:
            NotFoundError: deployment does not exist or has no broker adapter.
            StateTransitionError: deployment is not in executable live state.
            KillSwitchActiveError: trading halted for this scope.
            RiskGateRejectionError: order fails risk checks.
            ExternalServiceError: broker communication failure.

        Example:
            resp = service.submit_live_order(
                deployment_id="01HDEPLOY...",
                request=order_request,
                correlation_id="corr-001",
            )
            assert resp.status in (OrderStatus.SUBMITTED, OrderStatus.FILLED)
        """
        ...

    @abstractmethod
    def cancel_live_order(
        self,
        *,
        deployment_id: str,
        broker_order_id: str,
        correlation_id: str,
    ) -> OrderResponse:
        """
        Cancel an open live order through the broker adapter.

        Looks up the order by broker_order_id, submits cancellation to the
        broker, and persists the status update.

        Args:
            deployment_id: ULID of the deployment.
            broker_order_id: Broker-assigned order identifier.
            correlation_id: Distributed tracing ID.

        Returns:
            OrderResponse with updated status (CANCELLED or current state).

        Raises:
            NotFoundError: order or deployment not found.
            ExternalServiceError: broker communication failure.

        Example:
            resp = service.cancel_live_order(
                deployment_id="01HDEPLOY...",
                broker_order_id="ALPACA-12345",
                correlation_id="corr-002",
            )
        """
        ...

    @abstractmethod
    def list_live_orders(
        self,
        *,
        deployment_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        List live orders for a deployment, optionally filtered by status.

        Reads from the database (source of truth), not the broker.

        Args:
            deployment_id: ULID of the deployment.
            status: Optional status filter (e.g. "submitted", "filled").

        Returns:
            List of order dicts, ordered by created_at descending.

        Example:
            orders = service.list_live_orders(deployment_id="01HDEPLOY...")
        """
        ...

    @abstractmethod
    def get_live_positions(
        self,
        *,
        deployment_id: str,
    ) -> list[PositionSnapshot]:
        """
        Get current live positions for a deployment.

        Queries the broker adapter for real-time position data.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            List of PositionSnapshot for current positions.

        Raises:
            NotFoundError: deployment has no broker adapter.
            ExternalServiceError: broker communication failure.

        Example:
            positions = service.get_live_positions(deployment_id="01HDEPLOY...")
        """
        ...

    @abstractmethod
    def get_live_account(
        self,
        *,
        deployment_id: str,
    ) -> AccountSnapshot:
        """
        Get live account state for a deployment.

        Queries the broker adapter for real-time account data.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            AccountSnapshot with equity, cash, buying power.

        Raises:
            NotFoundError: deployment has no broker adapter.
            ExternalServiceError: broker communication failure.

        Example:
            acct = service.get_live_account(deployment_id="01HDEPLOY...")
        """
        ...

    @abstractmethod
    def get_live_pnl(
        self,
        *,
        deployment_id: str,
    ) -> dict[str, Any]:
        """
        Get live P&L summary for a deployment.

        Combines broker position data with persisted order history to
        calculate realized and unrealized P&L.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            Dict with total_unrealized_pnl, total_realized_pnl,
            positions (list of per-symbol P&L).

        Raises:
            NotFoundError: deployment has no broker adapter.
            ExternalServiceError: broker communication failure.

        Example:
            pnl = service.get_live_pnl(deployment_id="01HDEPLOY...")
            # {"total_unrealized_pnl": "450.00", ...}
        """
        ...

    @abstractmethod
    def sync_order_status(
        self,
        *,
        deployment_id: str,
        broker_order_id: str,
        correlation_id: str,
    ) -> OrderResponse:
        """
        Synchronise a single order's status from the broker.

        Fetches the latest order state from the broker and updates the
        database record. Used for reconciliation and fill detection.

        Args:
            deployment_id: ULID of the deployment.
            broker_order_id: Broker-assigned order identifier.
            correlation_id: Distributed tracing ID.

        Returns:
            OrderResponse with the latest broker-reported status.

        Raises:
            NotFoundError: order or deployment not found.
            ExternalServiceError: broker communication failure.

        Example:
            resp = service.sync_order_status(
                deployment_id="01HDEPLOY...",
                broker_order_id="ALPACA-12345",
                correlation_id="corr-003",
            )
        """
        ...
