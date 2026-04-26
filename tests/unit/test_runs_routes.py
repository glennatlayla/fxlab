"""
Unit tests for POST /runs/from-ir (M2.C2) and the GET
/runs/{run_id}/results/* sub-resources introduced in M2.C3.

Scope:
    Verify the route handlers:
      * POST /runs/from-ir (M2.C2 — pre-existing tests below).
      * GET /runs/{run_id}/results/equity-curve (M2.C3).
      * GET /runs/{run_id}/results/blotter (M2.C3, paginated).
      * GET /runs/{run_id}/results/metrics (M2.C3).

We mock the ResearchRunService at the module-level DI hook so this
file is a true unit test of the route layer; the service layer has
its own tests.
"""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from libs.contracts.backtest import (
    BacktestConfig,
    BacktestResult,
    BacktestTrade,
)
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
from libs.contracts.run_results import (
    DEFAULT_BLOTTER_PAGE_SIZE,
    MAX_BLOTTER_PAGE_SIZE,
    EquityCurveResponse,
    RunMetrics,
    TradeBlotterPage,
)
from libs.strategy_ir.dataset_resolver import (
    InMemoryDatasetResolver,
    seed_default_datasets,
)
from services.api.routes import runs as runs_routes
from services.api.services.research_run_service import ResearchRunService

AUTH_HEADERS = {"Authorization": "Bearer TEST_TOKEN"}

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PRODUCTION_PLAN = (
    _REPO_ROOT
    / "Strategy Repo"
    / "fxlab_chan_next3_strategy_pack"
    / "FX_TurnOfMonth_USDSeasonality_D1.experiment_plan.json"
)


@pytest.fixture(autouse=True)
def _force_test_env() -> Iterator[None]:
    """TEST_TOKEN bypass requires ENVIRONMENT=test."""
    old = os.environ.get("ENVIRONMENT")
    os.environ["ENVIRONMENT"] = "test"
    yield
    if old is None:
        os.environ.pop("ENVIRONMENT", None)
    else:
        os.environ["ENVIRONMENT"] = old


@pytest.fixture
def production_plan() -> dict:
    """Parsed production experiment plan body, freshly copied per test."""
    body = json.loads(_PRODUCTION_PLAN.read_text(encoding="utf-8"))
    return copy.deepcopy(body)


@pytest.fixture
def mock_repo() -> MockResearchRunRepository:
    return MockResearchRunRepository()


@pytest.fixture
def real_service(mock_repo: MockResearchRunRepository) -> ResearchRunService:
    """Real ResearchRunService against the in-memory repo (no engine I/O)."""
    return ResearchRunService(repo=mock_repo)


@pytest.fixture
def seeded_resolver() -> InMemoryDatasetResolver:
    """Resolver pre-seeded with every production dataset_ref."""
    resolver = InMemoryDatasetResolver()
    seed_default_datasets(resolver)
    return resolver


