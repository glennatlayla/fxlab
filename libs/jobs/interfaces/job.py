"""
Job domain interfaces and value objects.

Responsibilities:
- Define the abstract port for job management.
- Declare JobStatus, JobType, ComputePolicy domain types.
- Provide the Job value object used across the platform.

Does NOT:
- Connect to any queue backend or database.
- Contain business logic beyond type declarations.

Dependencies:
- None (pure Python + enum + Pydantic)

Example:
    from libs.jobs.interfaces.job import Job, JobType, ComputePolicy

    job = Job(
        id="01HQAAAAAAAAAAAAAAAAAAAAAA",
        type=JobType.OPTIMIZATION,
        status=JobStatus.PENDING,
        compute_policy=ComputePolicy.STANDARD,
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """
    Lifecycle states for an async compute job.

    State machine: PENDING → RUNNING → COMPLETED | FAILED | CANCELLED
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    """
    Classification of compute job types managed by the platform.

    Each type maps to a distinct execution path in the job runner.
    """

    OPTIMIZATION = "optimization"
    BACKTEST = "backtest"
    PROMOTION_VALIDATION = "promotion_validation"
    FEED_VERIFICATION = "feed_verification"
    PARITY_CHECK = "parity_check"


class ComputePolicy(str, Enum):
    """
    Resource allocation policy governing how jobs are scheduled.

    STANDARD: default priority, shared resource pool.
    HIGH_PRIORITY: elevated queue priority, reserved slots.
    EXCLUSIVE: dedicated compute resources, no sharing.
    """

    STANDARD = "standard"
    HIGH_PRIORITY = "high_priority"
    EXCLUSIVE = "exclusive"


class Job(BaseModel):
    """
    Immutable value object representing a compute job.

    Responsibilities:
    - Carry job identity, type, status, and policy configuration.
    - Serve as the canonical in-memory representation passed between layers.

    Does NOT:
    - Persist itself.
    - Trigger side-effects.

    Example:
        job = Job(
            id="01HQAAAAAAAAAAAAAAAAAAAAAA",
            type=JobType.OPTIMIZATION,
            status=JobStatus.PENDING,
            compute_policy=ComputePolicy.STANDARD,
        )
        assert job.is_terminal() is False
    """

    id: str = Field(..., description="ULID of the job", min_length=26, max_length=26)
    type: JobType = Field(..., description="Classification of the job")
    status: JobStatus = Field(..., description="Current lifecycle state")
    compute_policy: ComputePolicy = Field(
        default=ComputePolicy.STANDARD,
        description="Resource allocation policy for this job",
    )
    run_id: str | None = Field(
        default=None,
        description="ULID of the associated strategy run, if any",
    )
    strategy_id: str | None = Field(
        default=None,
        description="ULID of the strategy this job belongs to, if any",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp when the job was enqueued",
    )
    started_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when execution started",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when execution finished (completed/failed)",
    )
    error_message: str | None = Field(
        default=None,
        description="Human-readable error description for FAILED jobs",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value context attached to the job",
    )

    def is_terminal(self) -> bool:
        """
        Return True if the job is in a terminal (non-resumable) state.

        Returns:
            True for COMPLETED, FAILED, or CANCELLED; False otherwise.

        Example:
            job = Job(id="...", type=JobType.BACKTEST, status=JobStatus.FAILED, ...)
            assert job.is_terminal() is True
        """
        return self.status in {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }

    def is_active(self) -> bool:
        """
        Return True if the job is currently being processed.

        Returns:
            True for PENDING or RUNNING; False otherwise.
        """
        return self.status in {JobStatus.PENDING, JobStatus.RUNNING}

    model_config = {"frozen": True}


class JobRepositoryInterface(ABC):
    """
    Abstract port for job persistence.

    Responsibilities:
    - Save and retrieve Job value objects.
    - Support status-based queries.

    Does NOT:
    - Execute jobs.
    - Contain scheduling logic.

    Example:
        repo = ConcreteJobRepository(db_session=session)
        job = repo.get(job_id="01HQ...")
    """

    @abstractmethod
    def save(self, job: Job) -> Job:
        """
        Persist a job (insert or update by id).

        Args:
            job: Job value object to persist.

        Returns:
            The persisted job (may differ if server sets fields).

        Raises:
            ExternalServiceError: If the underlying store is unavailable.
        """

    @abstractmethod
    def get(self, job_id: str) -> Job:
        """
        Retrieve a job by its ULID.

        Args:
            job_id: ULID of the job.

        Returns:
            The Job with matching id.

        Raises:
            NotFoundError: If no job with that id exists.
        """

    @abstractmethod
    def list_by_status(self, status: JobStatus) -> list[Job]:
        """
        Return all jobs in the given status.

        Args:
            status: Filter to this JobStatus.

        Returns:
            List of matching Job objects (may be empty).
        """


__all__ = [
    "ComputePolicy",
    "Job",
    "JobRepositoryInterface",
    "JobStatus",
    "JobType",
]
