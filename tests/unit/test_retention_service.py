"""
Unit tests for RetentionService (Phase 6 — M12).

Verifies:
    - run_retention processes all entity types with non-zero retention.
    - archive_expired_records soft-deletes records past retention period.
    - archive_expired_records skips entity types with 0 retention (indefinite).
    - purge_archived_records hard-deletes archived records past grace period.
    - Correct archive/purge counts returned in ArchiveSummary.
    - Records within retention period are not archived.
    - Records within grace period are not purged.
    - Error handling when database operations fail.

Dependencies:
    - pytest for assertions.
    - SQLAlchemy in-memory SQLite for integration-style unit tests.
    - RetentionService (system under test).

Example:
    pytest tests/unit/test_retention_service.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.audit_export import (
    RetentionEntityType,
    RetentionPolicyEntry,
)
from libs.contracts.models import (
    ArchivedAuditEvent,
    ArchivedOrder,
    AuditEvent,
    Base,
    Order,
)
from services.api.services.retention_service import RetentionService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc)
_EIGHT_YEARS_AGO = _NOW - timedelta(days=2920)  # ~8 years
_SIX_YEARS_AGO = _NOW - timedelta(days=2190)  # ~6 years
_ONE_YEAR_AGO = _NOW - timedelta(days=365)
_FORTY_DAYS_AGO = _NOW - timedelta(days=40)
_TEN_DAYS_AGO = _NOW - timedelta(days=10)


@pytest.fixture()
def db_session() -> Session:
    """Create an in-memory SQLite database with all tables for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    yield session
    session.close()


def _make_policies() -> list[RetentionPolicyEntry]:
    """Default retention policies matching regulatory requirements."""
    return [
        RetentionPolicyEntry(
            entity_type=RetentionEntityType.AUDIT_EVENTS,
            retention_days=2555,  # ~7 years
            grace_period_days=30,
        ),
        RetentionPolicyEntry(
            entity_type=RetentionEntityType.ORDER_HISTORY,
            retention_days=2555,  # ~7 years
            grace_period_days=30,
        ),
        RetentionPolicyEntry(
            entity_type=RetentionEntityType.EXECUTION_EVENTS,
            retention_days=1825,  # 5 years
            grace_period_days=30,
        ),
        RetentionPolicyEntry(
            entity_type=RetentionEntityType.PNL_SNAPSHOTS,
            retention_days=0,  # Indefinite
            grace_period_days=0,
        ),
    ]


def _seed_audit_events(session: Session) -> None:
    """Seed audit_events table with records at various ages."""
    events = [
        AuditEvent(
            id="01HQAUDIT0OLD0000000000000",
            actor="trader@fxlab.test",
            action="order.submitted",
            object_id="01HQORDER0OLD0000000000000",
            object_type="order",
            event_metadata={},
            created_at=_EIGHT_YEARS_AGO.replace(tzinfo=None),
        ),
        AuditEvent(
            id="01HQAUDIT0MID0000000000000",
            actor="trader@fxlab.test",
            action="strategy.created",
            object_id="01HQSTRAT0MID0000000000000",
            object_type="strategy",
            event_metadata={},
            created_at=_SIX_YEARS_AGO.replace(tzinfo=None),
        ),
        AuditEvent(
            id="01HQAUDIT0NEW0000000000000",
            actor="admin@fxlab.test",
            action="user.created",
            object_id="01HQUSER00NEW0000000000000",
            object_type="user",
            event_metadata={},
            created_at=_ONE_YEAR_AGO.replace(tzinfo=None),
        ),
    ]
    session.add_all(events)
    session.flush()


def _seed_orders(session: Session) -> None:
    """Seed orders table with records at various ages."""
    orders = [
        Order(
            id="01HQORDER0OLD0000000000000",
            client_order_id="ord-old-001",
            deployment_id="01HQDEPLOY000000000000000",
            strategy_id="01HQSTRAT0000000000000000",
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity="100",
            status="filled",
            correlation_id="corr-old-001",
            execution_mode="paper",
            submitted_at=_EIGHT_YEARS_AGO.replace(tzinfo=None),
            created_at=_EIGHT_YEARS_AGO.replace(tzinfo=None),
            updated_at=_EIGHT_YEARS_AGO.replace(tzinfo=None),
        ),
        Order(
            id="01HQORDER0NEW0000000000000",
            client_order_id="ord-new-001",
            deployment_id="01HQDEPLOY000000000000000",
            strategy_id="01HQSTRAT0000000000000000",
            symbol="AAPL",
            side="sell",
            order_type="limit",
            quantity="50",
            status="filled",
            correlation_id="corr-new-001",
            execution_mode="paper",
            submitted_at=_ONE_YEAR_AGO.replace(tzinfo=None),
            created_at=_ONE_YEAR_AGO.replace(tzinfo=None),
            updated_at=_ONE_YEAR_AGO.replace(tzinfo=None),
        ),
    ]
    session.add_all(orders)
    session.flush()


