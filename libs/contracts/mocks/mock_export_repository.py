"""
Thread-safe in-memory mock implementation of ExportRepositoryInterface.

Purpose:
    Provide a fully functional in-memory export job store for unit testing
    without requiring database infrastructure.

Responsibilities:
    - Store and retrieve export jobs in memory.
    - Enforce ULID uniqueness on job IDs.
    - Support filtering by requested_by and object_id.
    - Provide introspection helpers for test assertions.
    - Use threading.Lock to protect concurrent access.

Does NOT:
    - Persist data across process boundaries.
    - Validate domain constraints (service layer responsibility).

Dependencies:
    - threading: Lock for thread safety.
    - libs.contracts.export: ExportJobResponse, ExportStatus.
    - libs.contracts.interfaces.export_repository: ExportRepositoryInterface.
    - libs.contracts.errors: NotFoundError.

Example:
    repo = MockExportRepository()
    job = repo.create_job(ExportJobResponse(...))
    assert repo.count() == 1
    repo.clear()
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from libs.contracts.errors import NotFoundError
from libs.contracts.export import ExportJobResponse, ExportStatus
from libs.contracts.interfaces.export_repository_interface import (
    ExportRepositoryInterface,
)


class MockExportRepository(ExportRepositoryInterface):
    """
    In-memory mock implementation of ExportRepositoryInterface for testing.

    Stores jobs in a dict keyed by job ID. Thread-safe via threading.Lock.
    Includes introspection methods for test assertions.

    Attributes:
        _store: Dict mapping job_id -> ExportJobResponse.
        _lock: threading.Lock protecting concurrent access to _store.
    """

    def __init__(self) -> None:
        """Initialize the in-memory store and lock."""
        self._store: dict[str, ExportJobResponse] = {}
        self._lock = threading.Lock()

    def create_job(self, job: ExportJobResponse) -> ExportJobResponse:
        """
        Persist a new export job.

        Args:
            job: ExportJobResponse with all required fields.

        Returns:
            The persisted job (same as input).

        Raises:
            ValueError: If a job with the same id already exists.
        """
        with self._lock:
            if job.id in self._store:
                raise ValueError(f"Export job {job.id} already exists")
            self._store[job.id] = job
            return job

    def get_job(self, job_id: str) -> ExportJobResponse | None:
        """
        Retrieve an export job by ID.

        Args:
            job_id: The ULID of the export job.

        Returns:
            The job if found, None otherwise.
        """
        with self._lock:
            return self._store.get(job_id)

    def update_job(
        self,
        job_id: str,
        status: ExportStatus,
        artifact_uri: str | None = None,
        error_message: str | None = None,
    ) -> ExportJobResponse:
        """
        Update the status, artifact URI, and/or error message of a job.

        Args:
            job_id: The ULID of the export job.
            status: New status for the job.
            artifact_uri: Optional artifact URI (set when complete).
            error_message: Optional error description (set on failure).

        Returns:
            The updated job.

        Raises:
            NotFoundError: If the job does not exist.
        """
        with self._lock:
            if job_id not in self._store:
                raise NotFoundError(f"Export job {job_id} not found")

            job = self._store[job_id]
            # Create updated version with new fields
            updated = ExportJobResponse(
                id=job.id,
                export_type=job.export_type,
                object_id=job.object_id,
                status=status,
                artifact_uri=artifact_uri if artifact_uri is not None else job.artifact_uri,
                requested_by=job.requested_by,
                error_message=error_message if error_message is not None else job.error_message,
                created_at=job.created_at,
                updated_at=datetime.now(timezone.utc),
                override_watermark=job.override_watermark,
            )
            self._store[job_id] = updated
            return updated

    def list_jobs(
        self,
        *,
        requested_by: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ExportJobResponse], int]:
        """
        List export jobs with optional filtering by requested_by.

        Args:
            requested_by: Optional ULID of requesting user (filters if provided).
            limit: Max number of jobs to return (default 50).
            offset: Pagination offset (default 0).

        Returns:
            Tuple of (list of jobs, total count of matching jobs).
        """
        with self._lock:
            # Filter by requested_by if provided
            filtered = [
                job
                for job in self._store.values()
                if requested_by is None or job.requested_by == requested_by
            ]

            # Sort by created_at descending (newest first)
            filtered.sort(key=lambda j: j.created_at, reverse=True)

            # Apply pagination
            total = len(filtered)
            paginated = filtered[offset : offset + limit]

            return paginated, total

    def list_by_object_id(
        self,
        object_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ExportJobResponse], int]:
        """
        List all export jobs for a specific object.

        Args:
            object_id: The ULID of the object (run, candidate, or artifact).
            limit: Max number of jobs to return (default 50).
            offset: Pagination offset (default 0).

        Returns:
            Tuple of (list of jobs, total count of matching jobs).
        """
        with self._lock:
            # Filter by object_id
            filtered = [job for job in self._store.values() if job.object_id == object_id]

            # Sort by created_at descending (newest first)
            filtered.sort(key=lambda j: j.created_at, reverse=True)

            # Apply pagination
            total = len(filtered)
            paginated = filtered[offset : offset + limit]

            return paginated, total

    # -----------------------------------------------------------------------
    # Introspection helpers (for testing)
    # -----------------------------------------------------------------------

    def count(self) -> int:
        """
        Return the total number of jobs in the store.

        Returns:
            Count of all jobs.
        """
        with self._lock:
            return len(self._store)

    def get_all(self) -> list[ExportJobResponse]:
        """
        Return all jobs (unordered, for inspection).

        Returns:
            List of all jobs.
        """
        with self._lock:
            return list(self._store.values())

    def clear(self) -> None:
        """
        Clear all jobs from the store (for test isolation).

        Returns:
            None
        """
        with self._lock:
            self._store.clear()
