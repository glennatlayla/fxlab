"""
Queue domain interfaces.

Responsibilities:
- Define the abstract port for queue state observation.
- Declare QueueDepthSnapshot and ContentionReport value objects.
- Provide ComputeContention — the API-level DTO for GET /queues/contention.

Does NOT:
- Manage queue backends (Redis, RabbitMQ, etc.).
- Contain scheduling or dispatch logic.

Dependencies:
- pydantic (value objects)

Example:
    from libs.jobs.interfaces.queue import QueueDepthSnapshot, ContentionReport

    snapshot = QueueDepthSnapshot(
        queue_name="optimization",
        depth=12,
        contention_score=37.5,
    )
    report = ContentionReport(queues=[snapshot], overall_score=37.5)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class QueueDepthSnapshot(BaseModel):
    """
    Point-in-time snapshot of a single queue's depth and contention.

    Responsibilities:
    - Carry queue identity, current depth, and contention metric.

    Attributes:
        queue_name: Human-readable name identifying the queue.
        depth: Number of items currently waiting in the queue.
        contention_score: 0–100 index; higher means more contention.
        captured_at: UTC timestamp when the snapshot was taken.
    """

    queue_name: str = Field(..., description="Identifier for the queue")
    depth: int = Field(..., ge=0, description="Current number of items in the queue")
    contention_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Contention index (0=idle, 100=fully saturated)",
    )
    captured_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of this snapshot",
    )

    model_config = {"frozen": True}


class ContentionReport(BaseModel):
    """
    Aggregated queue contention report for GET /queues/contention.

    Responsibilities:
    - Bundle per-queue snapshots with an overall contention index.
    - Serve as the response DTO for the contention endpoint.

    Attributes:
        queues: Snapshots for each tracked queue.
        overall_score: Weighted aggregate contention across all queues.
        generated_at: UTC timestamp when the report was assembled.
    """

    queues: list[QueueDepthSnapshot] = Field(
        default_factory=list,
        description="Per-queue depth and contention snapshots",
    )
    overall_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Aggregate contention index across all queues",
    )
    generated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when the report was generated",
    )

    model_config = {"frozen": True}


class QueueServiceInterface(ABC):
    """
    Abstract port for queue state observation.

    Responsibilities:
    - Produce ContentionReport snapshots for the monitoring endpoint.

    Does NOT:
    - Enqueue or dequeue jobs (that belongs to JobRepositoryInterface).
    - Connect directly to queue backends (adapters do that).

    Example:
        svc = ConcreteQueueService(redis=redis_client)
        report = svc.get_contention_report()
    """

    @abstractmethod
    def get_contention_report(self) -> ContentionReport:
        """
        Produce a current ContentionReport for all tracked queues.

        Returns:
            ContentionReport with per-queue snapshots and overall score.

        Raises:
            ExternalServiceError: If the queue backend is unreachable.
        """


__all__ = [
    "ContentionReport",
    "QueueDepthSnapshot",
    "QueueServiceInterface",
]
