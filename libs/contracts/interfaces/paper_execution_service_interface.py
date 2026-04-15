"""
Paper execution service interface (port).

Responsibilities:
- Define the abstract contract for paper-mode order execution.
- Paper mode uses a simulated broker with realistic order lifecycle:
  submit → ack → fill/partial/reject, with configurable latency.

Does NOT:
- Execute real broker operations.
- Contain risk gate logic (delegated to a risk gate interface in M5).

Dependencies:
- libs.contracts.execution: OrderRequest, OrderResponse, PositionSnapshot,
  AccountSnapshot.

Error conditions:
- NotFoundError: deployment_id does not exist or has no active paper adapter.
- StateTransitionError: deployment is not in an executable paper state.
- ValidationError: duplicate registration or invalid request.

Example:
    service: PaperExecutionServiceInterface = PaperExecutionService(...)
    resp = service.submit_paper_order(
        deployment_id="01HDEPLOY...",
        request=order_request,
        correlation_id="corr-001",
    )
    filled = service.process_pending_orders(deployment_id="01HDEPLOY...")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from libs.contracts.execution import (
    AccountSnapshot,
    OrderRequest,
    OrderResponse,
    PositionSnapshot,
)


class PaperExecutionServiceInterface(ABC):
    """
    Port interface for paper-mode execution orchestration.

    Paper execution follows the same signal → risk check → order lifecycle
    as live, but routes to a PaperBrokerAdapter that simulates realistic
    fills with configurable latency and partial fills.

    Each deployment gets its own isolated paper adapter instance.

    Implementations:
    - PaperExecutionService — production implementation (M4)
    """

    @abstractmethod
    def submit_paper_order(
        self,
        *,
        deployment_id: str,
        request: OrderRequest,
        correlation_id: str,
    ) -> OrderResponse:
        """
        Submit an order for paper execution.

        Returns SUBMITTED status (not instant fill). Call
        process_pending_orders() to advance the order lifecycle.

        Args:
            deployment_id: ULID of the deployment in paper mode.
            request: Normalized order submission payload.
            correlation_id: Distributed tracing ID.

        Returns:
            OrderResponse with SUBMITTED status.

        Raises:
            NotFoundError: deployment does not exist or has no adapter.
            StateTransitionError: deployment not in executable paper state.
        """
        ...

    @abstractmethod
    def process_pending_orders(
        self,
        *,
        deployment_id: str,
    ) -> list[OrderResponse]:
        """
        Process pending orders for a deployment (tick-based fill).

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            List of OrderResponse for orders that were filled this tick.

        Raises:
            NotFoundError: deployment_id has no active paper adapter.
        """
        ...

    @abstractmethod
    def cancel_paper_order(
        self,
        *,
        deployment_id: str,
        broker_order_id: str,
        correlation_id: str,
    ) -> OrderResponse:
        """
        Cancel an open paper order.

        Args:
            deployment_id: ULID of the deployment.
            broker_order_id: Broker-assigned order identifier.
            correlation_id: Distributed tracing ID.

        Returns:
            OrderResponse with current status.

        Raises:
            NotFoundError: deployment or order not found.
        """
        ...

    @abstractmethod
    def update_market_price(
        self,
        *,
        deployment_id: str,
        symbol: str,
        price: Decimal,
    ) -> None:
        """
        Update market price for a symbol in a deployment's paper adapter.

        Args:
            deployment_id: ULID of the deployment.
            symbol: Instrument ticker.
            price: Current market price.

        Raises:
            NotFoundError: deployment has no active paper adapter.
        """
        ...

    @abstractmethod
    def get_paper_positions(
        self,
        *,
        deployment_id: str,
    ) -> list[PositionSnapshot]:
        """
        Get current positions for a paper deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            List of PositionSnapshot for non-zero positions.

        Raises:
            NotFoundError: deployment has no active paper adapter.
        """
        ...

    @abstractmethod
    def get_paper_account(
        self,
        *,
        deployment_id: str,
    ) -> AccountSnapshot:
        """
        Get account state for a paper deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            AccountSnapshot with equity, cash, positions.

        Raises:
            NotFoundError: deployment has no active paper adapter.
        """
        ...

    @abstractmethod
    def get_open_orders(
        self,
        *,
        deployment_id: str,
    ) -> list[OrderResponse]:
        """
        Get all open/pending orders for a paper deployment.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            List of open OrderResponse objects.

        Raises:
            NotFoundError: deployment has no active paper adapter.
        """
        ...

    @abstractmethod
    def get_all_order_states(
        self,
        *,
        deployment_id: str,
    ) -> list[OrderResponse]:
        """
        Get all order states for reconciliation recovery.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            List of all OrderResponse objects (all statuses).

        Raises:
            NotFoundError: deployment has no active paper adapter.
        """
        ...

    @abstractmethod
    def register_deployment(
        self,
        *,
        deployment_id: str,
        initial_equity: Decimal,
        market_prices: dict[str, Decimal] | None = None,
        commission_per_order: Decimal = Decimal("0"),
    ) -> None:
        """
        Register a deployment for paper execution.

        Args:
            deployment_id: ULID of the deployment.
            initial_equity: Starting hypothetical equity.
            market_prices: Optional initial market price map.
            commission_per_order: Fixed commission per fill.

        Raises:
            ValidationError: deployment_id is already registered.
        """
        ...

    @abstractmethod
    def deregister_deployment(
        self,
        *,
        deployment_id: str,
    ) -> None:
        """
        Deregister a deployment and clean up its paper adapter.

        Args:
            deployment_id: ULID of the deployment.

        Raises:
            NotFoundError: deployment_id is not registered.
        """
        ...
