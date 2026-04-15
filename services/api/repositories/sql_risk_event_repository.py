"""
SQL repository for risk event persistence (append-only).

Responsibilities:
- Persist risk check events via SQLAlchemy to the risk_events table.
- Map between Pydantic RiskEvent and ORM RiskEvent models.
- Support querying by deployment with optional severity filter.

Does NOT:
- Make risk decisions (RiskGateService responsibility).
- Update or delete events (append-only semantics).
- Contain business logic.

Dependencies:
- SQLAlchemy Session (injected).
- libs.contracts.models.RiskEvent ORM model (aliased as RiskEventORM).
- libs.contracts.risk: RiskEvent Pydantic model, RiskEventSeverity.

Example:
    db = next(get_db())
    repo = SqlRiskEventRepository(db=db)
    event = RiskEvent(event_id="01HRISK...", deployment_id="01HDEPLOY...", ...)
    repo.save(event)
    events = repo.list_by_deployment(deployment_id="01HDEPLOY...")
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.orm import Session

from libs.contracts.interfaces.risk_event_repository_interface import (
    RiskEventRepositoryInterface,
)
from libs.contracts.models import RiskEvent as RiskEventORM
from libs.contracts.risk import RiskEvent, RiskEventSeverity

logger = structlog.get_logger(__name__)


def _pydantic_to_orm(event: RiskEvent) -> RiskEventORM:
    """
    Convert a Pydantic RiskEvent to its ORM counterpart.

    The severity enum value is stored as its string representation.
    The created_at datetime is stored directly.

    Args:
        event: Pydantic RiskEvent instance.

    Returns:
        ORM RiskEvent ready for persistence.
    """
    return RiskEventORM(
        id=event.event_id,
        deployment_id=event.deployment_id,
        check_name=event.check_name,
        passed=event.passed,
        severity=event.severity.value,
        reason=event.reason,
        current_value=event.current_value,
        limit_value=event.limit_value,
        order_client_id=event.order_client_id,
        symbol=event.symbol,
        correlation_id=event.correlation_id,
        created_at=event.created_at,
    )


def _orm_to_pydantic(record: RiskEventORM) -> RiskEvent:
    """
    Convert an ORM RiskEvent to its Pydantic counterpart.

    The severity string is mapped back to the RiskEventSeverity enum.

    Args:
        record: ORM RiskEvent instance.

    Returns:
        Pydantic RiskEvent.
    """
    return RiskEvent(
        event_id=record.id,
        deployment_id=record.deployment_id,
        check_name=record.check_name,
        severity=RiskEventSeverity(record.severity),
        passed=record.passed,
        reason=record.reason,
        current_value=record.current_value,
        limit_value=record.limit_value,
        order_client_id=record.order_client_id,
        symbol=record.symbol,
        correlation_id=record.correlation_id,
        created_at=record.created_at,
    )


class SqlRiskEventRepository(RiskEventRepositoryInterface):
    """
    SQL implementation of RiskEventRepositoryInterface.

    Responsibilities:
    - Append-only persistence of risk check events.
    - Query by deployment with optional severity filter.
    - Map between Pydantic and ORM models at the boundary.

    Does NOT:
    - Make risk decisions.
    - Update or delete events.

    Dependencies:
    - db: SQLAlchemy Session, injected by the caller.

    Example:
        repo = SqlRiskEventRepository(db=session)
        repo.save(event)
        events = repo.list_by_deployment(deployment_id="01HDEPLOY...")
    """

    def __init__(self, db: Any) -> None:
        """
        Initialise with an active SQLAlchemy session.

        Args:
            db: SQLAlchemy Session for database operations.
        """
        self._db: Session = db

    def save(self, event: RiskEvent) -> None:
        """
        Persist a risk event.

        Converts the Pydantic model to its ORM counterpart and flushes
        to the database within the current transaction.

        Args:
            event: Pydantic RiskEvent to persist.
        """
        orm_record = _pydantic_to_orm(event)
        self._db.add(orm_record)
        self._db.flush()

        logger.debug(
            "risk_event.saved",
            operation="risk_event_save",
            component="SqlRiskEventRepository",
            event_id=event.event_id,
            deployment_id=event.deployment_id,
            check_name=event.check_name,
            severity=event.severity.value,
            passed=event.passed,
        )

    def list_by_deployment(
        self,
        *,
        deployment_id: str,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[RiskEvent]:
        """
        List risk events for a deployment, most recent first.

        Args:
            deployment_id: ULID of the deployment.
            severity: Optional filter by severity level string.
            limit: Maximum number of events to return.

        Returns:
            List of Pydantic RiskEvent objects, most recent first.
        """
        query = self._db.query(RiskEventORM).filter(RiskEventORM.deployment_id == deployment_id)

        if severity is not None:
            query = query.filter(RiskEventORM.severity == severity)

        records = query.order_by(RiskEventORM.created_at.desc()).limit(limit).all()
        return [_orm_to_pydantic(r) for r in records]
