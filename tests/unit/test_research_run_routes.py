"""
Unit tests for research run API routes.

Covers:
- POST /research/runs — submit (201, auth)
- GET /research/runs — list with filters (200)
- GET /research/runs/{run_id} — get detail (200, 404)
- GET /research/runs/{run_id}/result — get result (200, 404)
- DELETE /research/runs/{run_id} — cancel (200, 404, 409)

Uses MockResearchRunRepository with ResearchRunService.
TEST_TOKEN bypass for auth in test environment.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

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
from services.api.services.research_run_service import ResearchRunService

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STRATEGY_ID = "01HSTRATEGY00000000000001"
_USER_ID = "01HUSER00000000000000001"


def _make_config_dict(
    run_type: str = "backtest",
    strategy_id: str = _STRATEGY_ID,
) -> dict:
    return {
        "run_type": run_type,
        "strategy_id": strategy_id,
        "symbols": ["AAPL"],
        "initial_equity": "100000",
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _test_env():
    """Ensure ENVIRONMENT=test for TEST_TOKEN bypass."""
    old = os.environ.get("ENVIRONMENT")
    os.environ["ENVIRONMENT"] = "test"
    yield
    if old is None:
        os.environ.pop("ENVIRONMENT", None)
    else:
        os.environ["ENVIRONMENT"] = old


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer TEST_TOKEN"}


@pytest.fixture()
def repo() -> MockResearchRunRepository:
    return MockResearchRunRepository()


@pytest.fixture()
def research_service(
    repo: MockResearchRunRepository,
) -> ResearchRunService:
    return ResearchRunService(repo=repo)


@pytest.fixture()
def client(research_service: ResearchRunService) -> TestClient:
    from services.api.routes.research import set_research_run_service

    set_research_run_service(research_service)
    from services.api.main import app

    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# POST /research/runs
# ---------------------------------------------------------------------------


class TestSubmitRun:
    """Tests for POST /research/runs."""

    def test_submit_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            "/research/runs",
            json={"config": _make_config_dict()},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["status"] == "queued"
        assert data["config"]["run_type"] == "backtest"
        assert data["config"]["strategy_id"] == _STRATEGY_ID

    def test_submit_walk_forward(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            "/research/runs",
            json={"config": _make_config_dict(run_type="walk_forward")},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["config"]["run_type"] == "walk_forward"

    def test_submit_no_auth_returns_401(
        self,
        client: TestClient,
    ) -> None:
        resp = client.post(
            "/research/runs",
            json={"config": _make_config_dict()},
        )
        assert resp.status_code == 401

    def test_submit_invalid_payload_returns_422(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            "/research/runs",
            json={"config": {"run_type": "invalid_type"}},
            headers=auth_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /research/runs
# ---------------------------------------------------------------------------


class TestListRuns:
    """Tests for GET /research/runs."""

    def test_list_by_strategy(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Submit two runs
        for _ in range(2):
            client.post(
                "/research/runs",
                json={"config": _make_config_dict()},
                headers=auth_headers,
            )

        resp = client.get(
            f"/research/runs?strategy_id={_STRATEGY_ID}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 2
        assert len(data["runs"]) == 2

    def test_list_with_pagination(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        for _ in range(5):
            client.post(
                "/research/runs",
                json={"config": _make_config_dict()},
                headers=auth_headers,
            )

        resp = client.get(
            f"/research/runs?strategy_id={_STRATEGY_ID}&limit=2&offset=0",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 5
        assert len(data["runs"]) == 2

    def test_list_no_filter_returns_empty(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.get(
            "/research/runs",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 0
        assert data["runs"] == []


# ---------------------------------------------------------------------------
# GET /research/runs/{run_id}
# ---------------------------------------------------------------------------


class TestGetRun:
    """Tests for GET /research/runs/{run_id}."""

    def test_get_existing_run(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Submit a run first
        submit_resp = client.post(
            "/research/runs",
            json={"config": _make_config_dict()},
            headers=auth_headers,
        )
        run_id = submit_resp.json()["id"]

        resp = client.get(
            f"/research/runs/{run_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == run_id

    def test_get_nonexistent_returns_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.get(
            "/research/runs/nonexistent",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /research/runs/{run_id}/result
# ---------------------------------------------------------------------------


class TestGetRunResult:
    """Tests for GET /research/runs/{run_id}/result."""

    def test_get_result_with_data(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        repo: MockResearchRunRepository,
    ) -> None:
        """Create a run with a result and verify retrieval."""
        config = ResearchRunConfig(
            run_type=ResearchRunType.BACKTEST,
            strategy_id=_STRATEGY_ID,
            symbols=["AAPL"],
            initial_equity=Decimal("100000"),
        )
        record = ResearchRunRecord(
            id="01HRUN_RESULT_ROUTE_TEST",
            config=config,
            status=ResearchRunStatus.PENDING,
            created_by=_USER_ID,
        )
        repo.create(record)
        repo.update_status("01HRUN_RESULT_ROUTE_TEST", ResearchRunStatus.QUEUED)
        repo.update_status("01HRUN_RESULT_ROUTE_TEST", ResearchRunStatus.RUNNING)
        repo.update_status("01HRUN_RESULT_ROUTE_TEST", ResearchRunStatus.COMPLETED)
        repo.save_result(
            "01HRUN_RESULT_ROUTE_TEST",
            ResearchRunResult(summary_metrics={"total_return": 0.15, "sharpe_ratio": 1.2}),
        )

        resp = client.get(
            "/research/runs/01HRUN_RESULT_ROUTE_TEST/result",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary_metrics"]["total_return"] == 0.15

    def test_get_result_no_result_returns_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Submit a run (status=QUEUED, no result)
        submit_resp = client.post(
            "/research/runs",
            json={"config": _make_config_dict()},
            headers=auth_headers,
        )
        run_id = submit_resp.json()["id"]

        resp = client.get(
            f"/research/runs/{run_id}/result",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_get_result_nonexistent_returns_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.get(
            "/research/runs/nonexistent/result",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /research/runs/{run_id} — Cancel
# ---------------------------------------------------------------------------


class TestCancelRun:
    """Tests for DELETE /research/runs/{run_id}."""

    def test_cancel_queued_run(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        submit_resp = client.post(
            "/research/runs",
            json={"config": _make_config_dict()},
            headers=auth_headers,
        )
        run_id = submit_resp.json()["id"]

        resp = client.delete(
            f"/research/runs/{run_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_cancel_nonexistent_returns_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.delete(
            "/research/runs/nonexistent",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_cancel_completed_returns_409(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        repo: MockResearchRunRepository,
    ) -> None:
        """Completed run cannot be cancelled."""
        config = ResearchRunConfig(
            run_type=ResearchRunType.BACKTEST,
            strategy_id=_STRATEGY_ID,
            symbols=["AAPL"],
            initial_equity=Decimal("100000"),
        )
        record = ResearchRunRecord(
            id="01HRUN_CANCEL_COMPLETED",
            config=config,
            status=ResearchRunStatus.PENDING,
            created_by=_USER_ID,
        )
        repo.create(record)
        repo.update_status("01HRUN_CANCEL_COMPLETED", ResearchRunStatus.QUEUED)
        repo.update_status("01HRUN_CANCEL_COMPLETED", ResearchRunStatus.RUNNING)
        repo.update_status("01HRUN_CANCEL_COMPLETED", ResearchRunStatus.COMPLETED)

        resp = client.delete(
            "/research/runs/01HRUN_CANCEL_COMPLETED",
            headers=auth_headers,
        )
        assert resp.status_code == 409

    def test_cancel_no_auth_returns_401(
        self,
        client: TestClient,
    ) -> None:
        resp = client.delete("/research/runs/somerun")
        assert resp.status_code == 401
