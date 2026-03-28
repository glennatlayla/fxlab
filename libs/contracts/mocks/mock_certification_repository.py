"""
MockCertificationRepository — in-memory CertificationRepositoryInterface for unit tests (M8).

Purpose:
    Provide a fast, fully controllable fake implementation of
    CertificationRepositoryInterface so that unit tests can exercise
    certification route handlers without a real database.

Responsibilities:
    - Store CertificationEvent objects in memory, keyed by feed_id.
    - Implement list() and find_by_feed_id() with the same error contracts as
      the real (SQL-backed) implementation.
    - Provide save() and clear() introspection helpers for test setup/teardown.

Does NOT:
    - Connect to any database or external system.
    - Contain certification business logic.

Dependencies:
    - CertificationRepositoryInterface (parent).
    - CertificationEvent (domain contract).
    - NotFoundError (typed exception).

Error conditions:
    - find_by_feed_id raises NotFoundError for unknown feed_id.

Example:
    repo = MockCertificationRepository()
    repo.save(
        CertificationEvent.model_construct(
            feed_id="01HQFEED0AAAAAAAAAAAAAAAA0",
            feed_name="AAPL_primary",
            status=CertificationStatus.CERTIFIED,
            blocked_reason="",
            generated_at=datetime.now(timezone.utc),
        )
    )
    events = repo.list(correlation_id="test")
    # events == [the saved event]
"""

from __future__ import annotations

from libs.contracts.certification import CertificationEvent
from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.certification_repository import (
    CertificationRepositoryInterface,
)


class MockCertificationRepository(CertificationRepositoryInterface):
    """
    In-memory CertificationRepositoryInterface for unit tests.

    Thread-safety: Not thread-safe.  Use only in synchronous unit tests.
    """

    def __init__(self) -> None:
        # Keyed by feed_id (str ULID).
        self._store: dict[str, CertificationEvent] = {}

    # ------------------------------------------------------------------
    # CertificationRepositoryInterface implementation
    # ------------------------------------------------------------------

    def list(self, correlation_id: str) -> list[CertificationEvent]:
        """
        Return all certification events.

        Args:
            correlation_id: Ignored in mock; accepted for interface parity.

        Returns:
            List of all saved CertificationEvent objects (insertion order).
        """
        return list(self._store.values())

    def find_by_feed_id(
        self, feed_id: str, correlation_id: str
    ) -> CertificationEvent:
        """
        Return the CertificationEvent for a specific feed.

        Args:
            feed_id:        Feed ULID to look up.
            correlation_id: Ignored in mock.

        Returns:
            CertificationEvent matching feed_id.

        Raises:
            NotFoundError: If no certification record exists for feed_id.

        Example:
            event = repo.find_by_feed_id("01HQFEED0AAAAAAAAAAAAAAAA0", "c")
        """
        if feed_id not in self._store:
            raise NotFoundError(f"CertificationEvent for feed_id={feed_id!r} not found")
        return self._store[feed_id]

    # ------------------------------------------------------------------
    # Test introspection helpers
    # ------------------------------------------------------------------

    def save(self, event: CertificationEvent) -> None:
        """
        Persist a CertificationEvent to the in-memory store.

        Args:
            event: CertificationEvent to store; keyed by event.feed_id.
        """
        self._store[event.feed_id] = event

    def clear(self) -> None:
        """Remove all stored certification events."""
        self._store.clear()

    def count(self) -> int:
        """Return the number of stored certification events."""
        return len(self._store)
