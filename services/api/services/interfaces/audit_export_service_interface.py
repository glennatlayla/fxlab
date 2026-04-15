"""
Audit Export Service interface (Phase 6 — M12).

Purpose:
    Define the abstract port for audit trail export operations so
    services depend on the interface, not the implementation.

Responsibilities:
    - create_export: Start an audit export job with given filters and format.
    - get_export_result: Retrieve the result metadata of a completed export.
    - get_export_content: Retrieve the raw bytes of a completed export.
    - get_retention_policy: Return the current retention policy configuration.

Does NOT:
    - Contain business logic.
    - Access the database directly.

Dependencies:
    - AuditExportRequest, AuditExportResult, RetentionPolicyConfig contracts.

Example:
    class MyExportService(AuditExportServiceInterface):
        def create_export(self, request: AuditExportRequest) -> AuditExportResult:
            ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.audit_export import (
    AuditExportRequest,
    AuditExportResult,
    RetentionPolicyConfig,
)


class AuditExportServiceInterface(ABC):
    """
    Abstract port for audit trail export and retention policy queries.

    Responsibilities:
        - create_export: Initiate an export job, return result metadata.
        - get_export_result: Look up export job metadata by job_id.
        - get_export_content: Retrieve raw export bytes by job_id.
        - get_retention_policy: Return current retention configuration.

    Does NOT:
        - Execute retention (that is the RetentionServiceInterface).
        - Access databases directly (uses injected repositories).

    Error conditions:
        - NotFoundError: If a job_id is unknown.
        - ValidationError: If request parameters are invalid.
    """

    @abstractmethod
    def create_export(self, request: AuditExportRequest, *, created_by: str) -> AuditExportResult:
        """
        Create and execute an audit trail export.

        Args:
            request: Export parameters (date range, format, filters, compression).
            created_by: User ID of the requesting actor.

        Returns:
            AuditExportResult with job_id, record_count, content_hash, etc.

        Raises:
            ValidationError: If date_from >= date_to.
        """

    @abstractmethod
    def get_export_result(self, job_id: str) -> AuditExportResult:
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
    def get_export_content(self, job_id: str) -> bytes:
        """
        Retrieve the raw export content bytes.

        Args:
            job_id: ULID of the export job.

        Returns:
            Raw bytes of the export file (may be gzip-compressed).

        Raises:
            NotFoundError: If job_id is unknown or content unavailable.
        """

    @abstractmethod
    def get_retention_policy(self) -> RetentionPolicyConfig:
        """
        Return the current data retention policy configuration.

        Returns:
            RetentionPolicyConfig with per-entity retention periods and schedule info.
        """
