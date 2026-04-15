"""
Unit tests for M10 enhancements: Structural Risk Gate Enforcement.

Covers:
- RiskGateRejectionError raised (not returned) on risk check failure
- enforce_order() persists RiskEvent for both pass and fail outcomes
- enforce_order() returns silently on success
- RiskGateRejectionError includes check details (check_name, severity, etc.)
- Paper execution service requires risk gate (not optional)
- Shadow execution service requires risk gate (not optional)
- No code path submits order without risk check
- Existing check_order() still works for backward compatibility

Dependencies:
- libs.contracts.mocks.mock_deployment_repository: MockDeploymentRepository
- libs.contracts.mocks.mock_risk_event_repository: MockRiskEventRepository
- services.api.services.risk_gate_service: RiskGateService
- services.api.services.paper_execution_service: PaperExecutionService
- services.api.services.shadow_execution_service: ShadowExecutionService
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from libs.contracts.errors import RiskGateRejectionError, ValidationError
from libs.contracts.execution import (
    AccountSnapshot,
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

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

DEP_ID = "01HDEPLOY0001"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_order(
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
        strategy_id="01HSTRAT0001",
        correlation_id="corr-001",
        execution_mode=ExecutionMode.PAPER,
    )


def _make_account(equity: Decimal = Decimal("100000")) -> AccountSnapshot:
    from datetime import datetime, timezone

    return AccountSnapshot(
        account_id="MOCK-ACCOUNT",
        equity=equity,
        cash=equity,
        buying_power=equity * 2,
        portfolio_value=Decimal("0"),
        daily_pnl=Decimal("0"),
        open_order_count=0,
        updated_at=datetime.now(timezone.utc),
    )


def _setup_risk_gate(
    max_order_value: Decimal = Decimal("999999"),
    max_position_size: Decimal = Decimal("999999"),
) -> tuple[RiskGateService, MockDeploymentRepository, MockRiskEventRepository]:
    deployment_repo = MockDeploymentRepository()
    deployment_repo.seed(
        deployment_id=DEP_ID,
        state="active",
        execution_mode="paper",
        emergency_posture="flatten_all",
        strategy_id="01HSTRAT0001",
    )
    risk_event_repo = MockRiskEventRepository()
    risk_gate = RiskGateService(
        deployment_repo=deployment_repo,
        risk_event_repo=risk_event_repo,
    )
    risk_gate.set_risk_limits(
        deployment_id=DEP_ID,
        limits=PreTradeRiskLimits(
            max_order_value=max_order_value,
            max_position_size=max_position_size,
        ),
    )
    return risk_gate, deployment_repo, risk_event_repo


# ------------------------------------------------------------------
# RiskGateRejectionError Contract Tests
# ------------------------------------------------------------------


class TestRiskGateRejectionError:
    """Tests for the RiskGateRejectionError exception class."""

    def test_is_subclass_of_validation_error(self) -> None:
        """RiskGateRejectionError inherits from ValidationError."""
        assert issubclass(RiskGateRejectionError, ValidationError)

    def test_error_includes_check_details(self) -> None:
        """Error instance carries check_name, severity, reason, etc."""
        error = RiskGateRejectionError(
            "Order blocked",
            check_name="order_value",
            severity="critical",
            reason="Order value 17550.00 exceeds limit 1000.00",
            deployment_id=DEP_ID,
            order_client_id="ord-001",
            current_value="17550.00",
            limit_value="1000.00",
        )
        assert error.check_name == "order_value"
        assert error.severity == "critical"
        assert error.reason == "Order value 17550.00 exceeds limit 1000.00"
        assert error.deployment_id == DEP_ID
        assert error.order_client_id == "ord-001"
        assert error.current_value == "17550.00"
        assert error.limit_value == "1000.00"
        assert str(error) == "Order blocked"

    def test_error_default_attributes(self) -> None:
        """Default attribute values are empty strings."""
        error = RiskGateRejectionError("blocked")
        assert error.check_name == ""
        assert error.severity == ""
        assert error.deployment_id == ""


# ------------------------------------------------------------------
# enforce_order() Tests
# ------------------------------------------------------------------


class TestEnforceOrder:
    """Tests for the enforce_order() structural enforcement method."""

    def test_enforce_order_returns_silently_on_success(self) -> None:
        """Passing risk checks → enforce_order returns None (no exception)."""
        risk_gate, _, _ = _setup_risk_gate(max_order_value=Decimal("999999"))
        # Should not raise
        risk_gate.enforce_order(
            deployment_id=DEP_ID,
            order=_make_order(),
            positions=[],
            account=_make_account(),
            correlation_id="corr-001",
        )

    def test_enforce_order_raises_on_failure(self) -> None:
        """Failing risk check → RiskGateRejectionError raised."""
        risk_gate, _, _ = _setup_risk_gate(max_order_value=Decimal("1"))
        with pytest.raises(RiskGateRejectionError, match="order_value"):
            risk_gate.enforce_order(
                deployment_id=DEP_ID,
                order=_make_order(),
                positions=[],
                account=_make_account(),
                correlation_id="corr-fail",
            )

    def test_enforce_order_error_includes_check_details(self) -> None:
        """RiskGateRejectionError carries the failing check's details."""
        risk_gate, _, _ = _setup_risk_gate(max_order_value=Decimal("1"))
        with pytest.raises(RiskGateRejectionError) as exc_info:
            risk_gate.enforce_order(
                deployment_id=DEP_ID,
                order=_make_order(),
                positions=[],
                account=_make_account(),
                correlation_id="corr-details",
            )
        error = exc_info.value
        assert error.check_name == "order_value"
        assert error.deployment_id == DEP_ID
        assert error.order_client_id == "ord-001"
        # current_value and limit_value should be populated
        assert error.current_value != ""
        assert error.limit_value != ""

    def test_enforce_order_persists_event_on_failure(self) -> None:
        """Risk event is persisted even when enforce_order raises."""
        risk_gate, _, risk_event_repo = _setup_risk_gate(max_order_value=Decimal("1"))
        initial_count = len(risk_event_repo.list_by_deployment(deployment_id=DEP_ID))

        with pytest.raises(RiskGateRejectionError):
            risk_gate.enforce_order(
                deployment_id=DEP_ID,
                order=_make_order(),
                positions=[],
                account=_make_account(),
                correlation_id="corr-persist-fail",
            )

        events = risk_event_repo.list_by_deployment(deployment_id=DEP_ID)
        assert len(events) > initial_count
        # The failed event should be recorded
        failed_events = [e for e in events if not e.passed]
        assert len(failed_events) >= 1

    def test_enforce_order_persists_event_on_success(self) -> None:
        """Risk event is persisted for passing checks too."""
        risk_gate, _, risk_event_repo = _setup_risk_gate(max_order_value=Decimal("999999"))
        initial_count = len(risk_event_repo.list_by_deployment(deployment_id=DEP_ID))

        risk_gate.enforce_order(
            deployment_id=DEP_ID,
            order=_make_order(),
            positions=[],
            account=_make_account(),
            correlation_id="corr-persist-pass",
        )

        events = risk_event_repo.list_by_deployment(deployment_id=DEP_ID)
        assert len(events) > initial_count


