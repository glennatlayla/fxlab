"""
Order fill repository interface (port).

Responsibilities:
- Define the abstract contract for order fill persistence and retrieval.
- Support listing fills by order and by deployment.

Does NOT:
- Implement storage logic.
- Update parent order status on fill (service layer responsibility).

Dependencies:
- None (pure interface).

Example:
    repo: OrderFillRepositoryInterface = SqlOrderFillRepository(db=session)
    fill = repo.save(
        order_id="01HORDER...",
        fill_id="fill-001",
        price="150.25",
        quantity="50",
        commission="1.00",
        filled_at="2026-04-11T14:30:00+00:00",
        correlation_id="corr-001",
    )
    fills = repo.list_by_order(order_id="01HORDER...")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class OrderFillRepositoryInterface(ABC):
    """
    Port interface for order fill persistence.

    Responsibilities:
    - Append-only persistence of individual fill events.
    - Retrieval by parent order or deployment.

    Does NOT:
    - Aggregate fill data (service or query responsibility).
    - Update parent order filled_quantity or average_fill_price.
    """

    @abstractmethod
    def save(
        self,
        *,
        order_id: str,
        fill_id: str,
        price: str,
        quantity: str,
        commission: str,
        filled_at: str,
        correlation_id: str,
        broker_execution_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Persist a new fill event.

        Generates a ULID primary key. All monetary values stored as strings
        for decimal precision safety.

        Args:
            order_id: Parent order ULID.
            fill_id: Broker-assigned fill identifier.
            price: Fill price as string.
            quantity: Fill quantity as string.
            commission: Commission charged as string.
            filled_at: ISO timestamp of the fill.
            correlation_id: Request correlation ID for tracing.
            broker_execution_id: Broker execution report ID (optional).

        Returns:
            Dict with all fill fields including generated id and timestamps.
        """
        ...

    @abstractmethod
    def list_by_order(self, *, order_id: str) -> list[dict[str, Any]]:
        """
        List all fills for a specific order, ordered chronologically.

        Args:
            order_id: Parent order ULID.

        Returns:
            List of fill dicts ordered by filled_at ascending.
        """
        ...

    @abstractmethod
    def list_by_deployment(
        self,
        *,
        deployment_id: str,
    ) -> list[dict[str, Any]]:
        """
        List all fills across all orders for a deployment.

        Requires a join to the orders table on order_id → orders.id
        filtered by orders.deployment_id.

        Args:
            deployment_id: Deployment ULID.

        Returns:
            List of fill dicts ordered by filled_at descending.
        """
        ...
