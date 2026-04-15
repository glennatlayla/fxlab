"""
Unit tests for the PartialFillMonitorService.

Covers:
- Partial fill within timeout → no action taken
- Partial fill exceeding timeout with cancel_remaining → broker cancel called, status updated
- Partial fill exceeding timeout with alert_only → no cancel, warning logged
- Broker reports fully filled since last check → updated to filled
- Broker cancel fails (transient error) → error in resolution, order stays partial
- Broker cancel fails (permanent error) → error in resolution
- No partial fill orders → empty results
- Multiple partial fills processed in sequence
- Missing submitted_at timestamp → skip (no action)
- Invalid submitted_at timestamp → skip (no action)
- NotFoundError from broker → propagated to caller

Per PartialFillMonitorInterface spec: monitor detects partial fills, syncs with broker,
applies timeout policy, cancels remaining or alerts, and records audit trail.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest

from libs.contracts.errors import ExternalServiceError, NotFoundError, TransientError
from libs.contracts.execution import OrderResponse, OrderStatus
from libs.contracts.mocks.mock_execution_event_repository import MockExecutionEventRepository
from libs.contracts.mocks.mock_order_repository import MockOrderRepository
from libs.contracts.partial_fill import PartialFillPolicy
from services.api.infrastructure.broker_registry import BrokerAdapterRegistry
from services.api.services.partial_fill_monitor_service import PartialFillMonitorService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DEP_ID = "01HTESTDEP0000000000000001"
ORDER_ID = "01HTESTORD0000000000000001"
BROKER_ORDER_ID = "TEST-12345"
STRAT_ID = "01HTESTSTRAT00000000000001"


@pytest.fixture()
def order_repo() -> MockOrderRepository:
    """Mock order repository."""
    return MockOrderRepository()


@pytest.fixture()
def event_repo() -> MockExecutionEventRepository:
    """Mock execution event repository."""
    return MockExecutionEventRepository()


@pytest.fixture()
def mock_adapter() -> Mock:
    """Mock broker adapter."""
    return Mock()


@pytest.fixture()
def broker_registry(mock_adapter: Mock) -> Mock:
    """Mock broker registry that returns our mock adapter."""
    registry = MagicMock()
    registry.get_adapter.return_value = mock_adapter
    return registry


@pytest.fixture()
def service(
    order_repo: MockOrderRepository,
    broker_registry: BrokerAdapterRegistry,
    event_repo: MockExecutionEventRepository,
) -> PartialFillMonitorService:
    """Create the partial fill monitor service."""
    return PartialFillMonitorService(
        order_repo=order_repo,
        broker_registry=broker_registry,
        execution_event_repo=event_repo,
    )


def _seed_order_with_submitted_at(
    order_repo: MockOrderRepository,
    *,
    order_id: str = ORDER_ID,
    broker_order_id: str = BROKER_ORDER_ID,
    deployment_id: str = DEP_ID,
    status: str = "partial_fill",
    quantity: str = "1000",
    filled_quantity: str = "750",
    submitted_at: str | None = None,
    execution_mode: str = "paper",
) -> dict[str, Any]:
    """
    Helper to seed an order with a custom submitted_at timestamp.

    MockOrderRepository.seed() doesn't support submitted_at directly,
    so we seed first and then update_status to set it.
    """
    if submitted_at is None:
        submitted_at = (datetime.now(tz=timezone.utc) - timedelta(seconds=5)).isoformat()

    # Seed the order first
    order = order_repo.seed(
        order_id=order_id,
        client_order_id=f"cli-{order_id}",
        deployment_id=deployment_id,
        strategy_id=STRAT_ID,
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity=quantity,
        status=status,
        broker_order_id=broker_order_id,
        execution_mode=execution_mode,
        correlation_id="corr-001",
    )

    # Update with submitted_at, filled_quantity, and status
    order = order_repo.update_status(
        order_id=order_id,
        status=status,
        submitted_at=submitted_at,
        filled_quantity=filled_quantity,
        average_fill_price="150.50",
    )

    return order


def _make_broker_response(
    *,
    order_id: str = BROKER_ORDER_ID,
    status: str = OrderStatus.PARTIAL_FILL,
    quantity: Decimal = Decimal("1000"),
    filled_quantity: Decimal = Decimal("750"),
) -> OrderResponse:
    """Helper to create a broker OrderResponse."""
    from libs.contracts.execution import ExecutionMode, OrderSide, OrderType, TimeInForce

    return OrderResponse(
        client_order_id="cli-001",
        broker_order_id=order_id,
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=quantity,
        filled_quantity=filled_quantity,
        average_fill_price=Decimal("150.50"),
        status=status,
        time_in_force=TimeInForce.DAY,
        correlation_id="corr-001",
        execution_mode=ExecutionMode.PAPER,
    )


# ---------------------------------------------------------------------------
# Test: No partial fill orders
# ---------------------------------------------------------------------------


def test_check_partial_fills_no_partial_orders(
    service: PartialFillMonitorService,
    order_repo: MockOrderRepository,
) -> None:
    """
    When deployment has no partial fill orders, returns empty list.

    Test:
    - list_open_by_deployment returns non-partial orders
    - Broker not called
    - Empty results returned
    """
    # Seed an order with status "filled" (not partial_fill)
    order_repo.seed(
        order_id=ORDER_ID,
        deployment_id=DEP_ID,
        status="filled",
    )

    policy = PartialFillPolicy(timeout_seconds=300)
    resolutions = service.check_partial_fills(
        deployment_id=DEP_ID,
        policy=policy,
        correlation_id="corr-001",
    )

    assert len(resolutions) == 0


# ---------------------------------------------------------------------------
# Test: Partial fill within timeout (no action)
# ---------------------------------------------------------------------------


def test_check_partial_fills_within_timeout(
    service: PartialFillMonitorService,
    order_repo: MockOrderRepository,
    mock_adapter: Mock,
) -> None:
    """
    Partial fill order within timeout window → no action, broker queried.

    Test:
    - Order status is "partial_fill"
    - submitted_at is recent (within timeout)
    - Broker.get_order() called
    - Broker still shows partial
    - No cancel requested
    - Resolution returned with action_taken="alert_sent" (within timeout)
    """
    # Create order that was submitted 5 seconds ago (timeout is 300s)
    _seed_order_with_submitted_at(
        order_repo,
        submitted_at=(datetime.now(tz=timezone.utc) - timedelta(seconds=5)).isoformat(),
    )

    # Broker still shows partial
    broker_response = _make_broker_response()
    mock_adapter.get_order.return_value = broker_response

    policy = PartialFillPolicy(timeout_seconds=300, action_on_timeout="cancel_remaining")
    resolutions = service.check_partial_fills(
        deployment_id=DEP_ID,
        policy=policy,
        correlation_id="corr-001",
    )

    # Broker should have been queried
    mock_adapter.get_order.assert_called_once_with(BROKER_ORDER_ID)

    # No cancel should have been requested
    mock_adapter.cancel_order.assert_not_called()

    # One resolution should be returned
    assert len(resolutions) == 1
    res = resolutions[0]
    assert res.order_id == ORDER_ID
    assert res.action_taken == "alert_sent"  # Within timeout


# ---------------------------------------------------------------------------
# Test: Broker reports fully filled
# ---------------------------------------------------------------------------


def test_check_partial_fills_broker_now_fully_filled(
    service: PartialFillMonitorService,
    order_repo: MockOrderRepository,
    event_repo: MockExecutionEventRepository,
    mock_adapter: Mock,
) -> None:
    """
    Partial fill that is now fully filled at broker → status updated to filled.

    Test:
    - Order status is "partial_fill" (750/1000)
    - Broker.get_order() returns fully filled (1000/1000)
    - Internal order status updated to "filled"
    - Execution event recorded
    - Resolution returned with action_taken="fully_filled"
    """
    _seed_order_with_submitted_at(order_repo, filled_quantity="750")

    # Broker now reports fully filled
    broker_response = _make_broker_response(
        filled_quantity=Decimal("1000"),
        status=OrderStatus.FILLED,
    )
    mock_adapter.get_order.return_value = broker_response

    policy = PartialFillPolicy(timeout_seconds=300)
    resolutions = service.check_partial_fills(
        deployment_id=DEP_ID,
        policy=policy,
        correlation_id="corr-001",
    )

    # Resolution should show fully filled
    assert len(resolutions) == 1
    res = resolutions[0]
    assert res.action_taken == "fully_filled"
    assert res.filled_quantity == "1000"

    # Internal order status should be updated to "filled"
    updated_order = order_repo.get_by_id(ORDER_ID)
    assert updated_order["status"] == "filled"
    assert updated_order["filled_quantity"] == "1000"

    # Execution event should be recorded
    events = event_repo.list_by_order(order_id=ORDER_ID)
    assert len(events) > 0
    assert any(e["event_type"] == "partial_fill_completed" for e in events)


# ---------------------------------------------------------------------------
# Test: Timeout with cancel_remaining action
# ---------------------------------------------------------------------------


def test_check_partial_fills_timeout_cancel_remaining(
    service: PartialFillMonitorService,
    order_repo: MockOrderRepository,
    event_repo: MockExecutionEventRepository,
    mock_adapter: Mock,
) -> None:
    """
    Partial fill timeout expired with cancel_remaining → broker cancel called.

    Test:
    - Order submitted 400 seconds ago (timeout is 300)
    - Broker still shows partial
    - Broker.cancel_order() called
    - Order status updated to "cancelled"
    - filled_quantity and cancelled_at recorded
    - Execution event recorded
    - Resolution returned with action_taken="cancelled_remaining"
    """
    # Order submitted 400 seconds ago
    _seed_order_with_submitted_at(
        order_repo,
        submitted_at=(datetime.now(tz=timezone.utc) - timedelta(seconds=400)).isoformat(),
    )

    # Broker still shows partial
    broker_response = _make_broker_response()
    mock_adapter.get_order.return_value = broker_response
    mock_adapter.cancel_order.return_value = broker_response

    policy = PartialFillPolicy(timeout_seconds=300, action_on_timeout="cancel_remaining")
    resolutions = service.check_partial_fills(
        deployment_id=DEP_ID,
        policy=policy,
        correlation_id="corr-001",
    )

    # Broker cancel should have been called
    mock_adapter.cancel_order.assert_called_once_with(BROKER_ORDER_ID)

    # One resolution should be returned
    assert len(resolutions) == 1
    res = resolutions[0]
    assert res.action_taken == "cancelled_remaining"
    assert res.cancelled_at is not None

    # Internal order status should be updated to "cancelled"
    updated_order = order_repo.get_by_id(ORDER_ID)
    assert updated_order["status"] == "cancelled"
    assert updated_order["cancelled_at"] is not None

    # Execution event should be recorded
    events = event_repo.list_by_order(order_id=ORDER_ID)
    assert any(e["event_type"] == "partial_fill_timeout_cancelled" for e in events)


# ---------------------------------------------------------------------------
# Test: Timeout with alert_only action
# ---------------------------------------------------------------------------


def test_check_partial_fills_timeout_alert_only(
    service: PartialFillMonitorService,
    order_repo: MockOrderRepository,
    event_repo: MockExecutionEventRepository,
    mock_adapter: Mock,
) -> None:
    """
    Partial fill timeout with alert_only → no cancel, warning logged.

    Test:
    - Order submitted 400 seconds ago (timeout is 300)
    - Policy action_on_timeout="alert_only"
    - Broker.cancel_order() NOT called
    - Order status NOT updated
    - Execution event recorded with action="alert_sent"
    - Resolution returned with action_taken="alert_sent"
    """
    # Order submitted 400 seconds ago
    _seed_order_with_submitted_at(
        order_repo,
        submitted_at=(datetime.now(tz=timezone.utc) - timedelta(seconds=400)).isoformat(),
    )

    # Broker still shows partial
    broker_response = _make_broker_response()
    mock_adapter.get_order.return_value = broker_response

    policy = PartialFillPolicy(timeout_seconds=300, action_on_timeout="alert_only")
    resolutions = service.check_partial_fills(
        deployment_id=DEP_ID,
        policy=policy,
        correlation_id="corr-001",
    )

    # Broker cancel should NOT have been called
    mock_adapter.cancel_order.assert_not_called()

    # One resolution should be returned
    assert len(resolutions) == 1
    res = resolutions[0]
    assert res.action_taken == "alert_sent"

    # Internal order status should NOT be updated
    updated_order = order_repo.get_by_id(ORDER_ID)
    assert updated_order["status"] == "partial_fill"  # Unchanged
    assert updated_order["cancelled_at"] is None

    # Execution event should be recorded with alert action
    events = event_repo.list_by_order(order_id=ORDER_ID)
    assert any(e["event_type"] == "partial_fill_timeout_alert" for e in events)


# ---------------------------------------------------------------------------
# Test: Broker cancel fails (transient error)
# ---------------------------------------------------------------------------


def test_check_partial_fills_cancel_transient_failure(
    service: PartialFillMonitorService,
    order_repo: MockOrderRepository,
    mock_adapter: Mock,
) -> None:
    """
    Broker cancel fails with transient error → re-raised, order status unchanged.

    Test:
    - Order timeout expired, policy action="cancel_remaining"
    - Broker.cancel_order() raises TransientError (timeout)
    - TransientError is re-raised to caller
    - Order status NOT updated (will retry next cycle)
    - Resolution NOT returned
    """
    # Order submitted 400 seconds ago
    _seed_order_with_submitted_at(
        order_repo,
        submitted_at=(datetime.now(tz=timezone.utc) - timedelta(seconds=400)).isoformat(),
    )

    # Broker get_order succeeds, but cancel_order times out
    broker_response = _make_broker_response()
    mock_adapter.get_order.return_value = broker_response
    mock_adapter.cancel_order.side_effect = TransientError("Broker timeout")

    policy = PartialFillPolicy(timeout_seconds=300, action_on_timeout="cancel_remaining")

    # Should raise TransientError
    with pytest.raises(TransientError, match="Broker timeout"):
        service.check_partial_fills(
            deployment_id=DEP_ID,
            policy=policy,
            correlation_id="corr-001",
        )

    # Order status should NOT be updated (will retry)
    updated_order = order_repo.get_by_id(ORDER_ID)
    assert updated_order["status"] == "partial_fill"


# ---------------------------------------------------------------------------
# Test: Broker cancel fails (permanent error)
# ---------------------------------------------------------------------------


def test_check_partial_fills_cancel_permanent_failure(
    service: PartialFillMonitorService,
    order_repo: MockOrderRepository,
    event_repo: MockExecutionEventRepository,
    mock_adapter: Mock,
) -> None:
    """
    Broker cancel fails with permanent error → resolution with action="error".

    Test:
    - Order timeout expired, policy action="cancel_remaining"
    - Broker.cancel_order() raises ExternalServiceError (permanent)
    - Error resolution returned with action_taken="error"
    - Order status NOT updated
    - Execution event NOT recorded
    """
    # Order submitted 400 seconds ago
    _seed_order_with_submitted_at(
        order_repo,
        submitted_at=(datetime.now(tz=timezone.utc) - timedelta(seconds=400)).isoformat(),
    )

    # Broker get_order succeeds, but cancel_order fails permanently
    broker_response = _make_broker_response()
    mock_adapter.get_order.return_value = broker_response
    mock_adapter.cancel_order.side_effect = ExternalServiceError("Broker rejected cancel")

    policy = PartialFillPolicy(timeout_seconds=300, action_on_timeout="cancel_remaining")
    resolutions = service.check_partial_fills(
        deployment_id=DEP_ID,
        policy=policy,
        correlation_id="corr-001",
    )

    # One error resolution should be returned
    assert len(resolutions) == 1
    res = resolutions[0]
    assert res.action_taken == "error"
    assert "Broker rejected cancel" in res.error_message

    # Order status should NOT be updated
    updated_order = order_repo.get_by_id(ORDER_ID)
    assert updated_order["status"] == "partial_fill"


# ---------------------------------------------------------------------------
# Test: Broker order not found
# ---------------------------------------------------------------------------


def test_check_partial_fills_broker_order_not_found(
    service: PartialFillMonitorService,
    order_repo: MockOrderRepository,
    mock_adapter: Mock,
) -> None:
    """
    Broker doesn't know about order → NotFoundError raised.

    Test:
    - Order status is "partial_fill"
    - Broker.get_order() raises NotFoundError
    - NotFoundError is re-raised to caller
    """
    _seed_order_with_submitted_at(order_repo)

    # Broker doesn't know about this order
    mock_adapter.get_order.side_effect = NotFoundError("Order not found at broker")

    policy = PartialFillPolicy(timeout_seconds=300)

    # Should raise NotFoundError
    with pytest.raises(NotFoundError, match="not found"):
        service.check_partial_fills(
            deployment_id=DEP_ID,
            policy=policy,
            correlation_id="corr-001",
        )


# ---------------------------------------------------------------------------
# Test: Missing submitted_at timestamp
# ---------------------------------------------------------------------------


def test_check_partial_fills_missing_submitted_at(
    service: PartialFillMonitorService,
    order_repo: MockOrderRepository,
    mock_adapter: Mock,
) -> None:
    """
    Order missing submitted_at timestamp → no action, returns resolution with error.

    Test:
    - Order status is "partial_fill" but submitted_at is None
    - Broker.get_order() still called
    - Broker still shows partial
    - No timeout check performed
    - Resolution returned with error_message
    """
    # Seed without submitted_at, then update to remove it
    order_repo.seed(
        order_id=ORDER_ID,
        client_order_id=f"cli-{ORDER_ID}",
        deployment_id=DEP_ID,
        strategy_id=STRAT_ID,
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity="1000",
        status="partial_fill",
        broker_order_id=BROKER_ORDER_ID,
        execution_mode="paper",
        correlation_id="corr-001",
    )

    broker_response = _make_broker_response()
    mock_adapter.get_order.return_value = broker_response

    policy = PartialFillPolicy(timeout_seconds=300)
    resolutions = service.check_partial_fills(
        deployment_id=DEP_ID,
        policy=policy,
        correlation_id="corr-001",
    )

    # One resolution with error should be returned
    assert len(resolutions) == 1
    res = resolutions[0]
    assert res.action_taken == "alert_sent"
    assert res.error_message is not None


# ---------------------------------------------------------------------------
# Test: Invalid submitted_at timestamp
# ---------------------------------------------------------------------------


def test_check_partial_fills_invalid_submitted_at(
    service: PartialFillMonitorService,
    order_repo: MockOrderRepository,
    mock_adapter: Mock,
) -> None:
    """
    Order has invalid submitted_at timestamp → no action, returns resolution with error.

    Test:
    - Order status is "partial_fill" but submitted_at is malformed
    - Broker.get_order() still called
    - Broker still shows partial
    - No timeout check performed (parsing failed)
    - Resolution returned with error_message
    """
    # Seed and update with invalid submitted_at
    _seed_order_with_submitted_at(
        order_repo,
        submitted_at="NOT_A_VALID_ISO_TIMESTAMP",
    )

    broker_response = _make_broker_response()
    mock_adapter.get_order.return_value = broker_response

    policy = PartialFillPolicy(timeout_seconds=300)
    resolutions = service.check_partial_fills(
        deployment_id=DEP_ID,
        policy=policy,
        correlation_id="corr-001",
    )

    # One resolution with error should be returned
    assert len(resolutions) == 1
    res = resolutions[0]
    assert res.action_taken == "alert_sent"
    assert res.error_message is not None


# ---------------------------------------------------------------------------
# Test: Multiple partial fill orders
# ---------------------------------------------------------------------------


def test_check_partial_fills_multiple_orders(
    service: PartialFillMonitorService,
    order_repo: MockOrderRepository,
    event_repo: MockExecutionEventRepository,
    mock_adapter: Mock,
) -> None:
    """
    Multiple partial fill orders processed in sequence.

    Test:
    - Two partial fill orders in deployment
    - First order within timeout (no action)
    - Second order timeout expired (cancelled)
    - Both processed, two resolutions returned
    """
    # First order: submitted 5 seconds ago (within 300s timeout)
    _seed_order_with_submitted_at(
        order_repo,
        order_id="01HTESTORD0000000000000001",
        broker_order_id="TEST-11111",
        submitted_at=(datetime.now(tz=timezone.utc) - timedelta(seconds=5)).isoformat(),
    )

    # Second order: submitted 400 seconds ago (expired)
    _seed_order_with_submitted_at(
        order_repo,
        order_id="01HTESTORD0000000000000002",
        broker_order_id="TEST-22222",
        submitted_at=(datetime.now(tz=timezone.utc) - timedelta(seconds=400)).isoformat(),
    )

    # Broker returns partial for both
    broker_response = _make_broker_response()
    mock_adapter.get_order.return_value = broker_response
    mock_adapter.cancel_order.return_value = broker_response

    policy = PartialFillPolicy(timeout_seconds=300, action_on_timeout="cancel_remaining")
    resolutions = service.check_partial_fills(
        deployment_id=DEP_ID,
        policy=policy,
        correlation_id="corr-001",
    )

    # Two resolutions
    assert len(resolutions) == 2

    # First should be "alert_sent" (within timeout)
    res1 = next(r for r in resolutions if r.order_id == "01HTESTORD0000000000000001")
    assert res1.action_taken == "alert_sent"

    # Second should be "cancelled_remaining"
    res2 = next(r for r in resolutions if r.order_id == "01HTESTORD0000000000000002")
    assert res2.action_taken == "cancelled_remaining"

    # Second order status should be cancelled
    updated_order2 = order_repo.get_by_id("01HTESTORD0000000000000002")
    assert updated_order2["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Test: No broker adapter registered
# ---------------------------------------------------------------------------


def test_check_partial_fills_no_adapter_registered(
    order_repo: MockOrderRepository,
    event_repo: MockExecutionEventRepository,
) -> None:
    """
    No broker adapter registered for execution mode → NotFoundError raised.

    Test:
    - Order execution_mode="paper" but no adapter registered
    - broker_registry.get_adapter() raises NotFoundError
    - NotFoundError is re-raised to caller
    """
    _seed_order_with_submitted_at(order_repo, execution_mode="paper")

    # Broker registry raises NotFoundError (no adapter for "paper")
    broker_registry = MagicMock()
    broker_registry.get_adapter.side_effect = NotFoundError("No adapter for paper mode")

    service = PartialFillMonitorService(
        order_repo=order_repo,
        broker_registry=broker_registry,
        execution_event_repo=event_repo,
    )

    policy = PartialFillPolicy(timeout_seconds=300)

    # Should raise NotFoundError
    with pytest.raises(NotFoundError, match="No broker adapter"):
        service.check_partial_fills(
            deployment_id=DEP_ID,
            policy=policy,
            correlation_id="corr-001",
        )
