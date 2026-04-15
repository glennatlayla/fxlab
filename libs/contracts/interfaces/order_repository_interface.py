"""
Order repository interface (port).

Responsibilities:
- Define the abstract contract for order persistence and retrieval.
- Support idempotent order lookup by client_order_id.
- Support filtering by deployment, status, and broker_order_id.

Does NOT:
- Implement storage logic.
- Enforce business rules or order validation.
- Manage order state transitions (service layer responsibility).

Dependencies:
- None (pure interface).

Error conditions:
- NotFoundError: raised by get_by_id when order does not exist.

Example:
    repo: OrderRepositoryInterface = SqlOrderRepository(db=session)
    order = repo.save(
        client_order_id="client-001",
        deployment_id="01HDEPLOY...",
        strategy_id="01HSTRAT...",
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity="100",
        time_in_force="day",
        status="pending",
        correlation_id="corr-001",
        execution_mode="paper",
    )
    found = repo.get_by_client_order_id(client_order_id="client-001")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class OrderRepositoryInterface(ABC):
    """
    Port interface for order persistence.

    Responsibilities:
    - CRUD operations for order records.
    - Idempotent lookup by client_order_id.
    - Filtering by deployment, status, and broker identifiers.

    Does NOT:
    - Enforce order validation or state machine rules.
    - Manage related fills or execution events (separate repositories).
    """

    @abstractmethod
    def save(
        self,
        *,
        client_order_id: str,
        deployment_id: str,
        strategy_id: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: str,
        time_in_force: str,
        status: str,
        correlation_id: str,
        execution_mode: str,
        limit_price: str | None = None,
        stop_price: str | None = None,
        broker_order_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Persist a new order record.

        Generates a ULID primary key. All monetary values stored as strings
        for decimal precision safety.

        Args:
            client_order_id: Client-assigned idempotency key (unique).
            deployment_id: Owning deployment ULID.
            strategy_id: Originating strategy ULID.
            symbol: Instrument ticker (e.g. "AAPL").
            side: Order side ("buy" or "sell").
            order_type: Order type ("market", "limit", "stop", "stop_limit").
            quantity: Order quantity as string for decimal safety.
            time_in_force: Time in force ("day", "gtc", "ioc", "fok").
            status: Initial order status ("pending", "submitted", etc.).
            correlation_id: Request correlation ID for tracing.
            execution_mode: Execution mode ("shadow", "paper", "live").
            limit_price: Limit price for limit/stop-limit orders.
            stop_price: Stop price for stop/stop-limit orders.
            broker_order_id: Broker-assigned order ID (may be set later).

        Returns:
            Dict with all order fields including generated id and timestamps.

        Raises:
            IntegrityError: If client_order_id already exists (use
                get_by_client_order_id for idempotent behavior).
        """
        ...

    @abstractmethod
    def get_by_id(self, order_id: str) -> dict[str, Any]:
        """
        Retrieve an order by its primary key.

        Args:
            order_id: ULID primary key.

        Returns:
            Dict with all order fields.

        Raises:
            NotFoundError: If no order exists with this ID.
        """
        ...

    @abstractmethod
    def get_by_client_order_id(self, client_order_id: str) -> dict[str, Any] | None:
        """
        Look up an order by its client-assigned idempotency key.

        Used to detect duplicate submissions. Returns None instead of raising
        when not found, since "not found" is the expected case for new orders.

        Args:
            client_order_id: Client-assigned order identifier.

        Returns:
            Dict with all order fields, or None if not found.
        """
        ...

    @abstractmethod
    def get_by_broker_order_id(
        self,
        broker_order_id: str,
    ) -> dict[str, Any] | None:
        """
        Look up an order by its broker-assigned order ID.

        Args:
            broker_order_id: Broker-assigned identifier.

        Returns:
            Dict with all order fields, or None if not found.
        """
        ...

    @abstractmethod
    def list_by_deployment(
        self,
        *,
        deployment_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        List orders belonging to a deployment, optionally filtered by status.

        Args:
            deployment_id: Deployment ULID.
            status: If provided, filter to orders with this status value.

        Returns:
            List of order dicts, ordered by created_at descending.
        """
        ...

    @abstractmethod
    def list_open_by_deployment(
        self,
        *,
        deployment_id: str,
    ) -> list[dict[str, Any]]:
        """
        List orders with non-terminal status for a deployment.

        Non-terminal statuses: pending, submitted, partial_fill.
        Terminal statuses: filled, cancelled, rejected, expired.

        Args:
            deployment_id: Deployment ULID.

        Returns:
            List of open order dicts, ordered by created_at descending.
        """
        ...

    @abstractmethod
    def update_status(
        self,
        *,
        order_id: str,
        status: str,
        broker_order_id: str | None = None,
        submitted_at: str | None = None,
        filled_at: str | None = None,
        cancelled_at: str | None = None,
        average_fill_price: str | None = None,
        filled_quantity: str | None = None,
        rejected_reason: str | None = None,
    ) -> dict[str, Any]:
        """
        Update an order's status and related fields atomically.

        Args:
            order_id: ULID of the order to update.
            status: New status value.
            broker_order_id: Broker-assigned ID (set on first submission).
            submitted_at: ISO timestamp when broker acknowledged.
            filled_at: ISO timestamp when fully filled.
            cancelled_at: ISO timestamp when cancelled.
            average_fill_price: Volume-weighted average fill price.
            filled_quantity: Total quantity filled so far.
            rejected_reason: Rejection reason text.

        Returns:
            Updated order dict.

        Raises:
            NotFoundError: If no order exists with this ID.
        """
        ...
