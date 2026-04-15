"""
Integration tests for the research run pipeline.

Covers:
- End-to-end API: submit run via POST → retrieve via GET → cancel via DELETE
- Service + SQL repo: full lifecycle PENDING → QUEUED → RUNNING → COMPLETED
  with result round-trip through SQLAlchemy
- API list + result retrieval with real service wiring

Uses two test strategies:
- API tests: MockResearchRunRepository (avoids SQLite cross-thread issues
  with ASGI test client)
- SQL round-trip tests: in-memory SQLite with real SqlResearchRunRepository

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.mocks.mock_research_run_repository import (
    MockResearchRunRepository,
)
from libs.contracts.models import Base
from libs.contracts.research_run import (
    ResearchRunConfig,
    ResearchRunRecord,
    ResearchRunResult,
    ResearchRunStatus,
    ResearchRunType,
)
from services.api.repositories.sql_research_run_repository import (
    SqlResearchRunRepository,
)
from services.api.services.research_run_service import ResearchRunService

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STRATEGY_ID = "01HSTRATEGY00000000000001"
_USER_ID = "01HUSER00000000000000001"


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
def mock_repo() -> MockResearchRunRepository:
    return MockResearchRunRepository()


@pytest.fixture()
def mock_service(mock_repo: MockResearchRunRepository) -> ResearchRunService:
    return ResearchRunService(repo=mock_repo)


@pytest.fixture()
def client(mock_service: ResearchRunService) -> TestClient:
    from services.api.routes.research import set_research_run_service

    set_research_run_service(mock_service)
    from services.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def db_session():
    """In-memory SQLite session for SQL round-trip tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

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
def sql_repo(db_session: Session) -> SqlResearchRunRepository:
    return SqlResearchRunRepository(db=db_session)


@pytest.fixture()
def sql_service(sql_repo: SqlResearchRunRepository) -> ResearchRunService:
    return ResearchRunService(repo=sql_repo)


# ---------------------------------------------------------------------------
# API Integration: Submit → Get → Cancel
# ---------------------------------------------------------------------------


