"""
Unit tests for M7: Chart + LTTB + Queue Backend APIs.

Coverage:
- libs/utils/lttb.py            — LTTB downsampling algorithm
- MockChartRepository           — behavioural parity with ChartRepositoryInterface
- MockQueueRepository           — behavioural parity with QueueRepositoryInterface
- GET /runs/{run_id}/charts     — composite chart payload endpoint
- GET /runs/{run_id}/charts/equity   — equity curve endpoint (LTTB applied)
- GET /runs/{run_id}/charts/drawdown — drawdown curve endpoint
- GET /queues                   — queue list endpoint
- GET /queues/{queue_class}/contention — per-class contention endpoint

All tests MUST FAIL on stub implementations and MUST PASS after the GREEN step.

LL-007 note: Use model_construct() for any Pydantic models with Optional[str] fields.
LL-008 note: Route handlers must use JSONResponse + model_dump() (no response_model=).
LL-010 note: Use explicit int() casts for numeric query params in route handlers.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from libs.contracts.chart import (
    DrawdownPoint,
    EquityCurvePoint,
    SamplingMethod,
)
from libs.contracts.errors import NotFoundError
from libs.contracts.mocks.mock_chart_repository import MockChartRepository
from libs.contracts.mocks.mock_queue_repository import MockQueueRepository
from libs.contracts.queue import QueueContentionResponse, QueueSnapshotResponse
from libs.utils.lttb import lttb_downsample

# ---------------------------------------------------------------------------
# Shared test data constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 27, 12, 0, 0, tzinfo=timezone.utc)
_RUN_ULID_1 = "01HQRUN0AAAAAAAAAAAAAAAA01"
_RUN_ULID_2 = "01HQRUN0BBBBBBBBBBBBBBBB02"
_RUN_ULID_MISSING = "01HQRUN0XXXXXXXXXXXXXXXX99"

# LTTB threshold used by the route layer (from Phase 3 spec §M24)
_EQUITY_LTTB_THRESHOLD = 2_000
_TRADES_TRUNCATE_THRESHOLD = 5_000


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _make_equity_points(n: int, start_value: float = 10_000.0) -> list[EquityCurvePoint]:
    """Build n ascending equity curve points starting from start_value."""
    return [
        EquityCurvePoint(
            timestamp=datetime(2026, 1, 1, i % 24, i % 60, 0, tzinfo=timezone.utc),
            equity=start_value + float(i) * 10.0,
        )
        for i in range(n)
    ]


def _make_drawdown_points(n: int) -> list[DrawdownPoint]:
    """Build n drawdown points all at 0.0 (no drawdown)."""
    return [
        DrawdownPoint(
            timestamp=datetime(2026, 1, 1, i % 24, i % 60, 0, tzinfo=timezone.utc),
            drawdown=0.0,
        )
        for i in range(n)
    ]


def _make_lttb_numeric(n: int) -> list[tuple[float, float]]:
    """Build n numeric (x, y) pairs for LTTB testing."""
    return [(float(i), float(i * i)) for i in range(n)]


# ---------------------------------------------------------------------------
# LTTB Algorithm Tests
# ---------------------------------------------------------------------------


class TestLttbAlgorithm:
    """
    Verify lttb_downsample against all three spec acceptance criteria:
    1. Output length ≤ threshold.
    2. First and last points always preserved.
    3. Peak-to-trough accuracy (max value in output ≥ max value in input).
    """

    def test_lttb_output_length_le_threshold(self) -> None:
        """
        GIVEN 10 000 data points
        WHEN lttb_downsample is called with threshold=500
        THEN output length is ≤ 500.
        """
        pts = _make_lttb_numeric(10_000)
        out = lttb_downsample(pts, threshold=500)
        assert len(out) <= 500

    def test_lttb_preserves_first_point(self) -> None:
        """
        GIVEN any input with > 2 points
        WHEN lttb_downsample is called
        THEN output[0] equals input[0].
        """
        pts = _make_lttb_numeric(5_000)
        out = lttb_downsample(pts, threshold=100)
        assert out[0] == pts[0]

    def test_lttb_preserves_last_point(self) -> None:
        """
        GIVEN any input with > 2 points
        WHEN lttb_downsample is called
        THEN output[-1] equals input[-1].
        """
        pts = _make_lttb_numeric(5_000)
        out = lttb_downsample(pts, threshold=100)
        assert out[-1] == pts[-1]

    def test_lttb_peak_to_trough_accuracy(self) -> None:
        """
        GIVEN a sinusoidal series with clear peaks and troughs (3 000 points)
        WHEN lttb_downsample is called with threshold=200
        THEN the max y-value in the output is ≥ 0.9 × max y-value in the input.

        This confirms LTTB preserves visual extremes rather than uniform sampling.
        """
        import math as _math

        pts = [(float(i), _math.sin(i / 30.0) * 100.0) for i in range(3_000)]
        out = lttb_downsample(pts, threshold=200)
        max_input_y = max(p[1] for p in pts)
        max_output_y = max(p[1] for p in out)
        # Output peak should be within 10% of the true peak (strict LTTB property)
        assert max_output_y >= 0.9 * max_input_y, (
            f"Peak not preserved: input max={max_input_y:.3f}, "
            f"output max={max_output_y:.3f}"
        )

    def test_lttb_no_downsampling_when_points_le_threshold(self) -> None:
        """
        GIVEN input with fewer points than threshold
        WHEN lttb_downsample is called
        THEN output is identical to input (no downsampling).
        """
        pts = _make_lttb_numeric(50)
        out = lttb_downsample(pts, threshold=200)
        assert len(out) == len(pts)
        assert out == pts

    def test_lttb_handles_empty_input(self) -> None:
        """
        GIVEN an empty point list
        WHEN lttb_downsample is called
        THEN an empty list is returned.
        """
        out = lttb_downsample([], threshold=100)
        assert out == []

    def test_lttb_handles_two_points(self) -> None:
        """
        GIVEN exactly 2 points (boundary case)
        WHEN lttb_downsample is called with any threshold ≥ 2
        THEN both points are returned unchanged.
        """
        pts = [(0.0, 1.0), (1.0, 2.0)]
        out = lttb_downsample(pts, threshold=2)
        assert len(out) == 2
        assert out[0] == pts[0]
        assert out[-1] == pts[-1]

    def test_lttb_raises_for_threshold_below_2(self) -> None:
        """
        GIVEN threshold < 2
        WHEN lttb_downsample is called
        THEN ValueError is raised.
        """
        pts = _make_lttb_numeric(100)
        with pytest.raises(ValueError, match="threshold"):
            lttb_downsample(pts, threshold=1)

    def test_lttb_threshold_exactly_equals_input_length(self) -> None:
        """
        GIVEN threshold == len(points)
        WHEN lttb_downsample is called
        THEN all points are returned (no downsampling triggered).
        """
        pts = _make_lttb_numeric(100)
        out = lttb_downsample(pts, threshold=100)
        assert len(out) == 100

    def test_lttb_output_is_sorted_by_x(self) -> None:
        """
        GIVEN sorted input
        WHEN lttb_downsample produces output
        THEN output is also sorted by x (LTTB never reorders points).
        """
        pts = _make_lttb_numeric(1_000)
        out = lttb_downsample(pts, threshold=100)
        xs = [p[0] for p in out]
        assert xs == sorted(xs)


# ---------------------------------------------------------------------------
# MockChartRepository Tests
# ---------------------------------------------------------------------------


class TestMockChartRepository:
    """
    Verify MockChartRepository honours the ChartRepositoryInterface contract.
    """

    def test_save_and_find_equity_round_trips(self) -> None:
        """
        GIVEN equity points saved for a run
        WHEN find_equity_by_run_id is called
        THEN the same points are returned.
        """
        repo = MockChartRepository()
        pts = _make_equity_points(10)
        repo.save_equity(_RUN_ULID_1, pts)
        found = repo.find_equity_by_run_id(_RUN_ULID_1, "c")
        assert len(found) == 10
        assert found[0].equity == pts[0].equity

    def test_find_equity_raises_not_found_for_unknown_run(self) -> None:
        """
        GIVEN an empty repository
        WHEN find_equity_by_run_id is called with an unknown run_id
        THEN NotFoundError is raised.
        """
        repo = MockChartRepository()
        with pytest.raises(NotFoundError, match=_RUN_ULID_MISSING):
            repo.find_equity_by_run_id(_RUN_ULID_MISSING, "c")

    def test_save_and_find_drawdown_round_trips(self) -> None:
        """
        GIVEN drawdown points saved for a run
        WHEN find_drawdown_by_run_id is called
        THEN the same points are returned.
        """
        repo = MockChartRepository()
        pts = _make_drawdown_points(5)
        repo.save_drawdown(_RUN_ULID_1, pts)
        found = repo.find_drawdown_by_run_id(_RUN_ULID_1, "c")
        assert len(found) == 5
        assert all(p.drawdown == 0.0 for p in found)

    def test_find_drawdown_raises_not_found_for_unknown_run(self) -> None:
        """
        GIVEN an empty repository
        WHEN find_drawdown_by_run_id is called with an unknown run_id
        THEN NotFoundError is raised.
        """
        repo = MockChartRepository()
        with pytest.raises(NotFoundError):
            repo.find_drawdown_by_run_id(_RUN_ULID_MISSING, "c")

    def test_save_and_find_trade_count_round_trips(self) -> None:
        """
        GIVEN a trade count saved for a run
        WHEN find_trade_count_by_run_id is called
        THEN the same count is returned.
        """
        repo = MockChartRepository()
        repo.save_trade_count(_RUN_ULID_1, 250)
        count = repo.find_trade_count_by_run_id(_RUN_ULID_1, "c")
        assert count == 250

    def test_find_trade_count_raises_not_found_for_unknown_run(self) -> None:
        """
        GIVEN an empty repository
        WHEN find_trade_count_by_run_id is called with an unknown run_id
        THEN NotFoundError is raised.
        """
        repo = MockChartRepository()
        with pytest.raises(NotFoundError):
            repo.find_trade_count_by_run_id(_RUN_ULID_MISSING, "c")

    def test_clear_removes_all_data(self) -> None:
        """
        GIVEN a populated repository
        WHEN clear() is called
        THEN run_count returns 0.
        """
        repo = MockChartRepository()
        repo.save_equity(_RUN_ULID_1, _make_equity_points(5))
        repo.save_equity(_RUN_ULID_2, _make_equity_points(3))
        repo.clear()
        assert repo.run_count() == 0


# ---------------------------------------------------------------------------
# MockQueueRepository Tests
# ---------------------------------------------------------------------------


class TestMockQueueRepository:
    """
    Verify MockQueueRepository honours the QueueRepositoryInterface contract.
    """

    def _make_snapshot(self, name: str) -> QueueSnapshotResponse:
        """Build a minimal QueueSnapshotResponse for tests."""
        return QueueSnapshotResponse(
            id=f"01HQQUEUE{name.upper()[:15]:0<15}",
            queue_name=name,
            timestamp=_NOW,
            depth=2,
            contention_score=5.0,
            metadata={},
            created_at=_NOW,
        )

    def _make_contention(
        self, queue_class: str, depth: int = 2
    ) -> QueueContentionResponse:
        """Build a minimal QueueContentionResponse for tests."""
        return QueueContentionResponse(
            queue_class=queue_class,
            depth=depth,
            running=1,
            failed=0,
            contention_score=10.0 * depth,
            generated_at=_NOW,
        )

    def test_list_returns_all_saved_snapshots(self) -> None:
        """
        GIVEN two queue snapshots saved
        WHEN list() is called
        THEN both are returned.
        """
        repo = MockQueueRepository()
        repo.save_snapshot(self._make_snapshot("research"))
        repo.save_snapshot(self._make_snapshot("optimize"))
        result = repo.list(correlation_id="c")
        assert len(result) == 2

    def test_list_returns_empty_for_empty_repository(self) -> None:
        """
        GIVEN an empty repository
        WHEN list() is called
        THEN an empty list is returned.
        """
        repo = MockQueueRepository()
        assert repo.list(correlation_id="c") == []

    def test_find_by_class_returns_correct_snapshot(self) -> None:
        """
        GIVEN a saved contention snapshot for 'research'
        WHEN find_by_class('research') is called
        THEN the matching snapshot is returned.
        """
        repo = MockQueueRepository()
        repo.save_contention(self._make_contention("research", depth=3))
        r = repo.find_by_class("research", correlation_id="c")
        assert r.queue_class == "research"
        assert r.depth == 3

    def test_find_by_class_raises_not_found_for_unknown_class(self) -> None:
        """
        GIVEN an empty repository
        WHEN find_by_class is called with unknown class
        THEN NotFoundError is raised.
        """
        repo = MockQueueRepository()
        with pytest.raises(NotFoundError, match="research"):
            repo.find_by_class("research", correlation_id="c")

    def test_clear_removes_all_data(self) -> None:
        """
        GIVEN a populated repository
        WHEN clear() is called
        THEN count and contention_count return 0.
        """
        repo = MockQueueRepository()
        repo.save_snapshot(self._make_snapshot("research"))
        repo.save_contention(self._make_contention("research"))
        repo.clear()
        assert repo.count() == 0
        assert repo.contention_count() == 0


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/charts — composite endpoint tests
# ---------------------------------------------------------------------------


class TestRunChartsEndpoint:
    """
    Unit tests for GET /runs/{run_id}/charts.

    The endpoint must:
    - Return 200 with run_id, equity, and drawdown keys.
    - Apply LTTB when equity point count exceeds 2 000.
    - Return sampling_applied: false for small datasets.
    - Return 404 for unknown run_id.
    """

    @pytest.fixture
    def chart_repo(self) -> MockChartRepository:
        repo = MockChartRepository()
        # Small run: below LTTB threshold
        repo.save_equity(_RUN_ULID_1, _make_equity_points(100))
        repo.save_drawdown(_RUN_ULID_1, _make_drawdown_points(100))
        repo.save_trade_count(_RUN_ULID_1, 50)
        # Large run: above LTTB threshold
        repo.save_equity(_RUN_ULID_2, _make_equity_points(3_000))
        repo.save_drawdown(_RUN_ULID_2, _make_drawdown_points(3_000))
        repo.save_trade_count(_RUN_ULID_2, 200)
        return repo

    @pytest.fixture
    def client(self, chart_repo: MockChartRepository) -> TestClient:
        from services.api.main import app
        from services.api.routes.charts import get_chart_repository

        app.dependency_overrides[get_chart_repository] = lambda: chart_repo
        tc = TestClient(app)
        yield tc
        app.dependency_overrides.clear()

    def test_get_charts_returns_200(self, client: TestClient) -> None:
        """
        GIVEN a run with chart data
        WHEN GET /runs/{run_id}/charts is requested
        THEN 200 is returned.

        FAILS: stub does not implement this endpoint.
        """
        resp = client.get(f"/runs/{_RUN_ULID_1}/charts")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_get_charts_returns_run_id(self, client: TestClient) -> None:
        """
        GIVEN a run with chart data
        WHEN GET /runs/{run_id}/charts is requested
        THEN response contains the correct run_id.
        """
        resp = client.get(f"/runs/{_RUN_ULID_1}/charts")
        body = resp.json()
        assert body.get("run_id") == _RUN_ULID_1

    def test_get_charts_contains_equity_and_drawdown_keys(self, client: TestClient) -> None:
        """
        GIVEN a run with chart data
        WHEN GET /runs/{run_id}/charts is requested
        THEN response contains 'equity' and 'drawdown' keys.
        """
        resp = client.get(f"/runs/{_RUN_ULID_1}/charts")
        body = resp.json()
        assert "equity" in body, f"Missing 'equity' key: {body}"
        assert "drawdown" in body, f"Missing 'drawdown' key: {body}"

    def test_get_charts_unknown_run_returns_404(self, client: TestClient) -> None:
        """
        GIVEN a run_id not in the chart repository
        WHEN GET /runs/{run_id}/charts is requested
        THEN 404 is returned.
        """
        resp = client.get(f"/runs/{_RUN_ULID_MISSING}/charts")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/charts/equity — equity endpoint tests
# ---------------------------------------------------------------------------


class TestRunChartsEquityEndpoint:
    """
    Unit tests for GET /runs/{run_id}/charts/equity.

    The endpoint must:
    - Apply LTTB and set sampling_applied: true when raw_equity_point_count > 2 000.
    - Return sampling_applied: false for datasets ≤ 2 000 points.
    - Report raw_equity_point_count accurately.
    - Set trades_truncated: true when total_trade_count > 5 000.
    - Return 404 for unknown run_id.
    """

    @pytest.fixture
    def chart_repo_small(self) -> MockChartRepository:
        """Small run: 100 equity points, 50 trades — no LTTB, no truncation."""
        repo = MockChartRepository()
        repo.save_equity(_RUN_ULID_1, _make_equity_points(100))
        repo.save_drawdown(_RUN_ULID_1, _make_drawdown_points(100))
        repo.save_trade_count(_RUN_ULID_1, 50)
        return repo

    @pytest.fixture
    def chart_repo_large(self) -> MockChartRepository:
        """Large run: 3 000 equity points, 6 000 trades — LTTB fires, trades truncated."""
        repo = MockChartRepository()
        repo.save_equity(_RUN_ULID_2, _make_equity_points(3_000))
        repo.save_drawdown(_RUN_ULID_2, _make_drawdown_points(3_000))
        repo.save_trade_count(_RUN_ULID_2, 6_000)
        return repo

    @pytest.fixture
    def client_small(self, chart_repo_small: MockChartRepository) -> TestClient:
        from services.api.main import app
        from services.api.routes.charts import get_chart_repository

        app.dependency_overrides[get_chart_repository] = lambda: chart_repo_small
        tc = TestClient(app)
        yield tc
        app.dependency_overrides.clear()

    @pytest.fixture
    def client_large(self, chart_repo_large: MockChartRepository) -> TestClient:
        from services.api.main import app
        from services.api.routes.charts import get_chart_repository

        app.dependency_overrides[get_chart_repository] = lambda: chart_repo_large
        tc = TestClient(app)
        yield tc
        app.dependency_overrides.clear()

    def test_equity_small_run_returns_200(self, client_small: TestClient) -> None:
        """
        GIVEN a run with ≤ 2 000 equity points
        WHEN GET /runs/{run_id}/charts/equity is requested
        THEN 200 is returned.

        FAILS: stub endpoint does not exist.
        """
        resp = client_small.get(f"/runs/{_RUN_ULID_1}/charts/equity")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_equity_small_run_sampling_not_applied(self, client_small: TestClient) -> None:
        """
        GIVEN a run with ≤ 2 000 equity points
        WHEN GET /runs/{run_id}/charts/equity is requested
        THEN sampling_applied is false.
        """
        resp = client_small.get(f"/runs/{_RUN_ULID_1}/charts/equity")
        body = resp.json()
        assert body.get("sampling_applied") is False, (
            f"Expected sampling_applied=false for 100-point run: {body}"
        )

    def test_equity_small_run_raw_count_matches(self, client_small: TestClient) -> None:
        """
        GIVEN a run with 100 equity points
        WHEN GET /runs/{run_id}/charts/equity is requested
        THEN raw_equity_point_count equals 100.
        """
        resp = client_small.get(f"/runs/{_RUN_ULID_1}/charts/equity")
        body = resp.json()
        assert body.get("raw_equity_point_count") == 100, (
            f"Unexpected raw count: {body}"
        )

    def test_equity_large_run_sampling_applied(self, client_large: TestClient) -> None:
        """
        GIVEN a run with 3 000 equity points (> 2 000 threshold)
        WHEN GET /runs/{run_id}/charts/equity is requested
        THEN sampling_applied is true.

        FAILS: stub does not apply LTTB.
        """
        resp = client_large.get(f"/runs/{_RUN_ULID_2}/charts/equity")
        body = resp.json()
        assert body.get("sampling_applied") is True, (
            f"Expected sampling_applied=true for 3000-point run: {body}"
        )

    def test_equity_large_run_point_count_le_threshold(self, client_large: TestClient) -> None:
        """
        GIVEN a run with 3 000 equity points (> 2 000 threshold)
        WHEN GET /runs/{run_id}/charts/equity is requested
        THEN len(points) ≤ 2 000.

        FAILS: stub does not apply LTTB.
        """
        resp = client_large.get(f"/runs/{_RUN_ULID_2}/charts/equity")
        body = resp.json()
        pts = body.get("points", [])
        assert len(pts) <= _EQUITY_LTTB_THRESHOLD, (
            f"Expected ≤ {_EQUITY_LTTB_THRESHOLD} points, got {len(pts)}"
        )

    def test_equity_large_run_raw_count_is_original(self, client_large: TestClient) -> None:
        """
        GIVEN a run with 3 000 equity points
        WHEN GET /runs/{run_id}/charts/equity is requested
        THEN raw_equity_point_count equals 3 000 (original, not downsampled).
        """
        resp = client_large.get(f"/runs/{_RUN_ULID_2}/charts/equity")
        body = resp.json()
        assert body.get("raw_equity_point_count") == 3_000

    def test_equity_large_run_trades_truncated_when_over_limit(
        self, client_large: TestClient
    ) -> None:
        """
        GIVEN a run with 6 000 trades (> 5 000 threshold)
        WHEN GET /runs/{run_id}/charts/equity is requested
        THEN trades_truncated is true and total_trade_count is 6 000.

        FAILS: stub does not report truncation.
        """
        resp = client_large.get(f"/runs/{_RUN_ULID_2}/charts/equity")
        body = resp.json()
        assert body.get("trades_truncated") is True, f"Expected trades_truncated=true: {body}"
        assert body.get("total_trade_count") == 6_000

    def test_equity_small_run_trades_not_truncated(self, client_small: TestClient) -> None:
        """
        GIVEN a run with 50 trades (< 5 000 threshold)
        WHEN GET /runs/{run_id}/charts/equity is requested
        THEN trades_truncated is false.
        """
        resp = client_small.get(f"/runs/{_RUN_ULID_1}/charts/equity")
        body = resp.json()
        assert body.get("trades_truncated") is False

    def test_equity_unknown_run_returns_404(self, client_small: TestClient) -> None:
        """
        GIVEN a run_id not in the chart repository
        WHEN GET /runs/{run_id}/charts/equity is requested
        THEN 404 is returned.
        """
        resp = client_small.get(f"/runs/{_RUN_ULID_MISSING}/charts/equity")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/charts/drawdown — drawdown endpoint tests
# ---------------------------------------------------------------------------


class TestRunChartsDrawdownEndpoint:
    """
    Unit tests for GET /runs/{run_id}/charts/drawdown.
    """

    @pytest.fixture
    def chart_repo(self) -> MockChartRepository:
        repo = MockChartRepository()
        repo.save_equity(_RUN_ULID_1, _make_equity_points(50))
        repo.save_drawdown(_RUN_ULID_1, _make_drawdown_points(50))
        repo.save_trade_count(_RUN_ULID_1, 20)
        return repo

    @pytest.fixture
    def client(self, chart_repo: MockChartRepository) -> TestClient:
        from services.api.main import app
        from services.api.routes.charts import get_chart_repository

        app.dependency_overrides[get_chart_repository] = lambda: chart_repo
        tc = TestClient(app)
        yield tc
        app.dependency_overrides.clear()

    def test_drawdown_returns_200(self, client: TestClient) -> None:
        """
        GIVEN a run with drawdown data
        WHEN GET /runs/{run_id}/charts/drawdown is requested
        THEN 200 is returned.

        FAILS: stub endpoint does not exist.
        """
        resp = client.get(f"/runs/{_RUN_ULID_1}/charts/drawdown")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_drawdown_contains_required_fields(self, client: TestClient) -> None:
        """
        GIVEN a run with drawdown data
        WHEN GET /runs/{run_id}/charts/drawdown is requested
        THEN response contains run_id, points, sampling_applied, raw_point_count.
        """
        resp = client.get(f"/runs/{_RUN_ULID_1}/charts/drawdown")
        body = resp.json()
        for field in ("run_id", "points", "sampling_applied", "raw_point_count"):
            assert field in body, f"Missing field '{field}': {body}"

    def test_drawdown_unknown_run_returns_404(self, client: TestClient) -> None:
        """
        GIVEN a run_id not in the chart repository
        WHEN GET /runs/{run_id}/charts/drawdown is requested
        THEN 404 is returned.
        """
        resp = client.get(f"/runs/{_RUN_ULID_MISSING}/charts/drawdown")
        assert resp.status_code == 404

    def test_drawdown_large_run_applies_lttb(self) -> None:
        """
        GIVEN a run with 3 000 drawdown points (> EQUITY_LTTB_THRESHOLD = 2 000)
        WHEN GET /runs/{run_id}/charts/drawdown is requested
        THEN sampling_applied is true and points ≤ EQUITY_LTTB_THRESHOLD.

        Exercises the drawdown LTTB branch (lines 328-337 of charts.py).
        """
        from services.api.main import app
        from services.api.routes.charts import get_chart_repository

        large_repo = MockChartRepository()
        large_repo.save_equity(_RUN_ULID_2, _make_equity_points(3_000))
        large_repo.save_drawdown(_RUN_ULID_2, _make_drawdown_points(3_000))
        large_repo.save_trade_count(_RUN_ULID_2, 10)

        app.dependency_overrides[get_chart_repository] = lambda: large_repo
        tc = TestClient(app)
        try:
            resp = tc.get(f"/runs/{_RUN_ULID_2}/charts/drawdown")
            body = resp.json()
            assert resp.status_code == 200, f"Expected 200: {resp.text}"
            assert body.get("sampling_applied") is True, f"Expected LTTB applied: {body}"
            assert len(body["points"]) <= _EQUITY_LTTB_THRESHOLD, (
                f"Too many points: {len(body['points'])}"
            )
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /queues — queue list endpoint tests
# ---------------------------------------------------------------------------


class TestQueuesListEndpoint:
    """
    Unit tests for GET /queues.

    The endpoint must:
    - Return 200 with a 'queues' list and 'generated_at' timestamp.
    - Return an empty list when no queues are registered.
    """

    @pytest.fixture
    def queue_repo(self) -> MockQueueRepository:
        repo = MockQueueRepository()
        for name in ("research", "optimize"):
            repo.save_snapshot(
                QueueSnapshotResponse(
                    id=f"01HQQUEUE{name[:10].upper():0<10}",
                    queue_name=name,
                    timestamp=_NOW,
                    depth=1,
                    contention_score=5.0,
                    metadata={},
                    created_at=_NOW,
                )
            )
        return repo

    @pytest.fixture
    def client(self, queue_repo: MockQueueRepository) -> TestClient:
        from services.api.main import app
        from services.api.routes.queues import get_queue_repository

        app.dependency_overrides[get_queue_repository] = lambda: queue_repo
        tc = TestClient(app)
        yield tc
        app.dependency_overrides.clear()

    def test_queues_returns_200(self, client: TestClient) -> None:
        """
        GIVEN two registered queues
        WHEN GET /queues is requested
        THEN 200 is returned.

        FAILS: stub does not delegate to QueueRepositoryInterface.
        """
        resp = client.get("/queues/")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_queues_returns_queues_and_generated_at(self, client: TestClient) -> None:
        """
        GIVEN two registered queues
        WHEN GET /queues is requested
        THEN response contains 'queues' list and 'generated_at' timestamp.
        """
        resp = client.get("/queues/")
        body = resp.json()
        assert "queues" in body, f"Missing 'queues' key: {body}"
        assert "generated_at" in body, f"Missing 'generated_at' key: {body}"

    def test_queues_returns_all_registered_queues(self, client: TestClient) -> None:
        """
        GIVEN two registered queues
        WHEN GET /queues is requested
        THEN response contains 2 items.
        """
        resp = client.get("/queues/")
        body = resp.json()
        assert len(body["queues"]) == 2

    def test_queues_empty_repository_returns_empty_list(self) -> None:
        """
        GIVEN no registered queues
        WHEN GET /queues is requested
        THEN queues is [].
        """
        from services.api.main import app
        from services.api.routes.queues import get_queue_repository

        empty_repo = MockQueueRepository()
        app.dependency_overrides[get_queue_repository] = lambda: empty_repo
        tc = TestClient(app)
        try:
            resp = tc.get("/queues/")
            body = resp.json()
            assert body.get("queues") == []
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /queues/{queue_class}/contention — contention endpoint tests
# ---------------------------------------------------------------------------


class TestQueueContentionEndpoint:
    """
    Unit tests for GET /queues/{queue_class}/contention.

    The endpoint must:
    - Return 200 with queue_class, depth, running, failed, contention_score.
    - Return 404 for unknown queue_class values.
    """

    @pytest.fixture
    def queue_repo(self) -> MockQueueRepository:
        repo = MockQueueRepository()
        for name, depth in (("research", 3), ("optimize", 7)):
            repo.save_contention(
                QueueContentionResponse(
                    queue_class=name,
                    depth=depth,
                    running=1,
                    failed=0,
                    contention_score=float(depth) * 5.0,
                    generated_at=_NOW,
                )
            )
        return repo

    @pytest.fixture
    def client(self, queue_repo: MockQueueRepository) -> TestClient:
        from services.api.main import app
        from services.api.routes.queues import get_queue_repository

        app.dependency_overrides[get_queue_repository] = lambda: queue_repo
        tc = TestClient(app)
        yield tc
        app.dependency_overrides.clear()

    def test_contention_returns_200(self, client: TestClient) -> None:
        """
        GIVEN a registered 'research' queue contention snapshot
        WHEN GET /queues/research/contention is requested
        THEN 200 is returned.

        FAILS: stub does not implement per-class contention endpoint.
        """
        resp = client.get("/queues/research/contention")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_contention_returns_required_fields(self, client: TestClient) -> None:
        """
        GIVEN a registered contention snapshot
        WHEN GET /queues/research/contention is requested
        THEN response contains queue_class, depth, running, failed, contention_score.
        """
        resp = client.get("/queues/research/contention")
        body = resp.json()
        for field in ("queue_class", "depth", "running", "failed", "contention_score"):
            assert field in body, f"Missing field '{field}': {body}"

    def test_contention_returns_correct_values(self, client: TestClient) -> None:
        """
        GIVEN 'optimize' queue with depth=7
        WHEN GET /queues/optimize/contention is requested
        THEN depth is 7.
        """
        resp = client.get("/queues/optimize/contention")
        body = resp.json()
        assert body.get("depth") == 7

    def test_contention_unknown_class_returns_404(self, client: TestClient) -> None:
        """
        GIVEN no 'backtest' queue snapshot registered
        WHEN GET /queues/backtest/contention is requested
        THEN 404 is returned.

        FAILS: stub does not raise 404.
        """
        resp = client.get("/queues/backtest/contention")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
