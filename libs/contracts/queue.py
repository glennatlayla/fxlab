"""
Queue health and contention contracts.

Pydantic v2 schemas for queue monitoring.
"""

from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel, Field


class QueueSnapshotResponse(BaseModel):
    """
    Response schema for queue depth and contention snapshot.
    
    Phase 1 contract. Phase 3 consumes for queue health charts.
    """
    id: str = Field(..., description="ULID")
    queue_name: str
    timestamp: datetime
    depth: int = Field(..., ge=0)
    contention_score: float = Field(..., ge=0.0, le=100.0)
    metadata: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class QueueContentionResponse(BaseModel):
    """
    Per-queue contention snapshot for Phase 3 operator dashboard (M7).

    Purpose:
        Provide the UI with per-queue-class depth, running, failed, and
        contention score data for the operator contention dashboard.

    Responsibilities:
    - Report current depth, running job count, failed job count for one queue class.
    - Carry the contention_score (0.0–100.0) aggregated by the service layer.

    Does NOT:
    - Access Redis or Celery directly (that is the repository's responsibility).
    - Contain scheduling or dispatch logic.

    Example:
        r = QueueContentionResponse(
            queue_class="research",
            depth=5,
            running=2,
            failed=0,
            contention_score=12.5,
            generated_at=datetime.now(utc),
        )
    """

    queue_class: str = Field(..., description="Queue class name (e.g. 'research', 'optimize')")
    depth: int = Field(..., ge=0, description="Number of jobs waiting in queue")
    running: int = Field(..., ge=0, description="Number of jobs currently running")
    failed: int = Field(..., ge=0, description="Number of jobs in failed state")
    contention_score: float = Field(
        ..., ge=0.0, le=100.0, description="Contention score 0–100 (higher = more congested)"
    )
    generated_at: datetime = Field(..., description="Snapshot generation timestamp")


class QueueListResponse(BaseModel):
    """
    List of all tracked queue snapshots.

    Purpose:
        Aggregate response for GET /queues, providing the operator dashboard
        with a single-request view of all active queue classes.

    Responsibilities:
    - Wrap a list of QueueSnapshotResponse objects with a generation timestamp.

    Does NOT:
    - Include contention details (use QueueContentionResponse per queue class).

    Example:
        resp = QueueListResponse(queues=[], generated_at=datetime.now(utc))
    """

    queues: list[QueueSnapshotResponse] = Field(
        default_factory=list, description="All registered queue snapshots"
    )
    generated_at: datetime = Field(..., description="List generation timestamp")
