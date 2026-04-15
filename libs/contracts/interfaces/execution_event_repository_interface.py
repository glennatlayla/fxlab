"""
Execution event repository interface (port).

Responsibilities:
- Define the abstract contract for execution event persistence and retrieval.
- Execution events are append-only (no update, no delete).
- Support querying by order, deployment, and correlation ID.

Does NOT:
- Implement storage logic.
- Manage order state transitions.
- Contain business logic.

Dependencies:
- None (pure interface).

Example:
    repo: ExecutionEventRepositoryInterface = SqlExecutionEventRepository(db=session)
    event = repo.save(
        order_id="01HORDER...",
        event_type="submitted",
        timestamp="2026-04-11T14:30:00+00:00",
        details={"broker_order_id": "ALPACA-12345"},
        correlation_id="corr-001",
    )
    events = repo.list_by_order(order_id="01HORDER...")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ExecutionEventRepositoryInterface(ABC):
    """
    Port interface for execution event persistence.

    Responsibilities:
    - Append-only persistence of execution lifecycle events.
    - Retrieval by parent order, deployment, or correlation ID.

    Does NOT:
    - Aggregate event data (service or query responsibility).
    - Update or delete events (append-only semantics).
    """

    @abstractmethod
    def save(
        self,
        *,
        order_id: str,
        event_type: str,
        timestamp: str,
        details: dict[str, Any] | None = None,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Persist a new execution event.

        Generates a ULID primary key. The timestamp is stored as a
        datetime parsed from the provided ISO 8601 string.

        Args:
            order_id: Parent order ULID.
            event_type: Event type (e.g. "submitted", "filled", "cancelled",
                "rejected", "risk_checked", "risk_failed", "partial_fill").
            timestamp: ISO 8601 timestamp of when the event occurred.
            details: Optional JSON-serialisable dict with event-specific context.
            correlation_id: Distributed tracing correlation ID.

        Returns:
            Dict with all event fields including generated id.
        """
        ...

    @abstractmethod
    def list_by_order(self, *, order_id: str) -> list[dict[str, Any]]:
        """
        List all execution events for a specific order, chronologically.

        Args:
            order_id: Parent order ULID.

        Returns:
            List of event dicts ordered by timestamp ascending.
        """
        ...

    @abstractmethod
    def search_by_correlation_id(self, *, correlation_id: str) -> list[dict[str, Any]]:
        """
        Search execution events by correlation ID.

        Supports distributed tracing and debugging by finding all events
        related to a single correlated request chain.

        Args:
            correlation_id: Distributed tracing ID.

        Returns:
            List of event dicts ordered by timestamp ascending.
        """
        ...

    @abstractmethod
    def list_by_deployment(self, *, deployment_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """
        List execution events across all orders for a deployment.

        Requires a join to the orders table on order_id -> orders.id
        filtered by orders.deployment_id.

        Args:
            deployment_id: Deployment ULID.
            limit: Maximum number of events to return.

        Returns:
            List of event dicts ordered by timestamp descending.
        """
        ...
