"""
Audit Export Repository interface (Phase 6 — M12).

Purpose:
    Define the abstract port for persisting audit export jobs and their
    content so the service layer depends on the interface, not the
    concrete storage implementation.

Responsibilities:
    - save_export_job: Persist export job metadata.
    - get_export_job: Retrieve export job metadata by ID.
    - save_export_content: Persist the raw export bytes.
    - get_export_content: Retrieve the raw export bytes.

Does NOT:
    - Contain business logic.
    - Decide export format or compression.

Dependencies:
    - AuditExportResult for job metadata.

Example:
    repo.save_export_job(result)
    content = repo.get_export_content(job_id)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.audit_export import AuditExportResult


class AuditExportRepositoryInterface(ABC):
    """
    Abstract port for audit export job persistence.

    Responsibilities:
        - Persist and retrieve export job metadata.
        - Persist and retrieve export file content (bytes).

    Does NOT:
        - Generate export content (service responsibility).
        - Apply retention policies.

    Error conditions:
        - NotFoundError: If a job_id is unknown.
    """

    @abstractmethod
    def save_export_job(self, result: AuditExportResult) -> None:
        """
        Persist export job metadata.

        Args:
            result: AuditExportResult with all job metadata fields populated.

        Raises:
            ExternalServiceError: If the database operation fails.
        """

    @abstractmethod
    def get_export_job(self, job_id: str) -> AuditExportResult:
        """
        Retrieve export job metadata by ID.

        Args:
            job_id: ULID of the export job.

        Returns:
            AuditExportResult for the given job.

        Raises:
            NotFoundError: If job_id is unknown.
        """

    @abstractmethod
    def save_export_content(self, job_id: str, content: bytes) -> None:
        """
        Persist the raw export file content.

        Args:
            job_id: ULID of the export job.
            content: Raw bytes (may be gzip-compressed).

        Raises:
            ExternalServiceError: If the storage operation fails.
        """

    @abstractmethod
    def get_export_content(self, job_id: str) -> bytes:
        """
        Retrieve the raw export file content.

        Args:
            job_id: ULID of the export job.

        Returns:
            Raw bytes of the export file.

        Raises:
            NotFoundError: If job_id is unknown or content unavailable.
        """
