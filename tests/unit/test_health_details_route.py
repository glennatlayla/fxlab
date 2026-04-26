"""
Unit tests for GET /health/details (catalog + run-pool inventory probe).

Scope:
    - Happy path: authenticated admin caller gets 200 with non-zero
      datasets / strategies / runs counts and an in-flight count read
      from the run executor pool on app.state.
    - DB error path: when the inline strategies/runs aggregate raises,
      the route returns 503 with the failed component marked
      ``status: "error"`` and a generic redacted reason (no SQL leaked
      to the wire).
    - Authentication: missing Authorization header → 401, regardless of
      what counts the components would have returned.
    - Authorization: caller without ``admin:manage`` scope → 403.
    - In-flight reflection: when the pool reports inflight_count() > 0
      the response surfaces that integer in components.runs.in_flight.

The router is wired against an in-memory SQLite database and a real
:class:`DatasetService` backed by an in-memory mock repository so the
tests exercise the route+service slice without a Postgres dependency.

The run executor pool is replaced by a tiny stand-in object that only
exposes ``inflight_count()`` — this is the same surface the production
:class:`RunExecutorPool` already publishes (see
``services/api/services/run_executor_pool.py``), so the tests verify the
route's contract with the pool without booting the asyncio machinery.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from libs.contracts.interfaces.dataset_repository_interface import DatasetRecord
from libs.contracts.mocks.mock_dataset_repository import MockDatasetRepository
from libs.contracts.models import Base, ResearchRun, Strategy, User
from services.api.auth import (
    ROLE_SCOPES,
    AuthenticatedUser,
    get_current_user,
)
from services.api.db import get_db
from services.api.main import app
from services.api.services.dataset_service import DatasetService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_ADMIN_USER = AuthenticatedUser(
    user_id="01HTESTFAKE000000000000000",
    role="admin",
    email="admin@fxlab.test",
    scopes=ROLE_SCOPES["admin"],
)
_VIEWER_USER = AuthenticatedUser(
    user_id="01HTESTFAKE000000000000001",
    role="viewer",
    email="viewer@fxlab.test",
    scopes=ROLE_SCOPES["viewer"],
)


class _StubPool:
    """
    Minimal in-flight-count surface mirroring :class:`RunExecutorPool`.

    Exposes :meth:`inflight_count` so the route handler can read the
    integer without the tests having to construct a real bounded async
    pool. The production pool's method has the identical signature and
    return type (see services/api/services/run_executor_pool.py).
    """

    def __init__(self, in_flight: int = 0) -> None:
        self._n = in_flight

    def inflight_count(self) -> int:
        return self._n


def _seed_dataset(repo: MockDatasetRepository, *, dataset_ref: str) -> None:
    repo.save(
        DatasetRecord(
            id=dataset_ref.upper().ljust(26, "0")[:26],
            dataset_ref=dataset_ref,
            symbols=["EURUSD"],
            timeframe="15m",
            source="oanda",
            version="v1",
            is_certified=True,
        )
    )


def _seed_strategy(session: Session, *, idx: int, owner_id: str) -> None:
    session.add(
        Strategy(
            id=f"01HSTRAT{idx:018d}",
            name=f"strategy-{idx}",
            code="def strat(): pass",
            version="v1",
            created_by=owner_id,
            is_active=True,
            source="ir_upload",
        )
    )


def _seed_research_run(session: Session, *, idx: int, owner_id: str) -> None:
    session.add(
        ResearchRun(
            id=f"01HRRUN{idx:019d}",
            run_type="backtest",
            strategy_id=f"01HSTRAT{idx:018d}",
            status="completed",
            config_json={"run_type": "backtest"},
            created_by=owner_id,
        )
    )


def _seed_user(session: Session, *, user_id: str) -> None:
    """Create the FK target row for Strategy.created_by."""
    session.add(
        User(
            id=user_id,
            email=f"user-{user_id}@fxlab.test",
            hashed_password="not-a-real-hash",
            role="admin",
            is_active=True,
        )
    )


@pytest.fixture()
def _db_session() -> Iterator[Session]:
    """
    In-memory SQLite session shared across the test's request handlers.

    Uses ``StaticPool`` + ``check_same_thread=False`` because FastAPI's
    :class:`TestClient` runs request handlers on a worker thread distinct
    from the test thread. The default SQLite connection is thread-pinned;
    StaticPool reuses a single connection across threads, and
    ``check_same_thread=False`` disables sqlite3's cross-thread guard so
    we can share the in-memory DB.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        engine.dispose()


