"""
Acceptance test: Kill switch MTTH within budget.

Spec gate 4: Kill switch activation measures MTTH (Mean Time To Halt)
and the value is within the SLA budget (< 500 ms for paper).

Covers:
- Kill switch activation produces a HaltEvent with mtth_ms.
- MTTH is measured and non-negative.
- Kill switch drill measures MTTH.
- MTTH is within the 500 ms SLA for paper deployments.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

from libs.contracts.execution import (
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)
from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from libs.contracts.mocks.mock_kill_switch_event_repository import (
    MockKillSwitchEventRepository,
)
from libs.contracts.safety import KillSwitchScope
from services.api.services.drill_service import DrillService
from services.api.services.kill_switch_service import KillSwitchService

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEP_ID = "01HACC_MTTH_001"
STRAT_ID = "01HACC_STRAT_MTTH_001"
MTTH_SLA_MS = 500  # Paper deployment MTTH SLA


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
        execution_mode="paper",
        emergency_posture="flatten_all",
    )
    return repo


@pytest.fixture()
def adapter() -> MockBrokerAdapter:
    return MockBrokerAdapter(fill_mode="instant")


def _make_order(oid: str, adapter: MockBrokerAdapter) -> None:
    adapter.submit_order(
        OrderRequest(
            client_order_id=oid,
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            time_in_force=TimeInForce.DAY,
            deployment_id=DEP_ID,
            strategy_id=STRAT_ID,
            correlation_id="corr-mtth",
            execution_mode=ExecutionMode.PAPER,
        )
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestKillSwitchMTTH:
    """Spec gate 4: MTTH within budget."""

    def test_kill_switch_measures_mtth(
        self,
        deployment_repo: MockDeploymentRepository,
        adapter: MockBrokerAdapter,
    ) -> None:
        """Kill switch activation produces a HaltEvent with mtth_ms."""
        service = KillSwitchService(
            deployment_repo=deployment_repo,
            ks_event_repo=MockKillSwitchEventRepository(),
            adapter_registry={DEP_ID: adapter},
        )
        event = service.activate_kill_switch(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            reason="MTTH measurement test",
            activated_by="acceptance_test",
        )
        assert event.mtth_ms is not None
        assert event.mtth_ms >= 0

    def test_mtth_within_sla_empty(
        self,
        deployment_repo: MockDeploymentRepository,
        adapter: MockBrokerAdapter,
    ) -> None:
        """MTTH with no open orders is within SLA."""
        service = KillSwitchService(
            deployment_repo=deployment_repo,
            ks_event_repo=MockKillSwitchEventRepository(),
            adapter_registry={DEP_ID: adapter},
        )
        event = service.activate_kill_switch(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            reason="SLA check",
            activated_by="test",
        )
        assert event.mtth_ms < MTTH_SLA_MS

    def test_mtth_with_open_orders(
        self,
        deployment_repo: MockDeploymentRepository,
        adapter: MockBrokerAdapter,
    ) -> None:
        """MTTH with open orders is still within SLA."""
        # Submit orders that won't auto-fill (use delayed mode adapter)
        delayed_adapter = MockBrokerAdapter(fill_mode="delayed")
        for i in range(5):
            delayed_adapter.submit_order(
                OrderRequest(
                    client_order_id=f"mtth-ord-{i}",
                    symbol="AAPL",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=Decimal("100"),
                    time_in_force=TimeInForce.DAY,
                    deployment_id=DEP_ID,
                    strategy_id=STRAT_ID,
                    correlation_id="corr-mtth",
                    execution_mode=ExecutionMode.PAPER,
                )
            )

        service = KillSwitchService(
            deployment_repo=deployment_repo,
            ks_event_repo=MockKillSwitchEventRepository(),
            adapter_registry={DEP_ID: delayed_adapter},
        )
        event = service.activate_kill_switch(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            reason="MTTH with orders",
            activated_by="test",
        )
        assert event.mtth_ms < MTTH_SLA_MS, f"MTTH {event.mtth_ms}ms exceeds SLA {MTTH_SLA_MS}ms"

    def test_drill_measures_mtth(
        self,
        deployment_repo: MockDeploymentRepository,
        adapter: MockBrokerAdapter,
    ) -> None:
        """Kill switch drill also measures MTTH."""
        drill_svc = DrillService(
            deployment_repo=deployment_repo,
            adapter_registry={DEP_ID: adapter},
        )
        result = drill_svc.execute_drill(
            drill_type="kill_switch",
            deployment_id=DEP_ID,
        )
        assert result.passed is True
        assert result.mtth_ms is not None
        assert result.mtth_ms >= 0
        assert result.mtth_ms < MTTH_SLA_MS
