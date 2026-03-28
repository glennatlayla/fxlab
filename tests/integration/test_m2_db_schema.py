"""
M2 integration tests — DB schema, migrations, and audit ledger.

Tests verify that all ORM models work together end-to-end:
- Schema creation from Base.metadata
- Foreign-key-linked object graphs (strategy → run → trial → artifact)
- Audit event write + query workflow
- Relationship traversal across tables

These tests use an in-memory SQLite engine so they run without
a running Postgres instance.  They are marked as integration tests
because they exercise multiple models and relationships together,
unlike the narrow unit tests in tests/unit/.
"""

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from libs.contracts.audit import write_audit_event
from libs.contracts.models import (
    AuditEvent,
    Artifact,
    Base,
    Candidate,
    Deployment,
    Feed,
    FeedHealthEvent,
    Override,
    Run,
    Strategy,
    Trial,
    User,
)

# ---------------------------------------------------------------------------
# 26-char test ULIDs (Crockford Base32, all uppercase)
# Format: "01HQ" (4 chars) + 22 repeated chars = 26 total
# ---------------------------------------------------------------------------
UID_USER = "01HQAAAAAAAAAAAAAAAAAAAAAA"   # 26 chars
UID_STRAT = "01HQBBBBBBBBBBBBBBBBBBBBBB"  # 26 chars
UID_RUN1 = "01HQCCCCCCCCCCCCCCCCCCCCCC"   # 26 chars
UID_RUN2 = "01HQDDDDDDDDDDDDDDDDDDDDDD"   # 26 chars
UID_RUN3 = "01HQEEEEEEEEEEEEEEEEEEEEEE"   # 26 chars
UID_RUN4 = "01HQFFFFFFFFFFFFFFFFFFFFFF"   # 26 chars
UID_FEED = "01HQGGGGGGGGGGGGGGGGGGGGGG"   # 26 chars
UID_ARTI = "01HQHHHHHHHHHHHHHHHHHHHHHH"   # 26 chars

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    """
    Module-scoped in-memory SQLite engine.

    Creates all tables once for the module; each test session uses a
    savepoint (nested transaction) so the DB is rolled back to a clean
    state after every test.
    """
    _engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(_engine)
    yield _engine
    Base.metadata.drop_all(_engine)
    _engine.dispose()


@pytest.fixture
def session(engine):
    """
    Function-scoped session with automatic rollback.

    Uses a connection-level transaction + nested savepoint so that
    every commit inside a test is rolled back at teardown, keeping the
    module-scoped DB clean between tests.
    """
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    sess = Session()
    # Use a nested (SAVEPOINT) transaction so sess.commit() works inside tests
    # but the outer transaction is rolled back at teardown.
    nested = connection.begin_nested()

    yield sess

    sess.close()
    if nested.is_active:
        nested.rollback()
    transaction.rollback()
    connection.close()


@pytest.fixture
def test_user(session):
    """Create and persist a test user, returning the instance."""
    user = User(
        id=UID_USER,
        email="test@fxlab.io",
        hashed_password="$2b$12$hashed",
        role="researcher",
    )
    session.add(user)
    session.flush()  # Write to DB within the current (nested) transaction
    return user


@pytest.fixture
def test_strategy(session, test_user):
    """Create and persist a test strategy."""
    strategy = Strategy(
        id=UID_STRAT,
        name="Test MA Crossover",
        code="def entry(ctx): pass",
        version="1.0.0",
        created_by=test_user.id,
    )
    session.add(strategy)
    session.flush()
    return strategy


# ---------------------------------------------------------------------------
# Schema existence tests
# ---------------------------------------------------------------------------


class TestM2AllTablesExist:
    """Verify all expected tables are created by Base.metadata."""

    EXPECTED_TABLES = [
        "users",
        "strategies",
        "strategy_builds",
        "candidates",
        "deployments",
        "runs",
        "trials",
        "artifacts",
        "audit_events",
        "feeds",
        "feed_health_events",
        "parity_events",
        "overrides",
        "approval_requests",
    ]

    def test_all_expected_tables_present(self, engine):
        """Verify all 14 expected tables exist after schema creation."""
        inspector = inspect(engine)
        actual_tables = set(inspector.get_table_names())
        for table in self.EXPECTED_TABLES:
            assert table in actual_tables, f"Expected table '{table}' not found"

    def test_table_count_at_least_expected(self, engine):
        """Verify at least all 14 expected tables were created."""
        inspector = inspect(engine)
        actual_tables = set(inspector.get_table_names())
        assert len(actual_tables) >= len(self.EXPECTED_TABLES)


# ---------------------------------------------------------------------------
# Object graph / relationship tests
# ---------------------------------------------------------------------------


