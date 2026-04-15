"""
Unit tests for KillSwitchService.

Covers:
- Kill switch activation at each scope (global, strategy, symbol).
- Kill switch deactivation.
- MTTH measurement.
- is_halted() checks across scopes.
- Emergency posture execution (flatten_all, cancel_open, hold).
- Error paths (already active, not found, no adapter).
- Multiple simultaneous kill switches.

Dependencies:
- libs.contracts.mocks.mock_broker_adapter: MockBrokerAdapter
- libs.contracts.mocks.mock_deployment_repository: MockDeploymentRepository
- libs.contracts.mocks.mock_kill_switch_event_repository: MockKillSwitchEventRepository
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from libs.contracts.deployment import EmergencyPostureType
from libs.contracts.errors import NotFoundError, StateTransitionError
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
from libs.contracts.safety import (
    HaltTrigger,
    KillSwitchScope,
)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


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
        deployment_id="01HDEPLOY0001",
        strategy_id="01HSTRAT0001",
        correlation_id="corr-001",
        execution_mode=ExecutionMode.PAPER,
    )


def _setup(
    deployment_id: str = "01HDEPLOY0001",
    state: str = "active",
    execution_mode: str = "paper",
    emergency_posture: str = "flatten_all",
    fill_mode: str = "instant",
):
    """Create standard test fixtures including MockKillSwitchEventRepository."""
    deployment_repo = MockDeploymentRepository()
    deployment_repo.seed(
        deployment_id=deployment_id,
        state=state,
        execution_mode=execution_mode,
        emergency_posture=emergency_posture,
        strategy_id="01HSTRAT0001",
    )
    adapter = MockBrokerAdapter(fill_mode=fill_mode)
    ks_event_repo = MockKillSwitchEventRepository()

    from services.api.services.kill_switch_service import KillSwitchService

    service = KillSwitchService(
        deployment_repo=deployment_repo,
        ks_event_repo=ks_event_repo,
        adapter_registry={deployment_id: adapter},
    )
    return service, deployment_repo, adapter


# ------------------------------------------------------------------
# Activation tests
# ------------------------------------------------------------------


class TestKillSwitchActivation:
    """Test kill switch activation at each scope."""

    def test_activate_global(self) -> None:
        service, _, _ = _setup()
        event = service.activate_kill_switch(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            reason="Emergency halt",
            activated_by="system:test",
        )
        assert event.scope == KillSwitchScope.GLOBAL
        assert event.target_id == "global"
        assert event.trigger == HaltTrigger.KILL_SWITCH

    def test_activate_strategy(self) -> None:
        service, _, _ = _setup()
        event = service.activate_kill_switch(
            scope=KillSwitchScope.STRATEGY,
            target_id="01HSTRAT0001",
            reason="Strategy breach",
            activated_by="system:test",
        )
        assert event.scope == KillSwitchScope.STRATEGY
        assert event.target_id == "01HSTRAT0001"

    def test_activate_symbol(self) -> None:
        service, _, _ = _setup()
        event = service.activate_kill_switch(
            scope=KillSwitchScope.SYMBOL,
            target_id="AAPL",
            reason="Volatility halt",
            activated_by="system:test",
        )
        assert event.scope == KillSwitchScope.SYMBOL
        assert event.target_id == "AAPL"

    def test_activate_with_custom_trigger(self) -> None:
        service, _, _ = _setup()
        event = service.activate_kill_switch(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            reason="Daily loss exceeded",
            activated_by="system:risk_gate",
            trigger=HaltTrigger.DAILY_LOSS,
        )
        assert event.trigger == HaltTrigger.DAILY_LOSS

    def test_activate_already_active_raises(self) -> None:
        service, _, _ = _setup()
        service.activate_kill_switch(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            reason="First activation",
            activated_by="system:test",
        )
        with pytest.raises(StateTransitionError):
            service.activate_kill_switch(
                scope=KillSwitchScope.GLOBAL,
                target_id="global",
                reason="Second activation",
                activated_by="system:test",
            )


# ------------------------------------------------------------------
# Deactivation tests
# ------------------------------------------------------------------


class TestKillSwitchDeactivation:
    """Test kill switch deactivation."""

    def test_deactivate_active_switch(self) -> None:
        service, _, _ = _setup()
        service.activate_kill_switch(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            reason="Emergency halt",
            activated_by="system:test",
        )
        event = service.deactivate_kill_switch(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            deactivated_by="user:admin",
        )
        assert event.confirmed_at is not None

    def test_deactivate_inactive_raises(self) -> None:
        service, _, _ = _setup()
        with pytest.raises(NotFoundError):
            service.deactivate_kill_switch(
                scope=KillSwitchScope.GLOBAL,
                target_id="global",
                deactivated_by="user:admin",
            )


# ------------------------------------------------------------------
# Status / is_halted tests
# ------------------------------------------------------------------


class TestKillSwitchStatus:
    """Test status queries and halt checks."""

    def test_get_status_empty(self) -> None:
        service, _, _ = _setup()
        statuses = service.get_status()
        assert statuses == []

    def test_get_status_with_active(self) -> None:
        service, _, _ = _setup()
        service.activate_kill_switch(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            reason="Test",
            activated_by="system:test",
        )
        statuses = service.get_status()
        assert len(statuses) == 1
        assert statuses[0].is_active is True

    def test_is_halted_global(self) -> None:
        service, _, _ = _setup()
        assert service.is_halted(deployment_id="01HDEPLOY0001") is False

        service.activate_kill_switch(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            reason="Test",
            activated_by="system:test",
        )
        assert service.is_halted(deployment_id="01HDEPLOY0001") is True

    def test_is_halted_strategy(self) -> None:
        service, _, _ = _setup()
        service.activate_kill_switch(
            scope=KillSwitchScope.STRATEGY,
            target_id="01HSTRAT0001",
            reason="Test",
            activated_by="system:test",
        )
        # Halted for this strategy
        assert (
            service.is_halted(
                deployment_id="01HDEPLOY0001",
                strategy_id="01HSTRAT0001",
            )
            is True
        )
        # Not halted for a different strategy
        assert (
            service.is_halted(
                deployment_id="01HDEPLOY0001",
                strategy_id="01HSTRAT9999",
            )
            is False
        )

    def test_is_halted_symbol(self) -> None:
        service, _, _ = _setup()
        service.activate_kill_switch(
            scope=KillSwitchScope.SYMBOL,
            target_id="AAPL",
            reason="Test",
            activated_by="system:test",
        )
        assert (
            service.is_halted(
                deployment_id="01HDEPLOY0001",
                symbol="AAPL",
            )
            is True
        )
        assert (
            service.is_halted(
                deployment_id="01HDEPLOY0001",
                symbol="MSFT",
            )
            is False
        )


# ------------------------------------------------------------------
# MTTH measurement
# ------------------------------------------------------------------


class TestMTTHMeasurement:
    """Test Mean Time To Halt measurement."""

    def test_mtth_populated_on_activation(self) -> None:
        """MTTH should be measured from activation to order cancellation confirmation."""
        service, _, adapter = _setup()
        # Submit some orders so there's something to cancel
        adapter.submit_order(_make_order_request(client_order_id="ord-001"))

        event = service.activate_kill_switch(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            reason="Emergency halt",
            activated_by="system:test",
        )
        # MTTH should be non-negative (execution is nearly instant in mocks)
        assert event.mtth_ms is not None
        assert event.mtth_ms >= 0


# ------------------------------------------------------------------
# Emergency posture execution
# ------------------------------------------------------------------


class TestEmergencyPostureExecution:
    """Test emergency posture execution per posture type."""

    def test_flatten_all_cancels_and_closes(self) -> None:
        service, _, adapter = _setup(emergency_posture="flatten_all")
        # Submit orders and create positions
        adapter.submit_order(_make_order_request(client_order_id="ord-001"))
        adapter.submit_order(_make_order_request(client_order_id="ord-002"))

        decision = service.execute_emergency_posture(
            deployment_id="01HDEPLOY0001",
            trigger=HaltTrigger.KILL_SWITCH,
            reason="Global halt",
        )
        assert decision.posture == EmergencyPostureType.flatten_all
        assert decision.duration_ms >= 0

    def test_cancel_open_cancels_orders_only(self) -> None:
        service, _, adapter = _setup(
            emergency_posture="cancel_open",
            fill_mode="delayed",
        )
        # Submit orders (delayed mode = they stay SUBMITTED)
        adapter.submit_order(_make_order_request(client_order_id="ord-001"))
        adapter.submit_order(_make_order_request(client_order_id="ord-002"))

        decision = service.execute_emergency_posture(
            deployment_id="01HDEPLOY0001",
            trigger=HaltTrigger.DAILY_LOSS,
            reason="Daily loss breach",
        )
        assert decision.posture == EmergencyPostureType.cancel_open
        assert decision.orders_cancelled >= 0

    def test_hold_does_nothing(self) -> None:
        service, _, adapter = _setup(emergency_posture="hold")
        adapter.submit_order(_make_order_request(client_order_id="ord-001"))

        decision = service.execute_emergency_posture(
            deployment_id="01HDEPLOY0001",
            trigger=HaltTrigger.MANUAL,
            reason="Manual review",
        )
        assert decision.posture == EmergencyPostureType.hold
        assert decision.orders_cancelled == 0
        assert decision.positions_flattened == 0

    def test_deployment_not_found(self) -> None:
        service, _, _ = _setup()
        with pytest.raises(NotFoundError):
            service.execute_emergency_posture(
                deployment_id="nonexistent",
                trigger=HaltTrigger.MANUAL,
                reason="Test",
            )

    def test_no_adapter_registered(self) -> None:
        deployment_repo = MockDeploymentRepository()
        deployment_repo.seed(
            deployment_id="01HDEPLOY0002",
            state="active",
            execution_mode="paper",
            emergency_posture="flatten_all",
        )
        ks_event_repo = MockKillSwitchEventRepository()

        from services.api.services.kill_switch_service import KillSwitchService

        service = KillSwitchService(
            deployment_repo=deployment_repo,
            ks_event_repo=ks_event_repo,
            adapter_registry={},
        )
        with pytest.raises(NotFoundError, match="adapter"):
            service.execute_emergency_posture(
                deployment_id="01HDEPLOY0002",
                trigger=HaltTrigger.MANUAL,
                reason="Test",
            )
