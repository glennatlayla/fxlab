"""
Unit tests for ``GET /runs/{run_id}/exports/blotter.csv``.

Scope:
    Verify the streaming CSV blotter route end-to-end through FastAPI:
        * 200 happy path with text/csv body, attachment Content-Disposition,
          and a body that round-trips cleanly through ``csv.reader``.
        * 422 for invalid ULID format.
        * 404 when the run does not exist.
        * 409 when the run is in a non-terminal state (pending / queued /
          running) — the route surfaces RunNotCompletedError as 409.
        * 401 when no Authorization header is supplied.
        * 403 when the caller authenticates but lacks the ``exports:read``
          scope.
        * 503 when the export service has not been wired into the route
          module (fail-closed DI).

    The export service itself is exercised against a real
    :class:`ExportService` backed by an in-memory
    :class:`MockResearchRunRepository` so the route layer's mapping of
    service exceptions onto HTTP status codes is verified without
    re-mocking the streamer's internals.
"""

from __future__ import annotations

import csv
import io
import os
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from libs.contracts.backtest import (
    BacktestConfig,
    BacktestResult,
    BacktestTrade,
)
from libs.contracts.mocks.mock_export_repository import MockExportRepository
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
from libs.contracts.run_results import RUN_BLOTTER_CSV_COLUMNS
from libs.storage.base import ArtifactStorageBase
from services.api.auth import create_access_token
from services.api.routes import run_exports as run_exports_routes
from services.api.services.export_service import ExportService

AUTH_HEADERS = {"Authorization": "Bearer TEST_TOKEN"}

# Stable ULIDs used across the suite so failures are easy to triage.
# All characters are valid Crockford base32 (ULID alphabet excludes I, L, O, U).
_COMPLETED_RUN_ID = "01HREXP0CMPED0000000000WA1"
_PENDING_RUN_ID = "01HREXP0PNDGT0000000000WA2"
_RUNNING_RUN_ID = "01HREXP0RNNGT0000000000WA3"
_QUEUED_RUN_ID = "01HREXP0QEDT00000000000WA4"
_MISSING_RUN_ID = "01HREXP0MSSGT0000000000WA5"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _NoOpArtifactStorage(ArtifactStorageBase):
    """No-op artifact storage; the streaming CSV path never touches storage."""

    def initialize(self, correlation_id: str) -> None:
        return None

    def is_initialized(self) -> bool:
        return True

    def health_check(self, correlation_id: str) -> bool:
        return True

    def put(
        self,
        data: bytes,
        bucket: str,
        key: str,
        metadata: dict[str, object] | None = None,
        correlation_id: str | None = None,
    ) -> str:
        raise AssertionError("storage.put must not be called")

    def get(self, bucket: str, key: str, correlation_id: str) -> bytes:
        raise AssertionError("storage.get must not be called")

    def get_with_metadata(
        self, bucket: str, key: str, correlation_id: str
    ) -> tuple[bytes, dict[str, object]]:
        raise AssertionError("storage.get_with_metadata must not be called")

    def list(
        self,
        bucket: str,
        prefix: str,
        correlation_id: str,
        max_keys: int | None = None,
    ) -> list[str]:
        return []

    def delete(self, bucket: str, key: str, correlation_id: str) -> None:
        raise AssertionError("storage.delete must not be called")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _force_test_env() -> Iterator[None]:
    """TEST_TOKEN bypass requires ENVIRONMENT=test (matches sibling suites)."""
    old = os.environ.get("ENVIRONMENT")
    os.environ["ENVIRONMENT"] = "test"
    yield
    if old is None:
        os.environ.pop("ENVIRONMENT", None)
    else:
        os.environ["ENVIRONMENT"] = old


@pytest.fixture()
def run_repo() -> MockResearchRunRepository:
    return MockResearchRunRepository()


@pytest.fixture()
def export_service(run_repo: MockResearchRunRepository) -> ExportService:
    """Real ExportService wired with the mock research-run repo."""
    return ExportService(
        repo=MockExportRepository(),
        storage=_NoOpArtifactStorage(),
        research_run_repo=run_repo,
    )


