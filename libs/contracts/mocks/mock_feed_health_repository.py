"""
In-memory mock implementation of FeedHealthRepositoryInterface.

Responsibilities:
- Provide a fully functional in-memory feed health repository for unit tests.
- Honour the same interface contract as the production SqlFeedHealthRepository.
- Expose introspection helpers (all(), count(), clear()) for test assertions.

Does NOT:
- Perform any I/O.
- Compute health scores (that belongs to the monitoring service).

Dependencies:
- libs.contracts.interfaces.feed_health_repository.FeedHealthRepositoryInterface
- libs.contracts.feed: FeedHealthListResponse
- libs.contracts.feed_health: FeedHealthReport
- libs.contracts.errors: NotFoundError

Example:
    from datetime import datetime, timezone
    from libs.contracts.feed_health import FeedHealthStatus
    repo = MockFeedHealthRepository()
    report = FeedHealthReport(
        feed_id="01HQFEEDAAAAAAAAAAAAAAAAA1",
        status=FeedHealthStatus.HEALTHY,
        last_update=datetime.now(timezone.utc),
        recent_anomalies=[],
    )
    repo.save(report)
    summary = repo.get_all_health(correlation_id="corr-1")
    assert len(summary.feeds) == 1
"""

from __future__ import annotations

from datetime import datetime, timezone

from libs.contracts.errors import NotFoundError
from libs.contracts.feed import FeedHealthListResponse
from libs.contracts.feed_health import FeedHealthReport
from libs.contracts.interfaces.feed_health_repository import FeedHealthRepositoryInterface


class MockFeedHealthRepository(FeedHealthRepositoryInterface):
    """
    In-memory feed health repository for unit testing.

    Stores FeedHealthReport objects keyed by feed ULID.
    get_all_health() wraps them in a FeedHealthListResponse.
    get_health_by_feed_id() returns the matching report or raises NotFoundError.

    Introspection helpers:
    - all()   — return every saved FeedHealthReport
    - count() — return number of saved reports
    - clear() — wipe the store
    """

    def __init__(self) -> None:
        """Initialise with an empty in-memory store."""
        self._store: dict[str, FeedHealthReport] = {}

    # ------------------------------------------------------------------
    # FeedHealthRepositoryInterface implementation
    # ------------------------------------------------------------------

    def get_all_health(self, correlation_id: str) -> FeedHealthListResponse:
        """
        Return the current health status for every registered feed.

        Args:
            correlation_id: Tracing correlation ID (unused in mock).

        Returns:
            FeedHealthListResponse with all stored reports and a UTC timestamp.

        Example:
            summary = repo.get_all_health(correlation_id="corr-1")
            assert isinstance(summary.generated_at, datetime)
        """
        reports = list(self._store.values())
        return FeedHealthListResponse(
            feeds=reports,
            generated_at=datetime.now(timezone.utc),
        )

    def get_health_by_feed_id(self, feed_id: str, correlation_id: str) -> FeedHealthReport:
        """
        Return the health report for a single feed.

        Args:
            feed_id: 26-character ULID of the feed.
            correlation_id: Tracing correlation ID (unused in mock).

        Returns:
            FeedHealthReport for the specified feed.

        Raises:
            NotFoundError: If no health record exists for feed_id.

        Example:
            report = repo.get_health_by_feed_id("01HQFEED...", correlation_id="corr-1")
            assert report.feed_id == "01HQFEED..."
        """
        if feed_id not in self._store:
            raise NotFoundError(f"No health record for feed {feed_id!r}")
        return self._store[feed_id]

    # ------------------------------------------------------------------
    # Convenience save (not part of interface — test setup only)
    # ------------------------------------------------------------------

    def save(self, report: FeedHealthReport) -> FeedHealthReport:
        """
        Persist a FeedHealthReport to the in-memory store.

        Not part of FeedHealthRepositoryInterface — used by tests to
        pre-populate the repository.

        Args:
            report: FeedHealthReport with a non-empty feed_id.

        Returns:
            The same report (pass-through).

        Raises:
            ValueError: If report.feed_id is empty or None.

        Example:
            repo.save(FeedHealthReport(feed_id="01HQ...", status=HEALTHY, ...))
            assert repo.count() == 1
        """
        if not report.feed_id:
            raise ValueError("FeedHealthReport.feed_id must be a non-empty ULID string")
        self._store[report.feed_id] = report
        return report

    # ------------------------------------------------------------------
    # Introspection helpers (test-only, not part of the interface)
    # ------------------------------------------------------------------

    def all(self) -> list[FeedHealthReport]:
        """
        Return all FeedHealthReport objects in the store.

        Returns:
            List of every saved report, in insertion order.
        """
        return list(self._store.values())

    def count(self) -> int:
        """
        Return the number of health reports in the store.

        Returns:
            Integer count >= 0.
        """
        return len(self._store)

    def clear(self) -> None:
        """
        Remove all health reports from the store.

        Use in test teardown or when a test needs a fresh state mid-run.
        """
        self._store.clear()
