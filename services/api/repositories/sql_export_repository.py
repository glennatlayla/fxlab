"""
SQL-backed export job repository.

Purpose:
    Persist and query export job records in PostgreSQL/SQLite via
    SQLAlchemy, implementing ExportRepositoryInterface.

Responsibilities:
    - Create export job records.
    - Retrieve jobs by ID.
    - Update job status, artifact URI, and error messages.
    - List jobs with pagination, optionally filtered by requested_by or object_id.

Does NOT:
    - Generate artifact URIs (service layer responsibility).
    - Execute export operations (service layer responsibility).
    - Call session.commit() — uses flush() for request-scoped transactions.
    - Contain business logic.

Dependencies:
    - SQLAlchemy Session (injected).
    - libs.contracts.models.ExportJob ORM model.
    - libs.contracts.interfaces.export_repository: ExportRepositoryInterface.
    - libs.contracts.export: ExportJobResponse, ExportStatus.
    - libs.contracts.errors: NotFoundError.

Error conditions:
    - update_job: NotFoundError if job_id missing.

Example:
    repo = SqlExportRepository(db=session)
    job = repo.create_job(job_response)
    job = repo.get_job("01HEXPORT...")
    job = repo.update_job(job_id="01HEXPORT...", status=ExportStatus.PROCESSING)
    jobs, total = repo.list_jobs(requested_by="01HUSER...", limit=10)
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy.orm import Session

from libs.contracts.errors import NotFoundError
from libs.contracts.export import ExportJobResponse, ExportStatus
from libs.contracts.interfaces.export_repository_interface import (
    ExportRepositoryInterface,
)
from libs.contracts.models import ExportJob

logger = structlog.get_logger(__name__)


class SqlExportRepository(ExportRepositoryInterface):
    """
    SQL-backed implementation of ExportRepositoryInterface.

    Stores export job records with full lifecycle tracking.

    Attributes:
        _db: SQLAlchemy session for database operations.

    Example:
        repo = SqlExportRepository(db=session)
        job = repo.create_job(job_response)
    """

    def __init__(self, db: Session) -> None:
        """
        Initialize the SQL export repository.

        Args:
            db: SQLAlchemy session for database operations.
        """
        self._db = db

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _orm_to_response(orm: ExportJob) -> ExportJobResponse:
        """
        Convert an ORM instance to a response DTO.

        Args:
            orm: The ExportJob ORM instance.

        Returns:
            An ExportJobResponse DTO.
        """
        return ExportJobResponse(
            id=orm.id,
            export_type=orm.export_type,
            object_id=orm.object_id,
            status=ExportStatus(orm.status),
            artifact_uri=orm.artifact_uri,
            requested_by=orm.requested_by,
            error_message=orm.error_message,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            override_watermark=orm.override_watermark,
        )

    @staticmethod
    def _response_to_orm(response: ExportJobResponse) -> ExportJob:
        """
        Convert a response DTO to an ORM instance.

        Args:
            response: The ExportJobResponse DTO.

        Returns:
            An ExportJob ORM instance ready for persistence.
        """
        return ExportJob(
            id=response.id,
            export_type=response.export_type.value,
            object_id=response.object_id,
            status=response.status.value,
            artifact_uri=response.artifact_uri,
            requested_by=response.requested_by,
            error_message=response.error_message,
            created_at=response.created_at,
            updated_at=response.updated_at,
            override_watermark=response.override_watermark,
        )

    # ------------------------------------------------------------------
    # Interface methods
    # ------------------------------------------------------------------

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
        existing = self._db.get(ExportJob, job.id)
        if existing is not None:
            raise ValueError(f"Export job {job.id} already exists")

        orm = self._response_to_orm(job)
        self._db.add(orm)
        self._db.flush()

        logger.debug(
            "export_job.created",
            job_id=job.id,
            export_type=job.export_type.value,
            object_id=job.object_id,
            requested_by=job.requested_by,
            component="sql_export_repository",
        )

        return self._orm_to_response(orm)

    def get_job(self, job_id: str) -> ExportJobResponse | None:
        """
        Retrieve an export job by ID.

        Args:
            job_id: The ULID of the export job.

        Returns:
            The job if found, None otherwise.
        """
        orm = self._db.get(ExportJob, job_id)
        if orm is None:
            return None
        return self._orm_to_response(orm)

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
        orm = self._db.get(ExportJob, job_id)
        if orm is None:
            raise NotFoundError(f"Export job {job_id} not found")

        orm.status = status.value
        orm.updated_at = datetime.now(timezone.utc)

        if artifact_uri is not None:
            orm.artifact_uri = artifact_uri

        if error_message is not None:
            orm.error_message = error_message

        self._db.flush()

        logger.info(
            "export_job.status_updated",
            job_id=job_id,
            new_status=status.value,
            component="sql_export_repository",
        )

        return self._orm_to_response(orm)

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
        query = self._db.query(ExportJob)

        # Filter by requested_by if provided
        if requested_by is not None:
            query = query.filter(ExportJob.requested_by == requested_by)

        # Get total count before pagination
        total = query.count()

        # Apply ordering (newest first) and pagination
        jobs = query.order_by(ExportJob.created_at.desc()).offset(offset).limit(limit).all()

        responses = [self._orm_to_response(job) for job in jobs]

        logger.debug(
            "export_jobs.listed",
            filter_requested_by=requested_by,
            limit=limit,
            offset=offset,
            total=total,
            component="sql_export_repository",
        )

        return responses, total

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
        query = self._db.query(ExportJob).filter(ExportJob.object_id == object_id)

        # Get total count before pagination
        total = query.count()

        # Apply ordering (newest first) and pagination
        jobs = query.order_by(ExportJob.created_at.desc()).offset(offset).limit(limit).all()

        responses = [self._orm_to_response(job) for job in jobs]

        logger.debug(
            "export_jobs.listed_by_object_id",
            object_id=object_id,
            limit=limit,
            offset=offset,
            total=total,
            component="sql_export_repository",
        )

        return responses, total
