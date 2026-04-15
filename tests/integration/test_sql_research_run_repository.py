"""
Integration tests for SqlResearchRunRepository.

Covers:
- create: persist + retrieve + duplicate rejection
- get_by_id: found + not found
- update_status: valid transitions, invalid, timestamps, error_message
- save_result: attach + retrieve, not found
- list_by_strategy: filter + pagination
- list_by_user: filter + pagination
- count_by_status: all + filtered

Uses in-memory SQLite with SAVEPOINT isolation per test.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.errors import NotFoundError
from libs.contracts.models import Base
from libs.contracts.research_run import (
    InvalidStatusTransitionError,
    ResearchRunConfig,
    ResearchRunRecord,
    ResearchRunResult,
    ResearchRunStatus,
    ResearchRunType,
)
from services.api.repositories.sql_research_run_repository import (
    SqlResearchRunRepository,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_STRATEGY_ID = "01HSTRATEGY00000000000001"
_USER_ID = "01HUSER00000000000000001"


def _make_config(
    strategy_id: str = _STRATEGY_ID,
    run_type: ResearchRunType = ResearchRunType.BACKTEST,
) -> ResearchRunConfig:
    return ResearchRunConfig(
        run_type=run_type,
        strategy_id=strategy_id,
        symbols=["AAPL"],
        initial_equity=Decimal("100000"),
    )


def _make_record(
    run_id: str = "01HRUN00000000000000000001",
    strategy_id: str = _STRATEGY_ID,
    user_id: str = _USER_ID,
) -> ResearchRunRecord:
    return ResearchRunRecord(
        id=run_id,
        config=_make_config(strategy_id=strategy_id),
        status=ResearchRunStatus.PENDING,
        created_by=user_id,
    )


@pytest.fixture()
def db_session():
    """
    In-memory SQLite session with SAVEPOINT isolation.

    Creates all tables from Base.metadata, yields a session,
    then rolls back and tears down.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    # Enable SAVEPOINT support on SQLite
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def repo(db_session: Session) -> SqlResearchRunRepository:
    return SqlResearchRunRepository(db=db_session)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestCreate:
    """Tests for create method."""

    def test_create_persists_and_retrieves(self, repo: SqlResearchRunRepository) -> None:
        record = _make_record()
        created = repo.create(record)
        assert created.id == record.id
        assert created.config.run_type == ResearchRunType.BACKTEST
        assert created.config.strategy_id == _STRATEGY_ID
        assert created.status == ResearchRunStatus.PENDING

    def test_create_duplicate_raises(self, repo: SqlResearchRunRepository) -> None:
        record = _make_record()
        repo.create(record)
        with pytest.raises(ValueError, match="already exists"):
            repo.create(record)

    def test_create_preserves_config_fields(self, repo: SqlResearchRunRepository) -> None:
        record = _make_record()
        created = repo.create(record)
        assert created.config.symbols == ["AAPL"]
        assert created.config.initial_equity == Decimal("100000")


# ---------------------------------------------------------------------------
# Get by ID
# ---------------------------------------------------------------------------


class TestGetById:
    """Tests for get_by_id method."""

    def test_get_existing(self, repo: SqlResearchRunRepository) -> None:
        record = _make_record()
        repo.create(record)
        result = repo.get_by_id(record.id)
        assert result is not None
        assert result.id == record.id

    def test_get_missing_returns_none(self, repo: SqlResearchRunRepository) -> None:
        assert repo.get_by_id("nonexistent") is None


# ---------------------------------------------------------------------------
# Update Status
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    """Tests for update_status method."""

    def test_pending_to_queued(self, repo: SqlResearchRunRepository) -> None:
        repo.create(_make_record())
        updated = repo.update_status("01HRUN00000000000000000001", ResearchRunStatus.QUEUED)
        assert updated.status == ResearchRunStatus.QUEUED

    def test_running_sets_started_at(self, repo: SqlResearchRunRepository) -> None:
        repo.create(_make_record())
        repo.update_status("01HRUN00000000000000000001", ResearchRunStatus.QUEUED)
        updated = repo.update_status("01HRUN00000000000000000001", ResearchRunStatus.RUNNING)
        assert updated.started_at is not None

    def test_completed_sets_completed_at(self, repo: SqlResearchRunRepository) -> None:
        repo.create(_make_record())
        repo.update_status("01HRUN00000000000000000001", ResearchRunStatus.QUEUED)
        repo.update_status("01HRUN00000000000000000001", ResearchRunStatus.RUNNING)
        updated = repo.update_status("01HRUN00000000000000000001", ResearchRunStatus.COMPLETED)
        assert updated.completed_at is not None

    def test_failed_with_error_message(self, repo: SqlResearchRunRepository) -> None:
        repo.create(_make_record())
        repo.update_status("01HRUN00000000000000000001", ResearchRunStatus.QUEUED)
        repo.update_status("01HRUN00000000000000000001", ResearchRunStatus.RUNNING)
        updated = repo.update_status(
            "01HRUN00000000000000000001",
            ResearchRunStatus.FAILED,
            error_message="Engine crashed",
        )
        assert updated.error_message == "Engine crashed"

    def test_invalid_transition_raises(self, repo: SqlResearchRunRepository) -> None:
        repo.create(_make_record())
        with pytest.raises(InvalidStatusTransitionError):
            repo.update_status(
                "01HRUN00000000000000000001",
                ResearchRunStatus.COMPLETED,
            )

    def test_missing_run_raises_not_found(self, repo: SqlResearchRunRepository) -> None:
        with pytest.raises(NotFoundError):
            repo.update_status("nonexistent", ResearchRunStatus.QUEUED)