@pytest.fixture
def client(
    real_service: ResearchRunService,
    seeded_resolver: InMemoryDatasetResolver,
) -> Iterator[TestClient]:
    """Test client with both DI hooks populated."""
    runs_routes.set_research_run_service(real_service)
    runs_routes.set_dataset_resolver(seeded_resolver)

    from services.api.main import app

    yield TestClient(app, raise_server_exceptions=False)

    # Teardown: clear DI to prevent leakage into other test files.
    runs_routes.set_research_run_service(None)  # type: ignore[arg-type]
    runs_routes.set_dataset_resolver(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_from_ir_happy_path_returns_201_with_run_id(
    client: TestClient,
    production_plan: dict,
    mock_repo: MockResearchRunRepository,
) -> None:
    """Submitting a valid plan returns 201 with run_id and queues a record."""
    payload = {
        "strategy_id": "01HSTRAT0000000000000000XX",
        "experiment_plan": production_plan,
    }
    resp = client.post("/runs/from-ir", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 201, resp.text

    body = resp.json()
    assert "run_id" in body
    assert body["run_id"] == body["id"]
    assert body["status"] == ResearchRunStatus.QUEUED.value
    assert body["config"]["strategy_id"] == "01HSTRAT0000000000000000XX"

    # Repository got exactly one record.
    assert mock_repo.count() == 1


def test_from_ir_routes_walk_forward_when_enabled(
    client: TestClient,
    production_plan: dict,
    mock_repo: MockResearchRunRepository,
) -> None:
    """walk_forward.enabled=True must produce a WALK_FORWARD run type."""
    # Production plans already have walk_forward.enabled=True.
    assert production_plan["validation"]["walk_forward"]["enabled"] is True
    payload = {
        "strategy_id": "01HSTRAT0000000000000000WF",
        "experiment_plan": production_plan,
    }
    resp = client.post("/runs/from-ir", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 201
    assert resp.json()["config"]["run_type"] == "walk_forward"


def test_from_ir_routes_backtest_when_walk_forward_disabled(
    client: TestClient,
    production_plan: dict,
) -> None:
    """walk_forward.enabled=False routes to BACKTEST."""
    production_plan["validation"]["walk_forward"]["enabled"] = False
    payload = {
        "strategy_id": "01HSTRAT0000000000000000BT",
        "experiment_plan": production_plan,
    }
    resp = client.post("/runs/from-ir", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 201
    assert resp.json()["config"]["run_type"] == "backtest"


def test_from_ir_propagates_dataset_metadata(
    client: TestClient,
    production_plan: dict,
) -> None:
    """The submitted ResearchRunConfig metadata must reference the plan."""
    payload = {
        "strategy_id": "01HSTRAT0000000000000000MD",
        "experiment_plan": production_plan,
    }
    resp = client.post("/runs/from-ir", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 201
    metadata = resp.json()["config"]["metadata"]
    assert metadata["source"] == "experiment_plan"
    assert (
        metadata["experiment_plan_dataset_ref"] == production_plan["data_selection"]["dataset_ref"]
    )
    assert (
        metadata["experiment_plan_strategy_name"]
        == production_plan["strategy_ref"]["strategy_name"]
    )


def test_from_ir_uses_resolved_dataset_symbols(
    client: TestClient,
    production_plan: dict,
    seeded_resolver: InMemoryDatasetResolver,
) -> None:
    """Symbols on the queued run must come from the resolver, not the plan."""
    payload = {
        "strategy_id": "01HSTRAT0000000000000000SY",
        "experiment_plan": production_plan,
    }
    resp = client.post("/runs/from-ir", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 201
    expected_symbols = seeded_resolver.resolve(
        production_plan["data_selection"]["dataset_ref"]
    ).symbols
    assert resp.json()["config"]["symbols"] == expected_symbols


# ---------------------------------------------------------------------------
# Negative paths — dataset
# ---------------------------------------------------------------------------


def test_from_ir_returns_404_when_dataset_ref_unknown(
    client: TestClient,
    production_plan: dict,
) -> None:
    """Unregistered dataset_ref surfaces as 404 with the offending ref."""
    production_plan["data_selection"]["dataset_ref"] = "fx-bogus-dataset-v999"
    payload = {
        "strategy_id": "01HSTRAT0000000000000000NX",
        "experiment_plan": production_plan,
    }
    resp = client.post("/runs/from-ir", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 404
    assert "fx-bogus-dataset-v999" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Negative paths — payload validation
# ---------------------------------------------------------------------------


def test_from_ir_returns_422_when_strategy_id_missing(
    client: TestClient,
    production_plan: dict,
) -> None:
    """Missing strategy_id is a Pydantic validation error -> 422."""
    payload = {"experiment_plan": production_plan}
    resp = client.post("/runs/from-ir", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 422


def test_from_ir_returns_422_when_experiment_plan_malformed(
    client: TestClient,
    production_plan: dict,
) -> None:
    """A malformed experiment_plan body is rejected with 422."""
    production_plan["artifact_type"] = "wrong_artifact_type"
    payload = {
        "strategy_id": "01HSTRAT00000000000000FAIL",
        "experiment_plan": production_plan,
    }
    resp = client.post("/runs/from-ir", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 422


def test_from_ir_returns_422_when_extra_top_level_field(
    client: TestClient,
    production_plan: dict,
) -> None:
    """The request body itself is extra='forbid'."""
    payload = {
        "strategy_id": "01HSTRAT00000000000000FAIL",
        "experiment_plan": production_plan,
        "rogue_field": "noise",
    }
    resp = client.post("/runs/from-ir", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_from_ir_requires_authentication(
    client: TestClient,
    production_plan: dict,
) -> None:
    """No Authorization header -> 401."""
    payload = {
        "strategy_id": "01HSTRAT00000000000000AUTH",
        "experiment_plan": production_plan,
    }
    resp = client.post("/runs/from-ir", json=payload)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DI fail-closed
# ---------------------------------------------------------------------------


def test_from_ir_returns_503_when_service_unconfigured(
    production_plan: dict,
    seeded_resolver: InMemoryDatasetResolver,
) -> None:
    """Without a registered service, the route must fail-closed with 503."""
    runs_routes.set_research_run_service(None)  # type: ignore[arg-type]
    runs_routes.set_dataset_resolver(seeded_resolver)
    try:
        from services.api.main import app

        client = TestClient(app, raise_server_exceptions=False)
        payload = {
            "strategy_id": "01HSTRAT0000000000000503SV",
            "experiment_plan": production_plan,
        }
        resp = client.post("/runs/from-ir", json=payload, headers=AUTH_HEADERS)
        assert resp.status_code == 503
    finally:
        runs_routes.set_research_run_service(None)  # type: ignore[arg-type]
        runs_routes.set_dataset_resolver(None)  # type: ignore[arg-type]


def test_from_ir_returns_503_when_resolver_unconfigured(
    real_service: ResearchRunService,
    production_plan: dict,
) -> None:
    """Without a registered resolver, the route must fail-closed with 503."""
    runs_routes.set_research_run_service(real_service)
    runs_routes.set_dataset_resolver(None)  # type: ignore[arg-type]
    try:
        from services.api.main import app

        client = TestClient(app, raise_server_exceptions=False)
        payload = {
            "strategy_id": "01HSTRAT0000000000000503DR",
            "experiment_plan": production_plan,
        }
        resp = client.post("/runs/from-ir", json=payload, headers=AUTH_HEADERS)
        assert resp.status_code == 503
    finally:
        runs_routes.set_research_run_service(None)  # type: ignore[arg-type]
        runs_routes.set_dataset_resolver(None)  # type: ignore[arg-type]


# ===========================================================================
# M2.C3 — GET /runs/{run_id}/results/{equity-curve,blotter,metrics}
# ===========================================================================
#
# These tests use the same MockResearchRunRepository + real
# ResearchRunService stack as the M2.C2 tests above. We seed a
# COMPLETED record with a synthetic BacktestResult so the projections
# the service performs in get_equity_curve / get_blotter / get_metrics
# have something concrete to walk over.

# Fixed run ULID so tests can hit the same record across requests.
_COMPLETED_RUN_ID = "01HRESDNE00000000000000001"
_PENDING_RUN_ID = "01HRESPND00000000000000002"


def _build_backtest_result(*, trade_count: int = 0) -> BacktestResult:
    """
    Build a deterministic BacktestResult with ``trade_count`` trades.

    Trades are emitted in deliberately reverse-chronological order so
    the service's ``(timestamp, trade_id)`` sort actually gets exercised
    rather than being a no-op against pre-sorted input.
    """
    base_ts = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    trades = [
        BacktestTrade(
            # Use descending timestamps so the service has to re-sort.
            timestamp=base_ts + timedelta(minutes=trade_count - 1 - i),
            symbol="EURUSD",
            side="buy" if i % 2 == 0 else "sell",
            quantity=Decimal("100"),
            price=Decimal("1.1000") + Decimal(i) / Decimal("10000"),
            commission=Decimal("0.50"),
            slippage=Decimal("0.10"),
        )
        for i in range(trade_count)
    ]
    config = BacktestConfig(
        strategy_id="01HSTRATBACKTEST0000000001",
        symbols=["EURUSD"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
    )
    return BacktestResult(
        config=config,
        total_return_pct=Decimal("12.34"),
        annualized_return_pct=Decimal("45.67"),
        max_drawdown_pct=Decimal("-3.21"),
        sharpe_ratio=Decimal("1.42"),
        total_trades=trade_count,
        win_rate=Decimal("0.55"),
        profit_factor=Decimal("1.80"),
        final_equity=Decimal("112340"),
        trades=trades,
        bars_processed=500,
    )


def _seed_completed_record(
    repo: MockResearchRunRepository,
    *,
    run_id: str = _COMPLETED_RUN_ID,
    trade_count: int = 0,
) -> ResearchRunRecord:
    """Insert a COMPLETED ResearchRunRecord directly into the mock repo."""
    config = ResearchRunConfig(
        run_type=ResearchRunType.BACKTEST,
        strategy_id="01HSTRATBACKTEST0000000001",
        symbols=["EURUSD"],
        initial_equity=Decimal("100000"),
    )
    result = ResearchRunResult(
        backtest_result=_build_backtest_result(trade_count=trade_count),
        summary_metrics={"sharpe_ratio": "1.42", "max_dd": "-3.21"},
    )
    record = ResearchRunRecord(
        id=run_id,
        config=config,
        status=ResearchRunStatus.COMPLETED,
        result=result,
        created_by="01HUSER0000000000000000001",
        completed_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
    )
    # Bypass create() to avoid the PENDING -> COMPLETED transition guard.
    with repo._lock:  # noqa: SLF001 — test seeding only
        repo._store[record.id] = record  # noqa: SLF001 — test seeding only
    return record


def _seed_pending_record(
    repo: MockResearchRunRepository,
    *,
    run_id: str = _PENDING_RUN_ID,
) -> ResearchRunRecord:
    """Insert a PENDING (not yet completed) record into the mock repo."""
    config = ResearchRunConfig(
        run_type=ResearchRunType.BACKTEST,
        strategy_id="01HSTRATBACKTEST0000000001",
        symbols=["EURUSD"],
    )
    record = ResearchRunRecord(
        id=run_id,
        config=config,
        status=ResearchRunStatus.PENDING,
        created_by="01HUSER0000000000000000001",
    )
    with repo._lock:  # noqa: SLF001 — test seeding only
        repo._store[record.id] = record  # noqa: SLF001 — test seeding only
    return record


# ---------------------------------------------------------------------------
# Equity curve
# ---------------------------------------------------------------------------


def test_equity_curve_invalid_ulid_returns_422(client: TestClient) -> None:
    """Bad ULID format -> 422 before service is touched."""
    resp = client.get("/runs/not-a-ulid/results/equity-curve", headers=AUTH_HEADERS)
    assert resp.status_code == 422


def test_equity_curve_missing_run_returns_404(client: TestClient) -> None:
    """Unknown run_id -> 404 with detail mentioning the id."""
    missing = "01HRESMSNG0000000000000099"
    resp = client.get(f"/runs/{missing}/results/equity-curve", headers=AUTH_HEADERS)
    assert resp.status_code == 404
    assert missing in resp.json()["detail"]


def test_equity_curve_pending_run_returns_409(
    client: TestClient,
    mock_repo: MockResearchRunRepository,
) -> None:
    """A non-COMPLETED run -> 409 with current status in detail."""
    _seed_pending_record(mock_repo)
    resp = client.get(f"/runs/{_PENDING_RUN_ID}/results/equity-curve", headers=AUTH_HEADERS)
    assert resp.status_code == 409
    assert "pending" in resp.json()["detail"]


def test_equity_curve_completed_run_returns_schema_locked_body(
    client: TestClient,
    mock_repo: MockResearchRunRepository,
) -> None:
    """Happy path -> 200 with body validating against EquityCurveResponse."""
    _seed_completed_record(mock_repo, trade_count=3)
    resp = client.get(f"/runs/{_COMPLETED_RUN_ID}/results/equity-curve", headers=AUTH_HEADERS)
    assert resp.status_code == 200, resp.text

    # Schema-locked: round-trip through the Pydantic model. Because the
    # model is extra='forbid' + frozen, any drift would surface here.
    body = EquityCurveResponse.model_validate(resp.json())
    assert body.run_id == _COMPLETED_RUN_ID
    # Empty equity curve is acceptable for the synthetic fixture; the
    # contract guarantees the field exists and matches point_count.
    assert body.point_count == len(body.points)


def test_equity_curve_requires_authentication(client: TestClient) -> None:
    """Missing Authorization header -> 401."""
    resp = client.get(f"/runs/{_COMPLETED_RUN_ID}/results/equity-curve")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Blotter — basic contract
# ---------------------------------------------------------------------------


def test_blotter_invalid_ulid_returns_422(client: TestClient) -> None:
    resp = client.get("/runs/not-a-ulid/results/blotter", headers=AUTH_HEADERS)
    assert resp.status_code == 422


def test_blotter_missing_run_returns_404(client: TestClient) -> None:
    missing = "01HRESMSNG0000000000000088"
    resp = client.get(f"/runs/{missing}/results/blotter", headers=AUTH_HEADERS)
    assert resp.status_code == 404


def test_blotter_pending_run_returns_409(
    client: TestClient, mock_repo: MockResearchRunRepository
) -> None:
    _seed_pending_record(mock_repo)
    resp = client.get(f"/runs/{_PENDING_RUN_ID}/results/blotter", headers=AUTH_HEADERS)
    assert resp.status_code == 409


def test_blotter_default_page_size_is_100(
    client: TestClient,
    mock_repo: MockResearchRunRepository,
) -> None:
    """Omitting page_size -> default of 100 in the response body."""
    _seed_completed_record(mock_repo, trade_count=5)
    resp = client.get(f"/runs/{_COMPLETED_RUN_ID}/results/blotter", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    body = TradeBlotterPage.model_validate(resp.json())
    assert body.page_size == DEFAULT_BLOTTER_PAGE_SIZE
    assert body.page == 1
    assert body.total_count == 5
    assert len(body.trades) == 5


def test_blotter_rejects_page_size_above_cap(
    client: TestClient,
    mock_repo: MockResearchRunRepository,
) -> None:
    """page_size beyond MAX_BLOTTER_PAGE_SIZE -> 422."""
    _seed_completed_record(mock_repo, trade_count=10)
    resp = client.get(
        f"/runs/{_COMPLETED_RUN_ID}/results/blotter",
        params={"page_size": MAX_BLOTTER_PAGE_SIZE + 1},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 422


def test_blotter_rejects_page_zero(
    client: TestClient,
    mock_repo: MockResearchRunRepository,
) -> None:
    """page < 1 -> 422 from FastAPI's Query validator."""
    _seed_completed_record(mock_repo, trade_count=10)
    resp = client.get(
        f"/runs/{_COMPLETED_RUN_ID}/results/blotter",
        params={"page": 0},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 422


def test_blotter_trades_are_sorted_deterministically(
    client: TestClient,
    mock_repo: MockResearchRunRepository,
) -> None:
    """Same query -> same order, ascending by timestamp."""
    _seed_completed_record(mock_repo, trade_count=10)
    resp1 = client.get(f"/runs/{_COMPLETED_RUN_ID}/results/blotter", headers=AUTH_HEADERS)
    resp2 = client.get(f"/runs/{_COMPLETED_RUN_ID}/results/blotter", headers=AUTH_HEADERS)
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    body1 = TradeBlotterPage.model_validate(resp1.json())
    body2 = TradeBlotterPage.model_validate(resp2.json())
    assert [t.trade_id for t in body1.trades] == [t.trade_id for t in body2.trades]
    # Ascending timestamps.
    timestamps = [t.timestamp for t in body1.trades]
    assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# Blotter — 1000-trade pagination acceptance
# ---------------------------------------------------------------------------


def test_blotter_pagination_with_1000_trades(
    client: TestClient,
    mock_repo: MockResearchRunRepository,
) -> None:
    """
    Acceptance: synthetic 1000-trade blotter paginates correctly.

    * page=1, page_size=100  -> trades 1-100, total_count=1000, total_pages=10.
    * page=10, page_size=100 -> trades 901-1000.
    * page=11, page_size=100 -> empty trades, total_count still 1000.
    """
    _seed_completed_record(mock_repo, trade_count=1000)

    # Page 1
    resp = client.get(
        f"/runs/{_COMPLETED_RUN_ID}/results/blotter",
        params={"page": 1, "page_size": 100},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    page1 = TradeBlotterPage.model_validate(resp.json())
    assert page1.total_count == 1000
    assert page1.total_pages == 10
    assert page1.page == 1
    assert page1.page_size == 100
    assert len(page1.trades) == 100

    # Page 10 (last populated)
    resp = client.get(
        f"/runs/{_COMPLETED_RUN_ID}/results/blotter",
        params={"page": 10, "page_size": 100},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    page10 = TradeBlotterPage.model_validate(resp.json())
    assert page10.total_count == 1000
    assert page10.total_pages == 10
    assert page10.page == 10
    assert len(page10.trades) == 100

    # Page 1 and page 10 must not overlap.
    page1_ids = {t.trade_id for t in page1.trades}
    page10_ids = {t.trade_id for t in page10.trades}
    assert page1_ids.isdisjoint(page10_ids)

    # Page 11 — beyond last populated page -> empty trades, totals unchanged.
    resp = client.get(
        f"/runs/{_COMPLETED_RUN_ID}/results/blotter",
        params={"page": 11, "page_size": 100},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    page11 = TradeBlotterPage.model_validate(resp.json())
    assert page11.total_count == 1000
    assert page11.total_pages == 10
    assert page11.page == 11
    assert page11.trades == []


def test_blotter_pagination_is_stable_across_calls(
    client: TestClient,
    mock_repo: MockResearchRunRepository,
) -> None:
    """Same query, different requests -> identical trades on the page."""
    _seed_completed_record(mock_repo, trade_count=1000)
    resp_a = client.get(
        f"/runs/{_COMPLETED_RUN_ID}/results/blotter",
        params={"page": 5, "page_size": 100},
        headers=AUTH_HEADERS,
    )
    resp_b = client.get(
        f"/runs/{_COMPLETED_RUN_ID}/results/blotter",
        params={"page": 5, "page_size": 100},
        headers=AUTH_HEADERS,
    )
    assert resp_a.json() == resp_b.json()


def test_blotter_requires_authentication(client: TestClient) -> None:
    resp = client.get(f"/runs/{_COMPLETED_RUN_ID}/results/blotter")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_metrics_invalid_ulid_returns_422(client: TestClient) -> None:
    resp = client.get("/runs/not-a-ulid/results/metrics", headers=AUTH_HEADERS)
    assert resp.status_code == 422


def test_metrics_missing_run_returns_404(client: TestClient) -> None:
    missing = "01HRESMSNG0000000000000077"
    resp = client.get(f"/runs/{missing}/results/metrics", headers=AUTH_HEADERS)
    assert resp.status_code == 404


def test_metrics_pending_run_returns_409(
    client: TestClient, mock_repo: MockResearchRunRepository
) -> None:
    _seed_pending_record(mock_repo)
    resp = client.get(f"/runs/{_PENDING_RUN_ID}/results/metrics", headers=AUTH_HEADERS)
    assert resp.status_code == 409


def test_metrics_completed_run_returns_schema_locked_body(
    client: TestClient,
    mock_repo: MockResearchRunRepository,
) -> None:
    """Happy path -> 200 with body validating against RunMetrics."""
    _seed_completed_record(mock_repo, trade_count=42)
    resp = client.get(f"/runs/{_COMPLETED_RUN_ID}/results/metrics", headers=AUTH_HEADERS)
    assert resp.status_code == 200, resp.text
    body = RunMetrics.model_validate(resp.json())
    assert body.run_id == _COMPLETED_RUN_ID
    assert body.total_trades == 42
    assert body.sharpe_ratio == Decimal("1.42")
    assert body.bars_processed == 500
    # summary_metrics passed through verbatim.
    assert body.summary_metrics["sharpe_ratio"] == "1.42"


def test_metrics_requires_authentication(client: TestClient) -> None:
    resp = client.get(f"/runs/{_COMPLETED_RUN_ID}/results/metrics")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DI fail-closed (M2.C3)
# ---------------------------------------------------------------------------


def test_results_endpoints_return_503_when_service_unconfigured() -> None:
    """Without a registered service, all three M2.C3 endpoints fail-closed."""
    runs_routes.set_research_run_service(None)  # type: ignore[arg-type]
    runs_routes.set_dataset_resolver(None)  # type: ignore[arg-type]
    try:
        from services.api.main import app

        client = TestClient(app, raise_server_exceptions=False)
        for path in (
            f"/runs/{_COMPLETED_RUN_ID}/results/equity-curve",
            f"/runs/{_COMPLETED_RUN_ID}/results/blotter",
            f"/runs/{_COMPLETED_RUN_ID}/results/metrics",
        ):
            resp = client.get(path, headers=AUTH_HEADERS)
            assert resp.status_code == 503, f"{path} did not fail-closed: {resp.status_code}"
    finally:
        runs_routes.set_research_run_service(None)  # type: ignore[arg-type]
        runs_routes.set_dataset_resolver(None)  # type: ignore[arg-type]


# ===========================================================================
# POST /runs/{run_id}/cancel — operator-driven cancellation
# ===========================================================================
#
# These tests exercise the new route end-to-end against the real
# ResearchRunService stack and the in-memory mock repository. The
# service is wired without an executor pool (the pool integration is
# tested in test_research_run_service.py and test_run_executor_pool.py)
# so the route tests focus purely on the HTTP contract: status codes,
# response shape, auth, scope enforcement.


_CANCEL_RUN_ID_RUNNING = "01HRNCANCE0000000000RNG001"
_CANCEL_RUN_ID_TERMINAL = "01HRNCANCE0000000000TRM002"
_CANCEL_RUN_ID_PENDING = "01HRNCANCE0000000000PND003"


def _seed_record_with_status(
    repo: MockResearchRunRepository,
    *,
    run_id: str,
    status: ResearchRunStatus,
) -> ResearchRunRecord:
    """Insert a record directly with a specific status for the cancel tests."""
    config = ResearchRunConfig(
        run_type=ResearchRunType.BACKTEST,
        strategy_id="01HSTRATCANCE000000000001",
        symbols=["EURUSD"],
        initial_equity=Decimal("100000"),
    )
    record = ResearchRunRecord(
        id=run_id,
        config=config,
        status=status,
        created_by="01HUSERCANCE0000000000001",
    )
    with repo._lock:  # noqa: SLF001 -- test seeding only
        repo._store[run_id] = record  # noqa: SLF001 -- test seeding only
    return record


def test_cancel_invalid_ulid_returns_422(client: TestClient) -> None:
    resp = client.post("/runs/not-a-ulid/cancel", headers=AUTH_HEADERS)
    assert resp.status_code == 422


def test_cancel_missing_run_returns_404(client: TestClient) -> None:
    missing = "01HRNCANCE0000000000NFND09"
    resp = client.post(f"/runs/{missing}/cancel", headers=AUTH_HEADERS)
    assert resp.status_code == 404
    assert missing in resp.json()["detail"]


def test_cancel_pending_run_returns_200_and_marks_cancelled(
    client: TestClient,
    mock_repo: MockResearchRunRepository,
) -> None:
    """PENDING -> CANCELLED via the route returns RunCancelResult body."""
    _seed_record_with_status(
        mock_repo, run_id=_CANCEL_RUN_ID_PENDING, status=ResearchRunStatus.PENDING
    )

    resp = client.post(f"/runs/{_CANCEL_RUN_ID_PENDING}/cancel", headers=AUTH_HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"] == _CANCEL_RUN_ID_PENDING
    assert body["previous_status"] == "pending"
    assert body["current_status"] == "cancelled"
    assert body["cancelled"] is True
    assert body["reason"] == "user_requested"

    persisted = mock_repo.get_by_id(_CANCEL_RUN_ID_PENDING)
    assert persisted is not None
    assert persisted.status == ResearchRunStatus.CANCELLED


def test_cancel_terminal_run_returns_409_with_reason(
    client: TestClient,
    mock_repo: MockResearchRunRepository,
) -> None:
    """COMPLETED runs surface a 409 with the no-op reason in the body."""
    _seed_record_with_status(
        mock_repo, run_id=_CANCEL_RUN_ID_TERMINAL, status=ResearchRunStatus.COMPLETED
    )

    resp = client.post(f"/runs/{_CANCEL_RUN_ID_TERMINAL}/cancel", headers=AUTH_HEADERS)
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert "terminal_state" in detail or "completed" in detail


def test_cancel_requires_authentication(client: TestClient) -> None:
    resp = client.post(f"/runs/{_CANCEL_RUN_ID_PENDING}/cancel")
    assert resp.status_code == 401


def test_cancel_requires_runs_write_scope(
    client: TestClient,
    mock_repo: MockResearchRunRepository,
) -> None:
    """A user lacking ``runs:write`` scope is rejected with 403."""
    from services.api.auth import AuthenticatedUser, get_current_user
    from services.api.main import app

    _seed_record_with_status(
        mock_repo, run_id=_CANCEL_RUN_ID_PENDING, status=ResearchRunStatus.PENDING
    )

    viewer = AuthenticatedUser(
        user_id="01HVEWERCANCE0000000000001",
        email="viewer@fxlab.test",
        role="viewer",
        scopes=[],
    )

    async def _viewer_dep() -> AuthenticatedUser:
        return viewer

    app.dependency_overrides[get_current_user] = _viewer_dep
    try:
        resp = client.post(
            f"/runs/{_CANCEL_RUN_ID_PENDING}/cancel",
            headers=AUTH_HEADERS,
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 403


def test_cancel_returns_503_when_service_unconfigured() -> None:
    """Without a registered service, the cancel route fails-closed with 503."""
    runs_routes.set_research_run_service(None)  # type: ignore[arg-type]
    runs_routes.set_dataset_resolver(None)  # type: ignore[arg-type]
    try:
        from services.api.main import app

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(f"/runs/{_CANCEL_RUN_ID_PENDING}/cancel", headers=AUTH_HEADERS)
        assert resp.status_code == 503
    finally:
        runs_routes.set_research_run_service(None)  # type: ignore[arg-type]
        runs_routes.set_dataset_resolver(None)  # type: ignore[arg-type]
