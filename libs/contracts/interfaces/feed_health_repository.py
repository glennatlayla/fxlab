"""
Feed health repository interface (port).

Responsibilities:
- Define the abstract contract for feed health data access.
- Decouple the feed_health route handler from any specific backend.
- Enable in-memory mock substitution in unit tests.

Does NOT:
- Execute SQL or I/O.
- Compute health scores or anomaly detection (that is done by the monitoring service).

Dependencies:
- libs.contracts.feed: FeedHealthListResponse.
- libs.contracts.feed_health: FeedHealthReport.
- libs.contracts.errors: NotFoundError.

Error conditions:
- get_health_by_feed_id: raises NotFoundError when feed_id has no health record.

Example:
    repo: FeedHealthRepositoryInterface = MockFeedHealthRepository()
    summary = repo.get_all_health(correlation_id="corr-1")
    report = repo.get_health_by_feed_id("01HQFEED...", correlation_id="corr-1")
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.errors import NotFoundError  # noqa: F401 — document raised type
from libs.contracts.feed import FeedHealthListResponse
from libs.contracts.feed_health import FeedHealthReport


class FeedHealthRepositoryInterface(ABC):
    """
    Port interface for feed health state access.

    Implementations:
    - MockFeedHealthRepository — in-memory, for unit tests
    - SqlFeedHealthRepository  — SQLAlchemy-backed, for production (future)
    """

    @abstractmethod
    def get_all_health(self, correlation_id: str) -> FeedHealthListResponse:
        """
        Return the current health status for every registered feed.

        Args:
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            FeedHealthListResponse with one FeedHealthReport per feed and a
            server-generated timestamp.

        Example:
            summary = repo.get_all_health(correlation_id="corr-1")
            # summary.feeds is a list of FeedHealthReport objects
            # summary.generated_at is a UTC datetime
        """
        ...

    @abstractmethod
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
            # report.status in FeedHealthStatus
        """
        ...
