"""
Unit tests for the ShadowExecutionService.

Covers:
- Register/deregister deployment lifecycle
- Execute shadow order: happy path (signal → risk check → shadow fill → audit)
- Execute shadow order: deployment not found
- Execute shadow order: deployment not in executable state
- Execute shadow order: deployment not in shadow mode
- Market price updates
- Shadow decision timeline queries
- Shadow P&L queries
- Shadow position queries
- Shadow account queries
- Idempotent order execution
- Multi-deployment isolation

Per M3 spec: signal → shadow fill → position update → audit trail, no broker side-effects.
Same risk gate as paper/live (pass-through for M3, real gate in M5).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from libs.contracts.errors import NotFoundError, StateTransitionError, ValidationError
from libs.contracts.execution import (
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from libs.contracts.mocks.mock_risk_event_repository import MockRiskEventRepository
from services.api.services.risk_gate_service import RiskGateService
from services.api.services.shadow_execution_service import ShadowExecutionService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DEP_ID = "01HTESTDEP0000000000000001"


@pytest.fixture()
def deployment_repo() -> MockDeploymentRepository:
    repo = MockDeploymentRepository()
    return repo


@pytest.fixture()
def risk_gate(deployment_repo: MockDeploymentRepository) -> RiskGateService:
    return RiskGateService(
        deployment_repo=deployment_repo,
        risk_event_repo=MockRiskEventRepository(),
    )


@pytest.fixture()
def service(
    deployment_repo: MockDeploymentRepository, risk_gate: RiskGateService
) -> ShadowExecutionService:
    return ShadowExecutionService(deployment_repo=deployment_repo, risk_gate=risk_gate)


@pytest.fixture()
def active_shadow_deployment(
    deployment_repo: MockDeploymentRepository,
    service: ShadowExecutionService,
) -> str:
    """Create and register an active shadow deployment, return its ID."""
    record = deployment_repo.seed(
        deployment_id=DEP_ID,
        state="active",
        execution_mode="shadow",
        emergency_posture="flatten_all",
    )
    service.register_deployment(
        deployment_id=record["id"],
        initial_equity=Decimal("1000000"),
        market_prices={"AAPL": Decimal("175.50"), "MSFT": Decimal("420.00")},
    )
    return record["id"]


def _make_order(
    *,
    client_order_id: str = "ord-001",
    symbol: str = "AAPL",
    side: OrderSide = OrderSide.BUY,
    quantity: Decimal = Decimal("100"),
) -> OrderRequest:
    return OrderRequest(
        client_order_id=client_order_id,
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        time_in_force=TimeInForce.DAY,
        deployment_id=DEP_ID,
        strategy_id="01HTESTSTRT000000000000001",
        correlation_id="corr-shadow-test-001",
        execution_mode=ExecutionMode.SHADOW,
    )


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestRegistration:
    """Tests for deployment registration/deregistration."""

    def test_register_deployment(self, service: ShadowExecutionService) -> None:
        service.register_deployment(
            deployment_id="dep-001",
            initial_equity=Decimal("500000"),
        )
        # Should be able to query account after registration
        acct = service.get_shadow_account(deployment_id="dep-001")
        assert acct.equity == Decimal("500000")

    def test_register_duplicate_raises_validation_error(
        self, service: ShadowExecutionService
    ) -> None:
        service.register_deployment(
            deployment_id="dep-001",
            initial_equity=Decimal("500000"),
        )
        with pytest.raises(ValidationError, match="already registered"):
            service.register_deployment(
                deployment_id="dep-001",
                initial_equity=Decimal("500000"),
            )

    def test_deregister_deployment(self, service: ShadowExecutionService) -> None:
        service.register_deployment(
            deployment_id="dep-001",
            initial_equity=Decimal("500000"),
        )
        service.deregister_deployment(deployment_id="dep-001")
        with pytest.raises(NotFoundError):
            service.get_shadow_account(deployment_id="dep-001")

    def test_deregister_not_found(self, service: ShadowExecutionService) -> None:
        with pytest.raises(NotFoundError):
            service.deregister_deployment(deployment_id="nonexistent")


# ---------------------------------------------------------------------------
# Execute shadow order tests
# ---------------------------------------------------------------------------


class TestExecuteShadowOrder:
    """Tests for shadow order execution pipeline."""

    def test_happy_path_instant_fill(
        self,
        service: ShadowExecutionService,
        active_shadow_deployment: str,
    ) -> None:
        """Signal → risk check → shadow fill at market price."""
        resp = service.execute_shadow_order(
            deployment_id=active_shadow_deployment,
            request=_make_order(),
            correlation_id="corr-001",
        )
        assert resp.status == OrderStatus.FILLED
        assert resp.average_fill_price == Decimal("175.50")
        assert resp.filled_quantity == Decimal("100")
        assert resp.execution_mode == ExecutionMode.SHADOW

    def test_broker_order_id_is_shadow_prefixed(
        self,
        service: ShadowExecutionService,
        active_shadow_deployment: str,
    ) -> None:
        resp = service.execute_shadow_order(
            deployment_id=active_shadow_deployment,
            request=_make_order(),
            correlation_id="corr-001",
        )
        assert resp.broker_order_id is not None
        assert resp.broker_order_id.startswith("SHADOW-")

    def test_deployment_not_found_raises(self, service: ShadowExecutionService) -> None:
        with pytest.raises(NotFoundError, match="not found"):
            service.execute_shadow_order(
                deployment_id="nonexistent",
                request=_make_order(),
                correlation_id="corr-001",
            )

    def test_deployment_not_active_raises(
        self,
        service: ShadowExecutionService,
        deployment_repo: MockDeploymentRepository,
    ) -> None:
        """Deployment must be in 'active' state to accept orders."""
        record = deployment_repo.seed(
            state="created",
            execution_mode="shadow",
        )
        service.register_deployment(
            deployment_id=record["id"],
            initial_equity=Decimal("1000000"),
        )
        with pytest.raises(StateTransitionError, match="not in executable state"):
            service.execute_shadow_order(
                deployment_id=record["id"],
                request=_make_order(),
                correlation_id="corr-001",
            )

    def test_deployment_not_shadow_mode_raises(
        self,
        service: ShadowExecutionService,
        deployment_repo: MockDeploymentRepository,
    ) -> None:
        """Deployment must be in 'shadow' execution mode."""
        record = deployment_repo.seed(
            state="active",
            execution_mode="paper",
        )
        service.register_deployment(
            deployment_id=record["id"],
            initial_equity=Decimal("1000000"),
        )
        with pytest.raises(StateTransitionError, match="not in shadow mode"):
            service.execute_shadow_order(
                deployment_id=record["id"],
                request=_make_order(),
                correlation_id="corr-001",
            )

    def test_adapter_not_registered_raises(
        self,
        service: ShadowExecutionService,
        deployment_repo: MockDeploymentRepository,
    ) -> None:
        """Deployment exists in repo but has no registered adapter."""
        deployment_repo.seed(
            deployment_id="dep-no-adapter",
            state="active",
            execution_mode="shadow",
        )
        with pytest.raises(NotFoundError, match="no active shadow adapter"):
            service.execute_shadow_order(
                deployment_id="dep-no-adapter",
                request=_make_order(),
                correlation_id="corr-001",
            )

    def test_idempotent_order_execution(
        self,
        service: ShadowExecutionService,
        active_shadow_deployment: str,
    ) -> None:
        """Same client_order_id returns existing response."""
        resp1 = service.execute_shadow_order(
            deployment_id=active_shadow_deployment,
            request=_make_order(client_order_id="ord-idem"),
            correlation_id="corr-001",
        )
        resp2 = service.execute_shadow_order(
            deployment_id=active_shadow_deployment,
            request=_make_order(client_order_id="ord-idem"),
            correlation_id="corr-001",
        )
        assert resp1.broker_order_id == resp2.broker_order_id

    def test_records_decision_timeline(
        self,
        service: ShadowExecutionService,
        active_shadow_deployment: str,
    ) -> None:
        """Each execution records submitted + filled events."""
        service.execute_shadow_order(
            deployment_id=active_shadow_deployment,
            request=_make_order(),
            correlation_id="corr-001",
        )
        decisions = service.get_shadow_decisions(
            deployment_id=active_shadow_deployment,
        )
        assert len(decisions) == 2
        assert decisions[0]["event_type"] == "shadow_order_submitted"
        assert decisions[1]["event_type"] == "shadow_order_filled"


# ---------------------------------------------------------------------------
# Market price update tests
# ---------------------------------------------------------------------------


class TestMarketPriceUpdate:
    """Tests for market price updates on shadow adapters."""

    def test_update_market_price(
        self,
        service: ShadowExecutionService,
        active_shadow_deployment: str,
    ) -> None:
        service.update_market_price(
            deployment_id=active_shadow_deployment,
            symbol="AAPL",
            price=Decimal("200.00"),
        )
        # Verify price update took effect via a new order
        resp = service.execute_shadow_order(
            deployment_id=active_shadow_deployment,
            request=_make_order(),
            correlation_id="corr-001",
        )
        assert resp.average_fill_price == Decimal("200.00")

    def test_update_price_not_found(self, service: ShadowExecutionService) -> None:
        with pytest.raises(NotFoundError):
            service.update_market_price(
                deployment_id="nonexistent",
                symbol="AAPL",
                price=Decimal("200.00"),
            )


# ---------------------------------------------------------------------------
# Shadow decision timeline tests
# ---------------------------------------------------------------------------


class TestShadowDecisions:
    """Tests for shadow decision timeline queries."""

    def test_empty_timeline(
        self,
        service: ShadowExecutionService,
        active_shadow_deployment: str,
    ) -> None:
        decisions = service.get_shadow_decisions(
            deployment_id=active_shadow_deployment,
        )
        assert decisions == []

    def test_timeline_includes_correlation_id(
        self,
        service: ShadowExecutionService,
        active_shadow_deployment: str,
    ) -> None:
        service.execute_shadow_order(
            deployment_id=active_shadow_deployment,
            request=_make_order(),
            correlation_id="corr-timeline-test",
        )
        decisions = service.get_shadow_decisions(
            deployment_id=active_shadow_deployment,
        )
        assert decisions[0]["correlation_id"] == "corr-shadow-test-001"

    def test_decisions_not_found(self, service: ShadowExecutionService) -> None:
        with pytest.raises(NotFoundError):
            service.get_shadow_decisions(deployment_id="nonexistent")


# ---------------------------------------------------------------------------
# Shadow P&L tests
# ---------------------------------------------------------------------------


class TestShadowPnL:
    """Tests for shadow P&L queries."""

    def test_pnl_with_open_position(
        self,
        service: ShadowExecutionService,
        active_shadow_deployment: str,
    ) -> None:
        service.execute_shadow_order(
            deployment_id=active_shadow_deployment,
            request=_make_order(),
            correlation_id="corr-001",
        )
        service.update_market_price(
            deployment_id=active_shadow_deployment,
            symbol="AAPL",
            price=Decimal("180.00"),
        )
        pnl = service.get_shadow_pnl(deployment_id=active_shadow_deployment)
        # (180 - 175.50) * 100 = 450
        assert pnl["total_unrealized_pnl"] == "450.00"

    def test_pnl_after_close(
        self,
        service: ShadowExecutionService,
        active_shadow_deployment: str,
    ) -> None:
        service.execute_shadow_order(
            deployment_id=active_shadow_deployment,
            request=_make_order(client_order_id="buy"),
            correlation_id="corr-001",
        )
        service.update_market_price(
            deployment_id=active_shadow_deployment,
            symbol="AAPL",
            price=Decimal("180.00"),
        )
        service.execute_shadow_order(
            deployment_id=active_shadow_deployment,
            request=_make_order(
                client_order_id="sell",
                side=OrderSide.SELL,
                quantity=Decimal("100"),
            ),
            correlation_id="corr-002",
        )
        pnl = service.get_shadow_pnl(deployment_id=active_shadow_deployment)
        assert pnl["total_realized_pnl"] == "450.00"

    def test_pnl_not_found(self, service: ShadowExecutionService) -> None:
        with pytest.raises(NotFoundError):
            service.get_shadow_pnl(deployment_id="nonexistent")


# ---------------------------------------------------------------------------
# Shadow position tests
# ---------------------------------------------------------------------------


class TestShadowPositions:
    """Tests for shadow position queries."""

    def test_positions_after_buy(
        self,
        service: ShadowExecutionService,
        active_shadow_deployment: str,
    ) -> None:
        service.execute_shadow_order(
            deployment_id=active_shadow_deployment,
            request=_make_order(),
            correlation_id="corr-001",
        )
        positions = service.get_shadow_positions(
            deployment_id=active_shadow_deployment,
        )
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert positions[0].quantity == Decimal("100")

    def test_positions_not_found(self, service: ShadowExecutionService) -> None:
        with pytest.raises(NotFoundError):
            service.get_shadow_positions(deployment_id="nonexistent")


# ---------------------------------------------------------------------------
# Shadow account tests
# ---------------------------------------------------------------------------


class TestShadowAccount:
    """Tests for shadow account queries."""

    def test_initial_account(
        self,
        service: ShadowExecutionService,
        active_shadow_deployment: str,
    ) -> None:
        acct = service.get_shadow_account(
            deployment_id=active_shadow_deployment,
        )
        assert acct.equity == Decimal("1000000")
        assert acct.account_id == "SHADOW-ACCOUNT"

    def test_account_reflects_unrealized_pnl(
        self,
        service: ShadowExecutionService,
        active_shadow_deployment: str,
    ) -> None:
        service.execute_shadow_order(
            deployment_id=active_shadow_deployment,
            request=_make_order(),
            correlation_id="corr-001",
        )
        service.update_market_price(
            deployment_id=active_shadow_deployment,
            symbol="AAPL",
            price=Decimal("180.00"),
        )
        acct = service.get_shadow_account(
            deployment_id=active_shadow_deployment,
        )
        expected = Decimal("1000000") + Decimal("450")
        assert acct.equity == expected

    def test_account_not_found(self, service: ShadowExecutionService) -> None:
        with pytest.raises(NotFoundError):
            service.get_shadow_account(deployment_id="nonexistent")


# ---------------------------------------------------------------------------
# Multi-deployment isolation tests
# ---------------------------------------------------------------------------


class TestMultiDeploymentIsolation:
    """Tests that shadow adapters are isolated per deployment."""

    def test_separate_deployments_have_independent_positions(
        self,
        service: ShadowExecutionService,
        deployment_repo: MockDeploymentRepository,
    ) -> None:
        dep1 = deployment_repo.seed(
            state="active",
            execution_mode="shadow",
        )
        dep2 = deployment_repo.seed(
            state="active",
            execution_mode="shadow",
        )
        service.register_deployment(
            deployment_id=dep1["id"],
            initial_equity=Decimal("1000000"),
            market_prices={"AAPL": Decimal("175.50")},
        )
        service.register_deployment(
            deployment_id=dep2["id"],
            initial_equity=Decimal("500000"),
            market_prices={"AAPL": Decimal("175.50")},
        )

        # Execute order only on dep1
        service.execute_shadow_order(
            deployment_id=dep1["id"],
            request=OrderRequest(
                client_order_id="ord-dep1",
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("100"),
                time_in_force=TimeInForce.DAY,
                deployment_id=dep1["id"],
                strategy_id="01HTESTSTRT000000000000001",
                correlation_id="corr-dep1",
                execution_mode=ExecutionMode.SHADOW,
            ),
            correlation_id="corr-dep1",
        )

        # dep1 has position, dep2 does not
        pos1 = service.get_shadow_positions(deployment_id=dep1["id"])
        pos2 = service.get_shadow_positions(deployment_id=dep2["id"])
        assert len(pos1) == 1
        assert len(pos2) == 0

        # Different initial equity
        acct1 = service.get_shadow_account(deployment_id=dep1["id"])
        acct2 = service.get_shadow_account(deployment_id=dep2["id"])
        assert acct1.equity != acct2.equity
