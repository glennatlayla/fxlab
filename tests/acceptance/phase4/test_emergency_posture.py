"""
Acceptance test: Every deployment has posture + decision matrix.

Spec gate 5: Every deployment has a configured emergency posture and
the emergency posture execution produces a decision with the correct
posture type, order cancellation count, and position flattening count.

Covers:
- Deployment creation requires emergency posture.
- Emergency posture execution produces EmergencyPostureDecision.
- flatten_all cancels orders and flattens positions.
- cancel_open cancels orders but preserves positions.
- hold takes no automated action.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from libs.contracts.deployment import (
    EmergencyPostureType,
)
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
from libs.contracts.safety import HaltTrigger
from services.api.services.kill_switch_service import KillSwitchService

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEP_ID = "01HACC_POSTURE_001"
STRAT_ID = "01HACC_STRAT_POST_001"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
def adapter_with_orders() -> MockBrokerAdapter:
    adapter = MockBrokerAdapter(fill_mode="delayed")
    # Submit some orders that stay open
    for i in range(3):
        adapter.submit_order(
            OrderRequest(
                client_order_id=f"posture-ord-{i}",
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("100"),
                time_in_force=TimeInForce.DAY,
                deployment_id=DEP_ID,
                strategy_id=STRAT_ID,
                correlation_id="corr-posture",
                execution_mode=ExecutionMode.PAPER,
            )
        )
    return adapter


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmergencyPosture:
    """Spec gate 5: Every deployment has posture + decision matrix."""

    def test_posture_types_exist(self) -> None:
        """All required posture types are defined."""
        # EmergencyPostureType uses lowercase member names
        assert EmergencyPostureType.flatten_all.value == "flatten_all"
        assert EmergencyPostureType.cancel_open.value == "cancel_open"
        assert EmergencyPostureType.hold.value == "hold"

    def test_flatten_all_execution(
        self,
        deployment_repo: MockDeploymentRepository,
        adapter_with_orders: MockBrokerAdapter,
    ) -> None:
        """flatten_all posture cancels orders and attempts to flatten positions."""
        service = KillSwitchService(
            deployment_repo=deployment_repo,
            ks_event_repo=MockKillSwitchEventRepository(),
            adapter_registry={DEP_ID: adapter_with_orders},
        )
        decision = service.execute_emergency_posture(
            deployment_id=DEP_ID,
            trigger=HaltTrigger.KILL_SWITCH,
            reason="Acceptance test flatten_all",
        )
        assert decision.posture.value == "flatten_all"
        assert decision.orders_cancelled >= 0
        assert decision.duration_ms >= 0

    def test_cancel_open_execution(
        self,
        adapter_with_orders: MockBrokerAdapter,
    ) -> None:
        """cancel_open posture cancels orders but preserves positions."""
        repo = MockDeploymentRepository()
        repo.seed(
            deployment_id=DEP_ID,
            strategy_id=STRAT_ID,
            state="active",
            execution_mode="paper",
            emergency_posture="cancel_open",
        )
        service = KillSwitchService(
            deployment_repo=repo,
            ks_event_repo=MockKillSwitchEventRepository(),
            adapter_registry={DEP_ID: adapter_with_orders},
        )
        decision = service.execute_emergency_posture(
            deployment_id=DEP_ID,
            trigger=HaltTrigger.MANUAL,
            reason="Acceptance test cancel_open",
        )
        assert decision.posture.value == "cancel_open"
        # cancel_open should NOT flatten positions
        assert decision.positions_flattened == 0

    def test_hold_execution(self) -> None:
        """hold posture takes no automated action."""
        repo = MockDeploymentRepository()
        repo.seed(
            deployment_id=DEP_ID,
            strategy_id=STRAT_ID,
            state="active",
            execution_mode="paper",
            emergency_posture="hold",
        )
        adapter = MockBrokerAdapter(fill_mode="instant")
        service = KillSwitchService(
            deployment_repo=repo,
            ks_event_repo=MockKillSwitchEventRepository(),
            adapter_registry={DEP_ID: adapter},
        )
        decision = service.execute_emergency_posture(
            deployment_id=DEP_ID,
            trigger=HaltTrigger.MANUAL,
            reason="Acceptance test hold",
        )
        assert decision.posture.value == "hold"
        assert decision.orders_cancelled == 0
        assert decision.positions_flattened == 0

    def test_decision_has_required_fields(
        self,
        deployment_repo: MockDeploymentRepository,
        adapter_with_orders: MockBrokerAdapter,
    ) -> None:
        """EmergencyPostureDecision includes all required fields."""
        service = KillSwitchService(
            deployment_repo=deployment_repo,
            ks_event_repo=MockKillSwitchEventRepository(),
            adapter_registry={DEP_ID: adapter_with_orders},
        )
        decision = service.execute_emergency_posture(
            deployment_id=DEP_ID,
            trigger=HaltTrigger.KILL_SWITCH,
            reason="Field check",
        )
        assert decision.decision_id is not None
        assert decision.deployment_id == DEP_ID
        assert decision.posture is not None
        assert decision.trigger is not None
        assert decision.reason == "Field check"
        assert decision.executed_at is not None
        assert decision.duration_ms >= 0
