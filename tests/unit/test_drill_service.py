"""
Unit tests for DrillService.

Covers:
- Kill switch drill execution and MTTH measurement.
- Rollback drill execution.
- Reconnect drill execution.
- Failover drill execution with reconciliation.
- Live eligibility gating (all drills must pass).
- Drill history retrieval.
- Error paths (not found, invalid drill type).

Dependencies:
- libs.contracts.mocks.mock_broker_adapter: MockBrokerAdapter
- libs.contracts.mocks.mock_deployment_repository: MockDeploymentRepository
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from libs.contracts.drill import DrillType
from libs.contracts.errors import NotFoundError
from libs.contracts.execution import (
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)
from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

DEP_ID = "01HDEPLOY0001"
STRAT_ID = "01HSTRAT0001"


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


def _setup(fill_mode: str = "instant"):
    deployment_repo = MockDeploymentRepository()
    deployment_repo.seed(
        deployment_id=DEP_ID,
        strategy_id=STRAT_ID,
        state="active",
        execution_mode="paper",
        emergency_posture="flatten_all",
    )
    adapter = MockBrokerAdapter(fill_mode=fill_mode)

    from services.api.services.drill_service import DrillService

    service = DrillService(
        deployment_repo=deployment_repo,
        adapter_registry={DEP_ID: adapter},
    )
    return service, deployment_repo, adapter


# ------------------------------------------------------------------
# Kill switch drill
# ------------------------------------------------------------------


class TestKillSwitchDrill:
    """Tests for kill switch drill execution."""

    def test_kill_switch_drill_passes(self) -> None:
        """Kill switch drill should pass with MTTH measurement."""
        service, _, adapter = _setup()
        # Submit an open order so the drill has something to cancel
        adapter.submit_order(_make_order_request())

        result = service.execute_drill(
            drill_type="kill_switch",
            deployment_id=DEP_ID,
        )
        assert result.passed is True
        assert result.drill_type == DrillType.KILL_SWITCH
        assert result.deployment_id == DEP_ID
        assert result.mtth_ms is not None
        assert result.mtth_ms >= 0
        assert len(result.timeline) >= 1

    def test_kill_switch_drill_no_open_orders(self) -> None:
        """Kill switch drill with no open orders still passes."""
        service, _, _ = _setup()
        result = service.execute_drill(
            drill_type="kill_switch",
            deployment_id=DEP_ID,
        )
        assert result.passed is True
        assert result.drill_type == DrillType.KILL_SWITCH


# ------------------------------------------------------------------
# Rollback drill
# ------------------------------------------------------------------


class TestRollbackDrill:
    """Tests for rollback drill execution."""

    def test_rollback_drill_passes(self) -> None:
        """Rollback drill should pass for valid deployment."""
        service, _, _ = _setup()
        result = service.execute_drill(
            drill_type="rollback",
            deployment_id=DEP_ID,
        )
        assert result.passed is True
        assert result.drill_type == DrillType.ROLLBACK
        assert len(result.timeline) >= 1


# ------------------------------------------------------------------
# Reconnect drill
# ------------------------------------------------------------------


class TestReconnectDrill:
    """Tests for reconnect drill execution."""

    def test_reconnect_drill_passes(self) -> None:
        """Reconnect drill should pass for valid deployment with adapter."""
        service, _, _ = _setup()
        result = service.execute_drill(
            drill_type="reconnect",
            deployment_id=DEP_ID,
        )
        assert result.passed is True
        assert result.drill_type == DrillType.RECONNECT
        assert len(result.timeline) >= 1


# ------------------------------------------------------------------
# Failover drill
# ------------------------------------------------------------------


class TestFailoverDrill:
    """Tests for failover drill execution."""

    def test_failover_drill_passes(self) -> None:
        """Failover drill should pass with reconciliation check."""
        service, _, _ = _setup()
        result = service.execute_drill(
            drill_type="failover",
            deployment_id=DEP_ID,
        )
        assert result.passed is True
        assert result.drill_type == DrillType.FAILOVER
        assert len(result.timeline) >= 1


# ------------------------------------------------------------------
# Error paths
# ------------------------------------------------------------------


class TestDrillErrors:
    """Tests for drill error conditions."""

    def test_deployment_not_found(self) -> None:
        """Nonexistent deployment raises NotFoundError."""
        service, _, _ = _setup()
        with pytest.raises(NotFoundError):
            service.execute_drill(
                drill_type="kill_switch",
                deployment_id="nonexistent",
            )

    def test_invalid_drill_type(self) -> None:
        """Invalid drill type raises ValueError."""
        service, _, _ = _setup()
        with pytest.raises(ValueError, match="Invalid drill type"):
            service.execute_drill(
                drill_type="invalid_drill",
                deployment_id=DEP_ID,
            )


# ------------------------------------------------------------------
# Live eligibility
# ------------------------------------------------------------------


class TestLiveEligibility:
    """Tests for live deployment eligibility checks."""

    def test_not_eligible_without_drills(self) -> None:
        """Deployment without drill results is not eligible."""
        service, _, _ = _setup()
        eligible, missing = service.check_live_eligibility(
            deployment_id=DEP_ID,
        )
        assert eligible is False
        assert len(missing) == 4  # All 4 drill types missing

    def test_eligible_after_all_drills_pass(self) -> None:
        """Deployment is eligible after passing all drill types."""
        service, _, _ = _setup()
        for drill_type in ["kill_switch", "rollback", "reconnect", "failover"]:
            service.execute_drill(
                drill_type=drill_type,
                deployment_id=DEP_ID,
            )

        eligible, missing = service.check_live_eligibility(
            deployment_id=DEP_ID,
        )
        assert eligible is True
        assert len(missing) == 0

    def test_partial_drills_not_eligible(self) -> None:
        """Deployment with only some drills passed is not eligible."""
        service, _, _ = _setup()
        service.execute_drill(drill_type="kill_switch", deployment_id=DEP_ID)
        service.execute_drill(drill_type="rollback", deployment_id=DEP_ID)

        eligible, missing = service.check_live_eligibility(
            deployment_id=DEP_ID,
        )
        assert eligible is False
        assert len(missing) == 2

    def test_eligibility_deployment_not_found(self) -> None:
        """Nonexistent deployment raises NotFoundError."""
        service, _, _ = _setup()
        with pytest.raises(NotFoundError):
            service.check_live_eligibility(deployment_id="nonexistent")


# ------------------------------------------------------------------
# Drill history
# ------------------------------------------------------------------


class TestDrillHistory:
    """Tests for drill history retrieval."""

    def test_empty_history(self) -> None:
        """No drill results returns empty list."""
        service, _, _ = _setup()
        history = service.get_drill_history(deployment_id=DEP_ID)
        assert history == []

    def test_history_after_drills(self) -> None:
        """History contains all executed drills."""
        service, _, _ = _setup()
        service.execute_drill(drill_type="kill_switch", deployment_id=DEP_ID)
        service.execute_drill(drill_type="rollback", deployment_id=DEP_ID)

        history = service.get_drill_history(deployment_id=DEP_ID)
        assert len(history) == 2
        types = {r.drill_type for r in history}
        assert DrillType.KILL_SWITCH in types
        assert DrillType.ROLLBACK in types
