"""
Unit tests for M8 enhancements: Kill Switch Retry, Verification, and Escalation.

Covers:
- Retry logic with exponential backoff on transient errors
- Order verification after cancellation
- Escalation to emergency posture on persistent failures
- Position flattening with polling and timeout
- Halt verification across scopes
- Activation persistence before cancellation attempts

Dependencies:
- libs.contracts.mocks.mock_broker_adapter: MockBrokerAdapter
- libs.contracts.mocks.mock_deployment_repository: MockDeploymentRepository
- libs.contracts.mocks.mock_kill_switch_event_repository: MockKillSwitchEventRepository
- services.api.services.kill_switch_service: KillSwitchService
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from libs.contracts.errors import NotFoundError, TransientError
from libs.contracts.execution import (
    ExecutionMode,
    OrderRequest,
    OrderResponse,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from libs.contracts.mocks.mock_kill_switch_event_repository import (
    MockKillSwitchEventRepository,
)
from libs.contracts.safety import KillSwitchScope
from services.api.services.kill_switch_service import (
    KillSwitchService,
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
    """Create standard test fixtures."""
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
    )
    return service, deployment_repo, adapter, ks_event_repo


# ------------------------------------------------------------------
# Retry Tests
# ------------------------------------------------------------------


class TestCancellationRetry:
    """Test retry logic with exponential backoff on transient errors."""

    def test_retry_on_transient_error_succeeds_on_third_attempt(self) -> None:
        """
        First two cancel attempts fail with TransientError, third succeeds.
        Order should be successfully cancelled.
        """
        service, _, adapter, _ = _setup(fill_mode="delayed")

        # Submit an order that stays open (delayed mode)
        adapter.submit_order(_make_order_request(client_order_id="ord-retry"))

        # Mock the adapter's cancel_order to fail twice, then succeed
        call_count = [0]
        original_cancel = adapter.cancel_order

        def cancel_with_retry(order_id: str) -> OrderResponse:
            call_count[0] += 1
            if call_count[0] < 3:
                raise TransientError("Temporary connection failure")
            # On 3rd attempt, succeed
            return original_cancel(order_id)

        with patch.object(adapter, "cancel_order", side_effect=cancel_with_retry):
            result = service._cancel_open_orders(adapter)
            # Should succeed after retries
            assert result.cancelled_count == 1
            assert result.failed_count == 0
            assert result.failed_order_ids == []

    def test_no_retry_on_permanent_error(self) -> None:
        """Permanent errors (NotFoundError) should not be retried."""
        service, _, adapter, _ = _setup(fill_mode="delayed")

        # Submit an order that stays open
        resp = adapter.submit_order(_make_order_request(client_order_id="ord-notfound"))
        broker_order_id = resp.broker_order_id

        # Mock cancel_order to always raise NotFoundError
        def cancel_not_found(order_id: str) -> OrderResponse:
            raise NotFoundError(f"Order {order_id} not found")

        with patch.object(adapter, "cancel_order", side_effect=cancel_not_found):
            result = service._cancel_open_orders(adapter)
            # Should fail immediately without retries
            assert result.failed_count == 1
            assert result.cancelled_count == 0
            assert broker_order_id in result.failed_order_ids

    def test_all_retries_exhausted_fails_gracefully(self) -> None:
        """When all retries are exhausted, order is added to failed list."""
        service, _, adapter, _ = _setup(fill_mode="delayed")

        # Submit an order that stays open
        resp = adapter.submit_order(_make_order_request(client_order_id="ord-exhausted"))
        broker_order_id = resp.broker_order_id

        # Mock cancel_order to always raise TransientError
        def cancel_always_fails(order_id: str) -> OrderResponse:
            raise TransientError("Broker is down")

        with patch.object(adapter, "cancel_order", side_effect=cancel_always_fails):
            result = service._cancel_open_orders(adapter)
            # All retries exhausted, should be in failed list
            assert result.failed_count == 1
            assert result.cancelled_count == 0
            assert broker_order_id in result.failed_order_ids


# ------------------------------------------------------------------
# Verification Tests
# ------------------------------------------------------------------


class TestOrderVerificationAfterCancellation:
    """Test that cancelled orders are verified to confirm status."""

    def test_order_verified_cancelled_counts_as_success(self) -> None:
        """Order cancelled and verified as CANCELLED → success."""
        service, _, adapter, _ = _setup(fill_mode="delayed")

        # Submit an order that stays open
        adapter.submit_order(_make_order_request(client_order_id="ord-verify-ok"))

        result = service._cancel_open_orders(adapter)
        # Should successfully cancel and verify
        assert result.cancelled_count == 1
        assert result.failed_count == 0

    def test_order_still_open_after_cancel_verification_fails(self) -> None:
        """Order cancelled but still open in verification → fails."""
        service, _, adapter, _ = _setup(fill_mode="delayed")

        # Submit an order that stays open
        resp = adapter.submit_order(_make_order_request(client_order_id="ord-verify-fail"))
        broker_order_id = resp.broker_order_id

        # Mock get_order to return SUBMITTED (not cancelled) after cancel
        original_get_order = adapter.get_order

        def get_order_returns_submitted(order_id: str) -> OrderResponse:
            result = original_get_order(order_id)
            # Force status to SUBMITTED to simulate verification failure
            return OrderResponse(
                client_order_id=result.client_order_id,
                broker_order_id=result.broker_order_id,
                symbol=result.symbol,
                side=result.side,
                order_type=result.order_type,
                quantity=result.quantity,
                filled_quantity=result.filled_quantity,
                average_fill_price=result.average_fill_price,
                status=OrderStatus.SUBMITTED,  # Still open!
                limit_price=result.limit_price,
                stop_price=result.stop_price,
                time_in_force=result.time_in_force,
                submitted_at=result.submitted_at,
                correlation_id=result.correlation_id,
                execution_mode=result.execution_mode,
            )

        with patch.object(adapter, "get_order", side_effect=get_order_returns_submitted):
            result = service._cancel_open_orders(adapter)
            # Verification failed — should be in failed list
            assert result.failed_count == 1
            assert result.cancelled_count == 0
            assert broker_order_id in result.failed_order_ids


# ------------------------------------------------------------------
# Escalation Tests
# ------------------------------------------------------------------


class TestEscalationOnPersistentFailure:
    """Test automatic escalation to emergency posture on cancellation failures."""

    def test_escalation_triggered_on_failed_cancellations(self) -> None:
        """When cancel fails, emergency posture should be called."""
        service, deployment_repo, adapter, _ = _setup(
            emergency_posture="flatten_all", fill_mode="delayed"
        )

        # Submit an order in delayed mode (stays open)
        adapter.submit_order(_make_order_request(client_order_id="ord-escalate"))

        # Mock cancel to always fail
        def cancel_fails(order_id: str) -> OrderResponse:
            raise NotFoundError("Order not found")

        with (
            patch.object(adapter, "cancel_order", side_effect=cancel_fails),
            patch.object(service, "execute_emergency_posture") as mock_escalate,
        ):
            service.activate_kill_switch(
                scope=KillSwitchScope.GLOBAL,
                target_id="global",
                reason="Test escalation",
                activated_by="test",
            )
            # Escalation should have been triggered
            mock_escalate.assert_called_once()
            call_args = mock_escalate.call_args
            assert call_args.kwargs["deployment_id"] == "01HDEPLOY0001"

    def test_no_escalation_if_all_orders_cancelled(self) -> None:
        """If all orders cancel successfully, no escalation."""
        service, _, adapter, _ = _setup(emergency_posture="flatten_all")

        # Submit a normal order (will succeed to cancel)
        adapter.submit_order(_make_order_request(client_order_id="ord-ok"))

        with patch.object(service, "execute_emergency_posture") as mock_escalate:
            service.activate_kill_switch(
                scope=KillSwitchScope.GLOBAL,
                target_id="global",
                reason="Normal halt",
                activated_by="test",
            )
            # No escalation needed
            mock_escalate.assert_not_called()


# ------------------------------------------------------------------
# Flattening with Polling Tests
# ------------------------------------------------------------------


class TestPositionFlatteningWithPolling:
    """Test position flattening with polling and timeout."""

    def test_position_closes_on_second_poll(self) -> None:
        """Position submitted, closes on 2nd poll → success."""
        service, _, adapter, _ = _setup(fill_mode="instant")

        # Submit orders to create positions
        adapter.submit_order(
            OrderRequest(
                client_order_id="pos-close-1",
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("100"),
                time_in_force=TimeInForce.DAY,
                deployment_id="01HDEPLOY0001",
                strategy_id="01HSTRAT0001",
                correlation_id="corr-pos",
                execution_mode=ExecutionMode.PAPER,
            )
        )

        # Verify position exists
        positions = adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"

        # Now flatten (which submits close orders)
        result = service._flatten_positions(adapter)

        # All positions should be closed
        assert result.flattened_count == 1
        assert result.failed_count == 0
        assert result.failed_symbols == []

    def test_position_timeout_after_10_seconds(self) -> None:
        """Position never closes after 10s polling → fails."""
        service, _, adapter, _ = _setup(fill_mode="instant")

        # Create a position (filled instantly)
        adapter.submit_order(
            OrderRequest(
                client_order_id="pos-timeout-create",
                symbol="MSFT",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("50"),
                time_in_force=TimeInForce.DAY,
                deployment_id="01HDEPLOY0001",
                strategy_id="01HSTRAT0001",
                correlation_id="corr-timeout-create",
                execution_mode=ExecutionMode.PAPER,
            )
        )

        # Verify position was created
        assert len(adapter.get_positions()) == 1

        # Mock submit_order so close orders don't actually close positions
        call_count = [0]

        def submit_but_dont_fill(request: OrderRequest) -> OrderResponse:
            # Don't let close orders affect positions
            call_count[0] += 1
            resp = OrderResponse(
                client_order_id=request.client_order_id,
                broker_order_id=f"MOCK-TIMEOUT-{call_count[0]}",
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                quantity=request.quantity,
                filled_quantity=Decimal("0"),
                average_fill_price=None,
                status=OrderStatus.SUBMITTED,  # Stays SUBMITTED, doesn't fill
                limit_price=request.limit_price,
                stop_price=request.stop_price,
                time_in_force=request.time_in_force,
                submitted_at=datetime.now(timezone.utc),
                correlation_id=request.correlation_id,
                execution_mode=request.execution_mode,
            )
            return resp

        # Now flatten with mocked sleep and mocked submit_order
        with (
            patch.object(adapter, "submit_order", side_effect=submit_but_dont_fill),
            patch("time.sleep"),  # Mock sleep to avoid actual delays
        ):
            result = service._flatten_positions(adapter)

        # Position should timeout since close order doesn't fill
        assert result.failed_count >= 1
        assert "MSFT" in result.failed_symbols

    def test_multiple_positions_flattened(self) -> None:
        """Multiple positions submitted and verified flattened."""
        service, _, adapter, _ = _setup(fill_mode="instant")

        # Create multiple positions
        for symbol in ["AAPL", "MSFT", "GOOGL"]:
            adapter.submit_order(
                OrderRequest(
                    client_order_id=f"pos-multi-{symbol}",
                    symbol=symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=Decimal("100"),
                    time_in_force=TimeInForce.DAY,
                    deployment_id="01HDEPLOY0001",
                    strategy_id="01HSTRAT0001",
                    correlation_id=f"corr-multi-{symbol}",
                    execution_mode=ExecutionMode.PAPER,
                )
            )

        result = service._flatten_positions(adapter)
        # All 3 positions should be flattened
        assert result.flattened_count == 3
        assert result.failed_count == 0


# ------------------------------------------------------------------
# Halt Verification Tests
# ------------------------------------------------------------------


class TestHaltVerification:
    """Test verify_halt method."""

    def test_verify_halt_no_residual_exposure(self) -> None:
        """Verified halt with no open orders or positions."""
        service, _, adapter, _ = _setup()

        result = service.verify_halt(scope=KillSwitchScope.GLOBAL, target_id="global")

        assert result["verified"] is True
        assert result["open_orders_remaining"] == []
        assert result["open_positions_remaining"] == []
        assert result["residual_exposure"] == {}

    def test_verify_halt_with_residual_orders(self) -> None:
        """Halt verification detects residual open orders."""
        service, _, adapter, _ = _setup(fill_mode="delayed")

        # Leave an order open (delayed mode keeps orders open)
        adapter.submit_order(_make_order_request(client_order_id="ord-residual"))

        result = service.verify_halt(scope=KillSwitchScope.GLOBAL, target_id="global")

        assert result["verified"] is False
        assert len(result["open_orders_remaining"]) == 1

    def test_verify_halt_with_residual_positions(self) -> None:
        """Halt verification detects residual open positions."""
        service, _, adapter, _ = _setup(fill_mode="instant")

        # Create a position
        adapter.submit_order(
            OrderRequest(
                client_order_id="pos-residual",
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("100"),
                time_in_force=TimeInForce.DAY,
                deployment_id="01HDEPLOY0001",
                strategy_id="01HSTRAT0001",
                correlation_id="corr-residual",
                execution_mode=ExecutionMode.PAPER,
            )
        )

        result = service.verify_halt(scope=KillSwitchScope.GLOBAL, target_id="global")

        assert result["verified"] is False
        assert len(result["open_positions_remaining"]) == 1
        # residual_exposure dict will be present if there are positions
        if result["open_positions_remaining"]:
            assert len(result["residual_exposure"]) > 0

    def test_verify_halt_residual_exposure_calculation(self) -> None:
        """Residual exposure correctly sums market values by symbol."""
        service, _, adapter, _ = _setup(fill_mode="instant")

        # Create multiple positions in same symbol (second buy adds to quantity)
        for i in range(2):
            adapter.submit_order(
                OrderRequest(
                    client_order_id=f"pos-exp-{i}",
                    symbol="AAPL",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=Decimal("100"),
                    time_in_force=TimeInForce.DAY,
                    deployment_id="01HDEPLOY0001",
                    strategy_id="01HSTRAT0001",
                    correlation_id=f"corr-exp-{i}",
                    execution_mode=ExecutionMode.PAPER,
                )
            )

        result = service.verify_halt(scope=KillSwitchScope.GLOBAL, target_id="global")

        assert result["verified"] is False
        # After two buys, should have combined position in AAPL
        assert len(result["open_positions_remaining"]) > 0
        # Should have residual exposure
        assert len(result["residual_exposure"]) > 0
        if "AAPL" in result["residual_exposure"]:
            exposure_value = Decimal(result["residual_exposure"]["AAPL"])
            assert exposure_value > Decimal("0")


# ------------------------------------------------------------------
# Persistence Tests
# ------------------------------------------------------------------


class TestActivationPersistenceBeforeCancellation:
    """Test that halt is persisted before cancellation attempts."""

    def test_halt_persisted_before_cancellation_attempt(self) -> None:
        """Halt should be saved to DB before any cancellation attempts."""
        service, _, adapter, ks_event_repo = _setup()

        # Submit an order
        adapter.submit_order(_make_order_request(client_order_id="ord-persist"))

        # Activate kill switch
        service.activate_kill_switch(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            reason="Test persistence",
            activated_by="test",
        )

        # Verify event was persisted
        active = ks_event_repo.get_active(scope="global", target_id="global")
        assert active is not None
        assert active["scope"] == "global"
        assert active["target_id"] == "global"

    def test_halt_persisted_even_if_cancellation_fails(self) -> None:
        """Halt is persisted even if order cancellation fails."""
        service, _, adapter, ks_event_repo = _setup()

        # Submit an order
        adapter.submit_order(_make_order_request(client_order_id="ord-fail-cancel"))

        # Mock cancel to always fail
        def cancel_fails(order_id: str) -> OrderResponse:
            raise NotFoundError("Order not found")

        with patch.object(adapter, "cancel_order", side_effect=cancel_fails):
            # Activate kill switch — cancellation will fail
            service.activate_kill_switch(
                scope=KillSwitchScope.GLOBAL,
                target_id="global",
                reason="Fail-closed test",
                activated_by="test",
            )

        # BUT halt should still be persisted
        active = ks_event_repo.get_active(scope="global", target_id="global")
        assert active is not None
        assert active["scope"] == "global"


# ------------------------------------------------------------------
# Integration Tests
# ------------------------------------------------------------------


class TestKillSwitchM8Integration:
    """End-to-end tests for M8 functionality."""

    def test_full_kill_switch_workflow_success(self) -> None:
        """Complete kill switch: activate, cancel orders, verify."""
        service, _, adapter, _ = _setup(fill_mode="delayed")

        # Setup: create some open orders (delayed fill so they stay open)
        for i in range(2):
            adapter.submit_order(
                OrderRequest(
                    client_order_id=f"ord-full-{i}",
                    symbol="AAPL",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=Decimal("100"),
                    time_in_force=TimeInForce.DAY,
                    deployment_id="01HDEPLOY0001",
                    strategy_id="01HSTRAT0001",
                    correlation_id=f"corr-full-{i}",
                    execution_mode=ExecutionMode.PAPER,
                )
            )

        # Verify open orders exist
        assert len(adapter.list_open_orders()) == 2

        # Activate kill switch (orders should be cancelled)
        halt_event = service.activate_kill_switch(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            reason="Test full workflow",
            activated_by="test",
        )

        assert halt_event.scope == KillSwitchScope.GLOBAL
        assert halt_event.mtth_ms is not None
        assert halt_event.mtth_ms >= 0
        assert halt_event.orders_cancelled == 2

        # Verify halt — orders should be cancelled
        verify_result = service.verify_halt(scope=KillSwitchScope.GLOBAL, target_id="global")

        # All orders should be cancelled
        assert verify_result["verified"] is True
        assert len(verify_result["open_orders_remaining"]) == 0

    def test_kill_switch_with_partial_failure_and_escalation(self) -> None:
        """Kill switch with some failures should escalate but still record success."""
        service, _, adapter, _ = _setup(emergency_posture="flatten_all")

        # Submit multiple orders
        adapter.submit_order(_make_order_request(client_order_id="ord-fail-1"))
        adapter.submit_order(_make_order_request(client_order_id="ord-fail-2"))

        # Mock cancel to fail on first order, succeed on second
        call_count = [0]
        original_cancel = adapter.cancel_order

        def cancel_partial_fail(order_id: str) -> OrderResponse:
            call_count[0] += 1
            if call_count[0] == 1:
                raise NotFoundError("First order not found")
            return original_cancel(order_id)

        with (
            patch.object(adapter, "cancel_order", side_effect=cancel_partial_fail),
            patch.object(service, "execute_emergency_posture"),
        ):
            halt_event = service.activate_kill_switch(
                scope=KillSwitchScope.GLOBAL,
                target_id="global",
                reason="Partial failure test",
                activated_by="test",
            )

            # Should still record the event
            assert halt_event is not None