class TestM2ObjectGraph:
    """Verify related objects can be created and traversal works."""

    def test_user_strategy_relationship(self, session, test_user, test_strategy):
        """Strategy can be created with a user as created_by FK."""
        assert test_strategy.created_by == test_user.id

    def test_strategy_run_workflow(self, session, test_strategy):
        """Run can be linked to a strategy."""
        run = Run(
            id=UID_RUN1,
            strategy_id=test_strategy.id,
            run_type="backtest",
            status="pending",
        )
        session.add(run)
        session.flush()

        queried = session.query(Run).filter_by(id=run.id).first()
        assert queried is not None
        assert queried.strategy_id == test_strategy.id
        assert queried.run_type == "backtest"

    def test_run_trial_workflow(self, session, test_strategy):
        """Trials can be linked to a run."""
        run = Run(
            id=UID_RUN2,
            strategy_id=test_strategy.id,
            run_type="backtest",
            status="running",
        )
        session.add(run)
        session.flush()

        trials = [
            Trial(
                id=f"01HQTRIAL{i:017d}",
                run_id=run.id,
                trial_index=i,
                status="completed",
                metrics={"sharpe": 1.5 + i * 0.1},
            )
            for i in range(3)
        ]
        session.add_all(trials)
        session.flush()

        queried_trials = session.query(Trial).filter_by(run_id=run.id).all()
        assert len(queried_trials) == 3

    def test_run_artifact_workflow(self, session, test_strategy):
        """Artifacts can be linked to a run."""
        run = Run(
            id=UID_RUN3,
            strategy_id=test_strategy.id,
            run_type="backtest",
            status="completed",
        )
        session.add(run)
        session.flush()

        artifact = Artifact(
            id=UID_ARTI,
            run_id=run.id,
            artifact_type="report",
            uri="s3://fxlab-artifacts/reports/01HQ.pdf",
            size_bytes=102400,
            checksum="abc123def456",
        )
        session.add(artifact)
        session.flush()

        queried = session.query(Artifact).filter_by(run_id=run.id).first()
        assert queried is not None
        assert queried.artifact_type == "report"

    def test_feed_health_event_relationship(self, session):
        """FeedHealthEvent can be linked to a Feed."""
        feed = Feed(
            id=UID_FEED,
            name="us_equities_ohlcv_1d",
            feed_type="price",
            source="alpaca",
        )
        session.add(feed)
        session.flush()

        health = FeedHealthEvent(
            id="01HQFEEDHEALTH000000000001",
            feed_id=feed.id,
            status="healthy",
            details={"latency_ms": 45, "row_count": 5000},
        )
        session.add(health)
        session.flush()

        queried = (
            session.query(FeedHealthEvent).filter_by(feed_id=feed.id).first()
        )
        assert queried is not None
        assert queried.status == "healthy"


# ---------------------------------------------------------------------------
# Audit ledger end-to-end tests
# ---------------------------------------------------------------------------


class TestM2AuditLedgerIntegration:
    """Verify the audit ledger write + query workflow end-to-end."""

    def test_write_and_query_audit_event(self, session):
        """write_audit_event can be queried back with all fields intact."""
        write_audit_event(
            session=session,
            actor="user:01HQAAAAAAAAAAAAAAAAAAAAAA",
            action="strategy.created",
            object_id="01HQAUDITSTRATEGY000000BBB",
            object_type="strategy",
            metadata={
                "name": "Test MA Crossover",
                "version": "1.0.0",
            },
        )

        events = (
            session.query(AuditEvent)
            .filter_by(
                object_id="01HQAUDITSTRATEGY000000BBB",
                action="strategy.created",
            )
            .all()
        )
        assert len(events) >= 1
        event = events[0]
        assert event.actor == "user:01HQAAAAAAAAAAAAAAAAAAAAAA"
        assert event.event_metadata["name"] == "Test MA Crossover"

    def test_multiple_audit_events_queryable(self, session):
        """Multiple audit events for the same object can be queried."""
        obj_id = "01HQAUDITOBJECT0000000FFF1"
        actions = ["run.started", "run.completed", "artifact.stored"]
        for action in actions:
            write_audit_event(
                session=session,
                actor="system:scheduler",
                action=action,
                object_id=obj_id,
                object_type="run",
                metadata={},
            )

        events = (
            session.query(AuditEvent)
            .filter_by(object_id=obj_id)
            .order_by(AuditEvent.created_at)
            .all()
        )
        assert len(events) == 3
        event_actions = [e.action for e in events]
        for action in actions:
            assert action in event_actions

    def test_audit_event_ulid_is_unique(self, session):
        """Each audit event receives a unique ULID."""
        ids = set()
        for i in range(5):
            event_id = write_audit_event(
                session=session,
                actor="system:test",
                action="test.action",
                object_id="01HQAUDITUNIQUE00000000001",
                object_type="test",
                metadata={"iteration": i},
            )
            ids.add(event_id)

        assert len(ids) == 5, "All event IDs should be unique ULIDs"
