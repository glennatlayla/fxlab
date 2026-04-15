"""
In-memory mock order fill repository for unit testing.

Responsibilities:
- Implement OrderFillRepositoryInterface with dict-backed storage.
- Maintain optional metadata mapping order_id → deployment_id for
  list_by_deployment() queries.
- Provide seed() and introspection helpers for test setup and assertions.
- Match the behavioural contract of the production SQL repository.

Does NOT:
- Persist data across process restarts.
- Contain business logic or aggregation rules.
- Update parent order filled_quantity or average_fill_price.

Dependencies:
- libs.contracts.interfaces.order_fill_repository_interface.OrderFillRepositoryInterface

Error conditions:
- None raised by the mock (fills can always be appended).

Example:
    repo = MockOrderFillRepository()
    fill = repo.save(
        order_id="01HORDER...",
        fill_id="fill-001",
        price="150.25",
        quantity="50",
        commission="1.00",
        filled_at="2026-04-11T14:30:00+00:00",
        correlation_id="test-corr-001",
    )
    assert repo.get_all() == [fill]
    fills = repo.list_by_order(order_id="01HORDER...")
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from libs.contracts.interfaces.order_fill_repository_interface import (
    OrderFillRepositoryInterface,
)


def _generate_test_ulid() -> str:
    """
    Generate a ULID for test use.

    Uses python-ulid which produces spec-compliant 26-character Crockford
    base32 ULIDs.

    Returns:
        26-character ULID string.
    """
    import ulid as _ulid

    return str(_ulid.ULID())


class MockOrderFillRepository(OrderFillRepositoryInterface):
    """
    In-memory implementation of OrderFillRepositoryInterface for unit tests.

    Responsibilities:
    - Store fill records in a dict keyed by fill ID.
    - Maintain a mapping of order_id → deployment_id for efficient
      deployment-level queries.
    - Provide seed() for prepopulating test data.
    - Provide introspection helpers for assertions.

    Does NOT:
    - Aggregate fill data across orders (caller responsibility).
    - Update parent order status.
    - Persist across test runs.

    Example:
        repo = MockOrderFillRepository()
        fill = repo.save(
            order_id="01HORDER...",
            fill_id="fill-001",
            price="150.25",
            quantity="50",
            commission="1.00",
            filled_at="2026-04-11T14:30:00+00:00",
            correlation_id="test-corr-001",
        )
        assert repo.count() == 1
        fills = repo.list_by_order(order_id="01HORDER...")
        assert len(fills) == 1
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        # Maps order_id to deployment_id for list_by_deployment queries
        self._order_deployment_map: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Interface methods
    # ------------------------------------------------------------------

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
        fill_pk = _generate_test_ulid()
        now = datetime.now(tz=timezone.utc).isoformat()
        record: dict[str, Any] = {
            "id": fill_pk,
            "order_id": order_id,
            "fill_id": fill_id,
            "price": price,
            "quantity": quantity,
            "commission": commission,
            "filled_at": filled_at,
            "correlation_id": correlation_id,
            "broker_execution_id": broker_execution_id,
            "created_at": now,
        }
        self._store[fill_pk] = record
        return dict(record)

    def list_by_order(self, *, order_id: str) -> list[dict[str, Any]]:
        """
        List all fills for a specific order, ordered chronologically.

        Args:
            order_id: Parent order ULID.

        Returns:
            List of fill dicts ordered by filled_at ascending.
        """
        result = [dict(r) for r in self._store.values() if r["order_id"] == order_id]
        # Sort by filled_at ascending (oldest first)
        result.sort(key=lambda x: x["filled_at"])
        return result

    def list_by_deployment(
        self,
        *,
        deployment_id: str,
    ) -> list[dict[str, Any]]:
        """
        List all fills across all orders for a deployment.

        Requires knowing which order_ids belong to the deployment.
        The mock stores this mapping via register_order_deployment().

        Args:
            deployment_id: Deployment ULID.

        Returns:
            List of fill dicts ordered by filled_at descending.
        """
        # Find all order_ids that belong to this deployment
        order_ids = {oid for oid, did in self._order_deployment_map.items() if did == deployment_id}
        result = [dict(r) for r in self._store.values() if r["order_id"] in order_ids]
        # Sort by filled_at descending (newest first)
        result.sort(key=lambda x: x["filled_at"], reverse=True)
        return result

    # ------------------------------------------------------------------
    # Test helpers / introspection
    # ------------------------------------------------------------------

    def register_order_deployment(self, order_id: str, deployment_id: str) -> None:
        """
        Register the mapping of order_id → deployment_id.

        Used by tests to support list_by_deployment() queries. Should be
        called when seeding or creating fills for known deployments.

        Args:
            order_id: Order ULID.
            deployment_id: Deployment ULID.
        """
        self._order_deployment_map[order_id] = deployment_id

    def seed(
        self,
        *,
        fill_id: str | None = None,
        order_id: str = "01HORDER000000000000000001",
        fill_pk: str | None = None,
        price: str = "150.25",
        quantity: str = "50",
        commission: str = "1.00",
        filled_at: str | None = None,
        correlation_id: str = "test-corr-001",
        broker_execution_id: str | None = None,
        deployment_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Prepopulate a fill record for test setup.

        Unlike save(), this allows setting arbitrary initial values and IDs
        for test determinism.

        Args:
            fill_id: Broker fill identifier (auto-generated as UUID if None).
            order_id: Parent order ULID.
            fill_pk: Internal fill primary key (auto-generated if None).
            price: Fill price.
            quantity: Fill quantity.
            commission: Commission amount.
            filled_at: Timestamp of fill (auto-generated if None).
            correlation_id: Correlation ID.
            broker_execution_id: Broker execution ID (optional).
            deployment_id: Deployment ULID (registers mapping if provided).

        Returns:
            Seeded fill dict.

        Example:
            fill = repo.seed(
                order_id="01HORDER...",
                deployment_id="01HDEPLOY...",
                quantity="100",
            )
        """
        if fill_pk is None:
            fill_pk = _generate_test_ulid()
        if fill_id is None:
            fill_id = _generate_test_ulid()
        if filled_at is None:
            filled_at = datetime.now(tz=timezone.utc).isoformat()

        now = datetime.now(tz=timezone.utc).isoformat()
        record: dict[str, Any] = {
            "id": fill_pk,
            "order_id": order_id,
            "fill_id": fill_id,
            "price": price,
            "quantity": quantity,
            "commission": commission,
            "filled_at": filled_at,
            "correlation_id": correlation_id,
            "broker_execution_id": broker_execution_id,
            "created_at": now,
        }
        self._store[fill_pk] = record
        if deployment_id is not None:
            self._order_deployment_map[order_id] = deployment_id
        return dict(record)

    def count(self) -> int:
        """Return the number of stored fills."""
        return len(self._store)

    def get_all(self) -> list[dict[str, Any]]:
        """Return all stored fills."""
        return [dict(r) for r in self._store.values()]

    def clear(self) -> None:
        """Remove all stored data."""
        self._store.clear()
        self._order_deployment_map.clear()