@pytest.fixture()
def admin_client(_db_session: Session) -> Iterator[tuple[TestClient, MockDatasetRepository]]:
    """
    Return a TestClient with admin auth + an SQLite-backed get_db override
    + a real DatasetService bound to an in-memory mock repo on app.state.
    """
    repo = MockDatasetRepository()
    service = DatasetService(repo=repo)

    async def _fake_admin() -> AuthenticatedUser:
        return _ADMIN_USER

    def _fake_db() -> Iterator[Session]:
        # Mirror the real get_db lifecycle (yield, commit on success).
        try:
            yield _db_session
            _db_session.commit()
        except Exception:
            _db_session.rollback()
            raise

    app.dependency_overrides[get_current_user] = _fake_admin
    app.dependency_overrides[get_db] = _fake_db

    pool = _StubPool(in_flight=0)
    previous_pool = getattr(app.state, "run_executor_pool", None)
    previous_dataset_service = getattr(app.state, "dataset_service", None)
    app.state.run_executor_pool = pool
    app.state.dataset_service = service

    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client, repo
    finally:
        app.dependency_overrides.clear()
        if previous_pool is None:
            # Tolerate the test having already removed the attribute.
            try:
                del app.state.run_executor_pool
            except (AttributeError, KeyError):
                pass
        else:
            app.state.run_executor_pool = previous_pool
        if previous_dataset_service is None:
            try:
                del app.state.dataset_service
            except (AttributeError, KeyError):
                pass
        else:
            app.state.dataset_service = previous_dataset_service
        repo.clear()


@pytest.fixture()
def viewer_client(_db_session: Session) -> Iterator[TestClient]:
    """TestClient where the authenticated user lacks the admin:manage scope."""

    async def _fake_viewer() -> AuthenticatedUser:
        return _VIEWER_USER

    def _fake_db() -> Iterator[Session]:
        try:
            yield _db_session
            _db_session.commit()
        except Exception:
            _db_session.rollback()
            raise

    app.dependency_overrides[get_current_user] = _fake_viewer
    app.dependency_overrides[get_db] = _fake_db

    pool = _StubPool(in_flight=0)
    previous_pool = getattr(app.state, "run_executor_pool", None)
    previous_dataset_service = getattr(app.state, "dataset_service", None)
    app.state.run_executor_pool = pool
    app.state.dataset_service = DatasetService(repo=MockDatasetRepository())

    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
        if previous_pool is None:
            # Tolerate the test having already removed the attribute.
            try:
                del app.state.run_executor_pool
            except (AttributeError, KeyError):
                pass
        else:
            app.state.run_executor_pool = previous_pool
        if previous_dataset_service is None:
            try:
                del app.state.dataset_service
            except (AttributeError, KeyError):
                pass
        else:
            app.state.dataset_service = previous_dataset_service


