"""
Unit tests for the PaperExecutionService.

Covers:
- Register/deregister deployment lifecycle
- Submit paper order: happy path
- Submit paper order: deployment not found / not active / not paper mode
- Process pending orders
- Cancel paper order
- Market price updates
- Position queries
- Account queries
- Open order queries
- Reconciliation via get_all_order_states
- Multi-deployment isolation

Per M4 spec: strategy signal → risk gate → paper fill → position → recon.
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
from services.api.services.paper_execution_service import PaperExecutionService
from services.api.services.risk_gate_service import RiskGateService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DEP_ID = "01HTESTDEP0000000000000001"


@pytest.fixture()
def deployment_repo() -> MockDeploymentRepository:
    return MockDeploymentRepository()


@pytest.fixture()
def risk_gate(deployment_repo: MockDeploymentRepository) -> RiskGateService:
    return RiskGateService(
        deployment_repo=deployment_repo,
        risk_event_repo=MockRiskEventRepository(),
    )


@pytest.fixture()
def service(
    deployment_repo: MockDeploymentRepository, risk_gate: RiskGateService
) -> PaperExecutionService:
    return PaperExecutionService(deployment_repo=deployment_repo, risk_gate=risk_gate)


@pytest.fixture()
def active_paper_deployment(
    deployment_repo: MockDeploymentRepository,
    service: PaperExecutionService,
) -> str:
    """Create and register an active paper deployment, return its ID."""
    record = deployment_repo.seed(
        deployment_id=DEP_ID,
        state="active",
        execution_mode="paper",
        emergency_posture="flatten_all",
    )
    service.register_deployment(
        deployment_id=record["id"],
        initial_equity=Decimal("1000000"),
        market_prices={"AAPL": Decimal("175.50"), "MSFT": Decimal("420.00")},
        commission_per_order=Decimal("1.00"),
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
        correlation_id="corr-paper-test-001",
        execution_mode=ExecutionMode.PAPER,
    )


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestRegistration:
    """Tests for deployment registration/deregistration."""

    def test_register_deployment(self, service: PaperExecutionService) -> None:
        service.register_deployment(
            deployment_id="dep-001",
            initial_equity=Decimal("500000"),
        )
        acct = service.get_paper_account(deployment_id="dep-001")
        assert acct.equity == Decimal("500000")

    def test_register_duplicate_raises(self, service: PaperExecutionService) -> None:
        service.register_deployment(
            deployment_id="dep-001",
            initial_equity=Decimal("500000"),
        )
        with pytest.raises(ValidationError, match="already registered"):
            service.register_deployment(
                deployment_id="dep-001",
                initial_equity=Decimal("500000"),
            )

    def test_deregister_deployment(self, service: PaperExecutionService) -> None:
        service.register_deployment(
            deployment_id="dep-001",
            initial_equity=Decimal("500000"),
        )
        service.deregister_deployment(deployment_id="dep-001")
        with pytest.raises(NotFoundError):
            service.get_paper_account(deployment_id="dep-001")

    def test_deregister_not_found(self, service: PaperExecutionService) -> None:
        with pytest.raises(NotFoundError):
            service.deregister_deployment(deployment_id="nonexistent")


# ---------------------------------------------------------------------------
# Submit paper order tests
# ---------------------------------------------------------------------------


class TestSubmitPaperOrder:
    """Tests for paper order submission."""

    def test_happy_path_returns_submitted(
        self, service: PaperExecutionService, active_paper_deployment: str
    ) -> None:
        resp = service.submit_paper_order(
            deployment_id=active_paper_deployment,
            request=_make_order(),
            correlation_id="corr-001",
        )
        assert resp.status == OrderStatus.SUBMITTED
        assert resp.broker_order_id.startswith("PAPER-")

    def test_deployment_not_found(self, service: PaperExecutionService) -> None:
        with pytest.raises(NotFoundError):
            service.submit_paper_order(
                deployment_id="nonexistent",
                request=_make_order(),
                correlation_id="corr-001",
            )

    def test_deployment_not_active(
        self, service: PaperExecutionService, deployment_repo: MockDeploymentRepository
    ) -> None:
        record = deployment_repo.seed(state="created", execution_mode="paper")
        service.register_deployment(
            deployment_id=record["id"],
            initial_equity=Decimal("1000000"),
        )
        with pytest.raises(StateTransitionError, match="not in executable state"):
            service.submit_paper_order(
                deployment_id=record["id"],
                request=_make_order(),
                correlation_id="corr-001",
            )

    def test_deployment_not_paper_mode(
        self, service: PaperExecutionService, deployment_repo: MockDeploymentRepository
    ) -> None:
        record = deployment_repo.seed(state="active", execution_mode="shadow")
        service.register_deployment(
            deployment_id=record["id"],
            initial_equity=Decimal("1000000"),
        )
        with pytest.raises(StateTransitionError, match="not in paper mode"):
            service.submit_paper_order(
                deployment_id=record["id"],
                request=_make_order(),
                correlation_id="corr-001",
            )


# ---------------------------------------------------------------------------
# Process pending orders tests
# ---------------------------------------------------------------------------


class TestProcessPendingOrders:
    """Tests for tick-based order processing."""

    def test_market_order_fills_on_process(
        self, service: PaperExecutionService, active_paper_deployment: str
    ) -> None:
        service.submit_paper_order(
            deployment_id=active_paper_deployment,
            request=_make_order(),
            correlation_id="corr-001",
        )
        filled = service.process_pending_orders(deployment_id=active_paper_deployment)
        assert len(filled) == 1
        assert filled[0].status == OrderStatus.FILLED
        assert filled[0].average_fill_price == Decimal("175.50")

    def test_process_not_found(self, service: PaperExecutionService) -> None:
        with pytest.raises(NotFoundError):
            service.process_pending_orders(deployment_id="nonexistent")


# ---------------------------------------------------------------------------
# Cancel order tests
# ---------------------------------------------------------------------------


class TestCancelPaperOrder:
    """Tests for paper order cancellation."""

    def test_cancel_pending(
        self, service: PaperExecutionService, active_paper_deployment: str
    ) -> None:
        resp = service.submit_paper_order(
            deployment_id=active_paper_deployment,
            request=_make_order(),
            correlation_id="corr-001",
        )
        cancel = service.cancel_paper_order(
            deployment_id=active_paper_deployment,
            broker_order_id=resp.broker_order_id,
            correlation_id="corr-002",
        )
        assert cancel.status == OrderStatus.CANCELLED


# ---------------------------------------------------------------------------
# Query tests
# ---------------------------------------------------------------------------


class TestQueries:
    """Tests for paper query methods."""

    def test_positions_after_fill(
        self, service: PaperExecutionService, active_paper_deployment: str
    ) -> None:
        service.submit_paper_order(
            deployment_id=active_paper_deployment,
            request=_make_order(),
            correlation_id="corr-001",
        )
        service.process_pending_orders(deployment_id=active_paper_deployment)
        positions = service.get_paper_positions(deployment_id=active_paper_deployment)
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert positions[0].quantity == Decimal("100")

    def test_open_orders(
        self, service: PaperExecutionService, active_paper_deployment: str
    ) -> None:
        service.submit_paper_order(
            deployment_id=active_paper_deployment,
            request=_make_order(),
            correlation_id="corr-001",
        )
        opens = service.get_open_orders(deployment_id=active_paper_deployment)
        assert len(opens) == 1

    def test_reconciliation(
        self, service: PaperExecutionService, active_paper_deployment: str
    ) -> None:
        service.submit_paper_order(
            deployment_id=active_paper_deployment,
            request=_make_order(),
            correlation_id="corr-001",
        )
        service.process_pending_orders(deployment_id=active_paper_deployment)
        states = service.get_all_order_states(deployment_id=active_paper_deployment)
        assert len(states) == 1
        assert states[0].status == OrderStatus.FILLED


# ---------------------------------------------------------------------------
# Multi-deployment isolation tests
# ---------------------------------------------------------------------------


class TestMultiDeploymentIsolation:
    """Paper adapters are isolated per deployment."""

    def test_separate_deployments(
        self, service: PaperExecutionService, deployment_repo: MockDeploymentRepository
    ) -> None:
        dep1 = deployment_repo.seed(state="active", execution_mode="paper")
        dep2 = deployment_repo.seed(state="active", execution_mode="paper")
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

        service.submit_paper_order(
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
                execution_mode=ExecutionMode.PAPER,
            ),
            correlation_id="corr-dep1",
        )
        service.process_pending_orders(deployment_id=dep1["id"])

        pos1 = service.get_paper_positions(deployment_id=dep1["id"])
        pos2 = service.get_paper_positions(deployment_id=dep2["id"])
        assert len(pos1) == 1
        assert len(pos2) == 0
