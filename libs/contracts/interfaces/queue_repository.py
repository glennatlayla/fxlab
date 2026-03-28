"""
Queue repository interface (port).

Purpose:
    Define the abstract contract for queue state data access, decoupling the
    operator dashboard route handlers from Celery/Redis or any other queue backend.

Responsibilities:
    - Declare abstract methods for listing all queues and finding a specific queue
      class contention snapshot.
    - Enable in-memory mock substitution in unit tests.

Does NOT:
    - Connect to Redis or inspect Celery directly.
    - Contain scheduling or dispatch logic.
    - Return job payloads or task results.

Dependencies:
    - libs.contracts.queue: QueueSnapshotResponse, QueueContentionResponse.
    - libs.contracts.errors: NotFoundError.

Error conditions:
    - find_by_class: raises NotFoundError when queue_class has no snapshot.

Example:
    repo: QueueRepositoryInterface = MockQueueRepository()
    all_q = repo.list(correlation_id="corr-1")
    contention = repo.find_by_class("research", correlation_id="corr-1")
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.errors import NotFoundError  # noqa: F401 — document raised type
from libs.contracts.queue import QueueContentionResponse, QueueSnapshotResponse


class QueueRepositoryInterface(ABC):
    """
    Port interface for queue state data access.

    Implementations:
    - MockQueueRepository      — in-memory, for unit tests
    - CeleryQueueRepository    — Celery/Redis-backed, for production (future)
    """

    @abstractmethod
    def list(self, correlation_id: str) -> list[QueueSnapshotResponse]:
        """
        Return snapshots for all registered queue classes.

        Args:
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            List of QueueSnapshotResponse objects.  May be empty when no
            queues are registered.

        Example:
            queues = repo.list(correlation_id="corr-1")
            # len(queues) >= 0
        """
        ...

    @abstractmethod
    def find_by_class(
        self,
        queue_class: str,
        correlation_id: str,
    ) -> QueueContentionResponse:
        """
        Return the contention snapshot for a specific queue class.

        Args:
            queue_class:    Name of the queue class (e.g. 'research', 'optimize').
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            QueueContentionResponse with depth, running, failed, contention_score.

        Raises:
            NotFoundError: If no queue class with that name has a registered snapshot.

        Example:
            r = repo.find_by_class("research", correlation_id="corr-1")
            # r.queue_class == "research"
            # 0.0 <= r.contention_score <= 100.0
        """
        ...