@pytest.fixture()
def unauthenticated_client(_db_session: Session) -> Iterator[TestClient]:
    """
    Default TestClient with no auth override — exercises the real
    get_current_user dependency, which rejects requests without an
    Authorization header.
    """

    def _fake_db() -> Iterator[Session]:
        try:
            yield _db_session
            _db_session.commit()
        except Exception:
            _db_session.rollback()
            raise

    app.dependency_overrides[get_db] = _fake_db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def _admin_headers() -> dict[str, str]:
    return {"Authorization": "Bearer TEST_TOKEN"}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHealthDetailsHappyPath:
    def test_returns_200_with_zero_counts_on_empty_state(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, _ = admin_client
        resp = client.get("/health/details", headers=_admin_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == "fxlab-api"
        assert body["version"] == "0.1.0-bootstrap"
        components = body["components"]
        assert components["database"] == "ok"
        assert components["datasets"] == {"status": "ok", "count": 0}
        assert components["strategies"] == {"status": "ok", "count": 0}
        assert components["runs"] == {
            "status": "ok",
            "in_flight": 0,
            "total_persisted": 0,
        }
        # checked_at must be ISO-8601 UTC with timezone designator.
        assert "checked_at" in body
        assert body["checked_at"].endswith("Z") or "+00:00" in body["checked_at"]

    def test_returns_200_with_real_counts(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
        _db_session: Session,
    ) -> None:
        client, repo = admin_client
        # Seed 3 datasets, 2 strategies, 4 research runs.
        owner_id = "01HOWNER0000000000000000001"
        _seed_user(_db_session, user_id=owner_id)
        for ref in ("a-ds", "b-ds", "c-ds"):
            _seed_dataset(repo, dataset_ref=ref)
        for idx in (1, 2):
            _seed_strategy(_db_session, idx=idx, owner_id=owner_id)
        for idx in (1, 2, 3, 4):
            _seed_research_run(_db_session, idx=idx, owner_id=owner_id)
        _db_session.flush()

        resp = client.get("/health/details", headers=_admin_headers())
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["components"]["datasets"]["count"] == 3
        assert body["components"]["strategies"]["count"] == 2
        assert body["components"]["runs"]["total_persisted"] == 4
        assert body["components"]["runs"]["in_flight"] == 0

    def test_in_flight_count_reflects_pool_state(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, _ = admin_client
        # Re-bind app.state.run_executor_pool to a pool that reports 2.
        app.state.run_executor_pool = _StubPool(in_flight=2)
        resp = client.get("/health/details", headers=_admin_headers())
        assert resp.status_code == 200
        assert resp.json()["components"]["runs"]["in_flight"] == 2

    def test_in_flight_zero_when_pool_absent(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        """A boot configuration without a run pool must not 500 the route."""
        client, _ = admin_client
        # Strip the pool so the route falls through to the safe default.
        try:
            del app.state.run_executor_pool
        except AttributeError:
            pass
        resp = client.get("/health/details", headers=_admin_headers())
        assert resp.status_code == 200
        assert resp.json()["components"]["runs"]["in_flight"] == 0


# ---------------------------------------------------------------------------
# Authentication / Authorization
# ---------------------------------------------------------------------------


class TestHealthDetailsAuth:
    def test_missing_authorization_returns_401(
        self,
        unauthenticated_client: TestClient,
    ) -> None:
        resp = unauthenticated_client.get("/health/details")
        assert resp.status_code == 401

    def test_viewer_without_admin_manage_returns_403(
        self,
        viewer_client: TestClient,
    ) -> None:
        resp = viewer_client.get("/health/details", headers=_admin_headers())
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Degraded path
# ---------------------------------------------------------------------------


class TestHealthDetailsDegraded:
    def test_db_failure_returns_503_with_redacted_error(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, repo = admin_client
        # Seed a dataset so the dataset component still reports a count.
        _seed_dataset(repo, dataset_ref="d-ds")

        # Patch the inline DB aggregate the route uses to count strategies.
        # The patch target intentionally lives in the route module so we
        # break only the strategies / runs path, not the dataset service.
        from services.api.routes import health as health_module

        def _boom(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("psycopg2.OperationalError: connection terminated")

        with patch.object(health_module, "_count_table", side_effect=_boom):
            resp = client.get("/health/details", headers=_admin_headers())

        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        # Datasets path was NOT broken — it still reports a real count.
        assert body["components"]["datasets"]["count"] == 1
        # Strategies + runs reflect the failure.
        assert body["components"]["strategies"]["status"] == "error"
        assert body["components"]["runs"]["status"] == "error"
        # The redacted reason must NOT leak the underlying psycopg2 string.
        for component in ("strategies", "runs"):
            reason = body["components"][component].get("reason", "")
            assert "psycopg2" not in reason
            assert "connection terminated" not in reason

    def test_dataset_service_failure_marks_only_datasets_degraded(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
        _db_session: Session,
    ) -> None:
        client, repo = admin_client
        owner_id = "01HOWNER0000000000000000002"
        _seed_user(_db_session, user_id=owner_id)
        _seed_strategy(_db_session, idx=1, owner_id=owner_id)
        _db_session.flush()

        # Force the dataset service count() to raise.
        with patch.object(
            DatasetService,
            "count",
            side_effect=RuntimeError("repository down"),
        ):
            resp = client.get("/health/details", headers=_admin_headers())

        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["components"]["datasets"]["status"] == "error"
        # Strategies + runs still report real counts because they took
        # an independent path and were not affected.
        assert body["components"]["strategies"]["count"] == 1
        assert body["components"]["runs"]["status"] == "ok"
        # The redacted reason must NOT leak internal exception text.
        reason = body["components"]["datasets"].get("reason", "")
        assert "repository down" not in reason
