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

import os
from datetime import datetime, timezone
from typing import Any

import structlog

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.queue_repository import QueueRepositoryInterface
from libs.contracts.queue import QueueContentionResponse, QueueSnapshotResponse
from services.api.infrastructure.task_retry import (
    DEFAULT_RETRY_CONFIG,
    TaskRetryConfig,
    with_retry,
)

logger = structlog.get_logger(__name__)

# Try to import Celery; if not available, gracefully degrade.
try:
    from celery import Celery
    from celery.app.control import Inspect

    _CELERY_AVAILABLE = True
except ImportError:
    _CELERY_AVAILABLE = False
    Celery = None
    Inspect = None


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

    def __init__(self, retry_config: TaskRetryConfig | None = None) -> None:
        """
        Initialize the Celery queue repository with optional retry configuration.

        Attempts to connect to Celery/Redis; if unavailable, marks as degraded.

        Args:
            retry_config: TaskRetryConfig for retry logic on Celery inspect calls.
                Defaults to DEFAULT_RETRY_CONFIG if not provided.

        Example:
            repo = CeleryQueueRepository()
            # Or with custom retry config:
            config = TaskRetryConfig(max_retries=5, base_delay_seconds=0.5)
            repo = CeleryQueueRepository(retry_config=config)
        """
        self.celery_app: Any = None
        self.inspect: Any = None
        self.retry_config = retry_config or DEFAULT_RETRY_CONFIG

        if _CELERY_AVAILABLE and Celery is not None:
            try:
                # Read broker URL from REDIS_URL env var.
                # Production: REDIS_URL is mandatory (fail fast on missing).
                # Development/test: falls back to localhost for ergonomics.
                broker_url = os.environ.get("REDIS_URL")
                environment = os.environ.get("ENVIRONMENT", "").lower()

                if not broker_url:
                    if environment == "production":
                        raise RuntimeError(
                            "REDIS_URL is required in production for the Celery "
                            "queue repository. Set REDIS_URL to your Redis cluster "
                            "endpoint (e.g. redis://redis:6379/0). Falling back to "
                            "localhost is not permitted in production deployments."
                        )
                    # Development/test: allow localhost fallback
                    broker_url = "redis://localhost:6379/0"
                    logger.warning(
                        "celery_queue.localhost_fallback",
                        component="celery_queue",
                        detail="REDIS_URL not set — falling back to localhost.",
                    )
                self.celery_app = Celery(broker=broker_url)
                self.inspect = self.celery_app.control.inspect()
                logger.info(
                    "celery_queue.initialized",
                    broker=broker_url.split("@")[-1] if "@" in broker_url else broker_url,
                )
            except RuntimeError:
                # Re-raise configuration errors (e.g. missing REDIS_URL in prod)
                raise
            except Exception as exc:
                logger.warning(
                    "celery_queue.init_failed",
                    error=str(exc),
                    status="degraded",
                )
        else:
            # Celery library not installed — check if this is production
            environment = os.environ.get("ENVIRONMENT", "").lower()
            redis_url = os.environ.get("REDIS_URL")
            if environment == "production" and not redis_url:
                raise RuntimeError(
                    "REDIS_URL is required in production for the Celery "
                    "queue repository. Set REDIS_URL to your Redis cluster "
                    "endpoint (e.g. redis://redis:6379/0). Falling back to "
                    "localhost is not permitted in production deployments."
                )
            logger.warning(
                "celery_queue.not_available",
                status="degraded",
            )

    def list(self, correlation_id: str) -> list[QueueSnapshotResponse]:
        """
        Return snapshots for all registered queue classes.

        Wraps Celery inspect calls with exponential backoff retry logic to handle
        transient failures (e.g., Redis unavailable, network timeouts).

        Args:
            correlation_id: Request correlation ID for distributed tracing.

        Returns:
            List of QueueSnapshotResponse objects. Empty list if Celery unavailable
            or unreachable after max retries.

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
            # Wrap Celery inspect calls with retry logic for transient failures.
            def get_active_tasks() -> dict[str, Any]:
                return self.inspect.active() or {}

            def get_registered_queues() -> dict[str, Any]:
                return self.inspect.registered() or {}

            active_tasks = with_retry(get_active_tasks, self.retry_config, logger)
            registered_queues = with_retry(get_registered_queues, self.retry_config, logger)

            # Build list of queue snapshots
            snapshots: list[QueueSnapshotResponse] = []
            seen_queues = set()

            # Count active tasks per queue
            queue_depths: dict[str, int] = {}
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
                        now = datetime.now(timezone.utc)
                        snapshots.append(
                            QueueSnapshotResponse(
                                id=f"queue:{queue_name}",
                                queue_name=queue_name,
                                timestamp=now,
                                depth=depth,
                                contention_score=contention_score,
                                metadata={},
                                created_at=now,
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
            if snapshot.queue_name == queue_class:
                logger.debug(
                    "celery_queue.find_by_class",
                    queue_class=queue_class,
                    correlation_id=correlation_id,
                    depth=snapshot.depth,
                )
                return QueueContentionResponse(
                    queue_class=queue_class,
                    depth=snapshot.depth,
                    running=0,
                    failed=0,
                    contention_score=snapshot.contention_score,
                    generated_at=snapshot.timestamp,
                )

        logger.warning(
            "celery_queue.queue_not_found",
            queue_class=queue_class,
            correlation_id=correlation_id,
        )
        raise NotFoundError(f"Queue class {queue_class!r} not found")
