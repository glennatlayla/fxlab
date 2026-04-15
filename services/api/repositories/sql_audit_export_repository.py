"""
SQL-backed audit export repository (Phase 6 — M12).

Purpose:
    Persist and retrieve audit export job metadata using the database-backed
    AuditExportJob ORM model, and export file content via the artifact
    storage backend (MinIO / local filesystem).

Responsibilities:
    - save_export_job: Persist export job metadata to the audit_export_jobs table.
    - get_export_job: Retrieve export job metadata by job_id.
    - save_export_content: Write raw export bytes to durable artifact storage.
    - get_export_content: Read raw export bytes from artifact storage.

Does NOT:
    - Create or execute export jobs (service responsibility).
    - Format export content (service responsibility).
    - Manage database schema or migrations.

Dependencies:
    - SQLAlchemy Session (injected): Database access.
    - ArtifactStorageBase (injected): Durable blob storage for export content.
    - AuditExportJob ORM model: Table mapping.
    - AuditExportResult Pydantic model: Domain contract.
    - structlog: Structured logging.

Error conditions:
    - NotFoundError: If job_id is unknown for get operations, or if export
      content is not found in the storage backend.

Example:
    repo = SqlAuditExportRepository(db=session, storage=artifact_storage)
    repo.save_export_job(result)
    repo.save_export_content("01HQEXPORT...", raw_bytes)
    content = repo.get_export_content("01HQEXPORT...")
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.contracts.audit_export import AuditExportFormat, AuditExportResult
from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.audit_export_repository_interface import (
    AuditExportRepositoryInterface,
)
from libs.contracts.models import AuditExportJob
from libs.storage.base import ArtifactStorageBase

logger = structlog.get_logger(__name__)

#: Bucket name for audit export blobs in artifact storage.
_EXPORT_BUCKET = "fxlab-audit-exports"

#: Key prefix inside the bucket — content is stored as {prefix}/{job_id}.
_EXPORT_KEY_PREFIX = "exports"


class SqlAuditExportRepository(AuditExportRepositoryInterface):
    """
    SQL-backed implementation of AuditExportRepositoryInterface.

    Persists audit export job metadata to the ``audit_export_jobs`` table
    and raw export content as blobs in the artifact storage backend
    (MinIO in production, local filesystem in dev/test).

    Responsibilities:
        - CRUD operations for audit export job metadata.
        - Store and retrieve raw export content bytes via ArtifactStorageBase.

    Does NOT:
        - Execute export logic (AuditExportService responsibility).
        - Manage transactions (caller owns the session commit).

    Dependencies:
        - SQLAlchemy Session (injected via constructor).
        - ArtifactStorageBase (injected via constructor) — durable blob storage.

    Raises:
        - NotFoundError: If the requested job_id does not exist.

    Example:
        repo = SqlAuditExportRepository(db=session, storage=storage)
        repo.save_export_job(result)
        job = repo.get_export_job(result.job_id)
    """

    def __init__(
        self,
        *,
        db: Session,
        storage: ArtifactStorageBase,
    ) -> None:
        """
        Initialize the SQL audit export repository.

        Args:
            db: SQLAlchemy session for database operations.
            storage: Durable artifact storage backend for export content
                (MinIO in production, local filesystem in dev/test).
        """
        self._db = db
        self._storage = storage

    def save_export_job(self, result: AuditExportResult) -> None:
        """
        Persist audit export job metadata to the database.

        Creates a new AuditExportJob row with all metadata fields from the
        AuditExportResult contract.

        Args:
            result: Completed export result with all metadata fields.

        Example:
            repo.save_export_job(result)
        """
        job = AuditExportJob(
            id=result.job_id,
            status=result.status,
            record_count=result.record_count,
            content_hash=result.content_hash,
            byte_size=result.byte_size,
            format=result.format.value,
            compressed=result.compressed,
            error_message=result.error_message,
            created_at=result.created_at,
            completed_at=result.completed_at,
        )
        self._db.add(job)
        self._db.flush()

        logger.info(
            "audit_export_repo.job_saved",
            operation="save_export_job",
            component="SqlAuditExportRepository",
            job_id=result.job_id,
            status=result.status,
        )

    def get_export_job(self, job_id: str) -> AuditExportResult:
        """
        Retrieve export job metadata by job ID.

        Args:
            job_id: ULID of the export job.

        Returns:
            AuditExportResult with all metadata fields.

        Raises:
            NotFoundError: If no job exists with the given ID.

        Example:
            result = repo.get_export_job("01HQEXPORT0AAAAAAAAAAAAAAA")
        """
        stmt = select(AuditExportJob).where(AuditExportJob.id == job_id)
        job = self._db.execute(stmt).scalar_one_or_none()

        if job is None:
            raise NotFoundError(f"Export job {job_id} not found")

        return AuditExportResult(
            job_id=job.id,
            status=job.status,
            record_count=job.record_count,
            content_hash=job.content_hash,
            byte_size=job.byte_size,
            format=AuditExportFormat(job.format),
            compressed=job.compressed,
            created_at=job.created_at,
            completed_at=job.completed_at,
            error_message=job.error_message,
        )

    def save_export_content(self, job_id: str, content: bytes) -> None:
        """
        Persist raw export content bytes to durable artifact storage.

        Content is stored at key ``exports/{job_id}`` in the
        ``fxlab-audit-exports`` bucket.

        Args:
            job_id: ULID of the export job.
            content: Raw bytes of the export file.

        Raises:
            ConnectionError: If the storage backend is unreachable.

        Example:
            repo.save_export_content("01HQEXPORT0AAAAAAAAAAAAAAA", b"...")
        """
        key = f"{_EXPORT_KEY_PREFIX}/{job_id}"
        self._storage.put(
            data=content,
            bucket=_EXPORT_BUCKET,
            key=key,
            metadata={"job_id": job_id, "content_type": "application/octet-stream"},
            correlation_id=f"export-{job_id}",
        )

        logger.debug(
            "audit_export_repo.content_saved",
            operation="save_export_content",
            component="SqlAuditExportRepository",
            job_id=job_id,
            byte_size=len(content),
            storage_key=key,
        )

    def get_export_content(self, job_id: str) -> bytes:
        """
        Retrieve raw export content bytes from artifact storage.

        Args:
            job_id: ULID of the export job.

        Returns:
            Raw bytes of the export file.

        Raises:
            NotFoundError: If no content exists for the given job ID.

        Example:
            content = repo.get_export_content("01HQEXPORT0AAAAAAAAAAAAAAA")
        """
        key = f"{_EXPORT_KEY_PREFIX}/{job_id}"
        try:
            return self._storage.get(
                bucket=_EXPORT_BUCKET,
                key=key,
                correlation_id=f"export-{job_id}",
            )
        except FileNotFoundError:
            raise NotFoundError(f"Export content for job {job_id} not found") from None
