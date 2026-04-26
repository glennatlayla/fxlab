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


# ---------------------------------------------------------------------------
# cancel_run_with_abort (POST /runs/{id}/cancel entry point)
# ---------------------------------------------------------------------------


class _FakeExecutorPool:
    """
    Test double for :class:`RunExecutorPool` exposing only the
    ``cancel_run`` coroutine the service actually awaits.

    Records every call so the tests can assert (a) the pool was
    consulted at all on a RUNNING cancel, and (b) was NOT consulted on
    a PENDING / QUEUED cancel (those skip the pool). Tunable via
    ``return_value`` so the race-condition branch can drive the
    pool-returned-False path.
    """

    def __init__(self, *, return_value: bool = True) -> None:
        self._return_value = return_value
        self.cancel_calls: list[str] = []

    async def cancel_run(self, run_id: str) -> bool:
        self.cancel_calls.append(run_id)
        return self._return_value


@pytest.fixture()
def fake_pool() -> _FakeExecutorPool:
    return _FakeExecutorPool()


@pytest.fixture()
def service_with_pool(
    repo: MockResearchRunRepository,
    fake_pool: _FakeExecutorPool,
) -> ResearchRunService:
    """Service wired with a fake executor pool for cancel-with-abort tests."""
    return ResearchRunService(repo=repo, executor_pool=fake_pool)  # type: ignore[arg-type]


