"""
Integration tests for all SQL repository implementations.

Responsibilities:
- Verify each SQL repository's CRUD operations against a real SQLite database.
- Confirm data integrity across create/read/delete cycles.
- Confirm not-found and edge-case behaviour.
- Verify query filtering and ordering where applicable.

Does NOT:
- Test business logic (that lives in services).
- Test HTTP routing (that lives in controller tests).
- Use mocks — every test hits a real database.

Dependencies:
- integration_db_session fixture (from conftest.py): per-test SAVEPOINT-isolated session.
- libs.contracts.models ORM definitions.

Example:
    pytest tests/integration/test_sql_repositories.py -v
"""

from __future__ import annotations

from typing import Any

import pytest
import ulid as _ulid_mod

from libs.contracts.models import (
    AuditEvent,
    Feed,
    Override,
    ResearchRun,
    User,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Stable test-only ULIDs that show up as FK targets in many test bodies.
# Seeding them via _seed_fk_parents() before any insert means a single
# helper fixture covers every test in this file that needs a user or a run.
# These literals are referenced verbatim by various test bodies, so any
# new test ULID added below must ALSO be added to _TEST_USER_IDS.
_TEST_USER_IDS: tuple[str, ...] = (
    "01HTESTSUBMITTER0000000000",  # SqlOverrideRepository.submitter_id
    "01HTESTUSER000000000000000",  # SqlDraftAutosaveRepository.test_create
    "01HTESTLATEST0000000000000",  # SqlDraftAutosaveRepository.test_get_latest
    "01HTESTDELETE0000000000000",  # SqlDraftAutosaveRepository.test_delete
)
_TEST_USER_ID = _TEST_USER_IDS[0]  # backwards-compat alias used in most tests
_TEST_RUN_ID = "01HTESTRUNSUBMITTER0000001"


def _seed_fk_parents(session: Any) -> None:
    """
    Seed the User and ResearchRun rows the rest of this file's tests
    reference as FK targets via hardcoded ULIDs.

    Idempotent: if the rows already exist (e.g. a previous test in the
    same SAVEPOINT-rolled-back transaction), skip the insert.

    Required because the SqlOverrideRepository,
    SqlDraftAutosaveRepository, and SqlArtifactRepository tests insert
    rows with submitter_id / user_id / run_id values that point at
    these ULIDs; the FKs are NOT NULL in production and the integration
    job runs against a real Postgres that enforces them.
    """
    for uid in _TEST_USER_IDS:
        if session.get(User, uid) is None:
            session.add(
                User(
                    # Email uses the FULL ULID for uniqueness; the last 8
                    # chars of every test ULID we use happen to be all
                    # zeroes, so a suffix-only email collides.
                    id=uid,
                    email=f"test-{uid.lower()}@fxlab.local",
                    hashed_password="not-a-real-hash-test-only",
                    role="admin",
                    is_active=True,
                )
            )
    if session.get(ResearchRun, _TEST_RUN_ID) is None:
        session.add(
            ResearchRun(
                id=_TEST_RUN_ID,
                strategy_id=_TEST_USER_ID,  # not an enforced FK on ResearchRun
                run_type="backtest",
                status="completed",
                config_json={"note": "seed for FK"},
                created_by=_TEST_USER_ID,
            )
        )
    session.flush()


@pytest.fixture
def fk_parents_seeded(integration_db_session: Any) -> Any:
    """Auto-seed the FK target rows; yields the same session for reuse."""
    _seed_fk_parents(integration_db_session)
    return integration_db_session


def _ulid() -> str:
    """Generate a fresh ULID string for test data."""
    return str(_ulid_mod.ULID())


def _make_feed(session: Any, *, feed_id: str | None = None, name: str = "test-feed") -> Feed:
    """Insert a Feed row and flush (no commit) so it's visible in the SAVEPOINT."""
    fid = feed_id or str(_ulid_mod.ULID())
    feed = Feed(id=fid, name=name, feed_type="market_data", source="test", is_active=True)
    session.add(feed)
    session.flush()
    return feed


def _make_override(
    session: Any,
    *,
    override_id: str | None = None,
    submitter_id: str = "01HTESTSUBMITTER0000000000",
) -> Override:
    """Insert an Override row and flush."""
    oid = override_id or str(_ulid_mod.ULID())
    row = Override(
        id=oid,
        target_id=str(_ulid_mod.ULID()),
        target_type="candidate",
        override_type="grade_override",
        rationale="Integration test rationale that is long enough",
        evidence_link="https://jira.example.com/browse/FX-999",
        submitter_id=submitter_id,
        status="pending",
        is_active=True,
        original_state={"grade": "C"},
        new_state={"grade": "B"},
    )
    session.add(row)
    session.flush()
    return row


def _make_audit_event(
    session: Any,
    *,
    event_id: str | None = None,
    actor: str = "user:01HTESTACTOR00000000000000",
    action: str = "test.action",
    object_type: str = "test_entity",
) -> AuditEvent:
    """Insert an AuditEvent row and flush."""
    eid = event_id or str(_ulid_mod.ULID())
    event = AuditEvent(
        id=eid,
        actor=actor,
        action=action,
        object_id=str(_ulid_mod.ULID()),
        object_type=object_type,
        event_metadata={"test": True},
    )
    session.add(event)
    session.flush()
    return event


# ---------------------------------------------------------------------------
# SqlOverrideRepository
# ---------------------------------------------------------------------------


class TestSqlOverrideRepository:
    """Integration tests for SqlOverrideRepository create/get_by_id."""

    @pytest.fixture(autouse=True)
    def _seed(self, integration_db_session):
        """Seed the User row that submitter_id FKs to before each test."""
        _seed_fk_parents(integration_db_session)

    def test_create_returns_override_id_and_pending_status(self, integration_db_session):
        """create() inserts a row and returns dict with override_id and status=pending."""
        from services.api.repositories.sql_override_repository import SqlOverrideRepository

        repo = SqlOverrideRepository(db=integration_db_session)
        result = repo.create(
            object_id=str(_ulid_mod.ULID()),
            object_type="candidate",
            override_type="grade_override",
            original_state={"grade": "C"},
            new_state={"grade": "B"},
            evidence_link="https://jira.example.com/browse/FX-100",
            rationale="Integration test — create returns id and status",
            submitter_id="01HTESTSUBMITTER0000000000",
        )

        assert "override_id" in result
        assert result["status"] == "pending"
        assert len(result["override_id"]) == 26  # ULID length

    def test_get_by_id_returns_created_record(self, integration_db_session):
        """get_by_id() retrieves a previously created override."""
        from services.api.repositories.sql_override_repository import SqlOverrideRepository

        repo = SqlOverrideRepository(db=integration_db_session)
        created = repo.create(
            object_id=str(_ulid_mod.ULID()),
            object_type="deployment",
            override_type="config_override",
            original_state=None,
            new_state={"flag": True},
            evidence_link="https://jira.example.com/browse/FX-101",
            rationale="Integration test — get_by_id roundtrip verification",
            submitter_id="01HTESTSUBMITTER0000000000",
        )

        record = repo.get_by_id(created["override_id"])
        assert record is not None
        assert record["override_id"] == created["override_id"]
        assert record["status"] == "pending"
        assert record["submitter_id"] == "01HTESTSUBMITTER0000000000"

    def test_get_by_id_returns_none_for_missing(self, integration_db_session):
        """get_by_id() returns None when the override does not exist."""
        from services.api.repositories.sql_override_repository import SqlOverrideRepository

        repo = SqlOverrideRepository(db=integration_db_session)
        result = repo.get_by_id("01HNOTEXIST0000000000000000")
        assert result is None


# ---------------------------------------------------------------------------
# SqlDraftAutosaveRepository
# ---------------------------------------------------------------------------


class TestSqlDraftAutosaveRepository:
    """Integration tests for SqlDraftAutosaveRepository create/get_latest/delete."""

    @pytest.fixture(autouse=True)
    def _seed(self, integration_db_session):
        """Seed the User row that user_id FKs to before each test."""
        _seed_fk_parents(integration_db_session)

    def test_create_returns_dict_with_autosave_id(self, integration_db_session):
        """create() inserts a row and returns dict with autosave_id."""
        from services.api.repositories.sql_draft_autosave_repository import (
            SqlDraftAutosaveRepository,
        )

        repo = SqlDraftAutosaveRepository(db=integration_db_session)
        result = repo.create(
            user_id="01HTESTUSER000000000000000",
            draft_payload={"name": "TestStrategy", "params": {"lookback": 20}},
            form_step="parameters",
            session_id="sess-integ-001",
            client_ts="2026-04-02T12:00:00Z",
        )

        assert "autosave_id" in result
        assert len(result["autosave_id"]) == 26

    def test_get_latest_returns_most_recent(self, integration_db_session):
        """get_latest() returns the most recently created autosave for a user."""
        from services.api.repositories.sql_draft_autosave_repository import (
            SqlDraftAutosaveRepository,
        )

        repo = SqlDraftAutosaveRepository(db=integration_db_session)
        user_id = "01HTESTLATEST0000000000000"

        repo.create(
            user_id=user_id,
            draft_payload={"step": 1},
            form_step="basics",
        )
        second = repo.create(
            user_id=user_id,
            draft_payload={"step": 2},
            form_step="review",
        )

        latest = repo.get_latest(user_id=user_id)
        assert latest is not None
        assert latest["autosave_id"] == second["autosave_id"]

    def test_get_latest_returns_none_for_unknown_user(self, integration_db_session):
        """get_latest() returns None when no autosaves exist for the user."""
        from services.api.repositories.sql_draft_autosave_repository import (
            SqlDraftAutosaveRepository,
        )

        repo = SqlDraftAutosaveRepository(db=integration_db_session)
        result = repo.get_latest(user_id="01HNOBODY000000000000000000")
        assert result is None

    def test_delete_removes_record(self, integration_db_session):
        """delete() removes the autosave and returns True."""
        from services.api.repositories.sql_draft_autosave_repository import (
            SqlDraftAutosaveRepository,
        )

        repo = SqlDraftAutosaveRepository(db=integration_db_session)
        created = repo.create(
            user_id="01HTESTDELETE0000000000000",
            draft_payload={"x": 1},
        )
        autosave_id = created["autosave_id"]

        assert repo.delete(autosave_id=autosave_id) is True
        assert repo.get_latest(user_id="01HTESTDELETE0000000000000") is None

    def test_delete_returns_false_for_missing(self, integration_db_session):
        """delete() returns False when the autosave does not exist."""
        from services.api.repositories.sql_draft_autosave_repository import (
            SqlDraftAutosaveRepository,
        )

        repo = SqlDraftAutosaveRepository(db=integration_db_session)
        result = repo.delete(autosave_id="01HNOTEXIST0000000000000000")
        assert result is False


# ---------------------------------------------------------------------------
# SqlFeedRepository
# ---------------------------------------------------------------------------


class TestSqlFeedRepository:
    """Integration tests for SqlFeedRepository list/find_by_id."""

    def test_list_returns_empty_when_no_feeds(self, integration_db_session):
        """list() returns an empty collection when no feeds exist."""
        from services.api.repositories.sql_feed_repository import SqlFeedRepository

        repo = SqlFeedRepository(db=integration_db_session)
        result = repo.list(limit=10, offset=0, correlation_id="corr-feed-01")
        assert result.feeds == []

    def test_list_returns_inserted_feeds(self, integration_db_session):
        """list() returns feeds after they are inserted."""
        from services.api.repositories.sql_feed_repository import SqlFeedRepository

        _make_feed(integration_db_session, name="alpha-feed")
        _make_feed(integration_db_session, name="beta-feed")

        repo = SqlFeedRepository(db=integration_db_session)
        result = repo.list(limit=10, offset=0, correlation_id="corr-feed-02")
        assert len(result.feeds) >= 2

    def test_find_by_id_returns_existing_feed(self, integration_db_session):
        """find_by_id() retrieves a feed by its ULID (wrapped in FeedDetailResponse)."""
        from services.api.repositories.sql_feed_repository import SqlFeedRepository

        feed = _make_feed(integration_db_session, name="findme-feed")

        repo = SqlFeedRepository(db=integration_db_session)
        result = repo.find_by_id(feed_id=feed.id, correlation_id="corr-feed-03")
        # find_by_id returns FeedDetailResponse with .feed attribute
        assert result.feed.id == feed.id
        assert result.feed.name == "findme-feed"

    def test_find_by_id_raises_not_found(self, integration_db_session):
        """find_by_id() raises NotFoundError for non-existent feed."""
        from libs.contracts.errors import NotFoundError
        from services.api.repositories.sql_feed_repository import SqlFeedRepository

        repo = SqlFeedRepository(db=integration_db_session)
        with pytest.raises(NotFoundError):
            repo.find_by_id(feed_id="01HNOTEXIST0000000000000000", correlation_id="corr-feed-04")


# ---------------------------------------------------------------------------
# SqlAuditExplorerRepository
# ---------------------------------------------------------------------------


class TestSqlAuditExplorerRepository:
    """Integration tests for SqlAuditExplorerRepository list/find_by_id."""

    def test_list_returns_empty_when_no_events(self, integration_db_session):
        """list() returns an empty list when no audit events exist."""
        from services.api.repositories.sql_audit_explorer_repository import (
            SqlAuditExplorerRepository,
        )

        repo = SqlAuditExplorerRepository(db=integration_db_session)
        result = repo.list(correlation_id="corr-audit-01")
        assert result == []

    def test_list_returns_inserted_events(self, integration_db_session):
        """list() returns audit events that were inserted."""
        from services.api.repositories.sql_audit_explorer_repository import (
            SqlAuditExplorerRepository,
        )

        _make_audit_event(integration_db_session, action="strategy.created")
        _make_audit_event(integration_db_session, action="run.started")

        repo = SqlAuditExplorerRepository(db=integration_db_session)
        result = repo.list(correlation_id="corr-audit-02")
        assert len(result) >= 2

    def test_list_filters_by_action_type(self, integration_db_session):
        """list() filters events by action_type prefix."""
        from services.api.repositories.sql_audit_explorer_repository import (
            SqlAuditExplorerRepository,
        )

        _make_audit_event(integration_db_session, action="override.submitted")
        _make_audit_event(integration_db_session, action="approval.approved")

        repo = SqlAuditExplorerRepository(db=integration_db_session)
        result = repo.list(action_type="override", correlation_id="corr-audit-03")
        assert all("override" in r.action for r in result)

    def test_find_by_id_returns_event(self, integration_db_session):
        """find_by_id() retrieves a specific audit event by ULID."""
        from services.api.repositories.sql_audit_explorer_repository import (
            SqlAuditExplorerRepository,
        )

        event = _make_audit_event(integration_db_session, action="test.find")

        repo = SqlAuditExplorerRepository(db=integration_db_session)
        result = repo.find_by_id(id=event.id, correlation_id="corr-audit-04")
        assert result.id == event.id
        assert result.action == "test.find"

    def test_find_by_id_raises_not_found(self, integration_db_session):
        """find_by_id() raises NotFoundError for non-existent event."""
        from libs.contracts.errors import NotFoundError
        from services.api.repositories.sql_audit_explorer_repository import (
            SqlAuditExplorerRepository,
        )

        repo = SqlAuditExplorerRepository(db=integration_db_session)
        with pytest.raises(NotFoundError):
            repo.find_by_id(id="01HNOTEXIST0000000000000000", correlation_id="corr-audit-05")


# ---------------------------------------------------------------------------
# SqlArtifactRepository
# ---------------------------------------------------------------------------


class TestSqlArtifactRepository:
    """Integration tests for SqlArtifactRepository save/find_by_id/list.

    Migration 0028 added ``subject_id`` / ``storage_path`` /
    ``created_by`` columns to the ``artifacts`` table so the schema
    matches the registry contract the repository reads/writes against.
    Inserts here use the registry-style fields directly; the legacy
    ``run_id`` / ``uri`` columns remain present (for backwards
    compatibility with other tests) but are not exercised by the
    repository itself.
    """

    @pytest.fixture(autouse=True)
    def _seed(self, integration_db_session):
        """Seed User and ResearchRun rows used as FK targets."""
        _seed_fk_parents(integration_db_session)

    def _make_artifact_orm(self, session: Any) -> Any:
        """Insert an artifact row via ORM and flush.

        Populates the registry-shape fields (``subject_id``,
        ``storage_path``, ``created_by``) the SqlArtifactRepository
        actually queries against. ``run_id`` is left NULL — the repo
        ignores it.

        Returns an ArtifactORM instance.
        """
        from libs.contracts.models import Artifact as ArtifactORM

        aid = str(_ulid_mod.ULID())
        row = ArtifactORM(
            id=aid,
            artifact_type="backtest_result",
            # Registry-style fields — what the repository reads.
            subject_id=_TEST_RUN_ID,
            storage_path=f"fxlab-artifacts/runs/{aid}.parquet",
            size_bytes=1024,
            created_by=_TEST_USER_ID,
        )
        session.add(row)
        session.flush()
        return row

    def test_find_by_id_returns_artifact(self, integration_db_session):
        """find_by_id() retrieves a previously saved artifact."""
        from services.api.repositories.sql_artifact_repository import SqlArtifactRepository

        inserted = self._make_artifact_orm(integration_db_session)

        repo = SqlArtifactRepository(db=integration_db_session)
        result = repo.find_by_id(artifact_id=inserted.id)
        assert result is not None
        assert result.id == inserted.id
        assert result.subject_id == _TEST_RUN_ID
        assert result.storage_path == inserted.storage_path
        assert result.created_by == _TEST_USER_ID

    def test_find_by_id_raises_not_found(self, integration_db_session):
        """find_by_id() raises NotFoundError for non-existent artifact."""
        from libs.contracts.errors import NotFoundError
        from services.api.repositories.sql_artifact_repository import SqlArtifactRepository

        repo = SqlArtifactRepository(db=integration_db_session)
        with pytest.raises(NotFoundError):
            repo.find_by_id(artifact_id="01HNOTEXIST0000000000000000")

    def test_save_persists_artifact(self, integration_db_session):
        """save() persists an Artifact and find_by_id() round-trips it."""
        from datetime import datetime, timezone

        from libs.contracts.artifact import Artifact, ArtifactType
        from services.api.repositories.sql_artifact_repository import SqlArtifactRepository

        repo = SqlArtifactRepository(db=integration_db_session)
        aid = str(_ulid_mod.ULID())
        contract = Artifact(
            id=aid,
            artifact_type=ArtifactType.BACKTEST_RESULT,
            subject_id=_TEST_RUN_ID,
            storage_path=f"fxlab-artifacts/runs/{aid}.json",
            size_bytes=512,
            created_at=datetime.now(timezone.utc),
            created_by=_TEST_USER_ID,
            metadata={},
        )

        saved = repo.save(contract)
        assert saved.id == aid

        fetched = repo.find_by_id(artifact_id=aid)
        assert fetched.id == aid
        assert fetched.subject_id == _TEST_RUN_ID
        assert fetched.storage_path == contract.storage_path
        assert fetched.size_bytes == 512
        assert fetched.created_by == _TEST_USER_ID

    def test_list_returns_paginated_artifacts(self, integration_db_session):
        """list() honours limit/offset and reports total_count."""
        from libs.contracts.artifact import ArtifactQuery
        from services.api.repositories.sql_artifact_repository import SqlArtifactRepository

        # Seed three rows directly through the ORM helper.
        for _ in range(3):
            self._make_artifact_orm(integration_db_session)

        repo = SqlArtifactRepository(db=integration_db_session)
        resp = repo.list(ArtifactQuery(limit=2, offset=0))
        assert resp.total_count >= 3
        assert len(resp.artifacts) == 2
        assert resp.limit == 2
        assert resp.offset == 0


# ---------------------------------------------------------------------------
# SqlChartRepository (stub — returns empty results)
# ---------------------------------------------------------------------------


class TestSqlChartRepository:
    """Integration tests for SqlChartRepository (currently returns empty data)."""

    def test_find_equity_returns_empty_list(self, integration_db_session):
        """find_equity_by_run_id() returns empty list (no equity data yet)."""
        from services.api.repositories.sql_chart_repository import SqlChartRepository

        repo = SqlChartRepository(db=integration_db_session)
        result = repo.find_equity_by_run_id(
            run_id=str(_ulid_mod.ULID()), correlation_id="corr-chart-01"
        )
        assert result == []

    def test_find_drawdown_returns_empty_list(self, integration_db_session):
        """find_drawdown_by_run_id() returns empty list (no drawdown data yet)."""
        from services.api.repositories.sql_chart_repository import SqlChartRepository

        repo = SqlChartRepository(db=integration_db_session)
        result = repo.find_drawdown_by_run_id(
            run_id=str(_ulid_mod.ULID()), correlation_id="corr-chart-02"
        )
        assert result == []

    def test_find_trade_count_returns_zero(self, integration_db_session):
        """find_trade_count_by_run_id() returns 0 (no trade data yet)."""
        from services.api.repositories.sql_chart_repository import SqlChartRepository

        repo = SqlChartRepository(db=integration_db_session)
        result = repo.find_trade_count_by_run_id(
            run_id=str(_ulid_mod.ULID()), correlation_id="corr-chart-03"
        )
        assert result == 0


# ---------------------------------------------------------------------------
# SqlFeedHealthRepository
# ---------------------------------------------------------------------------


class TestSqlFeedHealthRepository:
    """Integration tests for SqlFeedHealthRepository."""

    def test_get_all_health_returns_response(self, integration_db_session):
        """get_all_health() returns a FeedHealthListResponse."""
        from services.api.repositories.sql_feed_health_repository import (
            SqlFeedHealthRepository,
        )

        repo = SqlFeedHealthRepository(db=integration_db_session)
        result = repo.get_all_health(correlation_id="corr-fh-01")
        # Should return a response object (may be empty)
        assert hasattr(result, "feeds") or isinstance(result, (list, dict))

    def test_get_health_by_feed_id_with_existing_feed(self, integration_db_session):
        """get_health_by_feed_id() returns a report for an existing feed."""
        from services.api.repositories.sql_feed_health_repository import (
            SqlFeedHealthRepository,
        )

        feed = _make_feed(integration_db_session, name="health-check-feed")

        repo = SqlFeedHealthRepository(db=integration_db_session)
        result = repo.get_health_by_feed_id(feed_id=feed.id, correlation_id="corr-fh-02")
        assert result is not None


# ---------------------------------------------------------------------------
# SqlParityRepository
# ---------------------------------------------------------------------------


class TestSqlParityRepository:
    """Integration tests for SqlParityRepository."""

    def test_list_returns_empty_when_no_events(self, integration_db_session):
        """list() returns empty list when no parity events exist."""
        from services.api.repositories.sql_parity_repository import SqlParityRepository

        repo = SqlParityRepository(db=integration_db_session)
        result = repo.list(correlation_id="corr-par-01")
        assert result == []

    def test_list_returns_list_type(self, integration_db_session):
        """list() returns a list (empty when no parity events exist)."""
        from services.api.repositories.sql_parity_repository import SqlParityRepository

        repo = SqlParityRepository(db=integration_db_session)
        result = repo.list(correlation_id="corr-par-02")
        assert isinstance(result, list)

    def test_find_by_id_raises_not_found(self, integration_db_session):
        """find_by_id() raises NotFoundError for missing parity event."""
        from libs.contracts.errors import NotFoundError
        from services.api.repositories.sql_parity_repository import SqlParityRepository

        repo = SqlParityRepository(db=integration_db_session)
        with pytest.raises(NotFoundError):
            repo.find_by_id(id="01HNOTEXIST0000000000000000", correlation_id="corr-par-03")

    def test_summarize_returns_list(self, integration_db_session):
        """summarize() returns a list (possibly empty) of instrument summaries."""
        from services.api.repositories.sql_parity_repository import SqlParityRepository

        repo = SqlParityRepository(db=integration_db_session)
        result = repo.summarize(correlation_id="corr-par-04")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# SqlCertificationRepository (stub — returns empty results)
# ---------------------------------------------------------------------------


class TestSqlCertificationRepository:
    """Integration tests for SqlCertificationRepository."""

    def test_list_returns_empty(self, integration_db_session):
        """list() returns empty list (certification not yet populated)."""
        from services.api.repositories.sql_certification_repository import (
            SqlCertificationRepository,
        )

        repo = SqlCertificationRepository(db=integration_db_session)
        result = repo.list(correlation_id="corr-cert-01")
        assert result == []


# ---------------------------------------------------------------------------
# SqlSymbolLineageRepository (stub — returns empty lineage)
# ---------------------------------------------------------------------------


class TestSqlSymbolLineageRepository:
    """Integration tests for SqlSymbolLineageRepository."""

    def test_find_by_symbol_raises_not_found_when_no_data(self, integration_db_session):
        """find_by_symbol() raises NotFoundError when no lineage data exists."""
        from libs.contracts.errors import NotFoundError
        from services.api.repositories.sql_symbol_lineage_repository import (
            SqlSymbolLineageRepository,
        )

        repo = SqlSymbolLineageRepository(db=integration_db_session)
        with pytest.raises(NotFoundError, match="AAPL"):
            repo.find_by_symbol(symbol="AAPL", correlation_id="corr-sym-01")


# ---------------------------------------------------------------------------
# SqlDiagnosticsRepository
# ---------------------------------------------------------------------------


class TestSqlDiagnosticsRepository:
    """Integration tests for SqlDiagnosticsRepository."""

    def test_snapshot_returns_diagnostics(self, integration_db_session):
        """snapshot() returns a DiagnosticsSnapshot."""
        from services.api.repositories.sql_diagnostics_repository import (
            SqlDiagnosticsRepository,
        )

        repo = SqlDiagnosticsRepository(db=integration_db_session)
        result = repo.snapshot(correlation_id="corr-diag-01")
        assert result is not None
        assert hasattr(result, "feed_health_count") or hasattr(result, "db_status")
