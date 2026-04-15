"""
Unit tests for the RiskGateService.

Covers:
- Set/get/clear risk limits lifecycle
- Order value check (pass + fail)
- Position size check (pass + fail)
- Concentration check (pass + fail)
- Open order count check (pass + fail)
- Daily loss check (pass + fail)
- Fail-fast ordering (cheapest check first)
- All checks pass → single pass result
- Risk events recorded for each check
- Zero limits (0 = unlimited) bypass check
- Multi-deployment isolation

Per M5 spec: every order must pass through risk gate before broker adapter.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from libs.contracts.execution import (
    AccountSnapshot,
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderType,
    PositionSnapshot,
    TimeInForce,
)
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from libs.contracts.mocks.mock_risk_event_repository import MockRiskEventRepository
from libs.contracts.risk import PreTradeRiskLimits, RiskEventSeverity
from services.api.services.risk_gate_service import RiskGateService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DEP_ID = "01HTESTDEP0000000000000001"


@pytest.fixture()
def deployment_repo() -> MockDeploymentRepository:
    repo = MockDeploymentRepository()
    repo.seed(deployment_id=DEP_ID, state="active", execution_mode="paper")
    return repo


@pytest.fixture()
def event_repo() -> MockRiskEventRepository:
    return MockRiskEventRepository()


@pytest.fixture()
def service(
    deployment_repo: MockDeploymentRepository, event_repo: MockRiskEventRepository
) -> RiskGateService:
    return RiskGateService(deployment_repo=deployment_repo, risk_event_repo=event_repo)


@pytest.fixture()
def limits() -> PreTradeRiskLimits:
    return PreTradeRiskLimits(
        max_position_size=Decimal("1000"),
        max_daily_loss=Decimal("5000"),
        max_order_value=Decimal("50000"),
        max_concentration_pct=Decimal("25"),
        max_open_orders=10,
    )


@pytest.fixture()
def service_with_limits(service: RiskGateService, limits: PreTradeRiskLimits) -> RiskGateService:
    service.set_risk_limits(deployment_id=DEP_ID, limits=limits)
    return service


def _make_order(
    *,
    symbol: str = "AAPL",
    side: OrderSide = OrderSide.BUY,
    quantity: Decimal = Decimal("100"),
    client_order_id: str = "ord-001",
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
        correlation_id="corr-risk-test-001",
        execution_mode=ExecutionMode.PAPER,
    )


def _make_account(
    *,
    equity: Decimal = Decimal("100000"),
    cash: Decimal = Decimal("50000"),
    portfolio_value: Decimal = Decimal("50000"),
    daily_pnl: Decimal = Decimal("0"),
    pending_orders_count: int = 0,
) -> AccountSnapshot:
    return AccountSnapshot(
        account_id="PAPER-ACCOUNT",
        equity=equity,
        cash=cash,
        buying_power=cash * Decimal("2"),
        portfolio_value=portfolio_value,
        daily_pnl=daily_pnl,
        pending_orders_count=pending_orders_count,
        positions_count=0,
        updated_at=datetime.now(timezone.utc),
    )


def _make_position(
    *,
    symbol: str = "AAPL",
    quantity: Decimal = Decimal("500"),
    market_price: Decimal = Decimal("175.50"),
) -> PositionSnapshot:
    market_value = quantity * market_price
    return PositionSnapshot(
        symbol=symbol,
        quantity=quantity,
        average_entry_price=Decimal("170.00"),
        market_price=market_price,
        market_value=market_value,
        unrealized_pnl=(market_price - Decimal("170.00")) * quantity,
        realized_pnl=Decimal("0"),
        cost_basis=quantity * Decimal("170.00"),
        updated_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Risk limits lifecycle tests
# ---------------------------------------------------------------------------


class TestRiskLimitsLifecycle:
    """Tests for set/get/clear risk limits."""

    def test_set_and_get_limits(self, service: RiskGateService, limits: PreTradeRiskLimits) -> None:
        service.set_risk_limits(deployment_id=DEP_ID, limits=limits)
        result = service.get_risk_limits(deployment_id=DEP_ID)
        assert result == limits

    def test_get_limits_not_found(self, service: RiskGateService) -> None:
        from libs.contracts.errors import NotFoundError

        with pytest.raises(NotFoundError):
            service.get_risk_limits(deployment_id="nonexistent")

    def test_clear_limits(self, service: RiskGateService, limits: PreTradeRiskLimits) -> None:
        from libs.contracts.errors import NotFoundError

        service.set_risk_limits(deployment_id=DEP_ID, limits=limits)
        service.clear_risk_limits(deployment_id=DEP_ID)
        with pytest.raises(NotFoundError):
            service.get_risk_limits(deployment_id=DEP_ID)

    def test_clear_limits_not_found(self, service: RiskGateService) -> None:
        from libs.contracts.errors import NotFoundError

        with pytest.raises(NotFoundError):
            service.clear_risk_limits(deployment_id="nonexistent")


# ---------------------------------------------------------------------------
# All checks pass
# ---------------------------------------------------------------------------


class TestAllChecksPass:
    """Tests where all risk checks pass."""

    def test_all_pass_small_order(self, service_with_limits: RiskGateService) -> None:
        order = _make_order(quantity=Decimal("100"))
        account = _make_account()
        result = service_with_limits.check_order(
            deployment_id=DEP_ID,
            order=order,
            positions=[],
            account=account,
            correlation_id="corr-001",
        )
        assert result.passed is True
        assert result.check_name == "all_checks_passed"

    def test_pass_records_events(
        self, service_with_limits: RiskGateService, event_repo: MockRiskEventRepository
    ) -> None:
        order = _make_order(quantity=Decimal("100"))
        account = _make_account()
        service_with_limits.check_order(
            deployment_id=DEP_ID,
            order=order,
            positions=[],
            account=account,
            correlation_id="corr-001",
        )
        # All 5 checks should have been recorded as passing events
        events = event_repo.get_all()
        assert len(events) >= 1
        assert all(e.passed for e in events)


# ---------------------------------------------------------------------------
# Order value check
# ---------------------------------------------------------------------------


class TestOrderValueCheck:
    """Tests for order value limit check."""

    def test_order_value_pass(self, service_with_limits: RiskGateService) -> None:
        # Order value = 100 * 175.50 = 17550 < 50000 limit
        # Equity must be high enough to not trigger concentration (25%) check
        order = _make_order(quantity=Decimal("100"))
        positions = [_make_position()]
        account = _make_account(equity=Decimal("1000000"))
        result = service_with_limits.check_order(
            deployment_id=DEP_ID,
            order=order,
            positions=positions,
            account=account,
            correlation_id="corr-001",
        )
        assert result.passed is True

    def test_order_value_fail(self, service: RiskGateService) -> None:
        # Set very low order value limit
        service.set_risk_limits(
            deployment_id=DEP_ID,
            limits=PreTradeRiskLimits(
                max_order_value=Decimal("1000"),
            ),
        )
        # Order value = 100 * 175.50 = 17550 > 1000 limit
        order = _make_order(quantity=Decimal("100"))
        positions = [_make_position()]
        account = _make_account()
        result = service.check_order(
            deployment_id=DEP_ID,
            order=order,
            positions=positions,
            account=account,
            correlation_id="corr-001",
        )
        assert result.passed is False
        assert result.check_name == "order_value"
        assert result.severity == RiskEventSeverity.CRITICAL


# ---------------------------------------------------------------------------
# Position size check
# ---------------------------------------------------------------------------


class TestPositionSizeCheck:
    """Tests for position size limit check."""

    def test_position_size_pass(self, service_with_limits: RiskGateService) -> None:
        # Existing position: 500, order: 100, total: 600 < 1000 limit
        # Equity must be high enough to not trigger concentration (25%) check
        order = _make_order(quantity=Decimal("100"))
        positions = [_make_position(quantity=Decimal("500"))]
        account = _make_account(equity=Decimal("1000000"))
        result = service_with_limits.check_order(
            deployment_id=DEP_ID,
            order=order,
            positions=positions,
            account=account,
            correlation_id="corr-001",
        )
        assert result.passed is True

    def test_position_size_fail(self, service_with_limits: RiskGateService) -> None:
        # Existing position: 900, order: 200, total: 1100 > 1000 limit
        order = _make_order(quantity=Decimal("200"))
        positions = [_make_position(quantity=Decimal("900"))]
        account = _make_account()
        result = service_with_limits.check_order(
            deployment_id=DEP_ID,
            order=order,
            positions=positions,
            account=account,
            correlation_id="corr-001",
        )
        assert result.passed is False
        assert result.check_name == "position_size"
        assert result.severity == RiskEventSeverity.CRITICAL


# ---------------------------------------------------------------------------
# Concentration check
# ---------------------------------------------------------------------------


class TestConcentrationCheck:
    """Tests for portfolio concentration limit check."""

    def test_concentration_pass(self, service_with_limits: RiskGateService) -> None:
        # Order value = 100 * 175.50 = 17550
        # Equity = 100000, concentration = 17550 / 100000 = 17.55% < 25%
        order = _make_order(quantity=Decimal("100"))
        positions = [_make_position(quantity=Decimal("0"))]
        account = _make_account(equity=Decimal("100000"))
        result = service_with_limits.check_order(
            deployment_id=DEP_ID,
            order=order,
            positions=positions,
            account=account,
            correlation_id="corr-001",
        )
        assert result.passed is True

    def test_concentration_fail(self, service: RiskGateService) -> None:
        service.set_risk_limits(
            deployment_id=DEP_ID,
            limits=PreTradeRiskLimits(
                max_concentration_pct=Decimal("10"),
            ),
        )
        # Existing AAPL position value = 500 * 175.50 = 87750
        # New order value = 100 * 175.50 = 17550
        # Total AAPL = 105300, equity = 100000
        # concentration = 105300/100000 = 105.3% > 10%
        order = _make_order(quantity=Decimal("100"))
        positions = [_make_position(quantity=Decimal("500"), market_price=Decimal("175.50"))]
        account = _make_account(equity=Decimal("100000"))
        result = service.check_order(
            deployment_id=DEP_ID,
            order=order,
            positions=positions,
            account=account,
            correlation_id="corr-001",
        )
        assert result.passed is False
        assert result.check_name == "concentration"
        assert result.severity == RiskEventSeverity.CRITICAL


# ---------------------------------------------------------------------------
# Open orders check
# ---------------------------------------------------------------------------


class TestOpenOrdersCheck:
    """Tests for open order count limit check."""

    def test_open_orders_pass(self, service_with_limits: RiskGateService) -> None:
        # 3 pending < 10 limit
        order = _make_order()
        account = _make_account(pending_orders_count=3)
        result = service_with_limits.check_order(
            deployment_id=DEP_ID,
            order=order,
            positions=[],
            account=account,
            correlation_id="corr-001",
        )
        assert result.passed is True

    def test_open_orders_fail(self, service_with_limits: RiskGateService) -> None:
        # 10 pending + 1 new = 11 > 10 limit
        order = _make_order()
        account = _make_account(pending_orders_count=10)
        result = service_with_limits.check_order(
            deployment_id=DEP_ID,
            order=order,
            positions=[],
            account=account,
            correlation_id="corr-001",
        )
        assert result.passed is False
        assert result.check_name == "open_orders"
        assert result.severity == RiskEventSeverity.CRITICAL


# ---------------------------------------------------------------------------
# Daily loss check
# ---------------------------------------------------------------------------


class TestDailyLossCheck:
    """Tests for daily loss limit check."""

    def test_daily_loss_pass(self, service_with_limits: RiskGateService) -> None:
        # Daily PnL = -2000, limit = -5000
        order = _make_order()
        account = _make_account(daily_pnl=Decimal("-2000"))
        result = service_with_limits.check_order(
            deployment_id=DEP_ID,
            order=order,
            positions=[],
            account=account,
            correlation_id="corr-001",
        )
        assert result.passed is True

    def test_daily_loss_fail(self, service_with_limits: RiskGateService) -> None:
        # Daily PnL = -6000, exceeds limit of -5000
        order = _make_order()
        account = _make_account(daily_pnl=Decimal("-6000"))
        result = service_with_limits.check_order(
            deployment_id=DEP_ID,
            order=order,
            positions=[],
            account=account,
            correlation_id="corr-001",
        )
        assert result.passed is False
        assert result.check_name == "daily_loss"
        assert result.severity == RiskEventSeverity.CRITICAL


# ---------------------------------------------------------------------------
# Zero limits (unlimited) bypass
# ---------------------------------------------------------------------------


class TestZeroLimitsUnlimited:
    """Tests that zero limits mean unlimited (no enforcement)."""

    def test_zero_limits_all_pass(self, service: RiskGateService) -> None:
        # All limits set to 0 = unlimited
        service.set_risk_limits(
            deployment_id=DEP_ID,
            limits=PreTradeRiskLimits(),  # all defaults are 0
        )
        order = _make_order(quantity=Decimal("999999"))
        positions = [_make_position(quantity=Decimal("999999"))]
        account = _make_account(
            equity=Decimal("1"),
            daily_pnl=Decimal("-999999"),
            pending_orders_count=99999,
        )
        result = service.check_order(
            deployment_id=DEP_ID,
            order=order,
            positions=positions,
            account=account,
            correlation_id="corr-001",
        )
        assert result.passed is True


# ---------------------------------------------------------------------------
# No limits configured — fail-closed for live, pass-through for paper/shadow
# ---------------------------------------------------------------------------


class TestNoLimitsConfigured:
    """Test fail-closed behavior when no limits are configured."""

    def test_no_limits_paper_mode_passes(self, service: RiskGateService) -> None:
        """Paper mode without limits should pass (backward compatible)."""
        order = _make_order()
        account = _make_account()
        result = service.check_order(
            deployment_id=DEP_ID,
            order=order,
            positions=[],
            account=account,
            correlation_id="corr-001",
        )
        assert result.passed is True
        assert result.check_name == "no_limits_configured"
        assert result.severity == RiskEventSeverity.INFO

    def test_no_limits_shadow_mode_passes(
        self, deployment_repo: MockDeploymentRepository, service: RiskGateService
    ) -> None:
        """Shadow mode without limits should pass (backward compatible)."""
        shadow_dep_id = "01HTESTSHADOW000000000001"
        deployment_repo.seed(deployment_id=shadow_dep_id, state="active", execution_mode="shadow")
        order = _make_order()
        account = _make_account()
        result = service.check_order(
            deployment_id=shadow_dep_id,
            order=order,
            positions=[],
            account=account,
            correlation_id="corr-001",
        )
        assert result.passed is True
        assert result.check_name == "no_limits_configured"
        assert result.severity == RiskEventSeverity.INFO

    def test_no_limits_live_mode_rejects(
        self, deployment_repo: MockDeploymentRepository, service: RiskGateService
    ) -> None:
        """Live mode without limits should REJECT the order (fail-closed)."""
        live_dep_id = "01HTESTLIVE0000000000001"
        deployment_repo.seed(deployment_id=live_dep_id, state="active", execution_mode="live")
        order = _make_order()
        account = _make_account()
        result = service.check_order(
            deployment_id=live_dep_id,
            order=order,
            positions=[],
            account=account,
            correlation_id="corr-001",
        )
        assert result.passed is False
        assert result.check_name == "no_limits_configured"
        assert result.severity == RiskEventSeverity.CRITICAL
        assert "Risk limits not configured for live deployment" in result.reason
        assert "Configure limits before submitting live orders" in result.reason

    def test_deployment_not_found_rejects(self, service: RiskGateService) -> None:
        """Order should be rejected when deployment does not exist."""
        nonexistent_dep_id = "01HNOTFOUND00000000000001"
        order = _make_order()
        account = _make_account()
        result = service.check_order(
            deployment_id=nonexistent_dep_id,
            order=order,
            positions=[],
            account=account,
            correlation_id="corr-001",
        )
        assert result.passed is False
        assert result.check_name == "no_limits_configured"
        assert result.severity == RiskEventSeverity.CRITICAL
        assert "Deployment" in result.reason
        assert "not found" in result.reason

    def test_no_limits_live_mode_records_critical_event(
        self,
        deployment_repo: MockDeploymentRepository,
        service: RiskGateService,
        event_repo: MockRiskEventRepository,
    ) -> None:
        """Live mode without limits should record a critical risk event."""
        live_dep_id = "01HTESTLIVE0000000000001"
        deployment_repo.seed(deployment_id=live_dep_id, state="active", execution_mode="live")
        order = _make_order()
        account = _make_account()
        service.check_order(
            deployment_id=live_dep_id,
            order=order,
            positions=[],
            account=account,
            correlation_id="corr-001",
        )
        events = event_repo.list_by_deployment(deployment_id=live_dep_id)
        assert len(events) == 1
        assert events[0].passed is False
        assert events[0].severity == RiskEventSeverity.CRITICAL
        assert events[0].check_name == "no_limits_configured"

    def test_no_limits_paper_mode_records_info_event(
        self,
        service: RiskGateService,
        event_repo: MockRiskEventRepository,
    ) -> None:
        """Paper mode without limits should record an info-level event."""
        order = _make_order()
        account = _make_account()
        service.check_order(
            deployment_id=DEP_ID,
            order=order,
            positions=[],
            account=account,
            correlation_id="corr-001",
        )
        events = event_repo.list_by_deployment(deployment_id=DEP_ID)
        assert len(events) == 1
        assert events[0].passed is True
        assert events[0].severity == RiskEventSeverity.INFO
        assert events[0].check_name == "no_limits_configured"


# ---------------------------------------------------------------------------
# Fail-fast ordering
# ---------------------------------------------------------------------------


class TestFailFastOrdering:
    """Tests that checks fail-fast on first violation."""

    def test_first_failure_returned(
        self, service: RiskGateService, event_repo: MockRiskEventRepository
    ) -> None:
        # Set limits that will trigger order_value failure first
        service.set_risk_limits(
            deployment_id=DEP_ID,
            limits=PreTradeRiskLimits(
                max_order_value=Decimal("1"),  # will fail
                max_position_size=Decimal("1"),  # would also fail
                max_daily_loss=Decimal("1"),  # would also fail
            ),
        )
        order = _make_order(quantity=Decimal("100"))
        positions = [_make_position(quantity=Decimal("500"))]
        account = _make_account(daily_pnl=Decimal("-999"))
        result = service.check_order(
            deployment_id=DEP_ID,
            order=order,
            positions=positions,
            account=account,
            correlation_id="corr-001",
        )
        assert result.passed is False
        # Should be the first check that fails (order_value is checked first)
        assert result.check_name == "order_value"


# ---------------------------------------------------------------------------
# Risk events recording
# ---------------------------------------------------------------------------


class TestRiskEventRecording:
    """Tests that risk events are recorded."""

    def test_failed_check_records_critical_event(
        self, service: RiskGateService, event_repo: MockRiskEventRepository
    ) -> None:
        service.set_risk_limits(
            deployment_id=DEP_ID,
            limits=PreTradeRiskLimits(max_order_value=Decimal("1")),
        )
        order = _make_order(quantity=Decimal("100"))
        positions = [_make_position()]
        account = _make_account()
        service.check_order(
            deployment_id=DEP_ID,
            order=order,
            positions=positions,
            account=account,
            correlation_id="corr-001",
        )
        events = event_repo.list_by_deployment(deployment_id=DEP_ID)
        # Should have at least 1 critical event
        critical = [e for e in events if e.severity == RiskEventSeverity.CRITICAL]
        assert len(critical) >= 1
        assert critical[0].passed is False

    def test_get_risk_events(
        self, service_with_limits: RiskGateService, event_repo: MockRiskEventRepository
    ) -> None:
        order = _make_order()
        account = _make_account()
        service_with_limits.check_order(
            deployment_id=DEP_ID,
            order=order,
            positions=[],
            account=account,
            correlation_id="corr-001",
        )
        events = service_with_limits.get_risk_events(deployment_id=DEP_ID)
        assert len(events) >= 1


# ---------------------------------------------------------------------------
# Multi-deployment isolation
# ---------------------------------------------------------------------------


class TestMultiDeploymentIsolation:
    """Risk limits are isolated per deployment."""

    def test_separate_limits(
        self, deployment_repo: MockDeploymentRepository, service: RiskGateService
    ) -> None:
        dep1 = "01HTESTDEP0000000000000001"
        dep2 = "01HTESTDEP0000000000000002"
        # Seed second deployment
        deployment_repo.seed(deployment_id=dep2, state="active", execution_mode="paper")

        service.set_risk_limits(
            deployment_id=dep1,
            limits=PreTradeRiskLimits(max_order_value=Decimal("1")),
        )
        service.set_risk_limits(
            deployment_id=dep2,
            limits=PreTradeRiskLimits(max_order_value=Decimal("999999")),
        )
        order = _make_order(quantity=Decimal("100"))
        positions = [_make_position()]
        account = _make_account()

        result1 = service.check_order(
            deployment_id=dep1,
            order=order,
            positions=positions,
            account=account,
            correlation_id="corr-001",
        )
        result2 = service.check_order(
            deployment_id=dep2,
            order=order,
            positions=positions,
            account=account,
            correlation_id="corr-002",
        )
        assert result1.passed is False
        assert result2.passed is True
