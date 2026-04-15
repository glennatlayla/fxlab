"""
Unit tests for execution analysis API routes.

Covers:
- POST /execution-analysis/{deployment_id}/drift → 200 / 404
- GET /execution-analysis/timeline/{order_id} → 200 / 404
- GET /execution-analysis/search?correlation_id=... → 200

Per M8 spec: drift analysis, order timeline replay, correlation search.

Dependencies:
- libs.contracts.mocks.mock_broker_adapter: MockBrokerAdapter
- libs.contracts.mocks.mock_deployment_repository: MockDeploymentRepository
- services.api.services.execution_analysis_service: ExecutionAnalysisService
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from libs.contracts.execution import (
    ExecutionMode,
    OrderEvent,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)
from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from services.api.services.execution_analysis_service import (
    ExecutionAnalysisService,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEP_ID = "01HTESTDEP0000000000000001"
STRAT_ID = "01HTESTSTRT000000000000001"


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
def deployment_repo() -> MockDeploymentRepository:
    repo = MockDeploymentRepository()
    repo.seed(
        deployment_id=DEP_ID,
        strategy_id=STRAT_ID,
        state="active",
        execution_mode="paper",
    )
    return repo


@pytest.fixture()
def adapter() -> MockBrokerAdapter:
    return MockBrokerAdapter(fill_mode="instant")


@pytest.fixture()
def execution_analysis_service(
    deployment_repo: MockDeploymentRepository,
    adapter: MockBrokerAdapter,
) -> ExecutionAnalysisService:
    return ExecutionAnalysisService(
        deployment_repo=deployment_repo,
        adapter_registry={DEP_ID: adapter},
    )


@pytest.fixture()
def client(execution_analysis_service: ExecutionAnalysisService) -> TestClient:
    from services.api.routes.execution_analysis import (
        set_execution_analysis_service,
    )

    set_execution_analysis_service(execution_analysis_service)
    from services.api.main import app

    return TestClient(app, raise_server_exceptions=False)


def _make_order_request(
    client_order_id: str = "ord-001",
    symbol: str = "AAPL",
) -> OrderRequest:
    return OrderRequest(
        client_order_id=client_order_id,
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("100"),
        time_in_force=TimeInForce.DAY,
        deployment_id=DEP_ID,
        strategy_id=STRAT_ID,
        correlation_id="corr-001",
        execution_mode=ExecutionMode.PAPER,
    )


# ---------------------------------------------------------------------------
# POST /execution-analysis/{deployment_id}/drift
# ---------------------------------------------------------------------------


class TestComputeDrift:
    """Tests for POST /execution-analysis/{deployment_id}/drift."""

    def test_compute_drift_empty(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """No orders produces an empty report."""
        resp = client.post(
            f"/execution-analysis/{DEP_ID}/drift",
            json={"window": "1h"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["deployment_id"] == DEP_ID
        assert data["window"] == "1h"
        assert data["total_metrics"] == 0

    def test_compute_drift_with_orders(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        adapter: MockBrokerAdapter,
        execution_analysis_service: ExecutionAnalysisService,
    ) -> None:
        """Orders with expected prices produce drift metrics."""
        adapter.submit_order(_make_order_request())
        execution_analysis_service.set_expected_prices(
            deployment_id=DEP_ID,
            expected={"ord-001": Decimal("175.00")},
        )

        resp = client.post(
            f"/execution-analysis/{DEP_ID}/drift",
            json={"window": "1h"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_metrics"] >= 1
        assert "report_id" in data

    def test_compute_drift_deployment_not_found(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Nonexistent deployment returns 404."""
        resp = client.post(
            "/execution-analysis/nonexistent/drift",
            json={"window": "1h"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_compute_drift_no_auth(
        self,
        client: TestClient,
    ) -> None:
        """Missing auth returns 401."""
        resp = client.post(
            f"/execution-analysis/{DEP_ID}/drift",
            json={"window": "1h"},
        )
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /execution-analysis/timeline/{order_id}
# ---------------------------------------------------------------------------


class TestGetTimeline:
    """Tests for GET /execution-analysis/timeline/{order_id}."""

    def test_timeline_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        execution_analysis_service: ExecutionAnalysisService,
    ) -> None:
        """Registered events produce a timeline."""
        now = datetime.now(timezone.utc)
        execution_analysis_service.register_event(
            OrderEvent(
                event_id="evt-001",
                order_id="ord-001",
                event_type="signal",
                timestamp=now,
                details={"strategy": "momentum"},
                correlation_id="corr-001",
            )
        )
        execution_analysis_service.register_event(
            OrderEvent(
                event_id="evt-002",
                order_id="ord-001",
                event_type="submitted",
                timestamp=now,
                details={"broker_order_id": "BRK-001"},
                correlation_id="corr-001",
            )
        )

        resp = client.get(
            "/execution-analysis/timeline/ord-001",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["order_id"] == "ord-001"
        assert len(data["events"]) >= 2

    def test_timeline_not_found(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Nonexistent order returns 404."""
        resp = client.get(
            "/execution-analysis/timeline/nonexistent",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /execution-analysis/search?correlation_id=...
# ---------------------------------------------------------------------------


class TestCorrelationSearch:
    """Tests for GET /execution-analysis/search."""

    def test_search_finds_events(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        execution_analysis_service: ExecutionAnalysisService,
    ) -> None:
        """Search returns matching events."""
        now = datetime.now(timezone.utc)
        execution_analysis_service.register_event(
            OrderEvent(
                event_id="evt-001",
                order_id="ord-001",
                event_type="submitted",
                timestamp=now,
                correlation_id="corr-SEARCH",
            )
        )
        execution_analysis_service.register_event(
            OrderEvent(
                event_id="evt-002",
                order_id="ord-002",
                event_type="filled",
                timestamp=now,
                correlation_id="corr-SEARCH",
            )
        )

        resp = client.get(
            "/execution-analysis/search?correlation_id=corr-SEARCH",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert all(e["correlation_id"] == "corr-SEARCH" for e in data)

    def test_search_no_matches(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Search with no matches returns empty list."""
        resp = client.get(
            "/execution-analysis/search?correlation_id=nonexistent",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_search_missing_param(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Missing correlation_id parameter returns 422."""
        resp = client.get(
            "/execution-analysis/search",
            headers=auth_headers,
        )
        assert resp.status_code == 422
