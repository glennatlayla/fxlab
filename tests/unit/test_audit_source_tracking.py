"""
Tests for audit event source tracking (BE-07).

Responsibilities:
- Verify AuditEventSchema includes source field.
- Verify source field is optional (None default for backwards compatibility).
- Verify write_audit_event accepts source parameter.
- Verify AuditEventRecord includes source field for queries.
- Verify database round-trip preserves source field.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import inspect

from libs.contracts.audit import AuditEventSchema, write_audit_event
from libs.contracts.audit_explorer import AuditEventRecord
from libs.contracts.models import AuditEvent


class TestAuditEventSchemaIncludesSource:
    """Test AuditEventSchema contract includes source field."""

    def test_audit_event_schema_has_source_field(self):
        """Verify AuditEventSchema includes source field."""
        event = AuditEventSchema(
            id="01HQZX3Y7Z8F9G0H1J2K3L4M5N",
            actor="user@example.com",
            action="strategy.created",
            object_id="01HQZX3Y7Z8F9G0H1J2K3L4M5P",
            object_type="strategy",
            source="web-desktop",
        )
        assert event.source == "web-desktop"

    def test_audit_event_schema_source_defaults_to_none(self):
        """Verify source field defaults to None for backwards compatibility."""
        event = AuditEventSchema(
            id="01HQZX3Y7Z8F9G0H1J2K3L4M5N",
            actor="user@example.com",
            action="strategy.created",
            object_id="01HQZX3Y7Z8F9G0H1J2K3L4M5P",
            object_type="strategy",
        )
        assert event.source is None

    def test_audit_event_schema_source_accepts_valid_values(self):
        """Verify source field accepts all valid client sources."""
        valid_sources = ["web-desktop", "web-mobile", "api"]
        for source in valid_sources:
            event = AuditEventSchema(
                id="01HQZX3Y7Z8F9G0H1J2K3L4M5N",
                actor="user@example.com",
                action="strategy.created",
                object_id="01HQZX3Y7Z8F9G0H1J2K3L4M5P",
                object_type="strategy",
                source=source,
            )
            assert event.source == source

    def test_audit_event_schema_serializes_with_source(self):
        """Verify source field is included in JSON serialization."""
        event = AuditEventSchema(
            id="01HQZX3Y7Z8F9G0H1J2K3L4M5N",
            actor="user@example.com",
            action="strategy.created",
            object_id="01HQZX3Y7Z8F9G0H1J2K3L4M5P",
            object_type="strategy",
            source="web-mobile",
        )
        serialized = event.model_dump()
        assert "source" in serialized
        assert serialized["source"] == "web-mobile"


class TestAuditEventRecordIncludesSource:
    """Test AuditEventRecord contract includes source field for queries."""

    def test_audit_event_record_has_source_field(self):
        """Verify AuditEventRecord includes source field."""
        record = AuditEventRecord(
            id="01HQAUDIT0AAAAAAAAAAAAAAAA",
            actor="analyst@fxlab.io",
            action="approve_promotion",
            object_id="01HQPROM0AAAAAAAAAAAAAAA0",
            object_type="promotion_request",
            source="api",
            created_at=datetime.utcnow(),
        )
        assert record.source == "api"

    def test_audit_event_record_source_defaults_to_empty_string(self):
        """Verify source field defaults to empty string in AuditEventRecord (LL-007)."""
        record = AuditEventRecord(
            id="01HQAUDIT0AAAAAAAAAAAAAAAA",
            actor="analyst@fxlab.io",
            action="approve_promotion",
            object_id="01HQPROM0AAAAAAAAAAAAAAA0",
            object_type="promotion_request",
            created_at=datetime.utcnow(),
        )
        assert record.source == ""


class TestWriteAuditEventWithSource:
    """Test write_audit_event function accepts and stores source."""

    def test_write_audit_event_accepts_source_parameter(self, mock_session, sample_ulid):
        """Verify write_audit_event accepts source parameter."""
        event_id = write_audit_event(
            session=mock_session,
            actor="user:01HQZXYZ123456789ABCDEFGHJN",
            action="strategy.created",
            object_id=sample_ulid,
            object_type="strategy",
            source="web-desktop",
        )
        assert event_id is not None
        assert mock_session.add.called

    def test_write_audit_event_source_defaults_to_none(self, mock_session, sample_ulid):
        """Verify write_audit_event works without source (backwards compatible)."""
        event_id = write_audit_event(
            session=mock_session,
            actor="user:01HQZXYZ123456789ABCDEFGHJN",
            action="strategy.created",
            object_id=sample_ulid,
            object_type="strategy",
        )
        assert event_id is not None
        assert mock_session.add.called

    def test_write_audit_event_passes_source_to_model(self, mock_session, sample_ulid):
        """Verify write_audit_event passes source to AuditEvent model."""
        write_audit_event(
            session=mock_session,
            actor="user:01HQZXYZ123456789ABCDEFGHJN",
            action="run.started",
            object_id=sample_ulid,
            object_type="run",
            source="api",
        )

        # Verify the AuditEvent passed to session.add() has the source
        assert mock_session.add.called
        call_args = mock_session.add.call_args
        audit_event = call_args[0][0]
        assert hasattr(audit_event, "source")
        assert audit_event.source == "api"


class TestAuditEventModelIncludesSource:
    """Test ORM model has source column."""

    def test_audit_event_table_has_source_column(self, in_memory_db):
        """Verify audit_events table has source column."""
        inspector = inspect(in_memory_db.bind)
        columns = {col["name"]: col for col in inspector.get_columns("audit_events")}
        assert "source" in columns

    def test_audit_event_source_column_is_nullable(self, in_memory_db):
        """Verify source column is nullable for backwards compatibility."""
        inspector = inspect(in_memory_db.bind)
        columns = {col["name"]: col for col in inspector.get_columns("audit_events")}
        source_col = columns["source"]
        assert source_col["nullable"] is True

    def test_audit_event_source_column_is_varchar(self, in_memory_db):
        """Verify source column is string-based type."""
        inspector = inspect(in_memory_db.bind)
        columns = {col["name"]: col for col in inspector.get_columns("audit_events")}
        source_col = columns["source"]
        col_type = str(source_col["type"]).upper()
        # SQLite uses VARCHAR, PostgreSQL uses VARCHAR
        assert "VARCHAR" in col_type or "CHAR" in col_type or "TEXT" in col_type


class TestAuditEventDatabaseRoundTrip:
    """Test audit event with source can be written to and read from database."""

    def test_write_and_retrieve_audit_event_with_source(self, in_memory_db, sample_ulid):
        """Verify audit event with source survives write/read cycle."""
        write_audit_event(
            session=in_memory_db,
            actor="user:01HQZXYZ123456789ABCDEFGHJN",
            action="strategy.created",
            object_id=sample_ulid,
            object_type="strategy",
            source="web-mobile",
        )
        in_memory_db.commit()

        # Retrieve the event
        event = in_memory_db.query(AuditEvent).first()
        assert event is not None
        assert event.source == "web-mobile"

    def test_write_and_retrieve_audit_event_without_source(self, in_memory_db, sample_ulid):
        """Verify audit event without source (legacy) stores as NULL."""
        write_audit_event(
            session=in_memory_db,
            actor="user:01HQZXYZ123456789ABCDEFGHJN",
            action="strategy.created",
            object_id=sample_ulid,
            object_type="strategy",
        )
        in_memory_db.commit()

        # Retrieve the event
        event = in_memory_db.query(AuditEvent).first()
        assert event is not None
        assert event.source is None

    def test_audit_event_source_persisted_correctly_multiple_sources(
        self, in_memory_db, sample_ulid
    ):
        """Verify multiple audit events with different sources are persisted correctly."""
        sources = ["web-desktop", "web-mobile", "api", None]
        for source in sources:
            write_audit_event(
                session=in_memory_db,
                actor="user:test",
                action="test.action",
                object_id=sample_ulid,
                object_type="test",
                source=source,
            )
        in_memory_db.commit()

        # Retrieve all events
        events = in_memory_db.query(AuditEvent).order_by(AuditEvent.created_at).all()
        assert len(events) == 4
        assert events[0].source == "web-desktop"
        assert events[1].source == "web-mobile"
        assert events[2].source == "api"
        assert events[3].source is None
