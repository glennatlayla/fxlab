"""
Feed repository interface (port).

Responsibilities:
- Define the abstract contract for feed registry data access.
- Decouple route handlers from any specific database implementation.
- Enable in-memory mock substitution in unit tests.

Does NOT:
- Execute SQL or any I/O.
- Contain business logic or filtering beyond what the interface specifies.

Dependencies:
- libs.contracts.feed: FeedDetailResponse, FeedListResponse.
- libs.contracts.errors: NotFoundError.

Error conditions:
- find_by_id: raises NotFoundError when feed_id has no matching record.

Example:
    repo: FeedRepositoryInterface = MockFeedRepository()
    listing = repo.list(limit=20, offset=0, correlation_id="corr-1")
    detail = repo.find_by_id("01HQFEEDAAAAAAAAAAAAAAAAA1", correlation_id="corr-1")
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.feed import FeedDetailResponse, FeedListResponse
from libs.contracts.errors import NotFoundError  # noqa: F401 — document raised type


class FeedRepositoryInterface(ABC):
    """
    Port interface for feed registry data access.

    Implementations:
    - MockFeedRepository      — in-memory, for unit tests
    - SqlFeedRepository       — SQLAlchemy-backed, for production (future)
    """

    @abstractmethod
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
            # resp.total_count >= 0
            # len(resp.feeds) <= 20
        """
        ...

    @abstractmethod
    def find_by_id(self, feed_id: str, correlation_id: str) -> FeedDetailResponse:
        """
        Return the full detail record for a single feed.

        Args:
            feed_id: 26-character ULID of the feed.
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            FeedDetailResponse with feed metadata, version history, and
            connectivity test results.

        Raises:
            NotFoundError: If no feed with feed_id exists.

        Example:
            detail = repo.find_by_id("01HQFEED...", correlation_id="corr-1")
            # detail.feed.id == "01HQFEED..."
            # detail.version_history[0].version >= 1
        """
        ...