@pytest.fixture()
def client(export_service: ExportService) -> Iterator[TestClient]:
    """TestClient with the run-exports DI hook populated."""
    run_exports_routes.set_export_service(export_service)

    from services.api.main import app

    yield TestClient(app, raise_server_exceptions=False)

    run_exports_routes.set_export_service(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_completed_with_two_round_trips(
    repo: MockResearchRunRepository,
    *,
    run_id: str = _COMPLETED_RUN_ID,
) -> ResearchRunRecord:
    """Insert a COMPLETED run with 2 closed round-trips (4 legs)."""
    base_ts = datetime(2025, 1, 1, 9, 30, tzinfo=timezone.utc)
    trades = [
        BacktestTrade(
            timestamp=base_ts,
            symbol="EURUSD",
            side="buy",
            quantity=Decimal("100"),
            price=Decimal("1.1000"),
            commission=Decimal("0.50"),
            slippage=Decimal("0.10"),
        ),
        BacktestTrade(
            timestamp=base_ts + timedelta(minutes=60),
            symbol="EURUSD",
            side="sell",
            quantity=Decimal("100"),
            price=Decimal("1.1050"),
            commission=Decimal("0.50"),
            slippage=Decimal("0.10"),
        ),
        BacktestTrade(
            timestamp=base_ts + timedelta(minutes=120),
            symbol="EURUSD",
            side="buy",
            quantity=Decimal("75"),
            price=Decimal("1.1080"),
            commission=Decimal("0.40"),
            slippage=Decimal("0.05"),
        ),
        BacktestTrade(
            timestamp=base_ts + timedelta(minutes=180),
            symbol="EURUSD",
            side="sell",
            quantity=Decimal("75"),
            price=Decimal("1.1100"),
            commission=Decimal("0.40"),
            slippage=Decimal("0.05"),
        ),
    ]
    config = ResearchRunConfig(
        run_type=ResearchRunType.BACKTEST,
        strategy_id="01HSTRATBACKTEST0000000001",
        symbols=["EURUSD"],
        initial_equity=Decimal("100000"),
    )
    backtest = BacktestResult(
        config=BacktestConfig(
            strategy_id=config.strategy_id,
            symbols=config.symbols,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
        ),
        total_trades=len(trades),
        trades=trades,
    )
    record = ResearchRunRecord(
        id=run_id,
        config=config,
        status=ResearchRunStatus.COMPLETED,
        result=ResearchRunResult(
            backtest_result=backtest,
            summary_metrics={"total_trades": str(len(trades))},
        ),
        created_by="01HUSER0000000000000000001",
        completed_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
    )
    with repo._lock:  # noqa: SLF001 — test seeding only
        repo._store[record.id] = record  # noqa: SLF001 — test seeding only
    return record


def _seed_with_status(
    repo: MockResearchRunRepository,
    *,
    run_id: str,
    status: ResearchRunStatus,
) -> ResearchRunRecord:
    config = ResearchRunConfig(
        run_type=ResearchRunType.BACKTEST,
        strategy_id="01HSTRATBACKTEST0000000001",
        symbols=["EURUSD"],
    )
    record = ResearchRunRecord(
        id=run_id,
        config=config,
        status=status,
        created_by="01HUSER0000000000000000001",
    )
    with repo._lock:  # noqa: SLF001 — test seeding only
        repo._store[record.id] = record  # noqa: SLF001 — test seeding only
    return record


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_blotter_csv_returns_200_with_csv_body_and_attachment_disposition(
    client: TestClient,
    run_repo: MockResearchRunRepository,
) -> None:
    _seed_completed_with_two_round_trips(run_repo)

    resp = client.get(
        f"/runs/{_COMPLETED_RUN_ID}/exports/blotter.csv",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200, resp.text

    # Content-Type: text/csv (FastAPI may add a charset suffix).
    content_type = resp.headers.get("content-type", "")
    assert content_type.startswith("text/csv"), f"unexpected content-type: {content_type!r}"

    disposition = resp.headers.get("content-disposition", "")
    assert "attachment" in disposition.lower(), f"missing attachment disposition: {disposition!r}"
    assert f"run-{_COMPLETED_RUN_ID}-blotter.csv" in disposition

    # Body parses cleanly via csv.reader and matches the expected shape.
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert tuple(rows[0]) == RUN_BLOTTER_CSV_COLUMNS
    assert len(rows) == 1 + 2, f"expected header + 2 round-trips, got {len(rows)}"

    # First data row corresponds to the earlier round-trip.
    first = dict(zip(rows[0], rows[1], strict=True))
    assert first["symbol"] == "EURUSD"
    assert first["side"] == "buy"
    assert first["entry_time"] == "2025-01-01T09:30:00+00:00"
    assert first["exit_time"] == "2025-01-01T10:30:00+00:00"
    assert int(first["holding_period_seconds"]) == 3600


def test_blotter_csv_empty_run_returns_header_only(
    client: TestClient,
    run_repo: MockResearchRunRepository,
) -> None:
    """A COMPLETED run with no trades returns a header-only CSV (1 line)."""
    config = ResearchRunConfig(
        run_type=ResearchRunType.BACKTEST,
        strategy_id="01HSTRATBACKTEST0000000001",
        symbols=["EURUSD"],
        initial_equity=Decimal("100000"),
    )
    backtest = BacktestResult(
        config=BacktestConfig(
            strategy_id=config.strategy_id,
            symbols=config.symbols,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
        ),
        total_trades=0,
        trades=[],
    )
    record = ResearchRunRecord(
        id=_COMPLETED_RUN_ID,
        config=config,
        status=ResearchRunStatus.COMPLETED,
        result=ResearchRunResult(backtest_result=backtest, summary_metrics={}),
        created_by="01HUSER0000000000000000001",
        completed_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
    )
    with run_repo._lock:  # noqa: SLF001 — test seeding only
        run_repo._store[record.id] = record  # noqa: SLF001 — test seeding only

    resp = client.get(
        f"/runs/{_COMPLETED_RUN_ID}/exports/blotter.csv",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert len(rows) == 1
    assert tuple(rows[0]) == RUN_BLOTTER_CSV_COLUMNS


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def test_blotter_csv_invalid_ulid_returns_422(client: TestClient) -> None:
    resp = client.get("/runs/not-a-ulid/exports/blotter.csv", headers=AUTH_HEADERS)
    assert resp.status_code == 422


def test_blotter_csv_missing_run_returns_404(client: TestClient) -> None:
    resp = client.get(
        f"/runs/{_MISSING_RUN_ID}/exports/blotter.csv",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 404
    body = resp.json()
    assert _MISSING_RUN_ID in body["detail"]


@pytest.mark.parametrize(
    ("run_id", "status"),
    [
        (_PENDING_RUN_ID, ResearchRunStatus.PENDING),
        (_QUEUED_RUN_ID, ResearchRunStatus.QUEUED),
        (_RUNNING_RUN_ID, ResearchRunStatus.RUNNING),
    ],
)
def test_blotter_csv_in_progress_run_returns_409(
    client: TestClient,
    run_repo: MockResearchRunRepository,
    run_id: str,
    status: ResearchRunStatus,
) -> None:
    _seed_with_status(run_repo, run_id=run_id, status=status)
    resp = client.get(f"/runs/{run_id}/exports/blotter.csv", headers=AUTH_HEADERS)
    assert resp.status_code == 409
    assert status.value in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_blotter_csv_requires_authentication(client: TestClient) -> None:
    """Missing Authorization header -> 401."""
    resp = client.get(f"/runs/{_COMPLETED_RUN_ID}/exports/blotter.csv")
    assert resp.status_code == 401


def test_blotter_csv_requires_exports_read_scope(
    client: TestClient,
    run_repo: MockResearchRunRepository,
) -> None:
    """A token without ``exports:read`` -> 403."""
    _seed_completed_with_two_round_trips(run_repo)
    # Mint a JWT with an explicit scope set that omits ``exports:read``.
    # The fallback in ``services/api/auth.py`` is to use ROLE_SCOPES when
    # the scope claim is an empty string, so the scope list MUST be
    # non-empty (a benign placeholder) for the override to take effect.
    token = create_access_token(
        user_id="01HSER0NEXPRTSCPED000000A1",
        role="viewer",
        scopes=["operator:read"],
    )
    resp = client.get(
        f"/runs/{_COMPLETED_RUN_ID}/exports/blotter.csv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Fail-closed DI
# ---------------------------------------------------------------------------


def test_blotter_csv_returns_503_when_export_service_unconfigured() -> None:
    """Without a registered service, the route must fail-closed with 503."""
    run_exports_routes.set_export_service(None)  # type: ignore[arg-type]
    try:
        from services.api.main import app

        c = TestClient(app, raise_server_exceptions=False)
        resp = c.get(
            f"/runs/{_COMPLETED_RUN_ID}/exports/blotter.csv",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 503
    finally:
        run_exports_routes.set_export_service(None)  # type: ignore[arg-type]
