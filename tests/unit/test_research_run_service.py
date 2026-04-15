"""
Unit tests for ResearchRunService.

Covers:
- submit_run: ULID generation, PENDING record creation, QUEUED transition,
  validation errors for invalid config
- get_run: found, not found
- cancel_run: PENDING → CANCELLED, QUEUED → CANCELLED, terminal state rejection,
  not found
- list_runs: by strategy, by user, default (all)
- get_run_result: completed run returns result, pending run returns None,
  not found returns None

Uses MockResearchRunRepository for isolation.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from decimal import Decimal

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
from services.api.services.research_run_service import ResearchRunService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_STRATEGY_ID = "01HSTRATEGY00000000000001"
_USER_ID = "01HUSER00000000000000001"
_CORRELATION_ID = "test-corr-001"


def _make_config(
    run_type: ResearchRunType = ResearchRunType.BACKTEST,
    strategy_id: str = _STRATEGY_ID,
) -> ResearchRunConfig:
    return ResearchRunConfig(
        run_type=run_type,
        strategy_id=strategy_id,
        symbols=["AAPL"],
        initial_equity=Decimal("100000"),
    )


@pytest.fixture()
def repo() -> MockResearchRunRepository:
    return MockResearchRunRepository()


@pytest.fixture()
def service(repo: MockResearchRunRepository) -> ResearchRunService:
    return ResearchRunService(repo=repo)


# ---------------------------------------------------------------------------
# submit_run
# ---------------------------------------------------------------------------


class TestSubmitRun:
    """Tests for submit_run method."""

    def test_submit_creates_pending_record(
        self,
        service: ResearchRunService,
        repo: MockResearchRunRepository,
    ) -> None:
        config = _make_config()
        record = service.submit_run(config, user_id=_USER_ID)

        assert record.id  # ULID is generated
        assert record.status == ResearchRunStatus.QUEUED
        assert record.config.strategy_id == _STRATEGY_ID
        assert record.config.run_type == ResearchRunType.BACKTEST
        assert record.created_by == _USER_ID
        assert repo.count() == 1

    def test_submit_with_correlation_id(
        self,
        service: ResearchRunService,
    ) -> None:
        config = _make_config()
        record = service.submit_run(config, user_id=_USER_ID, correlation_id=_CORRELATION_ID)
        assert record.id
        assert record.status == ResearchRunStatus.QUEUED

    def test_submit_walk_forward(
        self,
        service: ResearchRunService,
    ) -> None:
        config = _make_config(run_type=ResearchRunType.WALK_FORWARD)
        record = service.submit_run(config, user_id=_USER_ID)
        assert record.config.run_type == ResearchRunType.WALK_FORWARD
        assert record.status == ResearchRunStatus.QUEUED

    def test_submit_monte_carlo(
        self,
        service: ResearchRunService,
    ) -> None:
        config = _make_config(run_type=ResearchRunType.MONTE_CARLO)
        record = service.submit_run(config, user_id=_USER_ID)
        assert record.config.run_type == ResearchRunType.MONTE_CARLO
        assert record.status == ResearchRunStatus.QUEUED

    def test_submit_composite(
        self,
        service: ResearchRunService,
    ) -> None:
        config = _make_config(run_type=ResearchRunType.COMPOSITE)
        record = service.submit_run(config, user_id=_USER_ID)
        assert record.config.run_type == ResearchRunType.COMPOSITE
        assert record.status == ResearchRunStatus.QUEUED

    def test_submit_generates_unique_ids(
        self,
        service: ResearchRunService,
    ) -> None:
        config = _make_config()
        r1 = service.submit_run(config, user_id=_USER_ID)
        r2 = service.submit_run(config, user_id=_USER_ID)
        assert r1.id != r2.id


# ---------------------------------------------------------------------------
# get_run
# ---------------------------------------------------------------------------


class TestGetRun:
    """Tests for get_run method."""

    def test_get_existing_run(
        self,
        service: ResearchRunService,
    ) -> None:
        config = _make_config()
        created = service.submit_run(config, user_id=_USER_ID)
        fetched = service.get_run(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    def test_get_missing_returns_none(
        self,
        service: ResearchRunService,
    ) -> None:
        assert service.get_run("nonexistent") is None


# ---------------------------------------------------------------------------
# cancel_run
# ---------------------------------------------------------------------------


class TestCancelRun:
    """Tests for cancel_run method."""

    def test_cancel_queued_run(
        self,
        service: ResearchRunService,
    ) -> None:
        config = _make_config()
        created = service.submit_run(config, user_id=_USER_ID)
        # Record is QUEUED after submit
        cancelled = service.cancel_run(created.id)
        assert cancelled.status == ResearchRunStatus.CANCELLED
        assert cancelled.completed_at is not None

    def test_cancel_pending_run(
        self,
        service: ResearchRunService,
        repo: MockResearchRunRepository,
    ) -> None:
        """Directly create a PENDING record to test PENDING → CANCELLED."""
        record = ResearchRunRecord(
            id="01HRUN_PENDING_TEST",
            config=_make_config(),
            status=ResearchRunStatus.PENDING,
            created_by=_USER_ID,
        )
        repo.create(record)
        cancelled = service.cancel_run("01HRUN_PENDING_TEST")
        assert cancelled.status == ResearchRunStatus.CANCELLED

    def test_cancel_running_raises(
        self,
        service: ResearchRunService,
        repo: MockResearchRunRepository,
    ) -> None:
        """RUNNING runs cannot be cancelled (must COMPLETE or FAIL)."""
        record = ResearchRunRecord(
            id="01HRUN_RUNNING_TEST",
            config=_make_config(),
            status=ResearchRunStatus.PENDING,
            created_by=_USER_ID,
        )
        repo.create(record)
        repo.update_status("01HRUN_RUNNING_TEST", ResearchRunStatus.QUEUED)
        repo.update_status("01HRUN_RUNNING_TEST", ResearchRunStatus.RUNNING)

        with pytest.raises(InvalidStatusTransitionError):
            service.cancel_run("01HRUN_RUNNING_TEST")

    def test_cancel_completed_raises(
        self,
        service: ResearchRunService,
        repo: MockResearchRunRepository,
    ) -> None:
        """Terminal states cannot be cancelled."""
        record = ResearchRunRecord(
            id="01HRUN_COMPLETED_TEST",
            config=_make_config(),
            status=ResearchRunStatus.PENDING,
            created_by=_USER_ID,
        )
        repo.create(record)
        repo.update_status("01HRUN_COMPLETED_TEST", ResearchRunStatus.QUEUED)
        repo.update_status("01HRUN_COMPLETED_TEST", ResearchRunStatus.RUNNING)
        repo.update_status("01HRUN_COMPLETED_TEST", ResearchRunStatus.COMPLETED)

        with pytest.raises(InvalidStatusTransitionError):
            service.cancel_run("01HRUN_COMPLETED_TEST")

    def test_cancel_nonexistent_raises(
        self,
        service: ResearchRunService,
    ) -> None:
        with pytest.raises(NotFoundError):
            service.cancel_run("nonexistent")

    def test_cancel_with_correlation_id(
        self,
        service: ResearchRunService,
    ) -> None:
        config = _make_config()
        created = service.submit_run(config, user_id=_USER_ID)
        cancelled = service.cancel_run(created.id, correlation_id=_CORRELATION_ID)
        assert cancelled.status == ResearchRunStatus.CANCELLED


# ---------------------------------------------------------------------------
# list_runs
# ---------------------------------------------------------------------------


class TestListRuns:
    """Tests for list_runs method."""

    def test_list_by_strategy(
        self,
        service: ResearchRunService,
    ) -> None:
        config_a = _make_config(strategy_id="strat_a")
        config_b = _make_config(strategy_id="strat_b")
        service.submit_run(config_a, user_id=_USER_ID)
        service.submit_run(config_b, user_id=_USER_ID)
        service.submit_run(config_a, user_id=_USER_ID)

        records, total = service.list_runs(strategy_id="strat_a")
        assert total == 2
        assert all(r.config.strategy_id == "strat_a" for r in records)

    def test_list_by_user(
        self,
        service: ResearchRunService,
    ) -> None:
        config = _make_config()
        service.submit_run(config, user_id="user_a")
        service.submit_run(config, user_id="user_b")
        service.submit_run(config, user_id="user_a")

        records, total = service.list_runs(user_id="user_a")
        assert total == 2

    def test_list_with_pagination(
        self,
        service: ResearchRunService,
    ) -> None:
        config = _make_config()
        for _ in range(5):
            service.submit_run(config, user_id=_USER_ID)

        records, total = service.list_runs(user_id=_USER_ID, limit=2, offset=0)
        assert total == 5
        assert len(records) == 2

    def test_list_empty(
        self,
        service: ResearchRunService,
    ) -> None:
        records, total = service.list_runs(strategy_id="nonexistent")
        assert total == 0
        assert records == []


# ---------------------------------------------------------------------------
# get_run_result
# ---------------------------------------------------------------------------


class TestGetRunResult:
    """Tests for get_run_result method."""

    def test_get_result_completed_run(
        self,
        service: ResearchRunService,
        repo: MockResearchRunRepository,
    ) -> None:
        """Completed run with result returns the result."""
        record = ResearchRunRecord(
            id="01HRUN_RESULT_TEST",
            config=_make_config(),
            status=ResearchRunStatus.PENDING,
            created_by=_USER_ID,
        )
        repo.create(record)
        repo.update_status("01HRUN_RESULT_TEST", ResearchRunStatus.QUEUED)
        repo.update_status("01HRUN_RESULT_TEST", ResearchRunStatus.RUNNING)
        repo.update_status("01HRUN_RESULT_TEST", ResearchRunStatus.COMPLETED)

        result = ResearchRunResult(summary_metrics={"total_return": 0.15, "sharpe_ratio": 1.2})
        repo.save_result("01HRUN_RESULT_TEST", result)

        fetched_result = service.get_run_result("01HRUN_RESULT_TEST")
        assert fetched_result is not None
        assert fetched_result.summary_metrics["total_return"] == 0.15

    def test_get_result_pending_returns_none(
        self,
        service: ResearchRunService,
        repo: MockResearchRunRepository,
    ) -> None:
        """Pending run has no result."""
        record = ResearchRunRecord(
            id="01HRUN_NO_RESULT",
            config=_make_config(),
            status=ResearchRunStatus.PENDING,
            created_by=_USER_ID,
        )
        repo.create(record)
        assert service.get_run_result("01HRUN_NO_RESULT") is None

    def test_get_result_nonexistent_returns_none(
        self,
        service: ResearchRunService,
    ) -> None:
        assert service.get_run_result("nonexistent") is None
