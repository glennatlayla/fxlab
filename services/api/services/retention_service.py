"""
Data Retention Service (Phase 6 — M12: Audit Trail Export and Retention Policy).

Purpose:
    Enforce configurable data retention policies by archiving (soft-deleting)
    records past their retention period and permanently purging archived records
    past their grace period.  Designed for regulatory compliance with financial
    industry record-keeping requirements (7-year audit trail, etc.).

Responsibilities:
    - run_retention: Execute the full retention cycle for all configured
      entity types — archive expired records, then purge old archives.
    - archive_expired_records: For a single entity type, move records older
      than the retention period from the source table to the archive table.
    - purge_archived_records: For a single entity type, hard-delete archived
      records whose archived_at timestamp exceeds the grace period.

Does NOT:
    - Schedule itself (caller / job scheduler responsibility).
    - Modify retention policy configuration.
    - Access external services — all operations are local database I/O.

Dependencies:
    - SQLAlchemy Session (injected): Database access.
    - RetentionPolicyEntry list (injected): Per-entity retention configuration.
    - now_fn callable (injected): Clock abstraction for deterministic testing.

Error conditions:
    - ExternalServiceError: If a database operation fails.
    - ValueError: If an unsupported entity type is requested that has no
      model mapping.

Example:
    service = RetentionService(
        db=session,
        policies=policies,
        now_fn=lambda: datetime.now(timezone.utc),
    )
    summaries = service.run_retention()
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple

import structlog
import ulid as _ulid
from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.contracts.audit_export import (
    ArchiveSummary,
    RetentionEntityType,
    RetentionPolicyEntry,
)
from libs.contracts.models import (
    ArchivedAuditEvent,
    ArchivedOrder,
    AuditEvent,
    Order,
)
from services.api.services.interfaces.retention_service_interface import (
    RetentionServiceInterface,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Entity-type ↔ ORM model mapping
# ---------------------------------------------------------------------------


class _EntityModelMapping(NamedTuple):
    """
    Maps a RetentionEntityType to its source and archive ORM models.

    Attributes:
        source_model: The ORM model for the live/active table.
        archive_model: The ORM model for the archive table.
        created_at_column: Column name on the source model used to determine
            record age (compared against retention period).
    """

    source_model: Any
    archive_model: Any
    created_at_column: str


# Only entity types that have both a source and archive table are mapped.
# EXECUTION_EVENTS and PNL_SNAPSHOTS do not yet have archive tables;
# they are handled gracefully (archive returns 0, purge returns 0).
_MODEL_MAP: dict[RetentionEntityType, _EntityModelMapping] = {
    RetentionEntityType.AUDIT_EVENTS: _EntityModelMapping(
        source_model=AuditEvent,
        archive_model=ArchivedAuditEvent,
        created_at_column="created_at",
    ),
    RetentionEntityType.ORDER_HISTORY: _EntityModelMapping(
        source_model=Order,
        archive_model=ArchivedOrder,
        created_at_column="created_at",
    ),
}

# Columns to copy from AuditEvent → ArchivedAuditEvent
_AUDIT_EVENT_COPY_COLUMNS = [
    "id",
    "actor",
    "action",
    "object_id",
    "object_type",
    "event_metadata",
    "created_at",
]

# Columns to copy from Order → ArchivedOrder
_ORDER_COPY_COLUMNS = [
    "id",
    "client_order_id",
    "deployment_id",
    "strategy_id",
    "symbol",
    "side",
    "order_type",
    "quantity",
    "status",
    "execution_mode",
    "submitted_at",
    "created_at",
    "updated_at",
]

# Entity type → list of column names to copy during archive
_COPY_COLUMNS: dict[RetentionEntityType, list[str]] = {
    RetentionEntityType.AUDIT_EVENTS: _AUDIT_EVENT_COPY_COLUMNS,
    RetentionEntityType.ORDER_HISTORY: _ORDER_COPY_COLUMNS,
}


# ---------------------------------------------------------------------------
# Service implementation
# ---------------------------------------------------------------------------


class RetentionService(RetentionServiceInterface):
    """
    Production implementation of data retention policy enforcement.

    Operates on the SQLAlchemy session to archive expired records and purge
    stale archives.  Each entity type is processed independently with its
    own retention period and grace period drawn from the injected policy list.

    Responsibilities:
        - Archive records older than the retention period (soft delete).
        - Purge archived records older than the grace period (hard delete).
        - Return ArchiveSummary with counts, timing, and error metadata.

    Does NOT:
        - Schedule itself (caller responsibility).
        - Modify retention policies.
        - Send notifications on completion.

    Dependencies:
        - SQLAlchemy Session (injected via constructor).
        - list[RetentionPolicyEntry] (injected): Per-entity-type policies.
        - Callable[[], datetime] now_fn (injected): Clock for testability.

    Raises:
        - ExternalServiceError: Propagated from database failures.

    Example:
        service = RetentionService(db=session, policies=policies)
        summaries = service.run_retention()
        for s in summaries:
            print(f"{s.entity_type}: archived={s.records_archived}, purged={s.records_purged}")
    """

    def __init__(
        self,
        *,
        db: Session,
        policies: list[RetentionPolicyEntry],
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        """
        Initialize the retention service.

        Args:
            db: SQLAlchemy session for database operations.
            policies: List of retention policy entries, one per entity type.
            now_fn: Optional clock function returning the current UTC datetime.
                    Defaults to ``datetime.now(timezone.utc)``.  Inject a fixed
                    clock in tests for deterministic behaviour.
        """
        self._db = db
        self._policies = {p.entity_type: p for p in policies}
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_retention(self) -> list[ArchiveSummary]:
        """
        Execute the full retention cycle for all configured entity types.

        Iterates each policy with a non-zero retention_days value, performing
        both archive and purge operations.  Entity types with retention_days=0
        (indefinite retention) are skipped entirely.

        Returns:
            List of ArchiveSummary objects — one archive summary and one purge
            summary per entity type that was processed.

        Example:
            summaries = service.run_retention()
            # len(summaries) >= 2 * number_of_non_indefinite_entity_types
        """
        summaries: list[ArchiveSummary] = []

        for entity_type, policy in self._policies.items():
            if policy.retention_days == 0:
                # Indefinite retention — skip entirely
                logger.debug(
                    "retention.skip_indefinite",
                    operation="run_retention",
                    component="RetentionService",
                    entity_type=entity_type.value,
                )
                continue

            logger.info(
                "retention.processing_entity",
                operation="run_retention",
                component="RetentionService",
                entity_type=entity_type.value,
                retention_days=policy.retention_days,
                grace_period_days=policy.grace_period_days,
            )

            archive_summary = self.archive_expired_records(entity_type)
            summaries.append(archive_summary)

            purge_summary = self.purge_archived_records(entity_type)
            summaries.append(purge_summary)

        logger.info(
            "retention.run_complete",
            operation="run_retention",
            component="RetentionService",
            total_summaries=len(summaries),
        )

        return summaries

    def archive_expired_records(self, entity_type: RetentionEntityType) -> ArchiveSummary:
        """
        Soft-delete records past the retention period for a single entity type.

        Records older than ``now - retention_days`` are copied to the archive
        table with an ``archived_at`` timestamp, then deleted from the source
        table.  Both operations run in the existing database session (caller
        is responsible for commit/rollback).

        For entity types with retention_days=0 (indefinite), returns immediately
        with records_archived=0.  For entity types without a model mapping
        (e.g. EXECUTION_EVENTS before its archive table exists), returns 0.

        Args:
            entity_type: The entity type to archive.

        Returns:
            ArchiveSummary with records_archived count and timing metadata.

        Example:
            summary = service.archive_expired_records(RetentionEntityType.AUDIT_EVENTS)
            # summary.records_archived == 42
        """
        run_id = str(_ulid.ULID())
        now = self._now_fn()
        start_ns = time.monotonic_ns()

        policy = self._policies.get(entity_type)

        # Indefinite retention or missing policy — nothing to archive
        if policy is None or policy.retention_days == 0:
            return self._empty_summary(run_id, entity_type, now)

        # No model mapping for this entity type yet
        mapping = _MODEL_MAP.get(entity_type)
        if mapping is None:
            logger.debug(
                "retention.no_model_mapping",
                operation="archive_expired_records",
                component="RetentionService",
                entity_type=entity_type.value,
            )
            return self._empty_summary(run_id, entity_type, now)

        cutoff = now - timedelta(days=policy.retention_days)
        # Strip timezone for comparison with naive-datetime columns in SQLite/Postgres
        cutoff_naive = cutoff.replace(tzinfo=None)

        source_model = mapping.source_model
        archive_model = mapping.archive_model
        created_col = getattr(source_model, mapping.created_at_column)

        # Find expired records
        expired_records = (
            self._db.execute(select(source_model).where(created_col < cutoff_naive)).scalars().all()
        )

        archived_count = 0
        copy_columns = _COPY_COLUMNS.get(entity_type, [])
        archive_now_naive = now.replace(tzinfo=None)

        for record in expired_records:
            # Build archive row by copying relevant columns
            archive_data = {col: getattr(record, col) for col in copy_columns}
            archive_data["archived_at"] = archive_now_naive

            archive_row = archive_model(**archive_data)
            self._db.add(archive_row)

            # Remove from source table
            self._db.delete(record)
            archived_count += 1

        if archived_count > 0:
            self._db.flush()

        duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000

        logger.info(
            "retention.archive_complete",
            operation="archive_expired_records",
            component="RetentionService",
            entity_type=entity_type.value,
            records_archived=archived_count,
            cutoff=cutoff.isoformat(),
            duration_ms=duration_ms,
        )

        return ArchiveSummary(
            run_id=run_id,
            entity_type=entity_type,
            records_archived=archived_count,
            records_purged=0,
            duration_ms=duration_ms,
            executed_at=now,
        )

    def purge_archived_records(self, entity_type: RetentionEntityType) -> ArchiveSummary:
        """
        Hard-delete archived records past the grace period for a single entity type.

        Permanently removes records from the archive table where ``archived_at``
        is older than ``now - grace_period_days``.  This is an irreversible
        operation — purged records cannot be recovered.

        For entity types with retention_days=0 (indefinite) or without a model
        mapping, returns immediately with records_purged=0.

        Args:
            entity_type: The entity type to purge.

        Returns:
            ArchiveSummary with records_purged count and timing metadata.

        Example:
            summary = service.purge_archived_records(RetentionEntityType.AUDIT_EVENTS)
            # summary.records_purged == 10
        """
        run_id = str(_ulid.ULID())
        now = self._now_fn()
        start_ns = time.monotonic_ns()

        policy = self._policies.get(entity_type)

        # Indefinite retention or missing policy — nothing to purge
        if policy is None or policy.retention_days == 0:
            return self._empty_summary(run_id, entity_type, now)

        # No model mapping for this entity type yet
        mapping = _MODEL_MAP.get(entity_type)
        if mapping is None:
            logger.debug(
                "retention.no_model_mapping",
                operation="purge_archived_records",
                component="RetentionService",
                entity_type=entity_type.value,
            )
            return self._empty_summary(run_id, entity_type, now)

        grace_cutoff = now - timedelta(days=policy.grace_period_days)
        grace_cutoff_naive = grace_cutoff.replace(tzinfo=None)

        archive_model = mapping.archive_model
        archived_at_col = archive_model.archived_at

        # Count before deleting so we can report accurate purge count
        stale_records = (
            self._db.execute(select(archive_model).where(archived_at_col < grace_cutoff_naive))
            .scalars()
            .all()
        )

        purged_count = len(stale_records)

        for record in stale_records:
            self._db.delete(record)

        if purged_count > 0:
            self._db.flush()

        duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000

        logger.info(
            "retention.purge_complete",
            operation="purge_archived_records",
            component="RetentionService",
            entity_type=entity_type.value,
            records_purged=purged_count,
            grace_cutoff=grace_cutoff.isoformat(),
            duration_ms=duration_ms,
        )

        return ArchiveSummary(
            run_id=run_id,
            entity_type=entity_type,
            records_archived=0,
            records_purged=purged_count,
            duration_ms=duration_ms,
            executed_at=now,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_summary(
        run_id: str,
        entity_type: RetentionEntityType,
        now: datetime,
    ) -> ArchiveSummary:
        """
        Build an ArchiveSummary with zero counts for skip/no-op scenarios.

        Args:
            run_id: ULID for this retention run.
            entity_type: The entity type being reported on.
            now: Current timestamp for executed_at.

        Returns:
            ArchiveSummary with all counts at zero.
        """
        return ArchiveSummary(
            run_id=run_id,
            entity_type=entity_type,
            records_archived=0,
            records_purged=0,
            duration_ms=0,
            executed_at=now,
        )
