"""
In-memory mock implementation of FeedRepositoryInterface.

Responsibilities:
- Provide a fully functional in-memory feed repository for unit tests.
- Honour the same interface contract as the production SqlFeedRepository.
- Expose introspection helpers (all(), count(), clear()) so tests can verify
  side-effects without depending on return values alone.

Does NOT:
- Perform any I/O.
- Validate business rules (that belongs in the service layer).

Dependencies:
- libs.contracts.interfaces.feed_repository.FeedRepositoryInterface
- libs.contracts.feed (FeedDetailResponse, FeedListResponse, FeedResponse)
- libs.contracts.errors.NotFoundError

Example:
    from datetime import datetime, timezone
    repo = MockFeedRepository()
    feed = FeedResponse(
        id="01HQFEEDAAAAAAAAAAAAAAAAA1",
        name="binance-btcusd",
        provider="Binance",
        config={},
        is_active=True,
        is_quarantined=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    detail = FeedDetailResponse(feed=feed, version_history=[], connectivity_tests=[])
    repo.save(detail)
    found = repo.find_by_id("01HQFEEDAAAAAAAAAAAAAAAAA1", correlation_id="corr-1")
    assert found.feed.name == "binance-btcusd"
"""

from __future__ import annotations

import builtins

from libs.contracts.errors import NotFoundError
from libs.contracts.feed import FeedDetailResponse, FeedListResponse
from libs.contracts.interfaces.feed_repository import FeedRepositoryInterface


class MockFeedRepository(FeedRepositoryInterface):
    """
    In-memory feed repository for unit testing.

    Stores FeedDetailResponse objects keyed by feed ULID.
    list() projects them to FeedResponse and applies pagination.
    find_by_id() returns the full FeedDetailResponse.

    Introspection helpers:
    - all()   — return every saved FeedDetailResponse
    - count() — return number of saved feeds
    - clear() — wipe the store
    """

    def __init__(self) -> None:
        """Initialise with an empty in-memory store."""
        # Store full detail objects; list() projects to the subset needed.
        self._store: dict[str, FeedDetailResponse] = {}

    # ------------------------------------------------------------------
    # FeedRepositoryInterface implementation
    # ------------------------------------------------------------------

    def list(self, limit: int, offset: int, correlation_id: str) -> FeedListResponse:
        """
        Return a paginated list of registered feeds.

        Projects stored FeedDetailResponse objects to FeedResponse for the list.

        Args:
            limit: Maximum number of results to return.
            offset: Number of results to skip.
            correlation_id: Tracing correlation ID (unused in mock).

        Returns:
            FeedListResponse with paginated FeedResponse objects.

        Example:
            resp = repo.list(limit=2, offset=0, correlation_id="corr-1")
            assert resp.total_count == repo.count()
        """
        all_details = list(self._store.values())
        total_count = len(all_details)
        page = all_details[offset : offset + limit]
        feeds = [d.feed for d in page]
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
            correlation_id: Tracing correlation ID (unused in mock).

        Returns:
            FeedDetailResponse if found.

        Raises:
            NotFoundError: If no feed with feed_id is in the store.

        Example:
            detail = repo.find_by_id("01HQFEED...", correlation_id="corr-1")
            assert detail.feed.id == "01HQFEED..."
        """
        if feed_id not in self._store:
            raise NotFoundError(f"Feed {feed_id!r} not found")
        return self._store[feed_id]

    # ------------------------------------------------------------------
    # Convenience save (not part of interface — test setup only)
    # ------------------------------------------------------------------

    def save(self, detail: FeedDetailResponse) -> FeedDetailResponse:
        """
        Persist a FeedDetailResponse to the in-memory store.

        Not part of FeedRepositoryInterface — used by tests to pre-populate
        the repository before exercising the read methods.

        Args:
            detail: Fully populated FeedDetailResponse. detail.feed.id must
                    be a non-empty ULID string.

        Returns:
            The same detail object (pass-through).

        Raises:
            ValueError: If detail.feed.id is empty or None.

        Example:
            repo.save(FeedDetailResponse(feed=FeedResponse(id="01HQ...", ...), ...))
            assert repo.count() == 1
        """
        if not detail.feed.id:
            raise ValueError("FeedDetailResponse.feed.id must be a non-empty ULID string")
        self._store[detail.feed.id] = detail
        return detail

    # ------------------------------------------------------------------
    # Introspection helpers (test-only, not part of the interface)
    # ------------------------------------------------------------------

    def all(self) -> builtins.list[FeedDetailResponse]:
        """
        Return all FeedDetailResponse objects in the store.

        Returns:
            List of every saved FeedDetailResponse, in insertion order.
        """
        return list(self._store.values())

    def count(self) -> int:
        """
        Return the number of feeds in the store.

        Returns:
            Integer count >= 0.
        """
        return len(self._store)

    def clear(self) -> None:
        """
        Remove all feeds from the store.

        Use in test teardown or when a test needs a fresh state mid-run.
        """
        self._store.clear()
