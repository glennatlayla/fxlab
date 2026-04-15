"""
Phase 9 Acceptance Test Pack (M13).

End-to-end acceptance tests verifying all Phase 9 deliverables:

1. Research run submission → execution → result retrieval
2. Research run cancellation
3. Walk-forward research run submission
4. Monte Carlo research run submission
5. Export creation → download (trades)
6. Export creation → download (runs)
7. Export list with pagination
8. Pydantic V2 zero-warning verification
9. Full pipeline: submit research → export result → download bundle

These tests exercise the full API surface through FastAPI's TestClient,
wiring real services with mock repositories. The mock repositories
provide behavioural parity with SQL implementations without needing a
live database, making these tests fast and deterministic.

Follows §5 TDD naming: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import zipfile
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from libs.contracts.backtest import (
    BacktestConfig,
    BacktestResult,
)
from libs.contracts.mocks.mock_export_repository import MockExportRepository
from libs.contracts.mocks.mock_research_run_repository import (
    MockResearchRunRepository,
)
from libs.contracts.monte_carlo import (
    MonteCarloConfig,
    MonteCarloResult,
    SimulationMethod,
)
from libs.contracts.research_run import (
    ResearchRunResult,
    ResearchRunStatus,
)
from libs.contracts.walk_forward import (
    OptimizationMetric,
    WalkForwardConfig,
    WalkForwardResult,
)
from services.api.services.export_service import ExportService
from services.api.services.research_run_service import ResearchRunService

# ---------------------------------------------------------------------------
# Mock artifact storage — minimal in-memory implementation for acceptance
# ---------------------------------------------------------------------------


class _AcceptanceArtifactStorage:
    """
    In-memory artifact storage for acceptance tests.

    Mimics ArtifactStorageBase's put/get interface without requiring
    real MinIO/S3. Thread-safe is not required here because TestClient
    serialises requests within a single thread for acceptance tests.

    Responsibilities:
    - Store and retrieve binary artifacts by bucket/key.
    - Provide health_check and initialize stubs for service compatibility.

    Does NOT:
    - Persist data across test runs.
    - Enforce bucket policies or access control.
    """

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    def initialize(self, correlation_id: str) -> None:
        """No-op initialisation for test compatibility."""

    def is_initialized(self) -> bool:
        """Always returns True in test context."""
        return True

    def health_check(self, correlation_id: str) -> bool:
        """Always healthy in test context."""
        return True

    def put(
        self,
        data: bytes,
        bucket: str,
        key: str,
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> str:
        """
        Store binary data at bucket/key.

        Args:
            data: Raw bytes to store.
            bucket: Storage bucket name.
            key: Object key within the bucket.
            metadata: Optional metadata (ignored in tests).
            correlation_id: Optional correlation ID (ignored in tests).

        Returns:
            The storage path "{bucket}/{key}".
        """
        path = f"{bucket}/{key}"
        self._store[path] = data
        return path

    def get(self, bucket: str, key: str, correlation_id: str) -> bytes:
        """
        Retrieve binary data from bucket/key.

        Args:
            bucket: Storage bucket name.
            key: Object key within the bucket.
            correlation_id: Request correlation ID.

        Returns:
            Raw bytes of the stored object.

        Raises:
            FileNotFoundError: If the object does not exist.
        """
        path = f"{bucket}/{key}"
        if path not in self._store:
            raise FileNotFoundError(f"Object not found: {path}")
        return self._store[path]


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
    """Standard auth headers using TEST_TOKEN bypass."""
    return {"Authorization": "Bearer TEST_TOKEN"}


@pytest.fixture()
def research_repo() -> MockResearchRunRepository:
    """Fresh mock research run repository per test."""
    return MockResearchRunRepository()


@pytest.fixture()
def export_repo() -> MockExportRepository:
    """Fresh mock export repository per test."""
    return MockExportRepository()


@pytest.fixture()
def artifact_storage() -> _AcceptanceArtifactStorage:
    """Fresh in-memory artifact storage per test."""
    return _AcceptanceArtifactStorage()


@pytest.fixture()
def research_service(
    research_repo: MockResearchRunRepository,
) -> ResearchRunService:
    """Wired research run service with mock repository."""
    return ResearchRunService(repo=research_repo)


@pytest.fixture()
def export_service(
    export_repo: MockExportRepository,
    artifact_storage: _AcceptanceArtifactStorage,
) -> ExportService:
    """Wired export service with mock repository and artifact storage."""
    return ExportService(repo=export_repo, storage=artifact_storage)  # type: ignore[arg-type]


@pytest.fixture()
def client(
    research_service: ResearchRunService,
    export_service: ExportService,
) -> TestClient:
    """
    TestClient with all Phase 9 services wired via module-level DI.

    Registers research run and export services before importing the
    app so that route handlers resolve to our test instances.
    """
    from services.api.routes.exports import set_export_service
    from services.api.routes.research import set_research_run_service

    set_research_run_service(research_service)
    set_export_service(export_service)

    from services.api.main import app

    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Test data builders
# ---------------------------------------------------------------------------


def _backtest_config_payload() -> dict[str, Any]:
    """Minimal valid backtest ResearchRunConfig as JSON-serialisable dict."""
    return {
        "config": {
            "run_type": "backtest",
            "strategy_id": "01HSTRATEGY0000000000001",
            "symbols": ["AAPL", "MSFT"],
            "initial_equity": "100000",
            "backtest_config": {
                "strategy_id": "01HSTRATEGY0000000000001",
                "symbols": ["AAPL", "MSFT"],
                "start_date": "2024-01-01",
                "end_date": "2024-06-30",
                "interval": "1d",
                "initial_equity": "100000",
            },
        }
    }


def _walk_forward_config_payload() -> dict[str, Any]:
    """Minimal valid walk-forward ResearchRunConfig as JSON-serialisable dict."""
    return {
        "config": {
            "run_type": "walk_forward",
            "strategy_id": "01HSTRATEGY0000000000002",
            "signal_strategy_id": "01HSIGNAL00000000000001",
            "symbols": ["SPY"],
            "initial_equity": "100000",
            "walk_forward_config": {
                "strategy_id": "01HSTRATEGY0000000000002",
                "signal_strategy_id": "01HSIGNAL00000000000001",
                "symbols": ["SPY"],
                "start_date": "2023-01-01",
                "end_date": "2024-01-01",
                "in_sample_bars": 60,
                "out_of_sample_bars": 20,
                "step_bars": 20,
                "parameter_grid": {"lookback": [10, 20, 30]},
                "optimization_metric": "sharpe",
                "initial_equity": "100000",
            },
        }
    }


def _monte_carlo_config_payload() -> dict[str, Any]:
    """Minimal valid Monte Carlo ResearchRunConfig as JSON-serialisable dict."""
    return {
        "config": {
            "run_type": "monte_carlo",
            "strategy_id": "01HSTRATEGY0000000000003",
            "symbols": ["AAPL"],
            "initial_equity": "100000",
            "monte_carlo_config": {
                "num_simulations": 500,
                "method": "trade_resample",
                "confidence_levels": [0.05, 0.50, 0.95],
                "ruin_threshold": 0.50,
                "random_seed": 42,
            },
        }
    }


def _make_backtest_result() -> BacktestResult:
    """Synthetic backtest result for simulating run completion."""
    return BacktestResult(
        config=BacktestConfig(
            strategy_id="01HSTRATEGY0000000000001",
            symbols=["AAPL", "MSFT"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
            initial_equity=Decimal("100000"),
        ),
        total_return_pct=Decimal("12.5"),
        annualized_return_pct=Decimal("25.0"),
        max_drawdown_pct=Decimal("-8.3"),
        sharpe_ratio=Decimal("1.45"),
        total_trades=42,
        win_rate=Decimal("0.58"),
        profit_factor=Decimal("1.72"),
        final_equity=Decimal("112500"),
    )


def _make_walk_forward_result() -> WalkForwardResult:
    """Synthetic walk-forward result for simulating run completion."""
    return WalkForwardResult(
        config=WalkForwardConfig(
            strategy_id="01HSTRATEGY0000000000002",
            signal_strategy_id="01HSIGNAL00000000000001",
            symbols=["SPY"],
            start_date=date(2023, 1, 1),
            end_date=date(2024, 1, 1),
            in_sample_bars=60,
            out_of_sample_bars=20,
            step_bars=20,
            parameter_grid={"lookback": [10, 20, 30]},
            optimization_metric=OptimizationMetric.SHARPE,
            initial_equity=Decimal("100000"),
        ),
        aggregate_oos_metric=1.23,
        stability_score=0.87,
        best_consensus_params={"lookback": 20},
        total_backtests_run=36,
    )


def _make_monte_carlo_result() -> MonteCarloResult:
    """Synthetic Monte Carlo result for simulating run completion."""
    return MonteCarloResult(
        config=MonteCarloConfig(
            num_simulations=500,
            method=SimulationMethod.TRADE_RESAMPLE,
            confidence_levels=[0.05, 0.50, 0.95],
            ruin_threshold=0.50,
            random_seed=42,
        ),
        num_trades=42,
        equity_percentiles={"5": 85000.0, "50": 110000.0, "95": 145000.0},
        max_drawdown_percentiles={"5": -22.0, "50": -12.0, "95": -4.0},
        probability_of_ruin=0.03,
        mean_final_equity=112000.0,
        median_final_equity=110000.0,
    )


# ---------------------------------------------------------------------------
# AC1: Research run submission → execution → result retrieval
# ---------------------------------------------------------------------------


class TestResearchRunLifecycle:
    """
    Acceptance test 1: Full research run lifecycle.

    Verifies the complete flow: submit via API → transition through
    states → attach result → retrieve result via API.
    """

    def test_acceptance_submit_execute_retrieve_result(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        research_repo: MockResearchRunRepository,
    ) -> None:
        """
        AC1: Submit a backtest run, simulate execution through status
        transitions, attach a result, and retrieve it via the API.
        """
        # --- Submit ---
        resp = client.post(
            "/research/runs",
            json=_backtest_config_payload(),
            headers=auth_headers,
        )
        assert resp.status_code == 201, f"Submit failed: {resp.text}"
        run_data = resp.json()
        run_id = run_data["id"]
        assert run_data["status"] in ("pending", "queued")

        # --- Simulate execution: QUEUED → RUNNING → COMPLETED ---
        research_repo.update_status(run_id, ResearchRunStatus.RUNNING)
        research_repo.update_status(run_id, ResearchRunStatus.COMPLETED)

        # --- Attach result ---
        result = ResearchRunResult(backtest_result=_make_backtest_result())
        research_repo.save_result(run_id, result)

        # --- Verify final state via API ---
        resp = client.get(f"/research/runs/{run_id}", headers=auth_headers)
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["status"] == "completed"

        # --- Retrieve result via API ---
        resp = client.get(f"/research/runs/{run_id}/result", headers=auth_headers)
        assert resp.status_code == 200
        result_data = resp.json()
        assert result_data["backtest_result"] is not None
        assert result_data["backtest_result"]["total_trades"] == 42, (
            "Result data must be retrievable end-to-end"
        )


# ---------------------------------------------------------------------------
# AC2: Research run cancellation
# ---------------------------------------------------------------------------


class TestResearchRunCancellation:
    """
    Acceptance test 2: Research run cancellation lifecycle.

    Verifies that a submitted run can be cancelled via the API,
    transitioning to CANCELLED status and preventing further
    state transitions.
    """

    def test_acceptance_cancel_pending_run(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """AC2: Submit then cancel a research run via the API."""
        # Submit
        resp = client.post(
            "/research/runs",
            json=_backtest_config_payload(),
            headers=auth_headers,
        )
        assert resp.status_code == 201
        run_id = resp.json()["id"]

        # Cancel
        resp = client.delete(f"/research/runs/{run_id}", headers=auth_headers)
        assert resp.status_code == 200
        cancel_data = resp.json()
        assert cancel_data["status"] == "cancelled"

        # Verify persisted state
        resp = client.get(f"/research/runs/{run_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_acceptance_cancel_completed_run_returns_409(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        research_repo: MockResearchRunRepository,
    ) -> None:
        """AC2: Cancelling a completed run must return 409 Conflict."""
        # Submit and advance to COMPLETED
        resp = client.post(
            "/research/runs",
            json=_backtest_config_payload(),
            headers=auth_headers,
        )
        run_id = resp.json()["id"]
        research_repo.update_status(run_id, ResearchRunStatus.RUNNING)
        research_repo.update_status(run_id, ResearchRunStatus.COMPLETED)

        # Attempt cancel — must fail
        resp = client.delete(f"/research/runs/{run_id}", headers=auth_headers)
        assert resp.status_code == 409, "Cancelling a completed run must return 409"


# ---------------------------------------------------------------------------
# AC3: Walk-forward research run
# ---------------------------------------------------------------------------


class TestWalkForwardResearchRun:
    """
    Acceptance test 3: Walk-forward research run submission and result.

    Verifies that a walk-forward run can be submitted, executed,
    and its result retrieved with the correct structure.
    """

    def test_acceptance_walk_forward_submit_and_result(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        research_repo: MockResearchRunRepository,
    ) -> None:
        """AC3: Submit walk-forward run, simulate completion, retrieve result."""
        # Submit
        resp = client.post(
            "/research/runs",
            json=_walk_forward_config_payload(),
            headers=auth_headers,
        )
        assert resp.status_code == 201
        run_data = resp.json()
        run_id = run_data["id"]
        assert run_data["config"]["run_type"] == "walk_forward"

        # Simulate execution
        research_repo.update_status(run_id, ResearchRunStatus.RUNNING)
        research_repo.update_status(run_id, ResearchRunStatus.COMPLETED)
        result = ResearchRunResult(walk_forward_result=_make_walk_forward_result())
        research_repo.save_result(run_id, result)

        # Retrieve result
        resp = client.get(f"/research/runs/{run_id}/result", headers=auth_headers)
        assert resp.status_code == 200
        result_data = resp.json()
        assert result_data["walk_forward_result"] is not None
        wf = result_data["walk_forward_result"]
        assert wf["stability_score"] == pytest.approx(0.87)
        assert wf["total_backtests_run"] == 36


# ---------------------------------------------------------------------------
# AC4: Monte Carlo research run
# ---------------------------------------------------------------------------


class TestMonteCarloResearchRun:
    """
    Acceptance test 4: Monte Carlo research run submission and result.

    Verifies that a Monte Carlo run can be submitted, executed,
    and its result retrieved with the correct probability metrics.
    """

    def test_acceptance_monte_carlo_submit_and_result(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        research_repo: MockResearchRunRepository,
    ) -> None:
        """AC4: Submit Monte Carlo run, simulate completion, retrieve result."""
        # Submit
        resp = client.post(
            "/research/runs",
            json=_monte_carlo_config_payload(),
            headers=auth_headers,
        )
        assert resp.status_code == 201
        run_data = resp.json()
        run_id = run_data["id"]
        assert run_data["config"]["run_type"] == "monte_carlo"

        # Simulate execution
        research_repo.update_status(run_id, ResearchRunStatus.RUNNING)
        research_repo.update_status(run_id, ResearchRunStatus.COMPLETED)
        result = ResearchRunResult(monte_carlo_result=_make_monte_carlo_result())
        research_repo.save_result(run_id, result)

        # Retrieve result
        resp = client.get(f"/research/runs/{run_id}/result", headers=auth_headers)
        assert resp.status_code == 200
        result_data = resp.json()
        assert result_data["monte_carlo_result"] is not None
        mc = result_data["monte_carlo_result"]
        assert mc["probability_of_ruin"] == pytest.approx(0.03)
        assert mc["num_trades"] == 42


# ---------------------------------------------------------------------------
# AC5: Export creation → download (trades)
# ---------------------------------------------------------------------------


class TestTradesExport:
    """
    Acceptance test 5: Trades export lifecycle.

    Verifies that a trades export can be created, completes
    successfully, and the artifact can be downloaded as a valid zip.
    """

    def test_acceptance_create_and_download_trades_export(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """AC5: Create trades export, verify completion, download zip."""
        # Create export
        resp = client.post(
            "/exports/",
            json={"export_type": "trades", "object_id": "01HOBJECT0TRADES001"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        export_data = resp.json()
        job_id = export_data["id"]
        assert export_data["status"] == "complete"
        assert export_data["export_type"] == "trades"
        assert export_data["artifact_uri"] is not None

        # Download artifact
        resp = client.get(f"/exports/{job_id}/download", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        assert "content-disposition" in resp.headers
        assert len(resp.content) > 0

        # Validate zip structure
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            names = zf.namelist()
            assert "metadata.json" in names, "Export zip must contain metadata.json"
            assert "README.txt" in names, "Export zip must contain README.txt"


# ---------------------------------------------------------------------------
# AC6: Export creation → download (runs)
# ---------------------------------------------------------------------------


class TestRunsExport:
    """
    Acceptance test 6: Runs export lifecycle.

    Verifies that a runs export can be created and downloaded,
    with the correct export_type persisted.
    """

    def test_acceptance_create_and_download_runs_export(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """AC6: Create runs export, verify completion, download zip."""
        # Create export
        resp = client.post(
            "/exports/",
            json={"export_type": "runs", "object_id": "01HOBJECT0RUNS0001"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        export_data = resp.json()
        job_id = export_data["id"]
        assert export_data["status"] == "complete"
        assert export_data["export_type"] == "runs"

        # Download
        resp = client.get(f"/exports/{job_id}/download", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"

        # Validate zip is well-formed
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            assert len(zf.namelist()) >= 2, (
                "Export zip must contain at least metadata.json and README.txt"
            )


# ---------------------------------------------------------------------------
# AC7: Export list with pagination
# ---------------------------------------------------------------------------


class TestExportListPagination:
    """
    Acceptance test 7: Export listing with pagination.

    Verifies that multiple exports can be listed with correct
    total_count, and pagination parameters (limit, offset) work.
    """

    def test_acceptance_list_exports_with_pagination(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """AC7: Create multiple exports, list with pagination."""
        # Create 5 exports
        job_ids = []
        for i in range(5):
            resp = client.post(
                "/exports/",
                json={
                    "export_type": "trades",
                    "object_id": f"01HOBJECTPAGE{i:04d}",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 201
            job_ids.append(resp.json()["id"])

        # List all by requester (TEST_TOKEN user)
        resp = client.get(
            "/exports/?requested_by=01HTESTFAKE000000000000000",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 5

        # Paginate: page 1 (limit=2, offset=0)
        resp = client.get(
            "/exports/?requested_by=01HTESTFAKE000000000000000&limit=2&offset=0",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        page1 = resp.json()
        assert len(page1["exports"]) == 2
        assert page1["total_count"] == 5

        # Paginate: page 2 (limit=2, offset=2)
        resp = client.get(
            "/exports/?requested_by=01HTESTFAKE000000000000000&limit=2&offset=2",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        page2 = resp.json()
        assert len(page2["exports"]) == 2
        assert page2["total_count"] == 5

        # Paginate: page 3 (limit=2, offset=4) — only 1 remaining
        resp = client.get(
            "/exports/?requested_by=01HTESTFAKE000000000000000&limit=2&offset=4",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        page3 = resp.json()
        assert len(page3["exports"]) == 1
        assert page3["total_count"] == 5


# ---------------------------------------------------------------------------
# AC8: Pydantic V2 zero-warning verification
# ---------------------------------------------------------------------------


class TestPydanticV2ZeroWarnings:
    """
    Acceptance test 8: Pydantic V2 deprecation cleanup verification.

    Verifies that importing all contract modules produces zero
    Pydantic deprecation warnings, confirming M8 cleanup is complete.
    """

    def test_acceptance_pydantic_v2_zero_deprecation_warnings(self) -> None:
        """AC8: Import all contracts with -W error::DeprecationWarning — no failures."""
        # Run a subprocess that imports all contract modules with
        # deprecation warnings promoted to errors. If any Pydantic V1
        # patterns remain (class Config, etc.), the import will raise.
        result = subprocess.run(
            [
                sys.executable,
                "-W",
                "error::DeprecationWarning",
                "-c",
                (
                    "import libs.contracts.backtest;"
                    "import libs.contracts.export;"
                    "import libs.contracts.monte_carlo;"
                    "import libs.contracts.research_run;"
                    "import libs.contracts.walk_forward;"
                    "import libs.contracts.portfolio;"
                    "import libs.contracts.errors;"
                    "print('ALL_CONTRACTS_IMPORTED_OK')"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Pydantic V2 deprecation warnings detected.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        assert "ALL_CONTRACTS_IMPORTED_OK" in result.stdout


# ---------------------------------------------------------------------------
# AC9: Full pipeline — submit research → export result → download bundle
# ---------------------------------------------------------------------------


class TestFullPipelineIntegration:
    """
    Acceptance test 9: Full pipeline integration.

    Verifies the complete end-to-end flow: submit a research run,
    simulate execution with a result, create an export of the
    completed run, and download the export bundle — all through
    the API surface.
    """

    def test_acceptance_full_pipeline_submit_export_download(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        research_repo: MockResearchRunRepository,
    ) -> None:
        """
        AC9: Submit research → execute → attach result → export → download.

        This is the capstone acceptance test that exercises the full
        Phase 9 feature set in a single scenario.
        """
        # --- Step 1: Submit a backtest research run ---
        resp = client.post(
            "/research/runs",
            json=_backtest_config_payload(),
            headers=auth_headers,
        )
        assert resp.status_code == 201
        run_id = resp.json()["id"]

        # --- Step 2: Simulate execution lifecycle ---
        research_repo.update_status(run_id, ResearchRunStatus.RUNNING)
        research_repo.update_status(run_id, ResearchRunStatus.COMPLETED)
        result = ResearchRunResult(backtest_result=_make_backtest_result())
        research_repo.save_result(run_id, result)

        # Verify run is completed via API
        resp = client.get(f"/research/runs/{run_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

        # Verify result is retrievable
        resp = client.get(f"/research/runs/{run_id}/result", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["backtest_result"]["total_trades"] == 42

        # --- Step 3: Create an export for the completed run ---
        resp = client.post(
            "/exports/",
            json={"export_type": "runs", "object_id": run_id},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        export_data = resp.json()
        export_id = export_data["id"]
        assert export_data["status"] == "complete"
        assert export_data["object_id"] == run_id

        # --- Step 4: Download the export bundle ---
        resp = client.get(f"/exports/{export_id}/download", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        assert len(resp.content) > 0

        # --- Step 5: Validate the zip bundle contents ---
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            names = zf.namelist()
            assert "metadata.json" in names, "Pipeline export must include metadata.json"
            assert "README.txt" in names, "Pipeline export must include README.txt"
            # Verify metadata references the correct object_id
            import json

            metadata = json.loads(zf.read("metadata.json"))
            assert metadata["object_id"] == run_id, (
                "Export metadata must reference the source run ID"
            )
