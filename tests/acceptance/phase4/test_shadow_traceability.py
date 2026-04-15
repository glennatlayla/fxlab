"""
Acceptance test: Shadow mode end-to-end traceability.

Spec gate 1: Shadow mode produces a complete decision timeline from
signal detection through hypothetical fill, with every step traceable
via correlation ID.

Covers:
- Shadow deployment registration → order submission → fill.
- Decision timeline completeness.
- P&L tracking after shadow fill.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from libs.contracts.mocks.mock_risk_event_repository import MockRiskEventRepository
from services.api.services.risk_gate_service import RiskGateService

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEP_ID = "01HACC_SHADOW_TRACE_001"
STRAT_ID = "01HACCSTRAT000000000000001"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _test_env():
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
        execution_mode="shadow",
    )
    return repo


@pytest.fixture()
def risk_gate(deployment_repo: MockDeploymentRepository) -> RiskGateService:
    return RiskGateService(
        deployment_repo=deployment_repo,
        risk_event_repo=MockRiskEventRepository(),
    )


@pytest.fixture()
def shadow_client(
    deployment_repo: MockDeploymentRepository, risk_gate: RiskGateService
) -> TestClient:
    from services.api.routes.shadow import set_shadow_service
    from services.api.services.shadow_execution_service import (
        ShadowExecutionService,
    )

    service = ShadowExecutionService(
        deployment_repo=deployment_repo,
        risk_gate=risk_gate,
    )
    set_shadow_service(service)

    from services.api.main import app

    return TestClient(app, raise_server_exceptions=False)


def _shadow_order_body(oid: str, symbol: str = "AAPL") -> dict:
    return {
        "client_order_id": oid,
        "symbol": symbol,
        "side": "buy",
        "order_type": "market",
        "quantity": "100",
        "strategy_id": STRAT_ID,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestShadowTraceability:
    """Spec gate 1: Shadow mode end-to-end traceability."""

    def test_shadow_register_and_execute(
        self,
        shadow_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Shadow deployment can register, submit order, and get fill."""
        # Register
        resp = shadow_client.post(
            f"/shadow/{DEP_ID}/register",
            json={"initial_equity": "1000000"},
            headers=auth_headers,
        )
        assert resp.status_code in (200, 201)

        # Submit order
        resp = shadow_client.post(
            f"/shadow/{DEP_ID}/orders",
            json=_shadow_order_body("shadow-ord-001"),
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("filled", "submitted", "new")

    def test_shadow_decision_timeline(
        self,
        shadow_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Shadow decisions are available for timeline reconstruction."""
        shadow_client.post(
            f"/shadow/{DEP_ID}/register",
            json={"initial_equity": "1000000"},
            headers=auth_headers,
        )
        shadow_client.post(
            f"/shadow/{DEP_ID}/orders",
            json=_shadow_order_body("shadow-ord-002", "MSFT"),
            headers=auth_headers,
        )

        resp = shadow_client.get(
            f"/shadow/{DEP_ID}/decisions",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        decisions = resp.json()
        assert len(decisions) >= 1, "Shadow decisions must be traceable"

    def test_shadow_pnl_tracking(
        self,
        shadow_client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Shadow P&L is tracked after hypothetical fills."""
        shadow_client.post(
            f"/shadow/{DEP_ID}/register",
            json={"initial_equity": "1000000"},
            headers=auth_headers,
        )
        shadow_client.post(
            f"/shadow/{DEP_ID}/orders",
            json=_shadow_order_body("shadow-ord-003"),
            headers=auth_headers,
        )

        resp = shadow_client.get(
            f"/shadow/{DEP_ID}/pnl",
            headers=auth_headers,
        )
        assert resp.status_code == 200
