"""
SQL-backed audit explorer repository implementation (ISS-021).

Responsibilities:
- Retrieve audit events from the database with optional filtering.
- Implement AuditExplorerRepositoryInterface using SQLAlchemy ORM.
- Support cursor-paginated listing and finding by ID.

Does NOT:
- Write audit events (write-side is separate).
- Perform business logic or filtering beyond query parameters.

Dependencies:
- sqlalchemy.orm.Session: Database session (injected via __init__).
- libs.contracts.models.AuditEvent: ORM model.
- libs.contracts.audit_explorer: AuditEventRecord contract.
- libs.contracts.errors.NotFoundError: Raised when record not found.
- structlog: Structured logging.

Error conditions:
- find_by_id: raises NotFoundError when audit event ID is unknown.

Example:
    from services.api.db import SessionLocal
    from services.api.repositories.sql_audit_explorer_repository import SqlAuditExplorerRepository

    db = SessionLocal()
    repo = SqlAuditExplorerRepository(db=db)
    events = repo.list(limit=50, correlation_id="corr-1")
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from libs.contracts.audit_explorer import AuditEventRecord
from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.audit_explorer_repository import AuditExplorerRepositoryInterface
from libs.contracts.models import AuditEvent as AuditEventModel

logger = structlog.get_logger(__name__)


class SqlAuditExplorerRepository(AuditExplorerRepositoryInterface):
    """
    SQL-backed implementation of AuditExplorerRepositoryInterface.

    Responsibilities:
    - Query audit_events table with optional actor/action_type/target_type/target_id filters.
    - Convert ORM models to Pydantic contracts.
    - Raise NotFoundError when audit event IDs are not found.
    - Support cursor-based pagination for efficient large result sets.

    Does NOT:
    - Write audit events (append-only write-side is separate).
    - Validate data beyond schema.
    - Perform orchestration or business logic.

    Dependencies:
    - SQLAlchemy Session (injected): Database connection.

    Error conditions:
    - find_by_id: raises NotFoundError if audit event ID not in database.

    Example:
        repo = SqlAuditExplorerRepository(db=session)
        events = repo.list(actor="user:123", limit=50, correlation_id="corr-1")
    """

    def __init__(self, db: Session) -> None:
        """
        Initialize the SQL audit explorer repository.

        Args:
            db: SQLAlchemy Session instance (injected by FastAPI Depends).

        Example:
            repo = SqlAuditExplorerRepository(db=get_db())
        """
        self.db = db

    def list(
        self,
        *,
        actor: str = "",
        action_type: str = "",
        target_type: str = "",
        target_id: str = "",
        cursor: str = "",
        limit: int = 50,
        correlation_id: str,
    ) -> list[AuditEventRecord]:
        """
        Return a filtered, cursor-paginated list of audit events.

        Args:
            actor:          Filter by actor identity string. Empty = no filter.
            action_type:    Filter by action verb prefix, e.g. 'run'. Empty = no filter.
            target_type:    Filter by object_type, e.g. 'run'. Empty = no filter.
            target_id:      Filter by object_id ULID. Empty = no filter.
            cursor:         Opaque cursor for next-page retrieval. Empty = first page.
            limit:          Maximum number of events to return.
            correlation_id: Request-scoped tracing ID.

        Returns:
            List of matching AuditEventRecord (may be empty).

        Example:
            events = repo.list(actor="user:123", limit=50, correlation_id="corr-1")
        """
        # Build query with filters
        stmt = select(AuditEventModel).order_by(AuditEventModel.created_at.desc())
        filters = []

        if actor:
            filters.append(AuditEventModel.actor == actor)
        if action_type:
            filters.append(AuditEventModel.action.startswith(action_type))
        if target_type:
            filters.append(AuditEventModel.object_type == target_type)
        if target_id:
            filters.append(AuditEventModel.object_id == target_id)

        if filters:
            stmt = stmt.where(and_(*filters))

        # Handle cursor pagination (cursor is the ID of the last item from previous page)
        if cursor:
            stmt = stmt.where(AuditEventModel.id < cursor)

        # Apply limit + 1 to detect if there are more pages
        orm_events = self.db.execute(stmt.limit(limit + 1)).scalars().all()

        events = [self._orm_to_contract(evt) for evt in orm_events[:limit]]

        logger.debug(
            "audit.list",
            correlation_id=correlation_id,
            event_count=len(events),
            actor_filter=actor,
            target_type_filter=target_type,
        )

        return events

    def find_by_id(self, id: str, correlation_id: str) -> AuditEventRecord:
        """
        Return a single audit event by ULID.

        Args:
            id:             ULID of the audit event.
            correlation_id: Request-scoped tracing ID.

        Returns:
            AuditEventRecord for the given ID.

        Raises:
            NotFoundError: If no audit event exists with the given ID.

        Example:
            event = repo.find_by_id("01HQAUDIT0AAAAAAAAAAAAAAAA1", "corr-1")
        """
        stmt = select(AuditEventModel).where(AuditEventModel.id == id)
        orm_event = self.db.execute(stmt).scalar_one_or_none()

        if orm_event is None:
            logger.warning(
                "audit.not_found",
                audit_id=id,
                correlation_id=correlation_id,
            )
            raise NotFoundError(f"Audit event {id!r} not found")

        logger.debug(
            "audit.found",
            audit_id=id,
            correlation_id=correlation_id,
        )

        return self._orm_to_contract(orm_event)

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _orm_to_contract(orm_event: Any) -> AuditEventRecord:
        """
        Convert an ORM AuditEvent model to a Pydantic AuditEventRecord contract.

        Args:
            orm_event: SQLAlchemy ORM AuditEvent instance.

        Returns:
            AuditEventRecord Pydantic model.
        """
        return AuditEventRecord(
            id=orm_event.id,
            actor=orm_event.actor,
            action=orm_event.action,
            target_id=orm_event.object_id,
            target_type=orm_event.object_type,
            metadata=orm_event.event_metadata or {},
            created_at=orm_event.created_at,
        )