# ------------------------------------------------------------------
# Execution Service Structural Enforcement
# ------------------------------------------------------------------


class TestPaperServiceRequiresRiskGate:
    """Paper execution service must have a risk gate — not optional."""

    def test_paper_service_rejects_order_on_risk_failure(self) -> None:
        """Paper order rejected with RiskGateRejectionError when risk fails."""
        risk_gate, deployment_repo, _ = _setup_risk_gate(max_order_value=Decimal("1"))
        service = PaperExecutionService(
            deployment_repo=deployment_repo,
            risk_gate=risk_gate,
        )
        service.register_deployment(
            deployment_id=DEP_ID,
            initial_equity=Decimal("1000000"),
            market_prices={"AAPL": Decimal("175.50")},
        )
        with pytest.raises(RiskGateRejectionError, match="order_value"):
            service.submit_paper_order(
                deployment_id=DEP_ID,
                request=_make_order(),
                correlation_id="corr-paper-fail",
            )

    def test_paper_service_accepts_order_on_risk_success(self) -> None:
        """Paper order accepted when risk checks pass."""
        risk_gate, deployment_repo, _ = _setup_risk_gate(max_order_value=Decimal("999999"))
        service = PaperExecutionService(
            deployment_repo=deployment_repo,
            risk_gate=risk_gate,
        )
        service.register_deployment(
            deployment_id=DEP_ID,
            initial_equity=Decimal("1000000"),
            market_prices={"AAPL": Decimal("175.50")},
        )
        response = service.submit_paper_order(
            deployment_id=DEP_ID,
            request=_make_order(),
            correlation_id="corr-paper-pass",
        )
        assert response is not None
        assert response.symbol == "AAPL"


class TestShadowServiceRequiresRiskGate:
    """Shadow execution service must have a risk gate — not optional."""

    def _setup_shadow(
        self,
        max_order_value: Decimal,
    ) -> tuple[ShadowExecutionService, RiskGateService]:
        """Create shadow service with proper shadow-mode deployment."""
        deployment_repo = MockDeploymentRepository()
        deployment_repo.seed(
            deployment_id=DEP_ID,
            state="active",
            execution_mode="shadow",
            emergency_posture="flatten_all",
            strategy_id="01HSTRAT0001",
        )
        risk_event_repo = MockRiskEventRepository()
        risk_gate = RiskGateService(
            deployment_repo=deployment_repo,
            risk_event_repo=risk_event_repo,
        )
        risk_gate.set_risk_limits(
            deployment_id=DEP_ID,
            limits=PreTradeRiskLimits(max_order_value=max_order_value),
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
        return service, risk_gate

    def test_shadow_service_rejects_order_on_risk_failure(self) -> None:
        """Shadow order rejected with RiskGateRejectionError when risk fails."""
        service, _ = self._setup_shadow(max_order_value=Decimal("1"))
        with pytest.raises(RiskGateRejectionError, match="order_value"):
            service.execute_shadow_order(
                deployment_id=DEP_ID,
                request=_make_order(),
                correlation_id="corr-shadow-fail",
            )

    def test_shadow_service_accepts_order_on_risk_success(self) -> None:
        """Shadow order accepted when risk checks pass."""
        service, _ = self._setup_shadow(max_order_value=Decimal("999999"))
        response = service.execute_shadow_order(
            deployment_id=DEP_ID,
            request=_make_order(),
            correlation_id="corr-shadow-pass",
        )
        assert response is not None
        assert response.symbol == "AAPL"


# ------------------------------------------------------------------
# Backward Compatibility: check_order still works
# ------------------------------------------------------------------


class TestCheckOrderBackwardCompat:
    """check_order() still returns results (not raises) for inspection."""

    def test_check_order_returns_result_on_failure(self) -> None:
        """check_order returns RiskCheckResult with passed=False (does not raise)."""
        risk_gate, _, _ = _setup_risk_gate(max_order_value=Decimal("1"))
        result = risk_gate.check_order(
            deployment_id=DEP_ID,
            order=_make_order(),
            positions=[],
            account=_make_account(),
            correlation_id="corr-compat",
        )
        assert result.passed is False
        assert result.check_name == "order_value"