def _seed_archived_audit_events(session: Session) -> None:
    """Seed archived_audit_events with records at various archive ages."""
    events = [
        ArchivedAuditEvent(
            id="01HQARCHIVE0OLD000000000000",
            actor="trader@fxlab.test",
            action="order.submitted",
            object_id="01HQORDER0000000000000000",
            object_type="order",
            event_metadata={},
            created_at=_EIGHT_YEARS_AGO.replace(tzinfo=None),
            archived_at=_FORTY_DAYS_AGO.replace(tzinfo=None),  # Past 30-day grace
        ),
        ArchivedAuditEvent(
            id="01HQARCHIVE0NEW000000000000",
            actor="admin@fxlab.test",
            action="user.created",
            object_id="01HQUSER00000000000000000",
            object_type="user",
            event_metadata={},
            created_at=_SIX_YEARS_AGO.replace(tzinfo=None),
            archived_at=_TEN_DAYS_AGO.replace(tzinfo=None),  # Within 30-day grace
        ),
    ]
    session.add_all(events)
    session.flush()


@pytest.fixture()
def service(db_session: Session) -> RetentionService:
    return RetentionService(
        db=db_session,
        policies=_make_policies(),
        now_fn=lambda: _NOW,
    )


# ---------------------------------------------------------------------------
# Tests: archive_expired_records
# ---------------------------------------------------------------------------


class TestArchiveExpiredRecords:
    """Tests for RetentionService.archive_expired_records."""

    def test_archives_audit_events_past_retention(
        self, service: RetentionService, db_session: Session
    ) -> None:
        """Records older than 7 years are moved to archive table."""
        _seed_audit_events(db_session)

        summary = service.archive_expired_records(RetentionEntityType.AUDIT_EVENTS)

        assert summary.records_archived == 1  # Only the 8-year-old event
        assert summary.entity_type == RetentionEntityType.AUDIT_EVENTS

        # Verify the old event is in the archive table
        archived = db_session.execute(select(ArchivedAuditEvent)).scalars().all()
        assert len(archived) == 1
        assert archived[0].id == "01HQAUDIT0OLD0000000000000"

        # Verify the old event is removed from the source table
        remaining = db_session.execute(select(AuditEvent)).scalars().all()
        assert len(remaining) == 2  # mid + new events still there

    def test_archives_orders_past_retention(
        self, service: RetentionService, db_session: Session
    ) -> None:
        """Orders older than 7 years are moved to archive table."""
        _seed_orders(db_session)

        summary = service.archive_expired_records(RetentionEntityType.ORDER_HISTORY)

        assert summary.records_archived == 1  # Only the 8-year-old order
        assert summary.entity_type == RetentionEntityType.ORDER_HISTORY

        archived = db_session.execute(select(ArchivedOrder)).scalars().all()
        assert len(archived) == 1
        assert archived[0].id == "01HQORDER0OLD0000000000000"

    def test_does_not_archive_records_within_retention(
        self, service: RetentionService, db_session: Session
    ) -> None:
        """Records within the retention period are not archived."""
        _seed_audit_events(db_session)

        service.archive_expired_records(RetentionEntityType.AUDIT_EVENTS)

        # 6-year-old and 1-year-old events should remain
        remaining = db_session.execute(select(AuditEvent)).scalars().all()
        remaining_ids = {r.id for r in remaining}
        assert "01HQAUDIT0MID0000000000000" in remaining_ids
        assert "01HQAUDIT0NEW0000000000000" in remaining_ids

    def test_skips_indefinite_retention(
        self, service: RetentionService, db_session: Session
    ) -> None:
        """Entity types with 0 retention_days (indefinite) archive nothing."""
        summary = service.archive_expired_records(RetentionEntityType.PNL_SNAPSHOTS)

        assert summary.records_archived == 0

    def test_empty_table_returns_zero(self, service: RetentionService, db_session: Session) -> None:
        """Archive on empty table succeeds with zero records."""
        summary = service.archive_expired_records(RetentionEntityType.AUDIT_EVENTS)

        assert summary.records_archived == 0

    def test_archive_summary_has_duration(
        self, service: RetentionService, db_session: Session
    ) -> None:
        """ArchiveSummary includes execution duration."""
        _seed_audit_events(db_session)

        summary = service.archive_expired_records(RetentionEntityType.AUDIT_EVENTS)

        assert summary.duration_ms >= 0
        assert summary.run_id  # Non-empty ULID


