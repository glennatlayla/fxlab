"""
SQL-backed feed health repository implementation (ISS-014).

Responsibilities:
- Retrieve feed health status from the feed_health_events table.
- Implement FeedHealthRepositoryInterface using SQLAlchemy ORM.
- Return current health report for all feeds or a single feed.

Does NOT:
- Compute health scores or anomaly detection (upstream service layer).
- Perform business logic or filtering beyond query parameters.

Dependencies:
- sqlalchemy.orm.Session: Database session (injected via __init__).
- libs.contracts.models.Feed, FeedHealthEvent: ORM models.
- libs.contracts.feed: FeedHealthListResponse contract.
- libs.contracts.feed_health: FeedHealthReport contract.
- libs.contracts.errors.NotFoundError: Raised when record not found.
- structlog: Structured logging.

Error conditions:
- get_health_by_feed_id: raises NotFoundError when no health record exists.

Example:
    from services.api.db import SessionLocal
    from services.api.repositories.sql_feed_health_repository import SqlFeedHealthRepository

    db = SessionLocal()
    repo = SqlFeedHealthRepository(db=db)
    summary = repo.get_all_health(correlation_id="corr-1")
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from libs.contracts.errors import NotFoundError
from libs.contracts.feed import FeedHealthListResponse
from libs.contracts.feed_health import Anomaly, AnomalyType, FeedHealthReport, FeedHealthStatus
from libs.contracts.interfaces.feed_health_repository import FeedHealthRepositoryInterface
from libs.contracts.models import Feed as FeedModel
from libs.contracts.models import FeedHealthEvent as FeedHealthEventModel

logger = structlog.get_logger(__name__)


class SqlFeedHealthRepository(FeedHealthRepositoryInterface):
    """
    SQL-backed implementation of FeedHealthRepositoryInterface.

    Responsibilities:
    - Query the feed_health_events table to retrieve latest health status.
    - Convert ORM models to Pydantic contracts.
    - Raise NotFoundError when feed health records are not found.
    - Aggregate health reports for all feeds.

    Does NOT:
    - Compute health scores or anomaly detection.
    - Validate health data beyond schema.
    - Perform business logic or orchestration.

    Dependencies:
    - SQLAlchemy Session (injected): Database connection.

    Error conditions:
    - get_health_by_feed_id: raises NotFoundError if feed_id has no health record.

    Example:
        repo = SqlFeedHealthRepository(db=session)
        report = repo.get_health_by_feed_id("01HQFEED...", correlation_id="corr-1")
    """

    def __init__(self, db: Session) -> None:
        """
        Initialize the SQL feed health repository.

        Args:
            db: SQLAlchemy Session instance (injected by FastAPI Depends).

        Example:
            repo = SqlFeedHealthRepository(db=get_db())
        """
        self.db = db

    def get_all_health(self, correlation_id: str) -> FeedHealthListResponse:
        """
        Return the current health status for every registered feed.

        Args:
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            FeedHealthListResponse with one FeedHealthReport per feed and
            a server-generated timestamp.

        Example:
            summary = repo.get_all_health(correlation_id="corr-1")
            assert isinstance(summary.feeds, list)
        """
        # Get all feeds with their latest health events
        stmt = select(FeedModel)
        orm_feeds = self.db.execute(stmt).scalars().all()

        health_reports = []
        for feed in orm_feeds:
            report = self._get_health_report_for_feed(feed.id)
            health_reports.append(report)

        logger.debug(
            "feed_health.get_all",
            correlation_id=correlation_id,
            feed_count=len(health_reports),
        )

        return FeedHealthListResponse(
            feeds=health_reports,
            generated_at=datetime.now(timezone.utc),
        )

    def get_health_by_feed_id(self, feed_id: str, correlation_id: str) -> FeedHealthReport:
        """
        Return the health report for a single feed.

        Args:
            feed_id: 26-character ULID of the feed.
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            FeedHealthReport for the specified feed.

        Raises:
            NotFoundError: If no health record exists for feed_id.

        Example:
            report = repo.get_health_by_feed_id("01HQFEED...", correlation_id="corr-1")
            assert report.feed_id == "01HQFEED..."
        """
        # Verify feed exists
        stmt = select(FeedModel).where(FeedModel.id == feed_id)
        feed = self.db.execute(stmt).scalar_one_or_none()

        if feed is None:
            logger.warning(
                "feed_health.feed_not_found",
                feed_id=feed_id,
                correlation_id=correlation_id,
            )
            raise NotFoundError(f"Feed {feed_id!r} not found")

        logger.debug(
            "feed_health.get_by_feed_id",
            feed_id=feed_id,
            correlation_id=correlation_id,
        )

        return self._get_health_report_for_feed(feed_id)

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _get_health_report_for_feed(self, feed_id: str) -> FeedHealthReport:
        """
        Build a FeedHealthReport for a single feed by querying health events.

        Args:
            feed_id: ULID of the feed.

        Returns:
            FeedHealthReport with latest status and empty anomalies list (M5+ feature).
        """
        # Get the latest health event for this feed
        stmt = (
            select(FeedHealthEventModel)
            .where(FeedHealthEventModel.feed_id == feed_id)
            .order_by(FeedHealthEventModel.checked_at.desc())
            .limit(1)
        )
        latest_event = self.db.execute(stmt).scalar_one_or_none()

        # Determine status
        status = FeedHealthStatus.UNKNOWN
        last_update = datetime.now(timezone.utc)

        if latest_event:
            # Map string status to enum
            status_str = latest_event.status.lower()
            if status_str == "healthy":
                status = FeedHealthStatus.HEALTHY
            elif status_str == "degraded":
                status = FeedHealthStatus.DEGRADED
            elif status_str == "failed":
                status = FeedHealthStatus.FAILED
            last_update = latest_event.checked_at

        return FeedHealthReport(
            feed_id=feed_id,
            status=status,
            last_update=last_update,
            recent_anomalies=[],  # M5+ feature
        )
