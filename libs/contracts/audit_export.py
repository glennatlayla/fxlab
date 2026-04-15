"""
Audit export and retention policy contracts (Phase 6 — M12).

Purpose:
    Define data shapes for audit trail export jobs, export results, and
    data retention policy configuration.

Responsibilities:
    - AuditExportFormat — enum of supported export formats (JSON, CSV, NDJSON).
    - AuditExportRequest — parameters for initiating an audit export job.
    - AuditExportResult — result of a completed export including content hash.
    - RetentionPolicyConfig — per-entity retention period configuration.
    - RetentionPolicyStatus — current state of retention policy execution.
    - ArchiveSummary — summary of records archived/purged in a retention run.

Does NOT:
    - Perform export or retention logic (delegated to services).
    - Access the database directly.
    - Write audit events (see libs/contracts/audit.py).

Dependencies:
    - pydantic for schema validation.

Example:
    request = AuditExportRequest(
        date_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
        date_to=datetime(2025, 12, 31, tzinfo=timezone.utc),
        format=AuditExportFormat.CSV,
    )
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class AuditExportFormat(str, Enum):
    """
    Supported audit export file formats.

    JSON:   Standard JSON array of audit event records.
    CSV:    Comma-separated values with header row.
    NDJSON: Newline-delimited JSON (one record per line, for log aggregators).
    """

    JSON = "json"
    CSV = "csv"
    NDJSON = "ndjson"


class AuditExportRequest(BaseModel):
    """
    Parameters for initiating an audit trail export.

    Responsibilities:
        - Validate date range (date_from < date_to enforced at service layer).
        - Carry optional filters: actor, action_type.
        - Specify export format and compression preference.

    Does NOT:
        - Execute the export (service responsibility).

    Example:
        req = AuditExportRequest(
            date_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
            date_to=datetime(2025, 12, 31, tzinfo=timezone.utc),
            format=AuditExportFormat.CSV,
            compress=True,
        )
    """

    date_from: datetime = Field(..., description="Start of export date range (inclusive)")
    date_to: datetime = Field(..., description="End of export date range (exclusive)")
    format: AuditExportFormat = Field(
        default=AuditExportFormat.JSON,
        description="Export file format",
    )
    actor: str = Field(default="", description="Filter by actor identity. Empty = all actors.")
    action_type: str = Field(
        default="",
        description="Filter by action verb prefix. Empty = all actions.",
    )
    compress: bool = Field(
        default=False,
        description="Whether to gzip-compress the export output",
    )


class AuditExportResult(BaseModel):
    """
    Result of a completed audit export job.

    Responsibilities:
        - Carry the export job identifier (ULID).
        - Store content hash (SHA-256) for tamper detection.
        - Record export metadata: record count, byte size, format, compression.

    Does NOT:
        - Carry the actual export content (content is stored separately as bytes).

    Example:
        result = AuditExportResult(
            job_id="01HQEXPORT0AAAAAAAAAAAAAAA",
            status="completed",
            record_count=50000,
            content_hash="sha256:abc123...",
            byte_size=1048576,
            format=AuditExportFormat.CSV,
            compressed=True,
            created_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
    """

    job_id: str = Field(..., description="ULID of the export job")
    status: str = Field(..., description="Job status: pending, running, completed, failed")
    record_count: int = Field(default=0, ge=0, description="Number of audit events exported")
    content_hash: str = Field(
        default="",
        description="SHA-256 hex digest prefixed with 'sha256:' for tamper detection",
    )
    byte_size: int = Field(default=0, ge=0, description="Size of the export content in bytes")
    format: AuditExportFormat = Field(
        default=AuditExportFormat.JSON,
        description="Format used for the export",
    )
    compressed: bool = Field(default=False, description="Whether the output is gzip-compressed")
    created_at: datetime = Field(..., description="When the export job was created")
    completed_at: datetime | None = Field(
        default=None,
        description="When the export completed (None if still running)",
    )
    error_message: str = Field(
        default="",
        description="Error message if status is 'failed'",
    )

    model_config = {"from_attributes": True}


class RetentionEntityType(str, Enum):
    """
    Entity types that have configurable retention policies.

    AUDIT_EVENTS:     Regulatory minimum 7 years.
    ORDER_HISTORY:    Regulatory minimum 7 years.
    EXECUTION_EVENTS: 5 years.
    PNL_SNAPSHOTS:    Indefinite (no expiry).
    """

    AUDIT_EVENTS = "audit_events"
    ORDER_HISTORY = "order_history"
    EXECUTION_EVENTS = "execution_events"
    PNL_SNAPSHOTS = "pnl_snapshots"


class RetentionPolicyEntry(BaseModel):
    """
    Retention policy for a single entity type.

    Responsibilities:
        - Define the retention period in days.
        - Define the grace period for archived records before hard delete.

    Example:
        entry = RetentionPolicyEntry(
            entity_type=RetentionEntityType.AUDIT_EVENTS,
            retention_days=2555,
            grace_period_days=30,
        )
    """

    entity_type: RetentionEntityType = Field(
        ..., description="Type of entity this policy applies to"
    )
    retention_days: int = Field(
        ...,
        ge=0,
        description="Number of days to retain records. 0 = indefinite.",
    )
    grace_period_days: int = Field(
        default=30,
        ge=0,
        description="Days to keep archived records before hard delete",
    )
    description: str = Field(default="", description="Human-readable description of the policy")


class RetentionPolicyConfig(BaseModel):
    """
    Complete retention policy configuration.

    Responsibilities:
        - Aggregate per-entity retention policies.
        - Carry last execution metadata.

    Does NOT:
        - Execute retention (service responsibility).

    Example:
        config = RetentionPolicyConfig(policies=[...])
    """

    policies: list[RetentionPolicyEntry] = Field(
        default_factory=list,
        description="Retention policies for each entity type",
    )
    last_run_at: datetime | None = Field(
        default=None,
        description="When the retention job last ran. None if never.",
    )
    next_run_at: datetime | None = Field(
        default=None,
        description="Next scheduled retention run. None if not scheduled.",
    )


class ArchiveSummary(BaseModel):
    """
    Summary of a single retention run.

    Responsibilities:
        - Record how many records were soft-deleted (archived) per entity.
        - Record how many records were hard-deleted (purged) per entity.
        - Carry execution metadata: duration, errors.

    Example:
        summary = ArchiveSummary(
            run_id="01HQRETENTION0AAAAAAAAAAAA",
            entity_type=RetentionEntityType.AUDIT_EVENTS,
            records_archived=500,
            records_purged=100,
            duration_ms=3500,
        )
    """

    run_id: str = Field(..., description="ULID of the retention run")
    entity_type: RetentionEntityType = Field(..., description="Entity type processed in this run")
    records_archived: int = Field(
        default=0, ge=0, description="Records soft-deleted (moved to archive)"
    )
    records_purged: int = Field(default=0, ge=0, description="Records hard-deleted from archive")
    duration_ms: int = Field(default=0, ge=0, description="Execution duration in milliseconds")
    executed_at: datetime = Field(..., description="When this retention step executed")
    errors: list[str] = Field(default_factory=list, description="Any errors encountered")