# ---------------------------------------------------------------------------
# Save Result
# ---------------------------------------------------------------------------


class TestSaveResult:
    """Tests for save_result method."""

    def test_save_and_retrieve_result(self, repo: SqlResearchRunRepository) -> None:
        repo.create(_make_record())
        result = ResearchRunResult(summary_metrics={"total_return": 0.15, "sharpe_ratio": 1.2})
        updated = repo.save_result("01HRUN00000000000000000001", result)
        assert updated.result is not None
        assert updated.result.summary_metrics["total_return"] == 0.15

        # Also verify via get_by_id
        fetched = repo.get_by_id("01HRUN00000000000000000001")
        assert fetched is not None
        assert fetched.result is not None
        assert fetched.result.summary_metrics["sharpe_ratio"] == 1.2

    def test_save_result_missing_raises(self, repo: SqlResearchRunRepository) -> None:
        result = ResearchRunResult()
        with pytest.raises(NotFoundError):
            repo.save_result("nonexistent", result)


# ---------------------------------------------------------------------------
# List by Strategy
# ---------------------------------------------------------------------------


class TestListByStrategy:
    """Tests for list_by_strategy method."""

    def test_filters_by_strategy(self, repo: SqlResearchRunRepository) -> None:
        repo.create(_make_record("run1", strategy_id="strat_a"))
        repo.create(_make_record("run2", strategy_id="strat_b"))
        repo.create(_make_record("run3", strategy_id="strat_a"))

        records, total = repo.list_by_strategy("strat_a")
        assert total == 2
        assert all(r.config.strategy_id == "strat_a" for r in records)

    def test_pagination(self, repo: SqlResearchRunRepository) -> None:
        for i in range(5):
            repo.create(_make_record(f"run{i:03d}", strategy_id="strat_a"))

        records, total = repo.list_by_strategy("strat_a", limit=2, offset=0)
        assert total == 5
        assert len(records) == 2

    def test_empty_result(self, repo: SqlResearchRunRepository) -> None:
        records, total = repo.list_by_strategy("nonexistent")
        assert total == 0
        assert records == []


# ---------------------------------------------------------------------------
# List by User
# ---------------------------------------------------------------------------


class TestListByUser:
    """Tests for list_by_user method."""

    def test_filters_by_user(self, repo: SqlResearchRunRepository) -> None:
        repo.create(_make_record("run1", user_id="user_a"))
        repo.create(_make_record("run2", user_id="user_b"))
        repo.create(_make_record("run3", user_id="user_a"))

        records, total = repo.list_by_user("user_a")
        assert total == 2

    def test_pagination(self, repo: SqlResearchRunRepository) -> None:
        for i in range(4):
            repo.create(_make_record(f"run{i:03d}", user_id="user_a"))

        records, total = repo.list_by_user("user_a", limit=2, offset=0)
        assert total == 4
        assert len(records) == 2


# ---------------------------------------------------------------------------
# Count by Status
# ---------------------------------------------------------------------------


class TestCountByStatus:
    """Tests for count_by_status method."""

    def test_count_all(self, repo: SqlResearchRunRepository) -> None:
        repo.create(_make_record("run1"))
        repo.create(_make_record("run2"))
        assert repo.count_by_status() == 2

    def test_count_filtered(self, repo: SqlResearchRunRepository) -> None:
        repo.create(_make_record("run1"))
        repo.create(_make_record("run2"))
        assert repo.count_by_status(ResearchRunStatus.PENDING) == 2
        assert repo.count_by_status(ResearchRunStatus.COMPLETED) == 0

    def test_count_empty(self, repo: SqlResearchRunRepository) -> None:
        assert repo.count_by_status() == 0
