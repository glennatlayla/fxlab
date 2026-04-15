"""
Integration tests for risk gate wiring into execution services.

Covers:
- Paper execution: order rejected when risk check fails
- Paper execution: order accepted when risk check passes
- Shadow execution: order rejected when risk check fails
- Shadow execution: order accepted when risk check passes

Per M5 spec: every order passes through risk gate before adapter.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from libs.contracts.errors import ValidationError
from libs.contracts.execution import (
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from libs.contracts.mocks.mock_risk_event_repository import MockRiskEventRepository
from libs.contracts.risk import PreTradeRiskLimits
from services.api.services.paper_execution_service import PaperExecutionService
from services.api.services.risk_gate_service import RiskGateService
from services.api.services.shadow_execution_service import ShadowExecutionService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DEP_ID = "01HTESTDEP0000000000000001"


@pytest.fixture()
def deployment_repo() -> MockDeploymentRepository:
    return MockDeploymentRepository()


@pytest.fixture()
def event_repo() -> MockRiskEventRepository:
    return MockRiskEventRepository()


@pytest.fixture()
def risk_gate(
    deployment_repo: MockDeploymentRepository, event_repo: MockRiskEventRepository
) -> RiskGateService:
    return RiskGateService(deployment_repo=deployment_repo, risk_event_repo=event_repo)


def _make_order(
    *,
    client_order_id: str = "ord-001",
    symbol: str = "AAPL",
    quantity: Decimal = Decimal("100"),
) -> OrderRequest:
    return OrderRequest(
        client_order_id=client_order_id,
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=quantity,
        time_in_force=TimeInForce.DAY,
        deployment_id=DEP_ID,
        strategy_id="01HTESTSTRT000000000000001",
        correlation_id="corr-integration-001",
        execution_mode=ExecutionMode.PAPER,
    )


# ---------------------------------------------------------------------------
# Paper execution + risk gate
# ---------------------------------------------------------------------------


class TestPaperWithRiskGate:
    """Paper execution service with risk gate wired in."""

    def test_paper_order_rejected_by_risk_gate(
        self,
        deployment_repo: MockDeploymentRepository,
        risk_gate: RiskGateService,
    ) -> None:
        deployment_repo.seed(
            deployment_id=DEP_ID,
            state="active",
            execution_mode="paper",
            emergency_posture="flatten_all",
        )
        # Set very restrictive order value limit
        risk_gate.set_risk_limits(
            deployment_id=DEP_ID,
            limits=PreTradeRiskLimits(max_order_value=Decimal("1")),
        )
        service = PaperExecutionService(
            deployment_repo=deployment_repo,
            risk_gate=risk_gate,
        )
        service.register_deployment(
            deployment_id=DEP_ID,
            initial_equity=Decimal("1000000"),
            market_prices={"AAPL": Decimal("175.50")},
        )
        with pytest.raises(ValidationError, match="order_value"):
            service.submit_paper_order(
                deployment_id=DEP_ID,
                request=_make_order(),
                correlation_id="corr-001",
            )

    def test_paper_order_accepted_by_risk_gate(
        self,
        deployment_repo: MockDeploymentRepository,
        risk_gate: RiskGateService,
    ) -> None:
        deployment_repo.seed(
            deployment_id=DEP_ID,
            state="active",
            execution_mode="paper",
            emergency_posture="flatten_all",
        )
        # Set permissive limits
        risk_gate.set_risk_limits(
            deployment_id=DEP_ID,
            limits=PreTradeRiskLimits(max_order_value=Decimal("999999")),
        )
        service = PaperExecutionService(
            deployment_repo=deployment_repo,
            risk_gate=risk_gate,
        )
        service.register_deployment(
            deployment_id=DEP_ID,
            initial_equity=Decimal("1000000"),
            market_prices={"AAPL": Decimal("175.50")},
        )
        resp = service.submit_paper_order(
            deployment_id=DEP_ID,
            request=_make_order(),
            correlation_id="corr-001",
        )
        assert resp.status == "submitted"


# ---------------------------------------------------------------------------
# Shadow execution + risk gate
# ---------------------------------------------------------------------------


class TestShadowWithRiskGate:
    """Shadow execution service with risk gate wired in."""

    def test_shadow_order_rejected_by_risk_gate(
        self,
        deployment_repo: MockDeploymentRepository,
        risk_gate: RiskGateService,
    ) -> None:
        deployment_repo.seed(
            deployment_id=DEP_ID,
            state="active",
            execution_mode="shadow",
            emergency_posture="flatten_all",
        )
        risk_gate.set_risk_limits(
            deployment_id=DEP_ID,
            limits=PreTradeRiskLimits(max_order_value=Decimal("1")),
        )
        service = ShadowExecutionService(
            deployment_repo=deployment_repo,
            risk_gate=risk_gate,
        )
        service.register_deployment(
            deployment_id=DEP_ID,
            initial_equity=Decimal("1000000"),
            market_prices={"AAPL": Decimal("175.50")},
        )
        order = OrderRequest(
            client_order_id="ord-shadow-001",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            time_in_force=TimeInForce.DAY,
            deployment_id=DEP_ID,
            strategy_id="01HTESTSTRT000000000000001",
            correlation_id="corr-shadow-001",
            execution_mode=ExecutionMode.SHADOW,
        )
        with pytest.raises(ValidationError, match="order_value"):
            service.execute_shadow_order(
                deployment_id=DEP_ID,
                request=order,
                correlation_id="corr-001",
            )

    def test_shadow_order_accepted_by_risk_gate(
        self,
        deployment_repo: MockDeploymentRepository,
        risk_gate: RiskGateService,
    ) -> None:
        deployment_repo.seed(
            deployment_id=DEP_ID,
            state="active",
            execution_mode="shadow",
            emergency_posture="flatten_all",
        )
        risk_gate.set_risk_limits(
            deployment_id=DEP_ID,
            limits=PreTradeRiskLimits(max_order_value=Decimal("999999")),
        )
        service = ShadowExecutionService(
            deployment_repo=deployment_repo,
            risk_gate=risk_gate,
        )
        service.register_deployment(
            deployment_id=DEP_ID,
            initial_equity=Decimal("1000000"),
            market_prices={"AAPL": Decimal("175.50")},
        )
        order = OrderRequest(
            client_order_id="ord-shadow-002",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            time_in_force=TimeInForce.DAY,
            deployment_id=DEP_ID,
            strategy_id="01HTESTSTRT000000000000001",
            correlation_id="corr-shadow-002",
            execution_mode=ExecutionMode.SHADOW,
        )
        resp = service.execute_shadow_order(
            deployment_id=DEP_ID,
            request=order,
            correlation_id="corr-001",
        )
        assert resp.status == "filled"