class TestCancelRunWithAbort:
    """Tests for the new POST /runs/{id}/cancel entry point."""

    @pytest.mark.asyncio
    async def test_cancel_running_run_aborts_pool_and_marks_cancelled(
        self,
        service_with_pool: ResearchRunService,
        repo: MockResearchRunRepository,
        fake_pool: _FakeExecutorPool,
    ) -> None:
        """
        RUNNING -> CANCELLED: must call pool.cancel_run AND persist the
        terminal CANCELLED row with error_message='user_requested'.
        """
        record = ResearchRunRecord(
            id="01HRUNCANCELRUNNING000001",
            config=_make_config(),
            status=ResearchRunStatus.PENDING,
            created_by=_USER_ID,
        )
        repo.create(record)
        repo.update_status(record.id, ResearchRunStatus.QUEUED)
        repo.update_status(record.id, ResearchRunStatus.RUNNING)

        result = await service_with_pool.cancel_run_with_abort(record.id, requested_by=_USER_ID)

        assert result.cancelled is True
        assert result.previous_status == "running"
        assert result.current_status == "cancelled"
        assert result.reason == "user_requested"
        # Pool was actually consulted.
        assert fake_pool.cancel_calls == [record.id]
        # DB row landed terminal with the cancellation reason.
        persisted = repo.get_by_id(record.id)
        assert persisted is not None
        assert persisted.status == ResearchRunStatus.CANCELLED
        assert persisted.error_message == "user_requested"
        assert persisted.completed_at is not None

    @pytest.mark.asyncio
    async def test_cancel_pending_run_skips_pool_and_marks_cancelled(
        self,
        service_with_pool: ResearchRunService,
        repo: MockResearchRunRepository,
        fake_pool: _FakeExecutorPool,
    ) -> None:
        """
        PENDING runs never hit the pool because there is no in-flight
        task; the row goes straight to CANCELLED.
        """
        record = ResearchRunRecord(
            id="01HRUNCANCELPENDING000002",
            config=_make_config(),
            status=ResearchRunStatus.PENDING,
            created_by=_USER_ID,
        )
        repo.create(record)

        result = await service_with_pool.cancel_run_with_abort(record.id, requested_by=_USER_ID)
        assert result.cancelled is True
        assert result.previous_status == "pending"
        assert result.current_status == "cancelled"
        assert fake_pool.cancel_calls == []  # pool not consulted
        persisted = repo.get_by_id(record.id)
        assert persisted is not None
        assert persisted.status == ResearchRunStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_queued_run_skips_pool_and_marks_cancelled(
        self,
        service_with_pool: ResearchRunService,
        repo: MockResearchRunRepository,
        fake_pool: _FakeExecutorPool,
    ) -> None:
        """QUEUED runs follow the same path as PENDING."""
        record = ResearchRunRecord(
            id="01HRUNCANCELQUEUED0000003",
            config=_make_config(),
            status=ResearchRunStatus.PENDING,
            created_by=_USER_ID,
        )
        repo.create(record)
        repo.update_status(record.id, ResearchRunStatus.QUEUED)

        result = await service_with_pool.cancel_run_with_abort(record.id, requested_by=_USER_ID)
        assert result.cancelled is True
        assert result.previous_status == "queued"
        assert result.current_status == "cancelled"
        assert fake_pool.cancel_calls == []
        persisted = repo.get_by_id(record.id)
        assert persisted is not None
        assert persisted.status == ResearchRunStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_completed_run_is_no_op(
        self,
        service_with_pool: ResearchRunService,
        repo: MockResearchRunRepository,
        fake_pool: _FakeExecutorPool,
    ) -> None:
        """COMPLETED runs return cancelled=False with reason=terminal_state."""
        record = ResearchRunRecord(
            id="01HRUNCANCELCOMPLETED0004",
            config=_make_config(),
            status=ResearchRunStatus.PENDING,
            created_by=_USER_ID,
        )
        repo.create(record)
        repo.update_status(record.id, ResearchRunStatus.QUEUED)
        repo.update_status(record.id, ResearchRunStatus.RUNNING)
        repo.update_status(record.id, ResearchRunStatus.COMPLETED)

        result = await service_with_pool.cancel_run_with_abort(record.id, requested_by=_USER_ID)
        assert result.cancelled is False
        assert result.previous_status == "completed"
        assert result.current_status == "completed"
        assert result.reason == "terminal_state"
        # Pool was not consulted because we skipped to the no-op branch.
        assert fake_pool.cancel_calls == []
        # Row was not mutated by the no-op path.
        persisted = repo.get_by_id(record.id)
        assert persisted is not None
        assert persisted.status == ResearchRunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_cancel_unknown_run_raises_not_found(
        self,
        service_with_pool: ResearchRunService,
    ) -> None:
        with pytest.raises(NotFoundError):
            await service_with_pool.cancel_run_with_abort(
                "01HRUNNEVERCREATED000005", requested_by=_USER_ID
            )

    @pytest.mark.asyncio
    async def test_running_cancel_with_pool_race_marks_task_already_finished(
        self,
        repo: MockResearchRunRepository,
    ) -> None:
        """
        Pool reports no in-flight task (race: worker finished between
        the row read and the pool call). If the row is now terminal,
        surface that with cancelled=False / reason=task_already_finished
        and DO NOT mutate the row.

        Interleaves the worker-completes side-effect inside the pool's
        cancel_run call so the service's first read sees RUNNING but
        the post-pool re-read sees COMPLETED -- exactly the race the
        branch defends against.
        """

        class _RaceyPool:
            def __init__(self, repo_ref: MockResearchRunRepository, run_id: str) -> None:
                self._repo = repo_ref
                self._run_id = run_id
                self.cancel_calls: list[str] = []

            async def cancel_run(self, run_id: str) -> bool:
                self.cancel_calls.append(run_id)
                # Worker finished mid-cancel: drop the row into COMPLETED
                # before returning False so the service sees the race.
                self._repo.update_status(run_id, ResearchRunStatus.COMPLETED)
                return False

        record = ResearchRunRecord(
            id="01HRUNCANCELRACE00000006",
            config=_make_config(),
            status=ResearchRunStatus.PENDING,
            created_by=_USER_ID,
        )
        repo.create(record)
        repo.update_status(record.id, ResearchRunStatus.QUEUED)
        repo.update_status(record.id, ResearchRunStatus.RUNNING)

        pool = _RaceyPool(repo, record.id)
        service = ResearchRunService(repo=repo, executor_pool=pool)  # type: ignore[arg-type]

        result = await service.cancel_run_with_abort(record.id, requested_by=_USER_ID)
        assert result.cancelled is False
        assert result.reason == "task_already_finished"
        assert result.current_status == "completed"
        # Row reflects the racing worker's terminal write, not a cancel.
        persisted = repo.get_by_id(record.id)
        assert persisted is not None
        assert persisted.status == ResearchRunStatus.COMPLETED
        # Pool was consulted exactly once (the RUNNING branch).
        assert pool.cancel_calls == [record.id]

    @pytest.mark.asyncio
    async def test_running_cancel_without_pool_still_marks_cancelled(
        self,
        repo: MockResearchRunRepository,
    ) -> None:
        """
        When the pool is not wired (no executor_pool injected), a RUNNING
        cancel still persists the terminal row -- the contract layer's
        RUNNING -> CANCELLED transition makes this safe even though no
        task gets aborted. Operators see ``cancelled=True`` because the
        DB state matches the operator intent.
        """
        service = ResearchRunService(repo=repo)
        record = ResearchRunRecord(
            id="01HRUNCANCELNOPOOL0000007",
            config=_make_config(),
            status=ResearchRunStatus.PENDING,
            created_by=_USER_ID,
        )
        repo.create(record)
        repo.update_status(record.id, ResearchRunStatus.QUEUED)
        repo.update_status(record.id, ResearchRunStatus.RUNNING)

        result = await service.cancel_run_with_abort(record.id, requested_by=_USER_ID)
        assert result.cancelled is True
        assert result.previous_status == "running"
        assert result.current_status == "cancelled"
        persisted = repo.get_by_id(record.id)
        assert persisted is not None
        assert persisted.status == ResearchRunStatus.CANCELLED
