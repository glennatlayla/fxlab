"""
SQL-backed diagnostics repository implementation (ISS-025).

Responsibilities:
- Aggregate platform-wide operational counts from multiple tables.
- Implement DiagnosticsRepositoryInterface using SQLAlchemy ORM.
- Query queue contention alerts, feed health degraded feeds, parity critical events,
  and certification blocked runs.

Does NOT:
- Contain classification or threshold logic.
- Store snapshots or history.
- Perform business logic beyond aggregation queries.

Dependencies:
- sqlalchemy.orm.Session: Database session (injected via __init__).
- libs.contracts.observability: DiagnosticsSnapshot contract.
- structlog: Structured logging.

Example:
    from services.api.db import SessionLocal
    from services.api.repositories.sql_diagnostics_repository import SqlDiagnosticsRepository

    db = SessionLocal()
    repo = SqlDiagnosticsRepository(db=db)
    snapshot = repo.snapshot(correlation_id="corr-1")
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from libs.contracts.interfaces.diagnostics_repository import DiagnosticsRepositoryInterface
from libs.contracts.observability import DiagnosticsSnapshot

logger = structlog.get_logger(__name__)


class SqlDiagnosticsRepository(DiagnosticsRepositoryInterface):
    """
    SQL-backed implementation of DiagnosticsRepositoryInterface.

    Responsibilities:
    - Query aggregation counts from multiple tables.
    - Compute platform-wide operational snapshot.
    - Convert results to Pydantic contracts.

    Does NOT:
    - Store snapshots or history.
    - Contain classification or threshold logic.
    - Perform orchestration or business logic.

    Dependencies:
    - SQLAlchemy Session (injected): Database connection.

    Example:
        repo = SqlDiagnosticsRepository(db=session)
        snapshot = repo.snapshot(correlation_id="corr-1")
    """

    def __init__(self, db: Session) -> None:
        """
        Initialize the SQL diagnostics repository.

        Args:
            db: SQLAlchemy Session instance (injected by FastAPI Depends).

        Example:
            repo = SqlDiagnosticsRepository(db=get_db())
        """
        self.db = db

    def snapshot(self, *, correlation_id: str) -> DiagnosticsSnapshot:
        """
        Return a platform-wide operational snapshot.

        Args:
            correlation_id: Request-scoped tracing ID for structured logging.

        Returns:
            DiagnosticsSnapshot containing:
            - queue_contention_count: Number of queues with high contention.
            - feed_health_count: Number of feeds with degraded or failed health.
            - parity_critical_count: Number of critical parity events.
            - certification_blocked_count: Number of feeds with blocked certification.
            - generated_at: Snapshot timestamp.

        Example:
            snap = repo.snapshot(correlation_id="corr-abc")
            assert snap.parity_critical_count >= 0
        """
        # For M5, diagnostics aggregation is not yet fully implemented.
        # Return zero counts for now.
        queue_contention_count = self._count_queue_contention()
        feed_health_count = self._count_degraded_feeds()
        parity_critical_count = self._count_critical_parity_events()
        certification_blocked_count = self._count_blocked_certifications()

        logger.debug(
            "diagnostics.snapshot",
            correlation_id=correlation_id,
            queue_contention_count=queue_contention_count,
            feed_health_count=feed_health_count,
            parity_critical_count=parity_critical_count,
            certification_blocked_count=certification_blocked_count,
        )

        return DiagnosticsSnapshot(
            queue_contention_count=queue_contention_count,
            feed_health_count=feed_health_count,
            parity_critical_count=parity_critical_count,
            certification_blocked_count=certification_blocked_count,
            generated_at=datetime.now(timezone.utc),
        )

    # -----------------------------------------------------------------------
    # Private aggregation helpers
    # -----------------------------------------------------------------------

    def _count_queue_contention(self) -> int:
        """
        Count queues with high contention (M5+ feature).

        Returns:
            Non-negative integer.
        """
        # For M5, queue contention data is not yet persisted.
        # Return 0 for now.
        return 0

    def _count_degraded_feeds(self) -> int:
        """
        Count feeds with degraded or failed health status.

        Returns:
            Non-negative integer.
        """
        try:
            from libs.contracts.models import FeedHealthEvent as FeedHealthEventModel

            # Count distinct feeds with status != "healthy"
            stmt = select(func.count(func.distinct(FeedHealthEventModel.feed_id))).where(
                FeedHealthEventModel.status != "healthy"
            )
            count = self.db.execute(stmt).scalar() or 0
            return count
        except Exception as exc:
            logger.warning(
                "diagnostics.count_degraded_feeds_failed",
                error=str(exc),
            )
            return 0

    def _count_critical_parity_events(self) -> int:
        """
        Count critical parity events (M5+ feature).

        Returns:
            Non-negative integer.
        """
        try:
            from libs.contracts.models import ParityEvent as ParityEventModel

            stmt = select(func.count(ParityEventModel.id)).where(
                ParityEventModel.status == "CRITICAL"
            )
            count = self.db.execute(stmt).scalar() or 0
            return count
        except Exception as exc:
            logger.warning(
                "diagnostics.count_critical_parity_failed",
                error=str(exc),
            )
            return 0

    def _count_blocked_certifications(self) -> int:
        """
        Count feeds with blocked certification (M5+ feature).

        Returns:
            Non-negative integer.
        """
        # For M5, certification blocking data is not yet persisted.
        # Return 0 for now.
        return 0
