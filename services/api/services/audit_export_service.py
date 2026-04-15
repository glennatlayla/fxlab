"""
Audit Export Service (Phase 6 — M12: Audit Trail Export and Retention Policy).

Purpose:
    Export audit trail events in multiple formats (JSON, CSV, NDJSON) with
    tamper-evident SHA-256 signing and optional gzip compression.  Also
    provides the current data retention policy configuration.

Responsibilities:
    - create_export: Query audit events by date range and filters, format
      them into the requested output format, compute SHA-256 hash, optionally
      compress, and persist the result.
    - get_export_result: Retrieve export job metadata by job_id.
    - get_export_content: Retrieve raw export bytes by job_id.
    - get_retention_policy: Return the default retention policy configuration.

Does NOT:
    - Execute retention (that is RetentionService).
    - Schedule background jobs (caller responsibility).
    - Access the database directly (uses injected repositories).

Dependencies:
    - AuditExportRepositoryInterface (injected): Persists export jobs and content.
    - Explorer repository (injected): Reads audit events for export queries.
    - structlog: Structured logging.

Error conditions:
    - ValidationError: If date_from >= date_to.
    - NotFoundError: If job_id is unknown.

Example:
    service = AuditExportService(export_repo=repo, explorer_repo=explorer)
    result = service.create_export(request, created_by="admin@fxlab.test")
    content = service.get_export_content(result.job_id)
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from datetime import datetime, timezone
from typing import Any, Protocol

import structlog
import ulid as _ulid

from libs.contracts.audit_explorer import AuditEventRecord
from libs.contracts.audit_export import (
    AuditExportFormat,
    AuditExportRequest,
    AuditExportResult,
    RetentionEntityType,
    RetentionPolicyConfig,
    RetentionPolicyEntry,
)
from libs.contracts.errors import ValidationError
from libs.contracts.interfaces.audit_export_repository_interface import (
    AuditExportRepositoryInterface,
)
from services.api.services.interfaces.audit_export_service_interface import (
    AuditExportServiceInterface,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Protocol for the explorer repository's export query
# ---------------------------------------------------------------------------


class AuditExplorerForExport(Protocol):
    """
    Protocol for the subset of audit explorer repository methods needed by exports.

    The export service calls list_for_export() which returns events within a date
    range with optional actor/action filtering.  This differs from the cursor-
    paginated list() on the full explorer repository.
    """

    def list_for_export(
        self,
        *,
        date_from: datetime,
        date_to: datetime,
        actor: str = "",
        action_type: str = "",
        batch_size: int = 1000,
        offset: int = 0,
    ) -> list[AuditEventRecord]: ...


# ---------------------------------------------------------------------------
# Default retention policy (regulatory minimums)
# ---------------------------------------------------------------------------

_DEFAULT_RETENTION_POLICIES: list[RetentionPolicyEntry] = [
    RetentionPolicyEntry(
        entity_type=RetentionEntityType.AUDIT_EVENTS,
        retention_days=2555,  # ~7 years (regulatory minimum)
        grace_period_days=30,
        description="Regulatory minimum: 7-year retention for audit events",
    ),
    RetentionPolicyEntry(
        entity_type=RetentionEntityType.ORDER_HISTORY,
        retention_days=2555,  # ~7 years (regulatory minimum)
        grace_period_days=30,
        description="Regulatory minimum: 7-year retention for order history",
    ),
    RetentionPolicyEntry(
        entity_type=RetentionEntityType.EXECUTION_EVENTS,
        retention_days=1825,  # 5 years
        grace_period_days=30,
        description="5-year retention for execution event records",
    ),
    RetentionPolicyEntry(
        entity_type=RetentionEntityType.PNL_SNAPSHOTS,
        retention_days=0,  # Indefinite
        grace_period_days=0,
        description="Indefinite retention for P&L snapshots",
    ),
]


# ---------------------------------------------------------------------------
# CSV field order for export
# ---------------------------------------------------------------------------

_CSV_FIELDS = [
    "id",
    "actor",
    "action",
    "object_id",
    "object_type",
    "correlation_id",
    "event_metadata",
    "created_at",
]


# ---------------------------------------------------------------------------
# Service implementation
# ---------------------------------------------------------------------------


class AuditExportService(AuditExportServiceInterface):
    """
    Production implementation of AuditExportServiceInterface.

    Responsibilities:
        - Export audit events in JSON, CSV, or NDJSON format.
        - Compute SHA-256 content hash for tamper-evident exports.
        - Optionally gzip-compress exports for large date ranges.
        - Persist export jobs and content via the export repository.
        - Return the default retention policy configuration.

    Does NOT:
        - Execute retention policy (see RetentionService).
        - Access databases directly (uses injected repositories).
        - Schedule background jobs.

    Dependencies:
        - AuditExportRepositoryInterface (injected): Job and content persistence.
        - AuditExplorerForExport (injected): Reads audit events.

    Raises:
        - ValidationError: If date_from >= date_to.
        - NotFoundError: If job_id is unknown (propagated from repository).

    Example:
        service = AuditExportService(export_repo=repo, explorer_repo=explorer)
        result = service.create_export(request, created_by="admin@fxlab.test")
    """

    def __init__(
        self,
        *,
        export_repo: AuditExportRepositoryInterface,
        explorer_repo: AuditExplorerForExport,
    ) -> None:
        """
        Initialize the audit export service.

        Args:
            export_repo: Repository for persisting export jobs and content.
            explorer_repo: Repository for querying audit events.
        """
        self._export_repo = export_repo
        self._explorer_repo = explorer_repo

    def create_export(
        self,
        request: AuditExportRequest,
        *,
        created_by: str,
    ) -> AuditExportResult:
        """
        Create and execute an audit trail export.

        Queries audit events within the requested date range, formats them into
        the requested output format, computes a SHA-256 content hash for tamper
        detection, and optionally gzip-compresses the output.

        Args:
            request: Export parameters (date range, format, filters, compression).
            created_by: User ID of the requesting actor.

        Returns:
            AuditExportResult with job_id, record_count, content_hash, etc.

        Raises:
            ValidationError: If date_from >= date_to.

        Example:
            result = service.create_export(request, created_by="admin@fxlab.test")
            # result.status == "completed"
            # result.content_hash starts with "sha256:"
        """
        # Validate date range
        if request.date_from >= request.date_to:
            raise ValidationError("date_from must be before date_to")

        job_id = str(_ulid.ULID())
        created_at = datetime.now(timezone.utc)

        logger.info(
            "audit_export.started",
            operation="create_export",
            component="AuditExportService",
            job_id=job_id,
            date_from=request.date_from.isoformat(),
            date_to=request.date_to.isoformat(),
            format=request.format.value,
            compress=request.compress,
            actor_filter=request.actor,
            action_type_filter=request.action_type,
            created_by=created_by,
        )

        # Fetch all matching events (batched internally by the repository)
        events = self._fetch_all_events(request)

        # Format events into the requested output
        raw_content = self._format_events(events, request.format)

        # Optionally compress
        content = gzip.compress(raw_content) if request.compress else raw_content

        # Compute SHA-256 hash for tamper detection
        content_hash = "sha256:" + hashlib.sha256(content).hexdigest()

        completed_at = datetime.now(timezone.utc)

        result = AuditExportResult(
            job_id=job_id,
            status="completed",
            record_count=len(events),
            content_hash=content_hash,
            byte_size=len(content),
            format=request.format,
            compressed=request.compress,
            created_at=created_at,
            completed_at=completed_at,
        )

        # Persist job metadata and content
        self._export_repo.save_export_job(result)
        self._export_repo.save_export_content(job_id, content)

        logger.info(
            "audit_export.completed",
            operation="create_export",
            component="AuditExportService",
            job_id=job_id,
            record_count=len(events),
            byte_size=len(content),
            content_hash=content_hash,
            compressed=request.compress,
            duration_ms=int((completed_at - created_at).total_seconds() * 1000),
            result="success",
        )

        return result

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
        return self._export_repo.get_export_job(job_id)

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
        return self._export_repo.get_export_content(job_id)

    def get_retention_policy(self) -> RetentionPolicyConfig:
        """
        Return the current data retention policy configuration.

        Returns:
            RetentionPolicyConfig with per-entity retention periods.
            Includes all entity types with regulatory minimums.
        """
        return RetentionPolicyConfig(
            policies=list(_DEFAULT_RETENTION_POLICIES),
            last_run_at=None,
            next_run_at=None,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_all_events(
        self,
        request: AuditExportRequest,
    ) -> list[AuditEventRecord]:
        """
        Fetch all audit events matching the request parameters.

        Iterates in batches of 1000 to handle large result sets without
        loading everything at once.

        Args:
            request: Export request with date range and filters.

        Returns:
            Complete list of matching AuditEventRecord objects.
        """
        batch_size = 1000
        offset = 0
        all_events: list[AuditEventRecord] = []

        while True:
            batch = self._explorer_repo.list_for_export(
                date_from=request.date_from,
                date_to=request.date_to,
                actor=request.actor,
                action_type=request.action_type,
                batch_size=batch_size,
                offset=offset,
            )
            all_events.extend(batch)

            if len(batch) < batch_size:
                break  # No more records
            offset += batch_size

        return all_events

    def _format_events(
        self,
        events: list[AuditEventRecord],
        fmt: AuditExportFormat,
    ) -> bytes:
        """
        Format audit events into the requested output format.

        Args:
            events: List of audit event records to format.
            fmt: Desired output format (JSON, CSV, NDJSON).

        Returns:
            Raw bytes of the formatted output (UTF-8 encoded).

        Raises:
            ValueError: If fmt is not a supported format.
        """
        if fmt == AuditExportFormat.JSON:
            return self._format_json(events)
        elif fmt == AuditExportFormat.CSV:
            return self._format_csv(events)
        elif fmt == AuditExportFormat.NDJSON:
            return self._format_ndjson(events)
        else:
            raise ValueError(f"Unsupported export format: {fmt}")

    @staticmethod
    def _event_to_dict(event: AuditEventRecord) -> dict[str, Any]:
        """
        Convert an AuditEventRecord to a JSON-serializable dict.

        Args:
            event: Audit event record.

        Returns:
            Dict with all fields, datetimes rendered as ISO 8601 strings.
        """
        return {
            "id": event.id,
            "actor": event.actor,
            "action": event.action,
            "object_id": event.object_id,
            "object_type": event.object_type,
            "correlation_id": event.correlation_id,
            "event_metadata": event.event_metadata,
            "created_at": event.created_at.isoformat(),
        }

    def _format_json(self, events: list[AuditEventRecord]) -> bytes:
        """Format events as a JSON array."""
        records = [self._event_to_dict(e) for e in events]
        return json.dumps(records, indent=2, sort_keys=False).encode("utf-8")

    def _format_csv(self, events: list[AuditEventRecord]) -> bytes:
        """Format events as CSV with header row."""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for event in events:
            row = self._event_to_dict(event)
            # Serialize nested dict as JSON string for CSV
            row["event_metadata"] = json.dumps(row["event_metadata"])
            writer.writerow(row)
        return output.getvalue().encode("utf-8")

    def _format_ndjson(self, events: list[AuditEventRecord]) -> bytes:
        """Format events as newline-delimited JSON (one record per line)."""
        lines = [json.dumps(self._event_to_dict(e), sort_keys=False) for e in events]
        return "\n".join(lines).encode("utf-8")
