"""
Unit tests for AuditExportService (Phase 6 — M12).

Verifies:
    - create_export with JSON, CSV, and NDJSON formats.
    - SHA-256 content hash for tamper detection.
    - Gzip compression when requested.
    - Date range validation (date_from >= date_to rejects).
    - Actor and action_type filtering passed to repository.
    - get_export_result retrieves job metadata.
    - get_export_content retrieves raw bytes.
    - NotFoundError raised for unknown job_id.
    - get_retention_policy returns configured policies.
    - Empty export (no matching events) succeeds with zero records.

Dependencies:
    - pytest for assertions.
    - MockAuditExportRepository for job persistence.
    - MockAuditExplorerRepository for reading audit events.
    - AuditExportService (system under test).

Example:
    pytest tests/unit/test_audit_export_service.py -v
"""

from __future__ import annotations

import csv
import gzip
import io
import json
from datetime import datetime, timedelta, timezone

import pytest

from libs.contracts.audit_explorer import AuditEventRecord
from libs.contracts.audit_export import (
    AuditExportFormat,
    AuditExportRequest,
    RetentionEntityType,
)
from libs.contracts.errors import NotFoundError, ValidationError
from libs.contracts.mocks.mock_audit_export_repository import MockAuditExportRepository
from services.api.services.audit_export_service import AuditExportService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc)
_ONE_YEAR_AGO = _NOW - timedelta(days=365)


def _make_audit_event(
    event_id: str = "01HQAUDIT0AAAAAAAAAAAAAAAA",
    actor: str = "trader@fxlab.test",
    action: str = "order.submitted",
    object_id: str = "01HQORDER0AAAAAAAAAAAAAAAA",
    object_type: str = "order",
    created_at: datetime | None = None,
) -> AuditEventRecord:
    """Create a test audit event record."""
    return AuditEventRecord(
        id=event_id,
        actor=actor,
        action=action,
        object_id=object_id,
        object_type=object_type,
        correlation_id="corr-test",
        event_metadata={"test": True},
        created_at=created_at or _NOW,
    )


class StubAuditExplorerRepository:
    """
    Stub audit explorer repository that returns preconfigured events.

    Supports filtering by actor and action_type to verify the service
    passes filters through correctly. Also filters by date range
    (date_from, date_to) for the export query interface.
    """

    def __init__(self, events: list[AuditEventRecord] | None = None) -> None:
        self._events = events or []

    def set_events(self, events: list[AuditEventRecord]) -> None:
        """Replace stored events (for test setup)."""
        self._events = events

    def list_for_export(
        self,
        *,
        date_from: datetime,
        date_to: datetime,
        actor: str = "",
        action_type: str = "",
        batch_size: int = 1000,
        offset: int = 0,
    ) -> list[AuditEventRecord]:
        """
        Return events within date range, optionally filtered.

        This matches the interface the service will call for export queries,
        which differs from the explorer's cursor-paginated list endpoint.
        """
        filtered = [e for e in self._events if date_from <= e.created_at < date_to]
        if actor:
            filtered = [e for e in filtered if e.actor == actor]
        if action_type:
            filtered = [e for e in filtered if e.action.startswith(action_type)]
        return filtered[offset : offset + batch_size]


@pytest.fixture()
def export_repo() -> MockAuditExportRepository:
    return MockAuditExportRepository()


@pytest.fixture()
def explorer_repo() -> StubAuditExplorerRepository:
    return StubAuditExplorerRepository()


@pytest.fixture()
def service(
    export_repo: MockAuditExportRepository,
    explorer_repo: StubAuditExplorerRepository,
) -> AuditExportService:
    return AuditExportService(
        export_repo=export_repo,
        explorer_repo=explorer_repo,
    )


# ---------------------------------------------------------------------------
# Tests: create_export
# ---------------------------------------------------------------------------


