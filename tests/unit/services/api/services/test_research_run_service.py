"""
Unit tests for :class:`services.api.services.research_run_service.ResearchRunService`.

Scope:
    Verify the service-layer projection of run history into the wire-shape
    :class:`StrategyRunsPage` envelope used by the recent-runs section on
    the StrategyDetail page. Backed by :class:`MockResearchRunRepository`
    so the tests stay hermetic and fast.

The existing in-flight execution tests (synthetic backtest path,
deferred-pool dispatch, etc.) live outside this file — these tests
intentionally focus on the new ``list_runs_for_strategy`` method to
avoid colliding with the sibling tranche extending the service.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from libs.contracts.backtest import BacktestConfig, BacktestResult
from libs.contracts.mocks.mock_research_run_repository import (
    MockResearchRunRepository,
)
from libs.contracts.research_run import (
    ResearchRunConfig,
    ResearchRunRecord,
    ResearchRunResult,
    ResearchRunStatus,
    ResearchRunType,
)
from libs.contracts.run_results import StrategyRunsPage
from services.api.services.research_run_service import ResearchRunService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

REFERENCE_NOW = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def repo() -> MockResearchRunRepository:
    return MockResearchRunRepository()


@pytest.fixture()
def service(repo: MockResearchRunRepository) -> ResearchRunService:
    """
    Build the service against the in-memory mock repository.

    The optional executor / ir_loader / executor_pool wiring is
    deliberately omitted because the recent-runs path is read-only —
    no execution happens during these tests.
    """
    return ResearchRunService(repo=repo)


def _seed(
    repo: MockResearchRunRepository,
    *,
    run_id: str,
    strategy_id: str,
    status: ResearchRunStatus = ResearchRunStatus.QUEUED,
    created_offset_seconds: int = 0,
    result: ResearchRunResult | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> ResearchRunRecord:
    """
    Insert a record directly into the mock store with explicit timing.

    Bypasses :meth:`MockResearchRunRepository.create` for the COMPLETED /
    FAILED branches so we can pin the persisted ``status`` and ``result``
    without walking the full PENDING→QUEUED→RUNNING→COMPLETED transition
    chain in every test.

    Args:
        repo: The :class:`MockResearchRunRepository` instance.
        run_id: ULID for the run.
        strategy_id: ULID of the strategy this run belongs to.
        status: Lifecycle status to seed.
        created_offset_seconds: Seconds added to the reference time
            when stamping ``created_at``. Larger numbers = newer.
        result: Optional :class:`ResearchRunResult` to attach.
        started_at: Optional started_at stamp.
        completed_at: Optional completed_at stamp.

    Returns:
        The persisted :class:`ResearchRunRecord`.
    """
    created_at = REFERENCE_NOW + timedelta(seconds=created_offset_seconds)
    config = ResearchRunConfig(
        run_type=ResearchRunType.BACKTEST,
        strategy_id=strategy_id,
        symbols=["EURUSD"],
        initial_equity=Decimal("100000"),
    )
    record = ResearchRunRecord(
        id=run_id,
        config=config,
        status=status,
        result=result,
        created_by="01HTESTUSER0000000000000001",
        created_at=created_at,
        updated_at=created_at,
        started_at=started_at,
        completed_at=completed_at,
    )
    # Direct store mutation — the mock's create() rejects duplicates and
    # would otherwise force us through the transition chain. The lock is
    # reentrant; a single assignment is fine.
    with repo._lock:
        repo._store[run_id] = record
    return record


def _backtest_result(
    *,
    total_return_pct: Decimal,
    sharpe_ratio: Decimal,
    win_rate: Decimal,
    total_trades: int,
) -> ResearchRunResult:
    """
    Build a :class:`ResearchRunResult` carrying a populated backtest_result.

    Used by the COMPLETED-run tests to exercise the explicit-field
    projection path on the service.
    """
    config = BacktestConfig(
        strategy_id="01HSTRATEGY00000000000000001",
        symbols=["EURUSD"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 4, 1),
    )
    backtest = BacktestResult(
        config=config,
        total_return_pct=total_return_pct,
        max_drawdown_pct=Decimal("-2.5"),
        sharpe_ratio=sharpe_ratio,
        total_trades=total_trades,
        win_rate=win_rate,
        profit_factor=Decimal("1.8"),
        final_equity=Decimal("112500"),
    )
    return ResearchRunResult(
        backtest_result=backtest,
        summary_metrics={
            "total_return_pct": str(total_return_pct),
            "sharpe_ratio": str(sharpe_ratio),
            "win_rate": str(win_rate),
            "total_trades": total_trades,
        },
        completed_at=REFERENCE_NOW,
    )


# ---------------------------------------------------------------------------
# Tests: list_runs_for_strategy
# ---------------------------------------------------------------------------


class TestListRunsForStrategy:
    """
    Verifies the recent-runs projection that powers the StrategyDetail
    page's "Recent runs" table.
    """

    def test_returns_empty_envelope_when_strategy_has_no_runs(
        self,
        service: ResearchRunService,
    ) -> None:
        result = service.list_runs_for_strategy(
            "01HSTRAT0000000000000001",
            page=1,
            page_size=20,
        )
        assert isinstance(result, StrategyRunsPage)
        assert result.runs == []
        assert result.page == 1
        assert result.page_size == 20
        assert result.total_count == 0
        assert result.total_pages == 0

    def test_orders_runs_newest_first(
        self,
        service: ResearchRunService,
        repo: MockResearchRunRepository,
    ) -> None:
        strategy_id = "01HSTRAT0000000000000001"
        _seed(
            repo,
            run_id="01HRUN0000000000000000001",
            strategy_id=strategy_id,
            created_offset_seconds=0,
        )
        _seed(
            repo,
            run_id="01HRUN0000000000000000002",
            strategy_id=strategy_id,
            created_offset_seconds=10,
        )
        _seed(
            repo,
            run_id="01HRUN0000000000000000003",
            strategy_id=strategy_id,
            created_offset_seconds=20,
        )

        result = service.list_runs_for_strategy(strategy_id, page=1, page_size=20)
        assert [r.id for r in result.runs] == [
            "01HRUN0000000000000000003",
            "01HRUN0000000000000000002",
            "01HRUN0000000000000000001",
        ]
        assert result.total_count == 3
        assert result.total_pages == 1

    def test_filters_to_target_strategy_id(
        self,
        service: ResearchRunService,
        repo: MockResearchRunRepository,
    ) -> None:
        target = "01HSTRAT0000000000000001"
        other = "01HSTRAT0000000000000002"
        _seed(
            repo, run_id="01HRUN0000000000000000001", strategy_id=target, created_offset_seconds=0
        )
        _seed(
            repo, run_id="01HRUN0000000000000000002", strategy_id=other, created_offset_seconds=10
        )
        _seed(
            repo, run_id="01HRUN0000000000000000003", strategy_id=target, created_offset_seconds=20
        )

        result = service.list_runs_for_strategy(target, page=1, page_size=20)
        assert {r.id for r in result.runs} == {
            "01HRUN0000000000000000001",
            "01HRUN0000000000000000003",
        }

    def test_pagination_partitions_dataset_correctly(
        self,
        service: ResearchRunService,
        repo: MockResearchRunRepository,
    ) -> None:
        strategy_id = "01HSTRAT0000000000000001"
        for i in range(5):
            _seed(
                repo,
                run_id=f"01HRUN000000000000000000{i}",
                strategy_id=strategy_id,
                created_offset_seconds=i,
            )

        page_1 = service.list_runs_for_strategy(strategy_id, page=1, page_size=2)
        assert page_1.total_count == 5
        assert page_1.total_pages == 3
        assert len(page_1.runs) == 2

        page_3 = service.list_runs_for_strategy(strategy_id, page=3, page_size=2)
        assert page_3.page == 3
        assert len(page_3.runs) == 1

        # Out-of-range page returns empty rows but populated totals.
        page_4 = service.list_runs_for_strategy(strategy_id, page=4, page_size=2)
        assert page_4.runs == []
        assert page_4.total_count == 5
        assert page_4.total_pages == 3

    def test_completed_run_projects_explicit_backtest_fields(
        self,
        service: ResearchRunService,
        repo: MockResearchRunRepository,
    ) -> None:
        strategy_id = "01HSTRAT0000000000000001"
        result_body = _backtest_result(
            total_return_pct=Decimal("12.5"),
            sharpe_ratio=Decimal("1.45"),
            win_rate=Decimal("0.55"),
            total_trades=42,
        )
        _seed(
            repo,
            run_id="01HRUNCOMPLETED00000000001",
            strategy_id=strategy_id,
            status=ResearchRunStatus.COMPLETED,
            created_offset_seconds=0,
            result=result_body,
            started_at=REFERENCE_NOW,
            completed_at=REFERENCE_NOW + timedelta(minutes=5),
        )

        page = service.list_runs_for_strategy(strategy_id, page=1, page_size=20)
        assert len(page.runs) == 1
        row = page.runs[0]
        assert row.id == "01HRUNCOMPLETED00000000001"
        assert row.status == "completed"
        assert row.started_at == REFERENCE_NOW
        assert row.completed_at == REFERENCE_NOW + timedelta(minutes=5)
        assert row.summary_metrics.total_return_pct == Decimal("12.5")
        assert row.summary_metrics.sharpe_ratio == Decimal("1.45")
        assert row.summary_metrics.win_rate == Decimal("0.55")
        assert row.summary_metrics.trade_count == 42

    def test_run_without_result_yields_null_metrics_and_zero_trades(
        self,
        service: ResearchRunService,
        repo: MockResearchRunRepository,
    ) -> None:
        strategy_id = "01HSTRAT0000000000000001"
        _seed(repo, run_id="01HRUNQUEUED00000000000001", strategy_id=strategy_id)

        page = service.list_runs_for_strategy(strategy_id, page=1, page_size=20)
        assert len(page.runs) == 1
        row = page.runs[0]
        assert row.status == "queued"
        assert row.summary_metrics.total_return_pct is None
        assert row.summary_metrics.sharpe_ratio is None
        assert row.summary_metrics.win_rate is None
        assert row.summary_metrics.trade_count == 0
        assert row.started_at is None
        assert row.completed_at is None

    def test_failed_run_with_summary_metrics_only_falls_back_to_flat_map(
        self,
        service: ResearchRunService,
        repo: MockResearchRunRepository,
    ) -> None:
        """
        A run whose ``result`` carries summary_metrics but no backtest_result
        (e.g. walk-forward / Monte-Carlo / partial result) still surfaces
        the headline metrics on the row.
        """
        strategy_id = "01HSTRAT0000000000000001"
        result_body = ResearchRunResult(
            backtest_result=None,
            summary_metrics={
                "total_return_pct": "8.25",
                "sharpe_ratio": "0.95",
                "win_rate": "0.5",
                "total_trades": 18,
            },
            completed_at=REFERENCE_NOW,
        )
        _seed(
            repo,
            run_id="01HRUNFLATMAP00000000000001",
            strategy_id=strategy_id,
            status=ResearchRunStatus.COMPLETED,
            result=result_body,
            started_at=REFERENCE_NOW,
            completed_at=REFERENCE_NOW + timedelta(minutes=3),
        )

        page = service.list_runs_for_strategy(strategy_id, page=1, page_size=20)
        assert len(page.runs) == 1
        row = page.runs[0]
        assert row.summary_metrics.total_return_pct == Decimal("8.25")
        assert row.summary_metrics.sharpe_ratio == Decimal("0.95")
        assert row.summary_metrics.win_rate == Decimal("0.5")
        assert row.summary_metrics.trade_count == 18

    def test_returned_value_is_validated_strategy_runs_page(
        self,
        service: ResearchRunService,
        repo: MockResearchRunRepository,
    ) -> None:
        """
        Service must return a :class:`StrategyRunsPage` (not a dict) so
        the route layer can call ``.model_dump`` directly without a
        re-validation step.
        """
        strategy_id = "01HSTRAT0000000000000001"
        _seed(repo, run_id="01HRUN0000000000000000001", strategy_id=strategy_id)

        page = service.list_runs_for_strategy(strategy_id, page=1, page_size=20)
        assert isinstance(page, StrategyRunsPage)
        # ``model_dump`` is the route-layer serialisation step; ensuring
        # it succeeds confirms the projection produces a schema-valid
        # envelope without further coaxing.
        body = page.model_dump(mode="json")
        assert "runs" in body and "page" in body and "total_count" in body