class TestApiSubmitGetCancel:
    """End-to-end API: submit, get, cancel via HTTP."""

    def test_submit_and_get_round_trip(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        submit_resp = client.post(
            "/research/runs",
            json={
                "config": {
                    "run_type": "backtest",
                    "strategy_id": _STRATEGY_ID,
                    "symbols": ["AAPL", "MSFT"],
                    "initial_equity": "50000",
                }
            },
            headers=auth_headers,
        )
        assert submit_resp.status_code == 201
        data = submit_resp.json()
        run_id = data["id"]
        assert data["status"] == "queued"
        assert data["config"]["symbols"] == ["AAPL", "MSFT"]

        get_resp = client.get(
            f"/research/runs/{run_id}",
            headers=auth_headers,
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == run_id
        assert get_resp.json()["status"] == "queued"

    def test_submit_and_cancel(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        submit_resp = client.post(
            "/research/runs",
            json={
                "config": {
                    "run_type": "backtest",
                    "strategy_id": _STRATEGY_ID,
                    "symbols": ["AAPL"],
                    "initial_equity": "100000",
                }
            },
            headers=auth_headers,
        )
        run_id = submit_resp.json()["id"]

        cancel_resp = client.delete(
            f"/research/runs/{run_id}",
            headers=auth_headers,
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "cancelled"

        # Verify GET returns cancelled
        get_resp = client.get(
            f"/research/runs/{run_id}",
            headers=auth_headers,
        )
        assert get_resp.json()["status"] == "cancelled"


# ---------------------------------------------------------------------------
# API Integration: List + Result
# ---------------------------------------------------------------------------


class TestApiListAndResult:
    """API listing and result retrieval."""

    def test_list_by_strategy(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        for _ in range(3):
            client.post(
                "/research/runs",
                json={
                    "config": {
                        "run_type": "backtest",
                        "strategy_id": _STRATEGY_ID,
                        "symbols": ["AAPL"],
                        "initial_equity": "100000",
                    }
                },
                headers=auth_headers,
            )

        resp = client.get(
            f"/research/runs?strategy_id={_STRATEGY_ID}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 3
        assert len(data["runs"]) == 3

    def test_get_result_via_api(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        mock_repo: MockResearchRunRepository,
    ) -> None:
        """Create a completed run with result, fetch via API."""
        config = ResearchRunConfig(
            run_type=ResearchRunType.BACKTEST,
            strategy_id=_STRATEGY_ID,
            symbols=["AAPL"],
            initial_equity=Decimal("100000"),
        )
        record = ResearchRunRecord(
            id="01HRUN_API_RESULT_INTEG",
            config=config,
            status=ResearchRunStatus.PENDING,
            created_by=_USER_ID,
        )
        mock_repo.create(record)
        mock_repo.update_status("01HRUN_API_RESULT_INTEG", ResearchRunStatus.QUEUED)
        mock_repo.update_status("01HRUN_API_RESULT_INTEG", ResearchRunStatus.RUNNING)
        mock_repo.update_status("01HRUN_API_RESULT_INTEG", ResearchRunStatus.COMPLETED)
        mock_repo.save_result(
            "01HRUN_API_RESULT_INTEG",
            ResearchRunResult(summary_metrics={"total_return": 0.22, "sharpe_ratio": 1.5}),
        )

        resp = client.get(
            "/research/runs/01HRUN_API_RESULT_INTEG/result",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary_metrics"]["total_return"] == 0.22
        assert data["summary_metrics"]["sharpe_ratio"] == 1.5


# ---------------------------------------------------------------------------
# SQL Round-Trip: Full Lifecycle
# ---------------------------------------------------------------------------


class TestSqlFullLifecycle:
    """Service + SQL repo: full lifecycle with result persistence."""

    def test_full_lifecycle_with_result(
        self,
        sql_service: ResearchRunService,
        sql_repo: SqlResearchRunRepository,
    ) -> None:
        config = ResearchRunConfig(
            run_type=ResearchRunType.BACKTEST,
            strategy_id=_STRATEGY_ID,
            symbols=["AAPL"],
            initial_equity=Decimal("100000"),
        )

        # Submit → QUEUED
        record = sql_service.submit_run(config, user_id=_USER_ID)
        assert record.status == ResearchRunStatus.QUEUED
        run_id = record.id

        # RUNNING
        sql_repo.update_status(run_id, ResearchRunStatus.RUNNING)
        running = sql_service.get_run(run_id)
        assert running is not None
        assert running.status == ResearchRunStatus.RUNNING
        assert running.started_at is not None

        # COMPLETED
        sql_repo.update_status(run_id, ResearchRunStatus.COMPLETED)

        # Attach result
        result = ResearchRunResult(
            summary_metrics={
                "total_return": 0.15,
                "sharpe_ratio": 1.2,
                "max_drawdown": -0.08,
            }
        )
        sql_repo.save_result(run_id, result)

        # Verify result
        fetched_result = sql_service.get_run_result(run_id)
        assert fetched_result is not None
        assert fetched_result.summary_metrics["total_return"] == 0.15
        assert fetched_result.summary_metrics["sharpe_ratio"] == 1.2

        # Verify completed
        completed = sql_service.get_run(run_id)
        assert completed is not None
        assert completed.status == ResearchRunStatus.COMPLETED
        assert completed.completed_at is not None

    def test_list_by_strategy_via_sql(
        self,
        sql_service: ResearchRunService,
    ) -> None:
        config_a = ResearchRunConfig(
            run_type=ResearchRunType.BACKTEST,
            strategy_id="strat_a",
            symbols=["AAPL"],
            initial_equity=Decimal("100000"),
        )
        config_b = ResearchRunConfig(
            run_type=ResearchRunType.BACKTEST,
            strategy_id="strat_b",
            symbols=["MSFT"],
            initial_equity=Decimal("100000"),
        )
        sql_service.submit_run(config_a, user_id=_USER_ID)
        sql_service.submit_run(config_b, user_id=_USER_ID)
        sql_service.submit_run(config_a, user_id=_USER_ID)

        records, total = sql_service.list_runs(strategy_id="strat_a")
        assert total == 2
        assert all(r.config.strategy_id == "strat_a" for r in records)
