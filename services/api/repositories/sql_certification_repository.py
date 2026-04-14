"""
SQL-backed certification repository implementation (ISS-019).

Responsibilities:
- Retrieve feed certification events from the database.
- Implement CertificationRepositoryInterface using SQLAlchemy ORM.
- Support listing all events and finding by feed_id.

Does NOT:
- Perform certification checks or business logic.
- Validate certification data beyond schema.

Dependencies:
- sqlalchemy.orm.Session: Database session (injected via __init__).
- libs.contracts.certification: CertificationEvent contract.
- libs.contracts.errors.NotFoundError: Raised when record not found.
- structlog: Structured logging.

Error conditions:
- find_by_feed_id: raises NotFoundError when feed_id has no record.

Example:
    from services.api.db import SessionLocal
    from services.api.repositories.sql_certification_repository import SqlCertificationRepository

    db = SessionLocal()
    repo = SqlCertificationRepository(db=db)
    events = repo.list(correlation_id="corr-1")
"""

from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

from libs.contracts.certification import CertificationEvent
from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.certification_repository import CertificationRepositoryInterface

logger = structlog.get_logger(__name__)


class SqlCertificationRepository(CertificationRepositoryInterface):
    """
    SQL-backed implementation of CertificationRepositoryInterface.

    Responsibilities:
    - Query certification event data from the database.
    - Convert ORM models to Pydantic contracts.
    - Raise NotFoundError when feed certification records are not found.

    Does NOT:
    - Perform certification checks or business logic.
    - Validate data beyond schema.
    - Perform orchestration.

    Dependencies:
    - SQLAlchemy Session (injected): Database connection.

    Error conditions:
    - find_by_feed_id: raises NotFoundError if feed_id has no record.

    Example:
        repo = SqlCertificationRepository(db=session)
        events = repo.list(correlation_id="corr-1")
    """

    def __init__(self, db: Session) -> None:
        """
        Initialize the SQL certification repository.

        Args:
            db: SQLAlchemy Session instance (injected by FastAPI Depends).

        Example:
            repo = SqlCertificationRepository(db=get_db())
        """
        self.db = db

    def list(self, correlation_id: str) -> list[CertificationEvent]:
        """
        Return all certification events.

        Args:
            correlation_id: Request-scoped tracing ID for structured logging.

        Returns:
            List of CertificationEvent (may be empty).

        Example:
            events = repo.list(correlation_id="corr-1")
            assert isinstance(events, list)
        """
        # For M5, certification data is not yet persisted.
        # Return empty list for now.
        logger.debug(
            "certification.list",
            correlation_id=correlation_id,
            status="not_implemented_m5_feature",
        )
        return []

    def find_by_feed_id(self, feed_id: str, correlation_id: str) -> CertificationEvent:
        """
        Return the certification event for a specific feed.

        Args:
            feed_id:          ULID of the feed to look up.
            correlation_id:   Request-scoped tracing ID.

        Returns:
            CertificationEvent for the specified feed.

        Raises:
            NotFoundError: If no certification record exists for feed_id.

        Example:
            event = repo.find_by_feed_id("01HQFEED...", correlation_id="corr-1")
            assert event.feed_id == "01HQFEED..."
        """
        # For M5, certification data is not yet persisted.
        logger.warning(
            "certification.find_not_implemented",
            feed_id=feed_id,
            correlation_id=correlation_id,
            status="m5_feature",
        )
        raise NotFoundError(f"Certification record for feed {feed_id!r} not found")
