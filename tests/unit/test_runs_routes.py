"""
Unit tests for POST /runs/from-ir (M2.C2).

Scope:
    Verify the route handler:
      * Resolves dataset_ref via the injected DatasetResolverInterface.
      * Delegates to ResearchRunService.submit_from_ir().
      * Returns 201 with run_id + queued status on the happy path.
      * Returns 404 when dataset_ref is unknown.
      * Returns 422 when the request body is malformed.
      * Returns 401/403 when the auth scope is wrong.
      * Returns 503 when the service or resolver is not configured.

We mock the ResearchRunService at the module-level DI hook so this
file is a true unit test of the route layer; the service layer has
its own tests.
"""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from libs.contracts.mocks.mock_research_run_repository import (
    MockResearchRunRepository,
)
from libs.contracts.research_run import ResearchRunStatus
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
