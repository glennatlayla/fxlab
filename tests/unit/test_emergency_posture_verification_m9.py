"""
Unit tests for M9 enhancements: Emergency Posture Verification Loop.

Covers:
- Post-execution verification loop in execute_emergency_posture()
- All positions close → verification.verified == True
- Partial close → residual exposure reported with positions_failed
- Timeout → CRITICAL log event emitted
- Configurable verification timeout
- Cancel-only posture includes verification
- Hold posture skips verification (no action taken)
- Residual exposure calculation (sum of abs(market_value))

Dependencies:
- libs.contracts.mocks.mock_broker_adapter: MockBrokerAdapter
- libs.contracts.mocks.mock_deployment_repository: MockDeploymentRepository
- libs.contracts.mocks.mock_kill_switch_event_repository: MockKillSwitchEventRepository
- services.api.services.kill_switch_service: KillSwitchService
- libs.contracts.safety: EmergencyPostureVerification
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from libs.contracts.execution import (
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderType,
    PositionSnapshot,
    TimeInForce,
)
from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from libs.contracts.mocks.mock_kill_switch_event_repository import (
    MockKillSwitchEventRepository,
)
from libs.contracts.safety import (
    EmergencyPostureVerification,
    HaltTrigger,
)
from services.api.services.kill_switch_service import KillSwitchService

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
    verification_timeout_s: int = 30,
):
    """Create standard test fixtures with configurable verification timeout."""
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

    service = KillSwitchService(
        deployment_repo=deployment_repo,
        ks_event_repo=ks_event_repo,
        adapter_registry={deployment_id: adapter},
        verification_timeout_s=verification_timeout_s,
    )
    return service, deployment_repo, adapter, ks_event_repo


# ------------------------------------------------------------------
# Verification Loop: All Positions Close Successfully
# ------------------------------------------------------------------


class TestPostureVerificationAllClose:
    """Tests for successful position closure during verification."""

    def test_flatten_all_verification_succeeds_when_all_close(self) -> None:
        """All positions close → verification.verified is True."""
        service, _, adapter, _ = _setup(fill_mode="instant")

        # Create a position by submitting and filling an order
        adapter.submit_order(_make_order_request(client_order_id="pos-1", symbol="AAPL"))

        with patch("time.sleep"):
            decision = service.execute_emergency_posture(
                deployment_id="01HDEPLOY0001",
                trigger=HaltTrigger.KILL_SWITCH,
                reason="Test flatten all",
            )

        assert decision.verification is not None
        verification = decision.verification
        assert verification.verified is True
        assert verification.positions_closed >= 0
        assert verification.positions_failed == []
        assert verification.residual_exposure_usd == Decimal("0")
        assert verification.timeout_s == 30

    def test_cancel_open_verification_checks_orders_not_positions(self) -> None:
        """Cancel-open posture verifies orders cancelled; positions may remain."""
        service, _, adapter, _ = _setup(
            emergency_posture="cancel_open",
            fill_mode="delayed",  # Orders stay open so cancel has something to do
        )

        # Submit an order that stays open (delayed fill mode)
        adapter.submit_order(_make_order_request(client_order_id="ord-cancel-1"))

        with patch("time.sleep"):
            decision = service.execute_emergency_posture(
                deployment_id="01HDEPLOY0001",
                trigger=HaltTrigger.KILL_SWITCH,
                reason="Test cancel open",
            )

        # cancel_open does run verification but only checks orders, not positions
        assert decision.verification is not None
        # Orders should be cancelled — no open orders remaining means verified
        assert decision.verification.verified is True


# ------------------------------------------------------------------
# Verification Loop: Partial Close → Residual Reported
# ------------------------------------------------------------------


class TestPostureVerificationPartialClose:
    """Tests for partial position closure with residual exposure."""

    def test_residual_exposure_reported_when_positions_remain(self) -> None:
        """Positions remaining after timeout → residual exposure calculated."""
        service, _, adapter, _ = _setup(
            fill_mode="delayed",
            verification_timeout_s=2,
        )

        # Create positions via orders
        adapter.submit_order(_make_order_request(client_order_id="pos-a", symbol="AAPL"))
        adapter.submit_order(
            OrderRequest(
                client_order_id="pos-b",
                symbol="TSLA",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("50"),
                time_in_force=TimeInForce.DAY,
                deployment_id="01HDEPLOY0001",
                strategy_id="01HSTRAT0001",
                correlation_id="corr-002",
                execution_mode=ExecutionMode.PAPER,
            )
        )

        # Mock get_positions to always return non-zero positions
        # (simulating positions that refuse to close)
        now = datetime.now(timezone.utc)
        stubborn_positions = [
            PositionSnapshot(
                symbol="TSLA",
                quantity=Decimal("50"),
                average_entry_price=Decimal("175.00"),
                market_price=Decimal("175.00"),
                market_value=Decimal("8750.00"),
                unrealized_pnl=Decimal("0"),
                cost_basis=Decimal("8750.00"),
                updated_at=now,
            ),
        ]

        original_get_positions = adapter.get_positions
        call_count = [0]

        def positions_with_stubborn(*args: object, **kwargs: object) -> list[PositionSnapshot]:
            """First call returns real, subsequent verification calls return stubborn."""
            call_count[0] += 1
            # First call is during _flatten_positions to get initial positions
            # Subsequent calls during verification should show stubborn positions
            if call_count[0] <= 1:
                return original_get_positions()
            return stubborn_positions

        with (
            patch.object(adapter, "get_positions", side_effect=positions_with_stubborn),
            patch("time.sleep"),
        ):
            decision = service.execute_emergency_posture(
                deployment_id="01HDEPLOY0001",
                trigger=HaltTrigger.KILL_SWITCH,
                reason="Partial close test",
            )

        assert decision.verification is not None
        verification = decision.verification
        assert verification.verified is False
        assert len(verification.positions_failed) >= 1
        assert verification.residual_exposure_usd > Decimal("0")

        # Check the failed position details
        failed_symbols = [p["symbol"] for p in verification.positions_failed]
        assert "TSLA" in failed_symbols

    def test_residual_exposure_is_sum_of_abs_market_value(self) -> None:
        """Residual exposure = sum of abs(market_value) for failed positions."""
        service, _, adapter, _ = _setup(
            fill_mode="delayed",
            verification_timeout_s=2,
        )

        adapter.submit_order(_make_order_request(client_order_id="pos-calc"))

        # Two stubborn positions with known market values
        now = datetime.now(timezone.utc)
        stubborn = [
            PositionSnapshot(
                symbol="AAPL",
                quantity=Decimal("100"),
                average_entry_price=Decimal("150.00"),
                market_price=Decimal("150.00"),
                market_value=Decimal("15000.00"),
                unrealized_pnl=Decimal("0"),
                cost_basis=Decimal("15000.00"),
                updated_at=now,
            ),
            PositionSnapshot(
                symbol="TSLA",
                quantity=Decimal("-50"),
                average_entry_price=Decimal("200.00"),
                market_price=Decimal("200.00"),
                market_value=Decimal("-10000.00"),
                unrealized_pnl=Decimal("0"),
                cost_basis=Decimal("10000.00"),
                updated_at=now,
            ),
        ]

        call_count = [0]

        def stubborn_positions(*args: object, **kwargs: object) -> list[PositionSnapshot]:
            call_count[0] += 1
            if call_count[0] <= 1:
                return list(adapter._positions.values())  # noqa: SLF001
            return stubborn

        with (
            patch.object(adapter, "get_positions", side_effect=stubborn_positions),
            patch("time.sleep"),
        ):
            decision = service.execute_emergency_posture(
                deployment_id="01HDEPLOY0001",
                trigger=HaltTrigger.KILL_SWITCH,
                reason="Exposure calc test",
            )

        verification = decision.verification
        assert verification is not None
        # abs(15000) + abs(-10000) = 25000
        assert verification.residual_exposure_usd == Decimal("25000.00")


# ------------------------------------------------------------------
# Verification Loop: Timeout → CRITICAL Log
# ------------------------------------------------------------------


class TestPostureVerificationCriticalLog:
    """Tests for CRITICAL logging when verification times out."""

    def test_critical_log_emitted_on_residual_exposure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """CRITICAL log event emitted when residual exposure remains after timeout."""
        service, _, adapter, _ = _setup(
            fill_mode="delayed",
            verification_timeout_s=2,
        )

        adapter.submit_order(_make_order_request(client_order_id="pos-crit"))

        now = datetime.now(timezone.utc)
        stubborn = [
            PositionSnapshot(
                symbol="AAPL",
                quantity=Decimal("100"),
                average_entry_price=Decimal("150.00"),
                market_price=Decimal("150.00"),
                market_value=Decimal("15000.00"),
                unrealized_pnl=Decimal("0"),
                cost_basis=Decimal("15000.00"),
                updated_at=now,
            ),
        ]
        call_count = [0]

        def stubborn_fn(*args: object, **kwargs: object) -> list[PositionSnapshot]:
            call_count[0] += 1
            if call_count[0] <= 1:
                return list(adapter._positions.values())  # noqa: SLF001
            return stubborn

        with (
            patch.object(adapter, "get_positions", side_effect=stubborn_fn),
            patch("time.sleep"),
            caplog.at_level(logging.CRITICAL),
        ):
            decision = service.execute_emergency_posture(
                deployment_id="01HDEPLOY0001",
                trigger=HaltTrigger.KILL_SWITCH,
                reason="Critical log test",
            )

        assert decision.verification is not None
        assert decision.verification.verified is False

        # Check CRITICAL log was emitted with the right operation
        critical_records = [
            r
            for r in caplog.records
            if r.levelno == logging.CRITICAL
            and hasattr(r, "operation")
            and r.operation == "emergency_posture_residual_exposure"
        ]
        # Use extra dict fallback if LogRecord doesn't have attribute directly
        if not critical_records:
            critical_records = [
                r
                for r in caplog.records
                if r.levelno == logging.CRITICAL and "residual_exposure" in r.getMessage().lower()
            ]
        assert len(critical_records) >= 1, (
            f"Expected CRITICAL log with 'residual_exposure', got: "
            f"{[(r.levelno, r.getMessage()) for r in caplog.records]}"
        )


# ------------------------------------------------------------------
# Configurable Timeout
# ------------------------------------------------------------------


class TestPostureVerificationTimeout:
    """Tests for configurable verification timeout."""

    def test_verification_uses_configured_timeout(self) -> None:
        """Verification timeout_s matches the configured value."""
        service, _, adapter, _ = _setup(
            fill_mode="instant",
            verification_timeout_s=15,
        )

        adapter.submit_order(_make_order_request(client_order_id="pos-timeout"))

        with patch("time.sleep"):
            decision = service.execute_emergency_posture(
                deployment_id="01HDEPLOY0001",
                trigger=HaltTrigger.KILL_SWITCH,
                reason="Timeout config test",
            )

        assert decision.verification is not None
        assert decision.verification.timeout_s == 15

    def test_default_timeout_is_30_seconds(self) -> None:
        """Default verification timeout is 30 seconds."""
        service, _, adapter, _ = _setup(fill_mode="instant")

        with patch("time.sleep"):
            decision = service.execute_emergency_posture(
                deployment_id="01HDEPLOY0001",
                trigger=HaltTrigger.KILL_SWITCH,
                reason="Default timeout test",
            )

        assert decision.verification is not None
        assert decision.verification.timeout_s == 30


# ------------------------------------------------------------------
# Hold Posture Skips Verification
# ------------------------------------------------------------------


class TestPostureHoldSkipsVerification:
    """Tests for hold posture which should not run verification."""

    def test_hold_posture_no_verification(self) -> None:
        """Hold posture returns None verification — no action to verify."""
        service, _, _, _ = _setup(emergency_posture="hold")

        with patch("time.sleep"):
            decision = service.execute_emergency_posture(
                deployment_id="01HDEPLOY0001",
                trigger=HaltTrigger.MANUAL,
                reason="Hold posture test",
            )

        assert decision.verification is None
        assert decision.orders_cancelled == 0
        assert decision.positions_flattened == 0

    def test_custom_posture_no_verification(self) -> None:
        """Custom posture (treated as hold) returns None verification."""
        service, _, _, _ = _setup(emergency_posture="custom")

        with patch("time.sleep"):
            decision = service.execute_emergency_posture(
                deployment_id="01HDEPLOY0001",
                trigger=HaltTrigger.MANUAL,
                reason="Custom posture test",
            )

        assert decision.verification is None


# ------------------------------------------------------------------
# Verification Result Structure
# ------------------------------------------------------------------


class TestEmergencyPostureVerificationContract:
    """Tests for EmergencyPostureVerification contract correctness."""

    def test_verification_schema_frozen(self) -> None:
        """EmergencyPostureVerification is immutable (frozen)."""
        verification = EmergencyPostureVerification(
            verified=True,
            positions_closed=2,
            timeout_s=30,
        )
        with pytest.raises(Exception):  # noqa: B017
            verification.verified = False  # type: ignore[misc]

    def test_verification_default_values(self) -> None:
        """Default values for optional fields are sensible."""
        verification = EmergencyPostureVerification(verified=True)
        assert verification.positions_closed == 0
        assert verification.positions_failed == []
        assert verification.residual_exposure_usd == Decimal("0")
        assert verification.timeout_s == 30
        assert verification.verification_duration_ms == 0

    def test_verification_with_failed_positions(self) -> None:
        """Verification schema accepts failed position data."""
        verification = EmergencyPostureVerification(
            verified=False,
            positions_closed=1,
            positions_failed=[
                {"symbol": "TSLA", "quantity": "50", "market_value": "8750.00"},
            ],
            residual_exposure_usd=Decimal("8750.00"),
            timeout_s=30,
            verification_duration_ms=30150,
        )
        assert len(verification.positions_failed) == 1
        assert verification.positions_failed[0]["symbol"] == "TSLA"
        assert verification.residual_exposure_usd == Decimal("8750.00")


# ------------------------------------------------------------------
# Verification Duration Tracking
# ------------------------------------------------------------------


class TestVerificationDuration:
    """Tests for verification timing measurement."""

    def test_verification_duration_recorded(self) -> None:
        """Verification duration_ms is recorded in the result."""
        service, _, adapter, _ = _setup(fill_mode="instant")

        adapter.submit_order(_make_order_request(client_order_id="pos-dur"))

        with patch("time.sleep"):
            decision = service.execute_emergency_posture(
                deployment_id="01HDEPLOY0001",
                trigger=HaltTrigger.KILL_SWITCH,
                reason="Duration test",
            )

        assert decision.verification is not None
        assert decision.verification.verification_duration_ms >= 0
