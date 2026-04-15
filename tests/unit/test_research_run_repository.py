"""
Unit tests for the mock research run repository.

Covers:
- create: store + duplicate rejection
- get_by_id: found + not found
- update_status: valid transitions, invalid transitions, error_message
- save_result: attach result, not found
- list_by_strategy: filter + pagination
- list_by_user: filter + pagination
- count_by_status: all + filtered
- introspection: count, get_all, clear

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import pytest

from libs.contracts.errors import NotFoundError
from libs.contracts.mocks.mock_research_run_repository import (
    MockResearchRunRepository,
)
from libs.contracts.research_run import (
    InvalidStatusTransitionError,
    ResearchRunConfig,
    ResearchRunRecord,
    ResearchRunResult,
    ResearchRunStatus,
    ResearchRunType,
)

# ---------------------------------------------------------------------------
# Helpers
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
    )


def _make_record(
    run_id: str = "01HRUN00000000000000000001",
    strategy_id: str = _STRATEGY_ID,
    user_id: str = _USER_ID,
    status: ResearchRunStatus = ResearchRunStatus.PENDING,
) -> ResearchRunRecord:
    return ResearchRunRecord(
        id=run_id,
        config=_make_config(strategy_id=strategy_id),
        status=status,
        created_by=user_id,
    )


@pytest.fixture()
def repo() -> MockResearchRunRepository:
    return MockResearchRunRepository()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestCreate:
    """Tests for create method."""

    def test_create_stores_record(self, repo: MockResearchRunRepository) -> None:
        record = _make_record()
        result = repo.create(record)
        assert result.id == record.id
        assert repo.count() == 1

    def test_create_duplicate_raises_value_error(self, repo: MockResearchRunRepository) -> None:
        record = _make_record()
        repo.create(record)
        with pytest.raises(ValueError, match="already exists"):
            repo.create(record)


# ---------------------------------------------------------------------------
# Get by ID
# ---------------------------------------------------------------------------


class TestGetById:
    """Tests for get_by_id method."""

    def test_get_existing_record(self, repo: MockResearchRunRepository) -> None:
        record = _make_record()
        repo.create(record)
        result = repo.get_by_id(record.id)
        assert result is not None
        assert result.id == record.id

    def test_get_missing_returns_none(self, repo: MockResearchRunRepository) -> None:
        assert repo.get_by_id("nonexistent") is None


# ---------------------------------------------------------------------------
# Update Status
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    """Tests for update_status method."""

    def test_pending_to_queued(self, repo: MockResearchRunRepository) -> None:
        record = _make_record()
        repo.create(record)
        updated = repo.update_status(record.id, ResearchRunStatus.QUEUED)
        assert updated.status == ResearchRunStatus.QUEUED

    def test_queued_to_running_sets_started_at(self, repo: MockResearchRunRepository) -> None:
        record = _make_record()
        repo.create(record)
        repo.update_status(record.id, ResearchRunStatus.QUEUED)
        updated = repo.update_status(record.id, ResearchRunStatus.RUNNING)
        assert updated.status == ResearchRunStatus.RUNNING
        assert updated.started_at is not None

    def test_running_to_completed_sets_completed_at(self, repo: MockResearchRunRepository) -> None:
        record = _make_record()
        repo.create(record)
        repo.update_status(record.id, ResearchRunStatus.QUEUED)
        repo.update_status(record.id, ResearchRunStatus.RUNNING)
        updated = repo.update_status(record.id, ResearchRunStatus.COMPLETED)
        assert updated.status == ResearchRunStatus.COMPLETED
        assert updated.completed_at is not None

    def test_running_to_failed_with_error_message(self, repo: MockResearchRunRepository) -> None:
        record = _make_record()
        repo.create(record)
        repo.update_status(record.id, ResearchRunStatus.QUEUED)
        repo.update_status(record.id, ResearchRunStatus.RUNNING)
        updated = repo.update_status(
            record.id,
            ResearchRunStatus.FAILED,
            error_message="Engine crashed",
        )
        assert updated.status == ResearchRunStatus.FAILED
        assert updated.error_message == "Engine crashed"

    def test_invalid_transition_raises_error(self, repo: MockResearchRunRepository) -> None:
        record = _make_record()
        repo.create(record)
        with pytest.raises(InvalidStatusTransitionError):
            repo.update_status(record.id, ResearchRunStatus.COMPLETED)

    def test_update_missing_run_raises_not_found(self, repo: MockResearchRunRepository) -> None:
        with pytest.raises(NotFoundError):
            repo.update_status("nonexistent", ResearchRunStatus.QUEUED)


# ---------------------------------------------------------------------------
# Save Result
# ---------------------------------------------------------------------------


class TestSaveResult:
    """Tests for save_result method."""

    def test_save_result_attaches_to_record(self, repo: MockResearchRunRepository) -> None:
        record = _make_record()
        repo.create(record)
        result = ResearchRunResult(summary_metrics={"total_return": 0.15})
        updated = repo.save_result(record.id, result)
        assert updated.result is not None
        assert updated.result.summary_metrics["total_return"] == 0.15

    def test_save_result_missing_run_raises_not_found(
        self, repo: MockResearchRunRepository
    ) -> None:
        result = ResearchRunResult()
        with pytest.raises(NotFoundError):
            repo.save_result("nonexistent", result)


# ---------------------------------------------------------------------------
# List by Strategy
# ---------------------------------------------------------------------------


class TestListByStrategy:
    """Tests for list_by_strategy method."""

    def test_filters_by_strategy(self, repo: MockResearchRunRepository) -> None:
        repo.create(_make_record("run1", strategy_id="strat_a"))
        repo.create(_make_record("run2", strategy_id="strat_b"))
        repo.create(_make_record("run3", strategy_id="strat_a"))

        records, total = repo.list_by_strategy("strat_a")
        assert total == 2
        assert all(r.config.strategy_id == "strat_a" for r in records)

    def test_pagination(self, repo: MockResearchRunRepository) -> None:
        for i in range(5):
            repo.create(_make_record(f"run{i}", strategy_id="strat_a"))
        records, total = repo.list_by_strategy("strat_a", limit=2, offset=0)
        assert total == 5
        assert len(records) == 2

        records2, _ = repo.list_by_strategy("strat_a", limit=2, offset=2)
        assert len(records2) == 2


# ---------------------------------------------------------------------------
# List by User
# ---------------------------------------------------------------------------


class TestListByUser:
    """Tests for list_by_user method."""

    def test_filters_by_user(self, repo: MockResearchRunRepository) -> None:
        repo.create(_make_record("run1", user_id="user_a"))
        repo.create(_make_record("run2", user_id="user_b"))
        repo.create(_make_record("run3", user_id="user_a"))

        records, total = repo.list_by_user("user_a")
        assert total == 2


# ---------------------------------------------------------------------------
# Count by Status
# ---------------------------------------------------------------------------


class TestCountByStatus:
    """Tests for count_by_status method."""

    def test_count_all(self, repo: MockResearchRunRepository) -> None:
        repo.create(_make_record("run1"))
        repo.create(_make_record("run2"))
        assert repo.count_by_status() == 2

    def test_count_by_specific_status(self, repo: MockResearchRunRepository) -> None:
        repo.create(_make_record("run1"))
        repo.create(_make_record("run2", status=ResearchRunStatus.PENDING))
        assert repo.count_by_status(ResearchRunStatus.PENDING) == 2
        assert repo.count_by_status(ResearchRunStatus.COMPLETED) == 0


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


class TestIntrospection:
    """Tests for introspection helpers."""

    def test_count(self, repo: MockResearchRunRepository) -> None:
        assert repo.count() == 0
        repo.create(_make_record())
        assert repo.count() == 1

    def test_get_all(self, repo: MockResearchRunRepository) -> None:
        repo.create(_make_record("run1"))
        repo.create(_make_record("run2"))
        all_records = repo.get_all()
        assert len(all_records) == 2

    def test_clear(self, repo: MockResearchRunRepository) -> None:
        repo.create(_make_record())
        repo.clear()
        assert repo.count() == 0
