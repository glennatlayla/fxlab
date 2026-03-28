"""
In-memory mock implementation of QueueRepositoryInterface.

Purpose:
    Provide a fast, deterministic substitute for queue state data access in unit
    tests, eliminating Celery/Redis dependencies from the test suite.

Responsibilities:
    - Store QueueSnapshotResponse and QueueContentionResponse objects keyed by
      queue_class name.
    - Implement full QueueRepositoryInterface contract including NotFoundError.
    - Expose introspection helpers so tests can assert on stored state.

Does NOT:
    - Connect to Redis, Celery, or any external queue backend.
    - Contain scheduling or dispatch logic.
    - Persist state between test runs.

Dependencies:
    - libs.contracts.queue: QueueSnapshotResponse, QueueContentionResponse.
    - libs.contracts.errors: NotFoundError.
    - libs.contracts.interfaces.queue_repository: QueueRepositoryInterface.

Error conditions:
    - find_by_class: raises NotFoundError when queue_class not in store.

Example:
    from datetime import datetime, timezone
    from libs.contracts.queue import QueueContentionResponse

    repo = MockQueueRepository()
    snap = QueueContentionResponse(
        queue_class="research",
        depth=3,
        running=1,
        failed=0,
        contention_score=15.0,
        generated_at=datetime.now(timezone.utc),
    )
    repo.save_contention(snap)
    r = repo.find_by_class("research", correlation_id="c")
    assert r.queue_class == "research"
"""

from __future__ import annotations

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.queue_repository import QueueRepositoryInterface
from libs.contracts.queue import (
    QueueContentionResponse,
    QueueSnapshotResponse,
)


class MockQueueRepository(QueueRepositoryInterface):
    """
    In-memory queue repository for unit testing.

    Stores QueueSnapshotResponse objects (for list()) and QueueContentionResponse
    objects (for find_by_class()) separately, keyed by queue_name / queue_class.
    """

    def __init__(self) -> None:
        self._snapshots: dict[str, QueueSnapshotResponse] = {}
        self._contention: dict[str, QueueContentionResponse] = {}

    # ------------------------------------------------------------------
    # QueueRepositoryInterface implementation
    # ------------------------------------------------------------------

    def list(self, correlation_id: str) -> list[QueueSnapshotResponse]:
        """
        Return all stored queue snapshots.

        Args:
            correlation_id: Tracing ID (unused in mock).

        Returns:
            List of QueueSnapshotResponse objects in insertion order.

        Example:
            queues = repo.list(correlation_id="c")
            assert len(queues) == repo.count()
        """
        return list(self._snapshots.values())

    def find_by_class(
        self,
        queue_class: str,
        correlation_id: str,
    ) -> QueueContentionResponse:
        """
        Return the contention snapshot for queue_class.

        Args:
            queue_class:    Queue class name to look up.
            correlation_id: Tracing ID (unused in mock).

        Returns:
            QueueContentionResponse for the named queue class.

        Raises:
            NotFoundError: If queue_class is not in the contention store.

        Example:
            r = repo.find_by_class("research", correlation_id="c")
            assert r.queue_class == "research"
        """
        if queue_class not in self._contention:
            raise NotFoundError(f"No contention data for queue class '{queue_class}'")
        return self._contention[queue_class]

    # ------------------------------------------------------------------
    # Test-setup helpers (not part of QueueRepositoryInterface)
    # ------------------------------------------------------------------

    def save_snapshot(self, snapshot: QueueSnapshotResponse) -> None:
        """
        Store a QueueSnapshotResponse keyed by queue_name.

        Args:
            snapshot: Queue snapshot to store.

        Example:
            repo.save_snapshot(QueueSnapshotResponse(id="01HQ...", ...))
        """
        self._snapshots[snapshot.queue_name] = snapshot

    def save_contention(self, contention: QueueContentionResponse) -> None:
        """
        Store a QueueContentionResponse keyed by queue_class.

        Args:
            contention: Queue contention snapshot to store.

        Example:
            repo.save_contention(QueueContentionResponse(queue_class="research", ...))
        """
        self._contention[contention.queue_class] = contention

    # ------------------------------------------------------------------
    # Introspection helpers for test assertions
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """
        Remove all stored data.

        Example:
            repo.clear()
            assert repo.count() == 0
        """
        self._snapshots.clear()
        self._contention.clear()

    def count(self) -> int:
        """
        Return the number of stored queue snapshots.

        Example:
            assert repo.count() == 0  # after clear()
        """
        return len(self._snapshots)

    def contention_count(self) -> int:
        """
        Return the number of stored contention snapshots.

        Example:
            assert repo.contention_count() == 1  # after save_contention(...)
        """
        return len(self._contention)
