"""
SQL repository for execution event persistence (append-only).

Responsibilities:
- Persist execution lifecycle events via SQLAlchemy.
- Support querying by order, deployment, and correlation ID.
- Generate ULID primary keys for new records.

Does NOT:
- Update or delete events (append-only semantics).
- Contain business logic or orchestration.
- Manage order state transitions.

Dependencies:
- SQLAlchemy Session (injected).
- libs.contracts.models.ExecutionEvent ORM model.
- libs.contracts.models.Order ORM model (for deployment join).

Error conditions:
- IntegrityError: raised if order_id FK constraint is violated.

Example:
    db = next(get_db())
    repo = SqlExecutionEventRepository(db=db)
    event = repo.save(
        order_id="01HORDER...",
        event_type="submitted",
        timestamp="2026-04-11T14:30:00+00:00",
        details={"broker_order_id": "ALPACA-12345"},
        correlation_id="corr-001",
    )
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from libs.contracts.interfaces.execution_event_repository_interface import (
    ExecutionEventRepositoryInterface,
)
from libs.contracts.models import ExecutionEvent, Order

logger = structlog.get_logger(__name__)


def _generate_ulid() -> str:
    """
    Generate a cryptographically random, time-ordered ULID.

    Returns:
        26-character ULID string (Crockford base32).
    """
    import ulid as _ulid

    return str(_ulid.ULID())


def _event_to_dict(event: ExecutionEvent) -> dict[str, Any]:
    """
    Convert an ExecutionEvent ORM instance to a plain dict.

    Timestamp is converted to ISO 8601 string for cross-layer transport.

    Args:
        event: ExecutionEvent ORM instance.

    Returns:
        Dict with all event fields.
    """
    return {
        "id": event.id,
        "order_id": event.order_id,
        "event_type": event.event_type,
        "timestamp": (event.timestamp.isoformat() if event.timestamp else None),
        "details": event.details,
        "correlation_id": event.correlation_id,
    }


class SqlExecutionEventRepository(ExecutionEventRepositoryInterface):
    """
    SQL implementation of ExecutionEventRepositoryInterface.

    Responsibilities:
    - Append-only persistence of execution lifecycle events.
    - Retrieval by order, deployment (via join), or correlation ID.
    - ULID generation for new records.

    Does NOT:
    - Update or delete events.
    - Contain business logic.

    Dependencies:
    - db: SQLAlchemy Session, injected by the caller.

    Example:
        repo = SqlExecutionEventRepository(db=session)
        event = repo.save(
            order_id="01HORDER...",
            event_type="submitted",
            timestamp="2026-04-11T14:30:00+00:00",
            correlation_id="corr-001",
        )
    """

    def __init__(self, db: Any) -> None:
        """
        Initialise with an active SQLAlchemy session.

        Args:
            db: SQLAlchemy Session for database operations.
        """
        self._db: Session = db

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

        Args:
            order_id: Parent order ULID.
            event_type: Event type string.
            timestamp: ISO 8601 timestamp string.
            details: Optional JSON-serialisable dict.
            correlation_id: Distributed tracing ID.

        Returns:
            Dict with all event fields including generated id.
        """
        event_id = _generate_ulid()
        ts = datetime.fromisoformat(timestamp)

        record = ExecutionEvent(
            id=event_id,
            order_id=order_id,
            event_type=event_type,
            timestamp=ts,
            details=details or {},
            correlation_id=correlation_id,
        )

        self._db.add(record)
        self._db.flush()

        logger.debug(
            "execution_event.saved",
            operation="execution_event_save",
            component="SqlExecutionEventRepository",
            event_id=event_id,
            order_id=order_id,
            event_type=event_type,
        )

        return _event_to_dict(record)

    def list_by_order(self, *, order_id: str) -> list[dict[str, Any]]:
        """
        List all execution events for a specific order, chronologically.

        Args:
            order_id: Parent order ULID.

        Returns:
            List of event dicts ordered by timestamp ascending.
        """
        records = (
            self._db.query(ExecutionEvent)
            .filter(ExecutionEvent.order_id == order_id)
            .order_by(ExecutionEvent.timestamp.asc())
            .all()
        )
        return [_event_to_dict(r) for r in records]

    def search_by_correlation_id(self, *, correlation_id: str) -> list[dict[str, Any]]:
        """
        Search execution events by correlation ID.

        Args:
            correlation_id: Distributed tracing ID.

        Returns:
            List of event dicts ordered by timestamp ascending.
        """
        records = (
            self._db.query(ExecutionEvent)
            .filter(ExecutionEvent.correlation_id == correlation_id)
            .order_by(ExecutionEvent.timestamp.asc())
            .all()
        )
        return [_event_to_dict(r) for r in records]

    def list_by_deployment(self, *, deployment_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """
        List execution events across all orders for a deployment.

        Joins ExecutionEvent to Order to filter by deployment_id.

        Args:
            deployment_id: Deployment ULID.
            limit: Maximum number of events to return.

        Returns:
            List of event dicts ordered by timestamp descending.
        """
        records = (
            self._db.query(ExecutionEvent)
            .join(Order, ExecutionEvent.order_id == Order.id)
            .filter(Order.deployment_id == deployment_id)
            .order_by(ExecutionEvent.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [_event_to_dict(r) for r in records]