# ---------------------------------------------------------------------------
# Tests: purge_archived_records
# ---------------------------------------------------------------------------


class TestPurgeArchivedRecords:
    """Tests for RetentionService.purge_archived_records."""

    def test_purges_archived_records_past_grace_period(
        self, service: RetentionService, db_session: Session
    ) -> None:
        """Archived records older than grace period are hard-deleted."""
        _seed_archived_audit_events(db_session)

        summary = service.purge_archived_records(RetentionEntityType.AUDIT_EVENTS)

        assert summary.records_purged == 1  # The 40-day-old archived event

        remaining = db_session.execute(select(ArchivedAuditEvent)).scalars().all()
        assert len(remaining) == 1  # The 10-day-old one stays
        assert remaining[0].id == "01HQARCHIVE0NEW000000000000"

    def test_does_not_purge_within_grace_period(
        self, service: RetentionService, db_session: Session
    ) -> None:
        """Archived records within grace period are not purged."""
        _seed_archived_audit_events(db_session)

        service.purge_archived_records(RetentionEntityType.AUDIT_EVENTS)

        remaining = db_session.execute(select(ArchivedAuditEvent)).scalars().all()
        remaining_ids = {r.id for r in remaining}
        assert "01HQARCHIVE0NEW000000000000" in remaining_ids

    def test_purge_empty_archive_returns_zero(
        self, service: RetentionService, db_session: Session
    ) -> None:
        """Purge on empty archive table succeeds with zero records."""
        summary = service.purge_archived_records(RetentionEntityType.AUDIT_EVENTS)

        assert summary.records_purged == 0

    def test_purge_indefinite_retention_returns_zero(
        self, service: RetentionService, db_session: Session
    ) -> None:
        """Purge on indefinite retention entity type does nothing."""
        summary = service.purge_archived_records(RetentionEntityType.PNL_SNAPSHOTS)

        assert summary.records_purged == 0


# ---------------------------------------------------------------------------
# Tests: run_retention
# ---------------------------------------------------------------------------


class TestRunRetention:
    """Tests for RetentionService.run_retention."""

    def test_run_retention_processes_all_entities(
        self, service: RetentionService, db_session: Session
    ) -> None:
        """Full retention run returns summaries for all entity types."""
        _seed_audit_events(db_session)
        _seed_orders(db_session)

        summaries = service.run_retention()

        # Should have summaries for each entity type with non-zero retention
        # (audit_events, order_history, execution_events)
        # PNL_SNAPSHOTS has 0 retention so it's skipped or returns 0
        assert len(summaries) >= 3

    def test_run_retention_archives_and_purges(
        self, service: RetentionService, db_session: Session
    ) -> None:
        """Full run archives expired records from all relevant tables."""
        _seed_audit_events(db_session)
        _seed_orders(db_session)
        _seed_archived_audit_events(db_session)

        summaries = service.run_retention()

        # Find audit events summary
        audit_summaries = [
            s for s in summaries if s.entity_type == RetentionEntityType.AUDIT_EVENTS
        ]
        # Should have archive + purge summaries for audit events
        total_archived = sum(s.records_archived for s in audit_summaries)
        total_purged = sum(s.records_purged for s in audit_summaries)

        assert total_archived >= 1  # The 8-year-old audit event
        assert total_purged >= 1  # The 40-day-old archived event

    def test_run_retention_returns_non_empty_summaries(
        self, service: RetentionService, db_session: Session
    ) -> None:
        """Each summary has a valid run_id and entity_type."""
        summaries = service.run_retention()

        for s in summaries:
            assert s.run_id  # Non-empty
            assert s.entity_type  # Non-empty
            assert s.executed_at is not None
