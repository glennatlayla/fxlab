"""
SQL-backed feed repository implementation (ISS-013).

Responsibilities:
- Persist and retrieve feed registry metadata from the database.
- Implement FeedRepositoryInterface using SQLAlchemy ORM.
- Support paginated listing with limit/offset.
- Return full detail including version history and connectivity tests.

Does NOT:
- Perform health checks or connectivity testing (upstream service layer).
- Perform business logic or filtering beyond query parameters.

Dependencies:
- sqlalchemy.orm.Session: Database session (injected via __init__).
- libs.contracts.models.Feed: ORM model for feeds table.
- libs.contracts.feed: Pydantic contract models.
- libs.contracts.errors.NotFoundError: Raised when record not found.
- structlog: Structured logging.

Error conditions:
- find_by_id: raises NotFoundError when feed_id has no matching record.

Example:
    from services.api.db import SessionLocal
    from services.api.repositories.sql_feed_repository import SqlFeedRepository

    db = SessionLocal()
    repo = SqlFeedRepository(db=db)
    detail = repo.find_by_id("01HQFEED...", correlation_id="corr-1")
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from libs.contracts.errors import NotFoundError
from libs.contracts.feed import FeedDetailResponse, FeedListResponse, FeedResponse
from libs.contracts.interfaces.feed_repository import FeedRepositoryInterface
from libs.contracts.models import Feed as FeedModel

logger = structlog.get_logger(__name__)


class SqlFeedRepository(FeedRepositoryInterface):
    """
    SQL-backed implementation of FeedRepositoryInterface.

    Responsibilities:
    - Query the feeds table using SQLAlchemy ORM.
    - Convert ORM models to Pydantic contracts for return values.
    - Raise NotFoundError when feeds are not found.
    - Support paginated listing via limit/offset.
    - Return complete detail with version history placeholders (M5+ feature).

    Does NOT:
    - Validate Feed data beyond schema.
    - Perform health checks or connectivity testing.
    - Perform business logic or orchestration.

    Dependencies:
    - SQLAlchemy Session (injected): Database connection.

    Error conditions:
    - find_by_id: raises NotFoundError if feed_id not in database.

    Example:
        repo = SqlFeedRepository(db=session)
        detail = repo.find_by_id("01HQFEED...", correlation_id="corr-1")
    """

    def __init__(self, db: Session) -> None:
        """
        Initialize the SQL feed repository.

        Args:
            db: SQLAlchemy Session instance (injected by FastAPI Depends).

        Example:
            repo = SqlFeedRepository(db=get_db())
        """
        self.db = db

    def list(self, limit: int, offset: int, correlation_id: str) -> FeedListResponse:
        """
        Return a paginated list of registered feeds.

        Args:
            limit: Maximum number of feeds to return.
            offset: Number of feeds to skip before returning results.
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            FeedListResponse containing feeds, total_count, limit, and offset.

        Example:
            resp = repo.list(limit=20, offset=0, correlation_id="corr-1")
            assert resp.total_count >= 0
            assert len(resp.feeds) <= 20
        """
        # Count total
        count_stmt = select(func.count(FeedModel.id))
        total_count = self.db.execute(count_stmt).scalar() or 0

        # Query with pagination
        stmt = select(FeedModel).limit(limit).offset(offset)
        orm_feeds = self.db.execute(stmt).scalars().all()

        feeds = [self._orm_to_feed_response(feed) for feed in orm_feeds]

        logger.debug(
            "feed.list",
            correlation_id=correlation_id,
            total_count=total_count,
            returned_count=len(feeds),
            limit=limit,
            offset=offset,
        )

        return FeedListResponse(
            feeds=feeds,
            total_count=total_count,
            limit=limit,
            offset=offset,
        )

    def find_by_id(self, feed_id: str, correlation_id: str) -> FeedDetailResponse:
        """
        Return the full detail record for a single feed.

        Args:
            feed_id: 26-character ULID of the feed.
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            FeedDetailResponse with feed metadata, version history,
            and connectivity test results.

        Raises:
            NotFoundError: If no feed with feed_id exists.

        Example:
            detail = repo.find_by_id("01HQFEED...", correlation_id="corr-1")
            assert detail.feed.id == "01HQFEED..."
        """
        stmt = select(FeedModel).where(FeedModel.id == feed_id)
        orm_feed = self.db.execute(stmt).scalar_one_or_none()

        if orm_feed is None:
            logger.warning(
                "feed.not_found",
                feed_id=feed_id,
                correlation_id=correlation_id,
            )
            raise NotFoundError(f"Feed {feed_id!r} not found")

        logger.debug(
            "feed.found",
            feed_id=feed_id,
            correlation_id=correlation_id,
        )

        feed_response = self._orm_to_feed_response(orm_feed)

        # Version history and connectivity tests are M5+ features.
        # For now, return empty lists.
        return FeedDetailResponse(
            feed=feed_response,
            version_history=[],
            connectivity_results=[],
        )

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _orm_to_feed_response(orm_feed: Any) -> FeedResponse:
        """
        Convert an ORM Feed model to a Pydantic FeedResponse contract.

        Args:
            orm_feed: SQLAlchemy ORM Feed instance.

        Returns:
            FeedResponse Pydantic model.
        """
        return FeedResponse(
            id=orm_feed.id,
            name=orm_feed.name,
            feed_type=orm_feed.feed_type,
            source=orm_feed.source or "",
            is_active=orm_feed.is_active,
            created_at=orm_feed.created_at,
            updated_at=orm_feed.updated_at,
        )
