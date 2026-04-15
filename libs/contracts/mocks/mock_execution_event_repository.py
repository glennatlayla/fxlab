"""
In-memory mock implementation of ExecutionEventRepositoryInterface.

Responsibilities:
- Provide a test double for execution event persistence.
- Support introspection helpers for test assertions.

Does NOT:
- Persist data beyond the lifetime of the instance.
- Contain business logic.

Dependencies:
- libs.contracts.interfaces.execution_event_repository_interface.

Example:
    repo = MockExecutionEventRepository()
    event = repo.save(order_id="ord-001", event_type="submitted", ...)
    assert repo.count() == 1
"""

from __future__ import annotations

from typing import Any

from libs.contracts.interfaces.execution_event_repository_interface import (
    ExecutionEventRepositoryInterface,
)


class MockExecutionEventRepository(ExecutionEventRepositoryInterface):
    """
    In-memory implementation of ExecutionEventRepositoryInterface.

    Responsibilities:
    - Store execution events in memory for testing.
    - Support retrieval by order, deployment, and correlation ID.
    - Provide introspection helpers (count, get_all, clear).

    Does NOT:
    - Persist data to any external store.

    Example:
        repo = MockExecutionEventRepository()
        event = repo.save(order_id="ord-001", event_type="submitted",
                         timestamp="2026-04-11T10:00:00+00:00",
                         correlation_id="corr-001")
        events = repo.list_by_order(order_id="ord-001")
    """

    def __init__(self) -> None:
        self._store: list[dict[str, Any]] = []
        self._counter: int = 0
        # Maps order_id -> deployment_id for list_by_deployment queries.
        self._order_deployment_map: dict[str, str] = {}

    def register_order_deployment(self, order_id: str, deployment_id: str) -> None:
        """
        Register the deployment for an order (needed for list_by_deployment).

        In production, this join is done via SQL. In the mock, the caller
        must register the mapping explicitly.

        Args:
            order_id: Order ULID.
            deployment_id: Deployment ULID that owns this order.
        """
        self._order_deployment_map[order_id] = deployment_id

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
        Persist a new execution event in memory.

        Args:
            order_id: Parent order ULID.
            event_type: Event type string.
            timestamp: ISO 8601 timestamp string.
            details: Optional JSON-serialisable dict.
            correlation_id: Distributed tracing ID.

        Returns:
            Dict with all event fields including generated mock id.
        """
        self._counter += 1
        event = {
            "id": f"mock-ee-{self._counter:06d}",
            "order_id": order_id,
            "event_type": event_type,
            "timestamp": timestamp,
            "details": details or {},
            "correlation_id": correlation_id,
        }
        self._store.append(event)
        return dict(event)

    def list_by_order(self, *, order_id: str) -> list[dict[str, Any]]:
        """
        List events for an order, ordered by timestamp ascending.

        Args:
            order_id: Parent order ULID.

        Returns:
            List of event dicts.
        """
        filtered = [e for e in self._store if e["order_id"] == order_id]
        filtered.sort(key=lambda e: e["timestamp"])
        return [dict(e) for e in filtered]

    def search_by_correlation_id(self, *, correlation_id: str) -> list[dict[str, Any]]:
        """
        Search events by correlation ID.

        Args:
            correlation_id: Distributed tracing ID.

        Returns:
            List of event dicts.
        """
        filtered = [e for e in self._store if e["correlation_id"] == correlation_id]
        filtered.sort(key=lambda e: e["timestamp"])
        return [dict(e) for e in filtered]

    def list_by_deployment(self, *, deployment_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """
        List events for a deployment via the registered order-deployment map.

        Args:
            deployment_id: Deployment ULID.
            limit: Maximum number of events to return.

        Returns:
            List of event dicts.
        """
        order_ids = {oid for oid, did in self._order_deployment_map.items() if did == deployment_id}
        filtered = [e for e in self._store if e["order_id"] in order_ids]
        filtered.sort(key=lambda e: e["timestamp"], reverse=True)
        return [dict(e) for e in filtered[:limit]]

    # ------------------------------------------------------------------
    # Introspection helpers for tests
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return total number of stored events."""
        return len(self._store)

    def get_all(self) -> list[dict[str, Any]]:
        """Return all stored events."""
        return [dict(e) for e in self._store]

    def clear(self) -> None:
        """Remove all stored events and reset counter."""
        self._store.clear()
        self._counter = 0
        self._order_deployment_map.clear()
