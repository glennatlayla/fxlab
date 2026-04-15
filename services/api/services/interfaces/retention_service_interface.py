"""
Data Retention Service interface (Phase 6 — M12).

Purpose:
    Define the abstract port for data retention policy enforcement so
    the background job and API depend on the interface, not the implementation.

Responsibilities:
    - run_retention: Execute the full retention cycle (soft delete + purge).
    - archive_expired_records: Soft-delete records past their retention period.
    - purge_archived_records: Hard-delete archived records past grace period.

Does NOT:
    - Contain business logic.
    - Access the database directly.

Dependencies:
    - ArchiveSummary, RetentionEntityType contracts.

Example:
    class MyRetentionService(RetentionServiceInterface):
        def run_retention(self) -> list[ArchiveSummary]:
            ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.audit_export import ArchiveSummary, RetentionEntityType


class RetentionServiceInterface(ABC):
    """
    Abstract port for data retention policy enforcement.

    Responsibilities:
        - run_retention: Full retention cycle across all entity types.
        - archive_expired_records: Soft-delete expired records for one entity type.
        - purge_archived_records: Hard-delete archived records past grace period.

    Does NOT:
        - Determine when to run (scheduling is the caller's responsibility).
        - Modify retention policy configuration.

    Error conditions:
        - ExternalServiceError: If database operations fail.
    """

    @abstractmethod
    def run_retention(self) -> list[ArchiveSummary]:
        """
        Execute the complete retention cycle for all configured entity types.

        For each entity type with a non-zero retention period:
        1. Archive (soft-delete) records older than the retention period.
        2. Purge (hard-delete) archived records older than the grace period.

        Returns:
            List of ArchiveSummary, one per entity type processed.

        Raises:
            ExternalServiceError: If a database operation fails.
        """

    @abstractmethod
    def archive_expired_records(self, entity_type: RetentionEntityType) -> ArchiveSummary:
        """
        Soft-delete records past the retention period for a single entity type.

        Records are marked as archived (moved to the archive table) but remain
        recoverable during the grace period.

        Args:
            entity_type: The entity type to process.

        Returns:
            ArchiveSummary with the count of archived records.

        Raises:
            ExternalServiceError: If the archive operation fails.
        """

    @abstractmethod
    def purge_archived_records(self, entity_type: RetentionEntityType) -> ArchiveSummary:
        """
        Hard-delete archived records past the grace period for a single entity type.

        Permanently removes records from the archive table that have been archived
        for longer than the configured grace period.

        Args:
            entity_type: The entity type to process.

        Returns:
            ArchiveSummary with the count of purged records.

        Raises:
            ExternalServiceError: If the purge operation fails.
        """
