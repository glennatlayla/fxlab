"""
In-memory mock audit export repository (Phase 6 — M12).

Purpose:
    Provide a test-only in-memory implementation of AuditExportRepositoryInterface
    for unit testing the audit export service without database dependencies.

Responsibilities:
    - Store export job metadata in a dict.
    - Store export content bytes in a dict.
    - Implement all AuditExportRepositoryInterface methods.
    - Provide introspection helpers for test assertions.

Does NOT:
    - Persist data across process restarts (in-memory only).
    - Compress or decompress content.

Dependencies:
    - AuditExportRepositoryInterface.
    - AuditExportResult contract.

Example:
    repo = MockAuditExportRepository()
    repo.save_export_job(result)
    assert repo.count() == 1
"""

from __future__ import annotations

from libs.contracts.audit_export import AuditExportResult
from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.audit_export_repository_interface import (
    AuditExportRepositoryInterface,
)


class MockAuditExportRepository(AuditExportRepositoryInterface):
    """
    In-memory implementation of AuditExportRepositoryInterface for testing.

    Responsibilities:
        - Store export jobs and content in Python dicts.
        - Raise NotFoundError for missing job IDs.
        - Provide introspection helpers: get_all(), count(), clear().

    Does NOT:
        - Persist data to disk or database.
        - Validate content format.

    Example:
        repo = MockAuditExportRepository()
        repo.save_export_job(result)
        retrieved = repo.get_export_job(result.job_id)
    """

    def __init__(self) -> None:
        self._jobs: dict[str, AuditExportResult] = {}
        self._content: dict[str, bytes] = {}

    def save_export_job(self, result: AuditExportResult) -> None:
        """Persist export job metadata in memory."""
        self._jobs[result.job_id] = result

    def get_export_job(self, job_id: str) -> AuditExportResult:
        """
        Retrieve export job metadata.

        Raises:
            NotFoundError: If job_id is unknown.
        """
        if job_id not in self._jobs:
            raise NotFoundError(f"Export job {job_id!r} not found")
        return self._jobs[job_id]

    def save_export_content(self, job_id: str, content: bytes) -> None:
        """Persist export content bytes in memory."""
        self._content[job_id] = content

    def get_export_content(self, job_id: str) -> bytes:
        """
        Retrieve export content bytes.

        Raises:
            NotFoundError: If job_id is unknown or content unavailable.
        """
        if job_id not in self._content:
            raise NotFoundError(f"Export content for job {job_id!r} not found")
        return self._content[job_id]

    # ------------------------------------------------------------------
    # Introspection helpers for test assertions
    # ------------------------------------------------------------------

    def get_all_jobs(self) -> list[AuditExportResult]:
        """Return all stored export job results."""
        return list(self._jobs.values())

    def count(self) -> int:
        """Return the number of stored export jobs."""
        return len(self._jobs)

    def clear(self) -> None:
        """Clear all stored data."""
        self._jobs.clear()
        self._content.clear()
