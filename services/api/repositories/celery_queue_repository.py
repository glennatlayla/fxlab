"""
Celery-backed queue repository implementation (ISS-017).

Responsibilities:
- Retrieve queue state and contention metrics from Celery inspect API.
- Implement QueueRepositoryInterface using Celery/Redis backend.
- Fall back gracefully when Celery/Redis are unavailable.

Does NOT:
- Contain scheduling or dispatch logic.
- Return job payloads or task results.
- Persist queue state (queries live queue state only).

Dependencies:
- celery.app.control.Inspect: Celery inspect API (optional).
- libs.contracts.queue: QueueSnapshotResponse, QueueContentionResponse.
- libs.contracts.errors.NotFoundError: Raised when queue not found.
- structlog: Structured logging.

Error conditions:
- find_by_class: raises NotFoundError when queue_class has no snapshot.
- Gracefully fallback when Celery is unavailable or misconfigured.

Example:
    from services.api.repositories.celery_queue_repository import CeleryQueueRepository

    repo = CeleryQueueRepository()
    all_queues = repo.list(correlation_id="corr-1")
    contention = repo.find_by_class("research", correlation_id="corr-1")
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.queue_repository import QueueRepositoryInterface
from libs.contracts.queue import QueueContentionResponse, QueueSnapshotResponse

logger = structlog.get_logger(__name__)

# Try to import Celery; if not available, gracefully degrade.
try:
    from celery import Celery
    from celery.app.control import Inspect

    _CELERY_AVAILABLE = True
except ImportError:
    _CELERY_AVAILABLE = False
    Celery = None  # type: ignore[assignment, misc]
    Inspect = None  # type: ignore[assignment, misc]


class CeleryQueueRepository(QueueRepositoryInterface):
    """
    Celery-backed implementation of QueueRepositoryInterface.

    Responsibilities:
    - Query Celery inspect API for queue state and contention.
    - Convert Celery data to Pydantic contracts.
    - Raise NotFoundError when queue_class is not found.
    - Gracefully handle Celery unavailability with fallback to empty list.

    Does NOT:
    - Contain scheduling or dispatch logic.
    - Persist queue state or history.
    - Return job payloads or full task results.

    Dependencies:
    - Celery with Redis broker (optional; gracefully degrades if unavailable).

    Error conditions:
    - find_by_class: raises NotFoundError if queue_class has no snapshot.

    Example:
        repo = CeleryQueueRepository()
        all_q = repo.list(correlation_id="corr-1")
        # If Celery unavailable, returns []
        contention = repo.find_by_class("research", correlation_id="corr-1")
        # If queue not found, raises NotFoundError
    """

    def __init__(self) -> None:
        """
        Initialize the Celery queue repository.

        Attempts to connect to Celery/Redis; if unavailable, marks as degraded.

        Example:
            repo = CeleryQueueRepository()
        """
        self.celery_app: Any = None
        self.inspect: Any = None

        if _CELERY_AVAILABLE and Celery is not None:
            try:
                # Try to get the default Celery app instance
                self.celery_app = Celery()
                self.celery_app.conf.broker_url = "redis://localhost:6379/0"
                self.inspect = self.celery_app.control.inspect()
                logger.info("celery_queue.initialized", broker="redis")
            except Exception as exc:
                logger.warning(
                    "celery_queue.init_failed",
                    error=str(exc),
                    status="degraded",
                )
        else:
            logger.warning(
                "celery_queue.not_available",
                status="degraded",
            )

    def list(self, correlation_id: str) -> list[QueueSnapshotResponse]:
        """
        Return snapshots for all registered queue classes.

        Args:
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            List of QueueSnapshotResponse objects. Empty list if Celery unavailable.

        Example:
            queues = repo.list(correlation_id="corr-1")
            assert isinstance(queues, list)
        """
        if self.inspect is None:
            logger.warning(
                "celery_queue.list_unavailable",
                correlation_id=correlation_id,
            )
            return []

        try:
            # Get active tasks and queues from Celery
            active_tasks = self.inspect.active() or {}
            registered_queues = self.inspect.registered() or {}

            # Build list of queue snapshots
            snapshots: list[QueueSnapshotResponse] = []
            seen_queues = set()

            # Count active tasks per queue
            queue_depths = {}
            for worker_tasks in active_tasks.values():
                for task in worker_tasks:
                    queue = task.get("delivery_info", {}).get("routing_key", "default")
                    queue_depths[queue] = queue_depths.get(queue, 0) + 1

            # Extract unique queue names from registered queues
            for queue_names in registered_queues.values():
                for queue_name in queue_names:
                    if queue_name not in seen_queues:
                        seen_queues.add(queue_name)
                        depth = queue_depths.get(queue_name, 0)
                        # Compute basic contention (depth as proxy)
                        contention_score = float(min(depth * 10, 100))
                        snapshots.append(
                            QueueSnapshotResponse(
                                queue_class=queue_name,
                                depth=depth,
                                running=0,
                                failed=0,
                                contention_score=contention_score,
                                generated_at=datetime.now(timezone.utc),
                            )
                        )

            logger.debug(
                "celery_queue.list",
                correlation_id=correlation_id,
                queue_count=len(snapshots),
            )

            return snapshots

        except Exception as exc:
            logger.warning(
                "celery_queue.list_failed",
                correlation_id=correlation_id,
                error=str(exc),
            )
            return []

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
            assert r.queue_class == "research"
        """
        snapshots = self.list(correlation_id=correlation_id)

        for snapshot in snapshots:
            if snapshot.queue_class == queue_class:
                logger.debug(
                    "celery_queue.find_by_class",
                    queue_class=queue_class,
                    correlation_id=correlation_id,
                    depth=snapshot.depth,
                )
                return QueueContentionResponse(
                    queue_class=snapshot.queue_class,
                    depth=snapshot.depth,
                    running=snapshot.running,
                    failed=snapshot.failed,
                    contention_score=snapshot.contention_score,
                    generated_at=snapshot.generated_at,
                )

        logger.warning(
            "celery_queue.queue_not_found",
            queue_class=queue_class,
            correlation_id=correlation_id,
        )
        raise NotFoundError(f"Queue class {queue_class!r} not found")