class TestCreateExport:
    """Tests for AuditExportService.create_export."""

    def test_create_export_json_format(
        self,
        service: AuditExportService,
        export_repo: MockAuditExportRepository,
        explorer_repo: StubAuditExplorerRepository,
    ) -> None:
        """Export in JSON format produces valid JSON array of records."""
        explorer_repo.set_events(
            [
                _make_audit_event(event_id="01HQAUDIT0AAAAAAAAAAAAAAAA"),
                _make_audit_event(event_id="01HQAUDIT0BBBBBBBBBBBBBBB0", action="order.filled"),
            ]
        )
        request = AuditExportRequest(
            date_from=_ONE_YEAR_AGO,
            date_to=_NOW + timedelta(hours=1),
            format=AuditExportFormat.JSON,
        )

        result = service.create_export(request, created_by="admin@fxlab.test")

        assert result.status == "completed"
        assert result.record_count == 2
        assert result.format == AuditExportFormat.JSON
        assert result.content_hash.startswith("sha256:")
        assert result.byte_size > 0
        assert result.compressed is False

        # Verify persisted content is valid JSON
        content = export_repo.get_export_content(result.job_id)
        parsed = json.loads(content.decode("utf-8"))
        assert len(parsed) == 2
        assert parsed[0]["id"] == "01HQAUDIT0AAAAAAAAAAAAAAAA"

    def test_create_export_csv_format(
        self,
        service: AuditExportService,
        export_repo: MockAuditExportRepository,
        explorer_repo: StubAuditExplorerRepository,
    ) -> None:
        """Export in CSV format produces valid CSV with header row."""
        explorer_repo.set_events(
            [
                _make_audit_event(event_id="01HQAUDIT0AAAAAAAAAAAAAAAA"),
            ]
        )
        request = AuditExportRequest(
            date_from=_ONE_YEAR_AGO,
            date_to=_NOW + timedelta(hours=1),
            format=AuditExportFormat.CSV,
        )

        result = service.create_export(request, created_by="admin@fxlab.test")

        assert result.status == "completed"
        assert result.record_count == 1
        assert result.format == AuditExportFormat.CSV

        content = export_repo.get_export_content(result.job_id)
        reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["id"] == "01HQAUDIT0AAAAAAAAAAAAAAAA"
        assert "actor" in reader.fieldnames
        assert "action" in reader.fieldnames

    def test_create_export_ndjson_format(
        self,
        service: AuditExportService,
        export_repo: MockAuditExportRepository,
        explorer_repo: StubAuditExplorerRepository,
    ) -> None:
        """Export in NDJSON format produces one JSON object per line."""
        explorer_repo.set_events(
            [
                _make_audit_event(event_id="01HQAUDIT0AAAAAAAAAAAAAAAA"),
                _make_audit_event(event_id="01HQAUDIT0BBBBBBBBBBBBBBB0"),
            ]
        )
        request = AuditExportRequest(
            date_from=_ONE_YEAR_AGO,
            date_to=_NOW + timedelta(hours=1),
            format=AuditExportFormat.NDJSON,
        )

        result = service.create_export(request, created_by="admin@fxlab.test")

        assert result.status == "completed"
        assert result.record_count == 2
        assert result.format == AuditExportFormat.NDJSON

        content = export_repo.get_export_content(result.job_id)
        lines = content.decode("utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["id"] == "01HQAUDIT0AAAAAAAAAAAAAAAA"
        assert json.loads(lines[1])["id"] == "01HQAUDIT0BBBBBBBBBBBBBBB0"

    def test_create_export_with_gzip_compression(
        self,
        service: AuditExportService,
        export_repo: MockAuditExportRepository,
        explorer_repo: StubAuditExplorerRepository,
    ) -> None:
        """Compressed export produces valid gzip-compressed content."""
        explorer_repo.set_events(
            [
                _make_audit_event(event_id="01HQAUDIT0AAAAAAAAAAAAAAAA"),
            ]
        )
        request = AuditExportRequest(
            date_from=_ONE_YEAR_AGO,
            date_to=_NOW + timedelta(hours=1),
            format=AuditExportFormat.JSON,
            compress=True,
        )

        result = service.create_export(request, created_by="admin@fxlab.test")

        assert result.compressed is True
        assert result.byte_size > 0

        compressed_content = export_repo.get_export_content(result.job_id)
        # Verify it's valid gzip by decompressing
        decompressed = gzip.decompress(compressed_content)
        parsed = json.loads(decompressed.decode("utf-8"))
        assert len(parsed) == 1

    def test_create_export_sha256_hash(
        self,
        service: AuditExportService,
        export_repo: MockAuditExportRepository,
        explorer_repo: StubAuditExplorerRepository,
    ) -> None:
        """Content hash matches SHA-256 of the actual export bytes."""
        import hashlib

        explorer_repo.set_events(
            [
                _make_audit_event(event_id="01HQAUDIT0AAAAAAAAAAAAAAAA"),
            ]
        )
        request = AuditExportRequest(
            date_from=_ONE_YEAR_AGO,
            date_to=_NOW + timedelta(hours=1),
            format=AuditExportFormat.JSON,
        )

        result = service.create_export(request, created_by="admin@fxlab.test")

        content = export_repo.get_export_content(result.job_id)
        expected_hash = "sha256:" + hashlib.sha256(content).hexdigest()
        assert result.content_hash == expected_hash

    def test_create_export_date_validation_rejects_invalid_range(
        self,
        service: AuditExportService,
    ) -> None:
        """Export request with date_from >= date_to raises ValidationError."""
        request = AuditExportRequest(
            date_from=_NOW,
            date_to=_ONE_YEAR_AGO,  # Before date_from
            format=AuditExportFormat.JSON,
        )

        with pytest.raises(ValidationError, match="date_from must be before date_to"):
            service.create_export(request, created_by="admin@fxlab.test")

    def test_create_export_date_equal_rejects(
        self,
        service: AuditExportService,
    ) -> None:
        """Export request with date_from == date_to raises ValidationError."""
        request = AuditExportRequest(
            date_from=_NOW,
            date_to=_NOW,
            format=AuditExportFormat.JSON,
        )

        with pytest.raises(ValidationError, match="date_from must be before date_to"):
            service.create_export(request, created_by="admin@fxlab.test")

    def test_create_export_with_actor_filter(
        self,
        service: AuditExportService,
        export_repo: MockAuditExportRepository,
        explorer_repo: StubAuditExplorerRepository,
    ) -> None:
        """Actor filter is passed through and only matching events exported."""
        explorer_repo.set_events(
            [
                _make_audit_event(event_id="01HQAUDIT0AAAAAAAAAAAAAAAA", actor="alice@fxlab.test"),
                _make_audit_event(event_id="01HQAUDIT0BBBBBBBBBBBBBBB0", actor="bob@fxlab.test"),
            ]
        )
        request = AuditExportRequest(
            date_from=_ONE_YEAR_AGO,
            date_to=_NOW + timedelta(hours=1),
            format=AuditExportFormat.JSON,
            actor="alice@fxlab.test",
        )

        result = service.create_export(request, created_by="admin@fxlab.test")

        assert result.record_count == 1
        content = export_repo.get_export_content(result.job_id)
        parsed = json.loads(content.decode("utf-8"))
        assert parsed[0]["actor"] == "alice@fxlab.test"

    def test_create_export_with_action_filter(
        self,
        service: AuditExportService,
        export_repo: MockAuditExportRepository,
        explorer_repo: StubAuditExplorerRepository,
    ) -> None:
        """Action type filter is passed through and only matching events exported."""
        explorer_repo.set_events(
            [
                _make_audit_event(event_id="01HQAUDIT0AAAAAAAAAAAAAAAA", action="order.submitted"),
                _make_audit_event(event_id="01HQAUDIT0BBBBBBBBBBBBBBB0", action="strategy.created"),
            ]
        )
        request = AuditExportRequest(
            date_from=_ONE_YEAR_AGO,
            date_to=_NOW + timedelta(hours=1),
            format=AuditExportFormat.JSON,
            action_type="order",
        )

        result = service.create_export(request, created_by="admin@fxlab.test")

        assert result.record_count == 1

    def test_create_export_empty_result(
        self,
        service: AuditExportService,
        export_repo: MockAuditExportRepository,
        explorer_repo: StubAuditExplorerRepository,
    ) -> None:
        """Export with no matching events succeeds with zero records."""
        explorer_repo.set_events([])
        request = AuditExportRequest(
            date_from=_ONE_YEAR_AGO,
            date_to=_NOW + timedelta(hours=1),
            format=AuditExportFormat.JSON,
        )

        result = service.create_export(request, created_by="admin@fxlab.test")

        assert result.status == "completed"
        assert result.record_count == 0
        assert result.byte_size > 0  # Even empty JSON "[]" has bytes

    def test_create_export_job_persisted(
        self,
        service: AuditExportService,
        export_repo: MockAuditExportRepository,
        explorer_repo: StubAuditExplorerRepository,
    ) -> None:
        """Export job metadata and content are persisted to the repository."""
        explorer_repo.set_events(
            [
                _make_audit_event(event_id="01HQAUDIT0AAAAAAAAAAAAAAAA"),
            ]
        )
        request = AuditExportRequest(
            date_from=_ONE_YEAR_AGO,
            date_to=_NOW + timedelta(hours=1),
        )

        result = service.create_export(request, created_by="admin@fxlab.test")

        assert export_repo.count() == 1
        stored_job = export_repo.get_export_job(result.job_id)
        assert stored_job.job_id == result.job_id
        assert stored_job.status == "completed"


# ---------------------------------------------------------------------------
# Tests: get_export_result
# ---------------------------------------------------------------------------


class TestGetExportResult:
    """Tests for AuditExportService.get_export_result."""

    def test_get_export_result_existing(
        self,
        service: AuditExportService,
        explorer_repo: StubAuditExplorerRepository,
    ) -> None:
        """Retrieve result for existing export job."""
        explorer_repo.set_events([_make_audit_event()])
        request = AuditExportRequest(
            date_from=_ONE_YEAR_AGO,
            date_to=_NOW + timedelta(hours=1),
        )
        created = service.create_export(request, created_by="admin@fxlab.test")

        result = service.get_export_result(created.job_id)

        assert result.job_id == created.job_id
        assert result.status == "completed"

    def test_get_export_result_not_found(
        self,
        service: AuditExportService,
    ) -> None:
        """NotFoundError raised for unknown job_id."""
        with pytest.raises(NotFoundError):
            service.get_export_result("01HQNONEXISTENT00000000000")


# ---------------------------------------------------------------------------
# Tests: get_export_content
# ---------------------------------------------------------------------------


class TestGetExportContent:
    """Tests for AuditExportService.get_export_content."""

    def test_get_export_content_returns_bytes(
        self,
        service: AuditExportService,
        explorer_repo: StubAuditExplorerRepository,
    ) -> None:
        """Content retrieval returns raw bytes."""
        explorer_repo.set_events([_make_audit_event()])
        request = AuditExportRequest(
            date_from=_ONE_YEAR_AGO,
            date_to=_NOW + timedelta(hours=1),
        )
        created = service.create_export(request, created_by="admin@fxlab.test")

        content = service.get_export_content(created.job_id)

        assert isinstance(content, bytes)
        assert len(content) > 0

    def test_get_export_content_not_found(
        self,
        service: AuditExportService,
    ) -> None:
        """NotFoundError raised for unknown job_id."""
        with pytest.raises(NotFoundError):
            service.get_export_content("01HQNONEXISTENT00000000000")


# ---------------------------------------------------------------------------
# Tests: get_retention_policy
# ---------------------------------------------------------------------------


class TestGetRetentionPolicy:
    """Tests for AuditExportService.get_retention_policy."""

    def test_retention_policy_contains_all_entity_types(
        self,
        service: AuditExportService,
    ) -> None:
        """Retention policy includes all configured entity types."""
        policy = service.get_retention_policy()

        entity_types = {p.entity_type for p in policy.policies}
        assert RetentionEntityType.AUDIT_EVENTS in entity_types
        assert RetentionEntityType.ORDER_HISTORY in entity_types
        assert RetentionEntityType.EXECUTION_EVENTS in entity_types
        assert RetentionEntityType.PNL_SNAPSHOTS in entity_types

    def test_audit_events_retention_minimum_7_years(
        self,
        service: AuditExportService,
    ) -> None:
        """Audit events retention period is at least 7 years (2555 days)."""
        policy = service.get_retention_policy()

        audit_policy = next(
            p for p in policy.policies if p.entity_type == RetentionEntityType.AUDIT_EVENTS
        )
        assert audit_policy.retention_days >= 2555  # ~7 years

    def test_pnl_snapshots_retention_indefinite(
        self,
        service: AuditExportService,
    ) -> None:
        """P&L snapshots have 0 retention_days (indefinite)."""
        policy = service.get_retention_policy()

        pnl_policy = next(
            p for p in policy.policies if p.entity_type == RetentionEntityType.PNL_SNAPSHOTS
        )
        assert pnl_policy.retention_days == 0  # Indefinite

    def test_grace_period_at_least_30_days(
        self,
        service: AuditExportService,
    ) -> None:
        """All entity types with retention have at least 30-day grace period."""
        policy = service.get_retention_policy()

        for p in policy.policies:
            if p.retention_days > 0:
                assert p.grace_period_days >= 30, (
                    f"{p.entity_type} grace period is {p.grace_period_days}, expected >= 30"
                )
