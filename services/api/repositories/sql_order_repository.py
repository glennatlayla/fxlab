"""
SQL repository for order lifecycle management.

Responsibilities:
- Persist order records and state updates via SQLAlchemy.
- Support idempotent order lookup by client_order_id.
- Filter orders by deployment, status, and broker identifiers.
- Generate ULID primary keys for new records.

Does NOT:
- Enforce order validation or state machine rules.
- Manage fills or execution events (separate repositories).
- Contain business logic or workflow orchestration.

Dependencies:
- SQLAlchemy Session (injected via get_db).
- libs.contracts.models.Order ORM model.
- libs.contracts.errors.NotFoundError.

Error conditions:
- NotFoundError: raised by get_by_id and update_status when order does not exist.
- IntegrityError: raised by save when client_order_id already exists.

Example:
    db = next(get_db())
    repo = SqlOrderRepository(db=db)
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
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.order_repository_interface import (
    OrderRepositoryInterface,
)
from libs.contracts.models import Order

logger = structlog.get_logger(__name__)


def _generate_ulid() -> str:
    """
    Generate a cryptographically random, time-ordered ULID for new records.

    Uses python-ulid which is thread-safe and produces spec-compliant
    26-character Crockford base32 ULIDs with millisecond-precision
    timestamps and 80 bits of cryptographic randomness.

    Returns:
        26-character ULID string (Crockford base32).
    """
    import ulid as _ulid

    return str(_ulid.ULID())


def _order_to_dict(order: Order) -> dict[str, Any]:
    """
    Convert an Order ORM instance to a plain dict for cross-layer transport.

    All timestamp fields are converted to ISO 8601 strings. Monetary values
    remain as strings (as stored in the database) for decimal precision safety.

    Args:
        order: Order ORM instance.

    Returns:
        Dict with all order fields, timestamps as ISO strings, monetary
        values as strings.
    """
    return {
        "id": order.id,
        "client_order_id": order.client_order_id,
        "deployment_id": order.deployment_id,
        "strategy_id": order.strategy_id,
        "symbol": order.symbol,
        "side": order.side,
        "order_type": order.order_type,
        "quantity": order.quantity,
        "limit_price": order.limit_price,
        "stop_price": order.stop_price,
        "time_in_force": order.time_in_force,
        "status": order.status,
        "broker_order_id": order.broker_order_id,
        "submitted_at": (order.submitted_at.isoformat() if order.submitted_at else None),
        "filled_at": (order.filled_at.isoformat() if order.filled_at else None),
        "cancelled_at": (order.cancelled_at.isoformat() if order.cancelled_at else None),
        "average_fill_price": order.average_fill_price,
        "filled_quantity": order.filled_quantity,
        "rejected_reason": order.rejected_reason,
        "correlation_id": order.correlation_id,
        "execution_mode": order.execution_mode,
        "row_version": order.row_version,
        "created_at": (order.created_at.isoformat() if order.created_at else None),
        "updated_at": (order.updated_at.isoformat() if order.updated_at else None),
    }


class SqlOrderRepository(OrderRepositoryInterface):
    """
    SQLAlchemy-backed repository for order lifecycle management.

    Responsibilities:
    - Save new orders with ULID primary keys.
    - Retrieve orders by id, client_order_id, or broker_order_id.
    - List orders filtered by deployment and/or status.
    - Update order status and related fields atomically.

    Does NOT:
    - Enforce order validation or state transitions.
    - Contain business logic.

    Dependencies:
        db: SQLAlchemy Session, injected by the caller.

    Example:
        repo = SqlOrderRepository(db=session)
        order = repo.save(
            client_order_id="ord-001",
            deployment_id="01HDEPLOY...",
            ...
        )
    """

    def __init__(self, db: Any) -> None:
        """
        Initialise with an active SQLAlchemy session.

        Args:
            db: An open SQLAlchemy Session from get_db().
        """
        self._db = db

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
        for decimal precision safety. Timestamps are auto-generated and stored
        as UTC.

        Args:
            client_order_id: Client-assigned idempotency key (unique).
            deployment_id: Owning deployment ULID.
            strategy_id: Originating strategy ULID.
            symbol: Instrument ticker (e.g. "AAPL", "ES=F").
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
                get_by_client_order_id for idempotent behaviour).
        """
        order_id = _generate_ulid()

        order = Order(
            id=order_id,
            client_order_id=client_order_id,
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            status=status,
            broker_order_id=broker_order_id,
            filled_quantity="0",
            correlation_id=correlation_id,
            execution_mode=execution_mode,
        )
        self._db.add(order)
        self._db.flush()

        logger.debug(
            "order_created",
            order_id=order_id,
            client_order_id=client_order_id,
            deployment_id=deployment_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            execution_mode=execution_mode,
        )

        return _order_to_dict(order)

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
        order = self._db.get(Order, order_id)
        if order is None:
            raise NotFoundError(f"Order {order_id} not found")

        logger.debug("order_retrieved", order_id=order_id)
        return _order_to_dict(order)

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
        order = self._db.query(Order).filter(Order.client_order_id == client_order_id).first()

        if order is None:
            return None

        logger.debug("order_found_by_client_id", client_order_id=client_order_id)
        return _order_to_dict(order)

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
        order = self._db.query(Order).filter(Order.broker_order_id == broker_order_id).first()

        if order is None:
            return None

        logger.debug("order_found_by_broker_id", broker_order_id=broker_order_id)
        return _order_to_dict(order)

    def list_by_deployment(
        self,
        *,
        deployment_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        List orders belonging to a deployment, optionally filtered by status.

        Orders are ordered by created_at descending (most recent first).

        Args:
            deployment_id: Deployment ULID.
            status: If provided, filter to orders with this status value.

        Returns:
            List of order dicts, ordered by created_at descending.
        """
        query = self._db.query(Order).filter(Order.deployment_id == deployment_id)

        if status is not None:
            query = query.filter(Order.status == status)

        orders = query.order_by(Order.created_at.desc()).all()

        logger.debug(
            "orders_listed_by_deployment",
            deployment_id=deployment_id,
            status_filter=status,
            count=len(orders),
        )

        return [_order_to_dict(o) for o in orders]

    def list_open_by_deployment(
        self,
        *,
        deployment_id: str,
    ) -> list[dict[str, Any]]:
        """
        List orders with non-terminal status for a deployment.

        Non-terminal statuses: pending, submitted, partial_fill.
        Terminal statuses: filled, cancelled, rejected, expired.

        Orders are ordered by created_at descending (most recent first).

        Args:
            deployment_id: Deployment ULID.

        Returns:
            List of open order dicts, ordered by created_at descending.
        """
        non_terminal_statuses = ("pending", "submitted", "partial_fill")

        orders = (
            self._db.query(Order)
            .filter(Order.deployment_id == deployment_id)
            .filter(Order.status.in_(non_terminal_statuses))
            .order_by(Order.created_at.desc())
            .all()
        )

        logger.debug(
            "open_orders_listed_by_deployment",
            deployment_id=deployment_id,
            count=len(orders),
        )

        return [_order_to_dict(o) for o in orders]

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
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """
        Update an order's status and related fields atomically.

        Only non-None arguments are updated. Datetime string arguments are
        parsed from ISO 8601 format before being stored. The updated_at
        timestamp is automatically set to now (UTC).

        When ``expected_version`` is supplied, optimistic locking is enforced:
        the update proceeds only if the current ``row_version`` matches.
        On mismatch, ``OptimisticLockError`` is raised (another worker
        updated the order concurrently).  The ``row_version`` is always
        incremented on a successful update regardless of whether the caller
        supplies ``expected_version``.

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
            expected_version: If provided, verify the current row_version
                matches before applying the update (optimistic locking).

        Returns:
            Updated order dict (includes the new row_version).

        Raises:
            NotFoundError: If no order exists with this ID.
            OptimisticLockError: If expected_version does not match
                the current row_version (concurrent write detected).

        Example:
            order = repo.update_status(
                order_id="01HORDER...",
                status="filled",
                expected_version=1,
            )
            # order["row_version"] == 2
        """
        from services.api.repositories import check_row_version

        order = self._db.get(Order, order_id)
        if order is None:
            raise NotFoundError(f"Order {order_id} not found")

        # Optimistic locking guard: reject if another worker mutated
        # the row since the caller last read it.
        if expected_version is not None:
            check_row_version(order, expected_version=expected_version)

        order.status = status

        if broker_order_id is not None:
            order.broker_order_id = broker_order_id

        if submitted_at is not None:
            order.submitted_at = datetime.fromisoformat(submitted_at)

        if filled_at is not None:
            order.filled_at = datetime.fromisoformat(filled_at)

        if cancelled_at is not None:
            order.cancelled_at = datetime.fromisoformat(cancelled_at)

        if average_fill_price is not None:
            order.average_fill_price = average_fill_price

        if filled_quantity is not None:
            order.filled_quantity = filled_quantity

        if rejected_reason is not None:
            order.rejected_reason = rejected_reason

        # Always bump row_version on every write for conflict detection.
        order.row_version = order.row_version + 1
        order.updated_at = datetime.now(tz=timezone.utc)
        self._db.flush()

        logger.debug(
            "order_status_updated",
            order_id=order_id,
            status=status,
            broker_order_id=broker_order_id,
            row_version=order.row_version,
        )

        return _order_to_dict(order)
