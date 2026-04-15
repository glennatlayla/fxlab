"""
Export job repository interface (port).

Responsibilities:
- Define the abstract contract for export job persistence and retrieval.
- Support create, get, update status, and list operations.
- Provide pagination support for list queries.

Does NOT:
- Implement storage logic.
- Contain business logic.

Dependencies:
- None (pure interface).

Example:
    repo: ExportRepositoryInterface = SqlExportRepository(db=session)
    job = repo.create_job(job_response)
    job = repo.get_job(job_id="01HEXPORT...")
    job = repo.update_job(job_id="01HEXPORT...", status=ExportStatus.PROCESSING)
    jobs, total = repo.list_jobs(requested_by="01HUSER...", limit=10)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.export import ExportJobResponse, ExportStatus


class ExportRepositoryInterface(ABC):
    """
    Port interface for export job persistence.

    Responsibilities:
    - Create new export jobs and persist them.
    - Retrieve jobs by ID.
    - Update job status, artifact URI, and error messages.
    - List jobs with pagination support.

    Does NOT:
    - Validate export type or object IDs (service layer responsibility).
    - Generate artifact URIs (service layer responsibility).
    """

    @abstractmethod
    def create_job(self, job: ExportJobResponse) -> ExportJobResponse:
        """
        Persist a new export job.

        Args:
            job: ExportJobResponse with id, export_type, object_id, status, requested_by, etc.

        Returns:
            The persisted job.

        Raises:
            ValueError: If a job with the same id already exists.
        """
        ...

    @abstractmethod
    def get_job(self, job_id: str) -> ExportJobResponse | None:
        """
        Retrieve an export job by ID.

        Args:
            job_id: The ULID of the export job.

        Returns:
            The job if found, None otherwise.
        """
        ...

    @abstractmethod
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
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    def list_by_object_id(
        self,
        object_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ExportJobResponse], int]:
        """
        List all export jobs for a specific object (run, candidate, artifact).

        Args:
            object_id: The ULID of the object (run, candidate, or artifact).
            limit: Max number of jobs to return (default 50).
            offset: Pagination offset (default 0).

        Returns:
            Tuple of (list of jobs, total count of matching jobs).
        """
        ...
