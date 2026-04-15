"""
SQL repository for order fill records.

Purpose:
    Persist and retrieve individual fill events via SQLAlchemy, providing
    a production-grade replacement for the in-memory MockOrderFillRepository.

Responsibilities:
    - Record individual fill events with broker execution details.
    - Retrieve fills by parent order (chronological).
    - Retrieve fills by deployment (across all orders in the deployment).
    - Generate ULID primary keys for new fill records.

Does NOT:
    - Calculate VWAP or aggregate fill data (service layer responsibility).
    - Update parent order status (service layer responsibility).
    - Contain business logic or order submission logic.

Dependencies:
    - SQLAlchemy Session (injected via get_db per request).
    - libs.contracts.models.OrderFill ORM model.
    - libs.contracts.models.Order ORM model (for join queries).
    - libs.contracts.errors.NotFoundError.

Error conditions:
    - list_by_order: returns empty list when no fills exist (no error).
    - list_by_deployment: returns empty list when no fills exist (no error).

Example:
    db = next(get_db())
    repo = SqlOrderFillRepository(db=db)
    fill = repo.save(
        order_id="01HORDER...",
        fill_id="fill-001",
        price="150.25",
        quantity="50",
        commission="1.00",
        filled_at="2026-04-11T14:30:00+00:00",
        correlation_id="corr-abc",
    )
    fills = repo.list_by_order(order_id="01HORDER...")
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from libs.contracts.interfaces.order_fill_repository_interface import (
    OrderFillRepositoryInterface,
)
from libs.contracts.models import Order, OrderFill

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


class SqlOrderFillRepository(OrderFillRepositoryInterface):
    """
    SQLAlchemy-backed repository for order fill events.

    Responsibilities:
    - Persist individual fill records (append-only).
    - Query fills by parent order and deployment.
    - Generate ULID primary keys for new fill records.

    Does NOT:
    - Contain business logic or order workflow orchestration.
    - Call session.commit() — uses flush() to stay within the
      request-scoped transaction managed by get_db().

    Dependencies:
        db: SQLAlchemy Session, injected by the caller.

    Example:
        repo = SqlOrderFillRepository(db=session)
        fill = repo.save(
            order_id="01HORDER...",
            fill_id="fill-001",
            price="150.25",
            quantity="50",
            commission="1.00",
            filled_at="2026-04-11T14:30:00+00:00",
            correlation_id="corr-abc",
        )
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    @staticmethod
    def _fill_to_dict(record: OrderFill) -> dict[str, Any]:
        """
        Convert an OrderFill ORM instance to a plain dict.

        Returns a dict with keys matching the interface contract so
        callers don't need to change based on storage implementation.

        Args:
            record: The ORM model instance.

        Returns:
            Dict with all fill detail fields.
        """
        return {
            "id": record.id,
            "order_id": record.order_id,
            "fill_id": record.fill_id,
            "price": record.price,
            "quantity": record.quantity,
            "commission": record.commission,
            "filled_at": record.filled_at.isoformat() if record.filled_at else None,
            "broker_execution_id": record.broker_execution_id,
            "correlation_id": record.correlation_id,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

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

        Generates a ULID primary key. Parses filled_at from ISO string to
        datetime. All monetary values stored as strings for decimal precision.

        Args:
            order_id: Parent order ULID.
            fill_id: Broker-assigned fill identifier.
            price: Fill price as string.
            quantity: Fill quantity as string.
            commission: Commission charged as string.
            filled_at: ISO timestamp of the fill (e.g. "2026-04-11T14:30:00+00:00").
            correlation_id: Request correlation ID for tracing.
            broker_execution_id: Broker execution report ID (optional).

        Returns:
            Dict with all fill fields including generated id and timestamps.

        Example:
            result = repo.save(
                order_id="01HORDER...",
                fill_id="fill-001",
                price="150.25",
                quantity="50",
                commission="1.00",
                filled_at="2026-04-11T14:30:00+00:00",
                correlation_id="corr-abc",
            )
            # result["id"] == "01HFILL..."
        """
        # Parse ISO string to datetime
        filled_at_dt = datetime.fromisoformat(filled_at)

        record = OrderFill(
            id=_generate_ulid(),
            order_id=order_id,
            fill_id=fill_id,
            price=price,
            quantity=quantity,
            commission=commission,
            filled_at=filled_at_dt,
            broker_execution_id=broker_execution_id,
            correlation_id=correlation_id,
        )

        self._db.add(record)
        self._db.flush()

        logger.debug(
            "order_fill_repository.fill_persisted",
            fill_id=record.id,
            order_id=order_id,
            price=price,
            quantity=quantity,
            component="sql_order_fill_repository",
        )

        return self._fill_to_dict(record)

    def list_by_order(self, *, order_id: str) -> list[dict[str, Any]]:
        """
        List all fills for a specific order, ordered chronologically.

        Args:
            order_id: Parent order ULID.

        Returns:
            List of fill dicts ordered by filled_at ascending (earliest first).
            Returns empty list if no fills exist.

        Example:
            fills = repo.list_by_order(order_id="01HORDER...")
            # fills[0] is the first (earliest) fill
        """
        records = (
            self._db.query(OrderFill)
            .filter(OrderFill.order_id == order_id)
            .order_by(OrderFill.filled_at.asc())
            .all()
        )

        logger.debug(
            "order_fill_repository.fills_listed_by_order",
            order_id=order_id,
            count=len(records),
            component="sql_order_fill_repository",
        )

        return [self._fill_to_dict(r) for r in records]

    def list_by_deployment(self, *, deployment_id: str) -> list[dict[str, Any]]:
        """
        List all fills across all orders for a deployment.

        Joins the order_fills table to the orders table and filters by
        orders.deployment_id. Returns results ordered by filled_at descending
        (most recent first).

        Args:
            deployment_id: Deployment ULID.

        Returns:
            List of fill dicts ordered by filled_at descending.
            Returns empty list if no fills exist in the deployment.

        Example:
            fills = repo.list_by_deployment(deployment_id="01HDEPLOY...")
            # fills[0] is the most recent fill
        """
        records = (
            self._db.query(OrderFill)
            .join(Order, OrderFill.order_id == Order.id)
            .filter(Order.deployment_id == deployment_id)
            .order_by(OrderFill.filled_at.desc())
            .all()
        )

        logger.debug(
            "order_fill_repository.fills_listed_by_deployment",
            deployment_id=deployment_id,
            count=len(records),
            component="sql_order_fill_repository",
        )

        return [self._fill_to_dict(r) for r in records]
