"""
In-memory mock order repository for unit testing.

Responsibilities:
- Implement OrderRepositoryInterface with dict-backed storage.
- Maintain multiple indexes (client_order_id, broker_order_id) for lookups.
- Provide seed() and introspection helpers for test setup and assertions.
- Match the behavioural contract of the production SQL repository.

Does NOT:
- Persist data across process restarts.
- Contain business logic or state machine rules.
- Enforce uniqueness constraints (tested elsewhere).

Dependencies:
- libs.contracts.interfaces.order_repository_interface.OrderRepositoryInterface
- libs.contracts.errors.NotFoundError

Error conditions:
- NotFoundError: order_id does not exist (same as SQL repo).

Example:
    repo = MockOrderRepository()
    record = repo.save(
        client_order_id="client-001",
        deployment_id="01HDEPLOYTEST...",
        strategy_id="01HSTRATTEST...",
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity="100",
        time_in_force="day",
        status="pending",
        correlation_id="test-corr-001",
        execution_mode="paper",
    )
    assert repo.get_by_id(record["id"]) is not None
    assert repo.get_by_client_order_id("client-001") == record
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.order_repository_interface import (
    OrderRepositoryInterface,
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


class MockOrderRepository(OrderRepositoryInterface):
    """
    In-memory implementation of OrderRepositoryInterface for unit tests.

    Responsibilities:
    - Store order records in a dict keyed by order ID.
    - Maintain indices for client_order_id and broker_order_id lookups.
    - Provide seed() for prepopulating test data.
    - Provide introspection helpers for assertions.

    Does NOT:
    - Enforce business rules or order validation (service responsibility).
    - Persist across test runs.

    Example:
        repo = MockOrderRepository()
        record = repo.save(
            client_order_id="client-001",
            deployment_id="01HDEPLOYTEST...",
            strategy_id="01HSTRATTEST...",
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity="100",
            time_in_force="day",
            status="pending",
            correlation_id="test-corr-001",
            execution_mode="paper",
        )
        assert repo.count() == 1
        assert repo.get_by_client_order_id("client-001") == record
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._client_id_index: dict[str, str] = {}
        self._broker_id_index: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Interface methods
    # ------------------------------------------------------------------

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
        """
        order_id = _generate_test_ulid()
        now = datetime.now(tz=timezone.utc).isoformat()
        record: dict[str, Any] = {
            "id": order_id,
            "client_order_id": client_order_id,
            "deployment_id": deployment_id,
            "strategy_id": strategy_id,
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "time_in_force": time_in_force,
            "status": status,
            "correlation_id": correlation_id,
            "execution_mode": execution_mode,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "broker_order_id": broker_order_id,
            "submitted_at": None,
            "filled_at": None,
            "cancelled_at": None,
            "average_fill_price": None,
            "filled_quantity": None,
            "rejected_reason": None,
            "created_at": now,
            "updated_at": now,
        }
        self._store[order_id] = record
        self._client_id_index[client_order_id] = order_id
        if broker_order_id is not None:
            self._broker_id_index[broker_order_id] = order_id
        return dict(record)

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
        record = self._store.get(order_id)
        if record is None:
            raise NotFoundError(f"Order {order_id} not found")
        return dict(record)

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
        order_id = self._client_id_index.get(client_order_id)
        if order_id is None:
            return None
        return dict(self._store[order_id])

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
        order_id = self._broker_id_index.get(broker_order_id)
        if order_id is None:
            return None
        return dict(self._store[order_id])

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
        result = [
            dict(r)
            for r in self._store.values()
            if r["deployment_id"] == deployment_id and (status is None or r["status"] == status)
        ]
        # Sort by created_at descending
        result.sort(key=lambda x: x["created_at"], reverse=True)
        return result

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
        non_terminal_statuses = {"pending", "submitted", "partial_fill"}
        result = [
            dict(r)
            for r in self._store.values()
            if r["deployment_id"] == deployment_id and r["status"] in non_terminal_statuses
        ]
        # Sort by created_at descending
        result.sort(key=lambda x: x["created_at"], reverse=True)
        return result

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
        record = self._store.get(order_id)
        if record is None:
            raise NotFoundError(f"Order {order_id} not found")

        record["status"] = status
        if broker_order_id is not None:
            # Update index if broker_order_id was previously None
            if record["broker_order_id"] is None:
                self._broker_id_index[broker_order_id] = order_id
            # Otherwise, assume the broker_order_id was already indexed
            record["broker_order_id"] = broker_order_id
        if submitted_at is not None:
            record["submitted_at"] = submitted_at
        if filled_at is not None:
            record["filled_at"] = filled_at
        if cancelled_at is not None:
            record["cancelled_at"] = cancelled_at
        if average_fill_price is not None:
            record["average_fill_price"] = average_fill_price
        if filled_quantity is not None:
            record["filled_quantity"] = filled_quantity
        if rejected_reason is not None:
            record["rejected_reason"] = rejected_reason

        record["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
        return dict(record)

    # ------------------------------------------------------------------
    # Test helpers / introspection
    # ------------------------------------------------------------------

    def seed(
        self,
        *,
        order_id: str | None = None,
        client_order_id: str = "test-client-001",
        deployment_id: str = "01HDEPLOYTEST0000000000001",
        strategy_id: str = "01HSTRATTEST00000000000001",
        symbol: str = "AAPL",
        side: str = "buy",
        order_type: str = "market",
        quantity: str = "100",
        time_in_force: str = "day",
        status: str = "pending",
        correlation_id: str = "test-corr-001",
        execution_mode: str = "paper",
        limit_price: str | None = None,
        stop_price: str | None = None,
        broker_order_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Prepopulate an order record for test setup.

        Unlike save(), this allows setting an arbitrary initial state
        and order_id for test determinism.

        Args:
            order_id: Fixed ULID (auto-generated if None).
            client_order_id: Client order identifier.
            deployment_id: Deployment ULID.
            strategy_id: Strategy ULID.
            symbol: Instrument ticker.
            side: Order side ("buy" or "sell").
            order_type: Order type.
            quantity: Order quantity.
            time_in_force: Time in force.
            status: Order status.
            correlation_id: Correlation ID.
            execution_mode: Execution mode.
            limit_price: Limit price (optional).
            stop_price: Stop price (optional).
            broker_order_id: Broker order ID (optional).

        Returns:
            Seeded order dict.

        Example:
            record = repo.seed(status="submitted", symbol="GOOGL")
        """
        if order_id is None:
            order_id = _generate_test_ulid()
        now = datetime.now(tz=timezone.utc).isoformat()
        record: dict[str, Any] = {
            "id": order_id,
            "client_order_id": client_order_id,
            "deployment_id": deployment_id,
            "strategy_id": strategy_id,
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "time_in_force": time_in_force,
            "status": status,
            "correlation_id": correlation_id,
            "execution_mode": execution_mode,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "broker_order_id": broker_order_id,
            "submitted_at": None,
            "filled_at": None,
            "cancelled_at": None,
            "average_fill_price": None,
            "filled_quantity": None,
            "rejected_reason": None,
            "created_at": now,
            "updated_at": now,
        }
        self._store[order_id] = record
        self._client_id_index[client_order_id] = order_id
        if broker_order_id is not None:
            self._broker_id_index[broker_order_id] = order_id
        return dict(record)

    def count(self) -> int:
        """Return the number of stored orders."""
        return len(self._store)

    def get_all(self) -> list[dict[str, Any]]:
        """Return all stored orders."""
        return [dict(r) for r in self._store.values()]

    def clear(self) -> None:
        """Remove all stored data."""
        self._store.clear()
        self._client_id_index.clear()
        self._broker_id_index.clear()
