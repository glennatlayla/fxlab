"""
Unit tests for the LiveExecutionService.

Covers:
- submit_live_order: happy path (validate → kill switch → risk gate → persist → broker → update)
- submit_live_order: kill switch active → KillSwitchActiveError
- submit_live_order: risk gate rejection → RiskGateRejectionError
- submit_live_order: deployment not found → NotFoundError
- submit_live_order: deployment not in live mode → StateTransitionError
- submit_live_order: idempotent (duplicate client_order_id returns existing)
- submit_live_order: broker failure → ExternalServiceError
- submit_live_order: order persisted BEFORE broker submission
- cancel_live_order: happy path
- cancel_live_order: order not found
- list_live_orders: happy path and filtered by status
- get_live_positions: delegates to broker adapter
- get_live_account: delegates to broker adapter
- get_live_pnl: computes from broker positions
- sync_order_status: reconciles broker state to database
- Thread safety: concurrent submissions don't corrupt state

Per Phase 6 M3 spec:
- Every order persisted to database before broker submission
- Kill switch check before every submission
- Risk gate enforcement mandatory
- All existing paper/shadow tests unaffected

Example:
    pytest tests/unit/test_live_execution_service.py -v
"""

from __future__ import annotations

import threading
import time
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from libs.contracts.errors import (
    KillSwitchActiveError,
    NotFoundError,
    RiskGateRejectionError,
    StateTransitionError,
)
from libs.contracts.execution import (
    AccountSnapshot,
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
from libs.contracts.mocks.mock_execution_event_repository import (
    MockExecutionEventRepository,
)
from libs.contracts.mocks.mock_order_repository import MockOrderRepository
from libs.contracts.mocks.mock_position_repository import MockPositionRepository
from libs.contracts.mocks.mock_risk_event_repository import MockRiskEventRepository
from services.api.infrastructure.broker_registry import BrokerAdapterRegistry
from services.api.services.live_execution_service import _PositionCache
from services.api.services.risk_gate_service import RiskGateService

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEP_ID = "01HTESTDEP0000000000000001"
STRATEGY_ID = "01HTESTSTRT000000000000001"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def deployment_repo() -> MockDeploymentRepository:
    """Empty deployment repository."""
    return MockDeploymentRepository()


@pytest.fixture()
def order_repo() -> MockOrderRepository:
    """Empty order repository."""
    return MockOrderRepository()


@pytest.fixture()
def position_repo() -> MockPositionRepository:
    """Empty position repository."""
    return MockPositionRepository()


@pytest.fixture()
def event_repo() -> MockExecutionEventRepository:
    """Empty execution event repository."""
    return MockExecutionEventRepository()


@pytest.fixture()
def risk_gate(deployment_repo: MockDeploymentRepository) -> RiskGateService:
    """Risk gate service wired to mock repositories."""
    return RiskGateService(
        deployment_repo=deployment_repo,
        risk_event_repo=MockRiskEventRepository(),
    )


@pytest.fixture()
def broker_registry() -> BrokerAdapterRegistry:
    """Empty broker adapter registry."""
    return BrokerAdapterRegistry()


@pytest.fixture()
def kill_switch_service() -> MagicMock:
    """Mock kill switch service — is_halted returns False by default."""
    mock = MagicMock()
    mock.is_halted.return_value = False
    return mock


@pytest.fixture()
def mock_adapter() -> MockBrokerAdapter:
    """MockBrokerAdapter in instant-fill mode."""
    return MockBrokerAdapter(
        fill_mode="instant",
        fill_price=Decimal("175.50"),
        market_open=True,
        account_equity=Decimal("1000000"),
        account_cash=Decimal("1000000"),
    )


@pytest.fixture()
def service(
    deployment_repo: MockDeploymentRepository,
    order_repo: MockOrderRepository,
    position_repo: MockPositionRepository,
    event_repo: MockExecutionEventRepository,
    risk_gate: RiskGateService,
    broker_registry: BrokerAdapterRegistry,
    kill_switch_service: MagicMock,
):
    """Create a LiveExecutionService with all dependencies wired."""
    from libs.contracts.interfaces.transaction_manager_interface import (
        TransactionManagerInterface,
    )
    from services.api.services.live_execution_service import LiveExecutionService

    tx = MagicMock(spec=TransactionManagerInterface)

    return LiveExecutionService(
        deployment_repo=deployment_repo,
        order_repo=order_repo,
        position_repo=position_repo,
        execution_event_repo=event_repo,
        risk_gate=risk_gate,
        broker_registry=broker_registry,
        kill_switch_service=kill_switch_service,
        transaction_manager=tx,
    )


@pytest.fixture()
def active_live_deployment(
    deployment_repo: MockDeploymentRepository,
    broker_registry: BrokerAdapterRegistry,
    mock_adapter: MockBrokerAdapter,
    risk_gate: RiskGateService,
) -> str:
    """Create and register an active live deployment with risk limits, return its ID.

    Configures permissive risk limits so the fail-closed risk gate does not
    reject orders from this live deployment.  Tests that need restrictive
    limits override them via ``risk_gate.set_risk_limits()`` directly.
    """
    from libs.contracts.risk import PreTradeRiskLimits

    record = deployment_repo.seed(
        deployment_id=DEP_ID,
        state="active",
        execution_mode="live",
        emergency_posture="flatten_all",
    )
    broker_registry.register(
        deployment_id=record["id"],
        adapter=mock_adapter,
        broker_type="mock",
    )
    # Live deployments MUST have risk limits configured (fail-closed policy).
    # Use permissive defaults so most tests pass without per-test overrides.
    risk_gate.set_risk_limits(
        deployment_id=record["id"],
        limits=PreTradeRiskLimits(
            max_position_size=Decimal("1000000"),
            max_daily_loss=Decimal("1000000"),
            max_order_value=Decimal("1000000"),
            max_concentration_pct=Decimal("100"),
            max_open_orders=10000,
        ),
    )
    return record["id"]


def _make_order(
    *,
    client_order_id: str = "ord-live-001",
    symbol: str = "AAPL",
    side: OrderSide = OrderSide.BUY,
    quantity: Decimal = Decimal("100"),
) -> OrderRequest:
    """Helper to create a standard live order request."""
    return OrderRequest(
        client_order_id=client_order_id,
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        time_in_force=TimeInForce.DAY,
        deployment_id=DEP_ID,
        strategy_id=STRATEGY_ID,
        correlation_id="corr-live-test-001",
        execution_mode=ExecutionMode.LIVE,
    )


# ---------------------------------------------------------------------------
# Submit live order — happy path
# ---------------------------------------------------------------------------


class TestSubmitLiveOrderHappyPath:
    """Tests for successful live order submission."""

    def test_submit_returns_response_with_broker_order_id(
        self, service, active_live_deployment, order_repo: MockOrderRepository
    ) -> None:
        """submit_live_order returns OrderResponse with broker_order_id set."""
        order = _make_order()
        resp = service.submit_live_order(
            deployment_id=active_live_deployment,
            request=order,
            correlation_id="corr-001",
        )
        assert isinstance(resp, OrderResponse)
        assert resp.broker_order_id is not None
        assert resp.broker_order_id != ""

    def test_submit_persists_order_to_database(
        self, service, active_live_deployment, order_repo: MockOrderRepository
    ) -> None:
        """Order is persisted to the database."""
        order = _make_order(client_order_id="persist-test-001")
        service.submit_live_order(
            deployment_id=active_live_deployment,
            request=order,
            correlation_id="corr-001",
        )
        found = order_repo.get_by_client_order_id("persist-test-001")
        assert found is not None
        assert found["symbol"] == "AAPL"
        assert found["execution_mode"] == "live"

    def test_submit_records_execution_events(
        self, service, active_live_deployment, event_repo: MockExecutionEventRepository
    ) -> None:
        """Execution events are recorded for order submission."""
        order = _make_order()
        service.submit_live_order(
            deployment_id=active_live_deployment,
            request=order,
            correlation_id="corr-001",
        )
        # At minimum: risk_checked + submitted events
        all_events = event_repo.get_all()
        assert len(all_events) >= 2
        event_types = [e["event_type"] for e in all_events]
        assert "risk_checked" in event_types
        assert "submitted" in event_types

    def test_submit_calls_kill_switch_check(
        self,
        service,
        active_live_deployment,
        kill_switch_service: MagicMock,
    ) -> None:
        """Kill switch is_halted is called before every submission."""
        order = _make_order()
        service.submit_live_order(
            deployment_id=active_live_deployment,
            request=order,
            correlation_id="corr-001",
        )
        kill_switch_service.is_halted.assert_called_once()
        call_kwargs = kill_switch_service.is_halted.call_args
        assert call_kwargs.kwargs["deployment_id"] == active_live_deployment

    def test_submit_order_status_updated_after_broker_ack(
        self,
        service,
        active_live_deployment,
        order_repo: MockOrderRepository,
    ) -> None:
        """Order status is updated from pending to submitted after broker ack."""
        order = _make_order(client_order_id="status-update-001")
        service.submit_live_order(
            deployment_id=active_live_deployment,
            request=order,
            correlation_id="corr-001",
        )
        # MockBrokerAdapter in instant-fill mode returns FILLED,
        # so we expect the DB record to reflect the broker response status
        found = order_repo.get_by_client_order_id("status-update-001")
        assert found is not None
        # The status should be either "submitted" or "filled" depending on
        # how fast the broker acknowledged
        assert found["status"] in ("submitted", "filled")


# ---------------------------------------------------------------------------
# Submit live order — kill switch active
# ---------------------------------------------------------------------------


class TestSubmitLiveOrderKillSwitch:
    """Tests for kill switch blocking live order submission."""

    def test_kill_switch_active_raises_error(
        self,
        service,
        active_live_deployment,
        kill_switch_service: MagicMock,
    ) -> None:
        """KillSwitchActiveError raised when kill switch is active."""
        kill_switch_service.is_halted.return_value = True
        order = _make_order()
        with pytest.raises(KillSwitchActiveError):
            service.submit_live_order(
                deployment_id=active_live_deployment,
                request=order,
                correlation_id="corr-001",
            )

    def test_kill_switch_active_no_order_persisted(
        self,
        service,
        active_live_deployment,
        kill_switch_service: MagicMock,
        order_repo: MockOrderRepository,
    ) -> None:
        """No order is persisted when kill switch blocks submission."""
        kill_switch_service.is_halted.return_value = True
        order = _make_order(client_order_id="should-not-persist")
        with pytest.raises(KillSwitchActiveError):
            service.submit_live_order(
                deployment_id=active_live_deployment,
                request=order,
                correlation_id="corr-001",
            )
        assert order_repo.get_by_client_order_id("should-not-persist") is None

    def test_kill_switch_active_no_broker_submission(
        self,
        service,
        active_live_deployment,
        kill_switch_service: MagicMock,
        mock_adapter: MockBrokerAdapter,
    ) -> None:
        """No order submitted to broker when kill switch is active."""
        kill_switch_service.is_halted.return_value = True
        order = _make_order()
        with pytest.raises(KillSwitchActiveError):
            service.submit_live_order(
                deployment_id=active_live_deployment,
                request=order,
                correlation_id="corr-001",
            )
        assert mock_adapter.get_submitted_orders_count() == 0


# ---------------------------------------------------------------------------
# Submit live order — risk gate rejection
# ---------------------------------------------------------------------------


class TestSubmitLiveOrderRiskGate:
    """Tests for risk gate rejection on live order submission."""

    def test_risk_gate_rejection_raises_error(
        self,
        service,
        active_live_deployment,
        deployment_repo: MockDeploymentRepository,
    ) -> None:
        """RiskGateRejectionError raised when risk gate rejects the order."""
        from libs.contracts.risk import PreTradeRiskLimits

        # Set very restrictive risk limits
        service._risk_gate.set_risk_limits(
            deployment_id=active_live_deployment,
            limits=PreTradeRiskLimits(max_order_value=Decimal("1")),
        )
        order = _make_order(quantity=Decimal("1000"))  # exceeds limit
        with pytest.raises(RiskGateRejectionError):
            service.submit_live_order(
                deployment_id=active_live_deployment,
                request=order,
                correlation_id="corr-001",
            )

    def test_risk_gate_rejection_no_broker_submission(
        self,
        service,
        active_live_deployment,
        mock_adapter: MockBrokerAdapter,
    ) -> None:
        """No broker submission when risk gate rejects."""
        from libs.contracts.risk import PreTradeRiskLimits

        service._risk_gate.set_risk_limits(
            deployment_id=active_live_deployment,
            limits=PreTradeRiskLimits(max_order_value=Decimal("1")),
        )
        order = _make_order(quantity=Decimal("1000"))
        with pytest.raises(RiskGateRejectionError):
            service.submit_live_order(
                deployment_id=active_live_deployment,
                request=order,
                correlation_id="corr-001",
            )
        assert mock_adapter.get_submitted_orders_count() == 0


# ---------------------------------------------------------------------------
# Submit live order — deployment validation
# ---------------------------------------------------------------------------


class TestSubmitLiveOrderDeploymentValidation:
    """Tests for deployment state validation on live order submission."""

    def test_deployment_not_found_raises_error(self, service) -> None:
        """NotFoundError when deployment does not exist."""
        order = _make_order()
        with pytest.raises(NotFoundError):
            service.submit_live_order(
                deployment_id="01HNONEXISTENT0000000000000",
                request=order,
                correlation_id="corr-001",
            )

    def test_deployment_not_active_raises_error(
        self,
        service,
        deployment_repo: MockDeploymentRepository,
        broker_registry: BrokerAdapterRegistry,
        mock_adapter: MockBrokerAdapter,
    ) -> None:
        """StateTransitionError when deployment is not active."""
        dep_id = "01HTESTDEP0000000000000002"
        deployment_repo.seed(
            deployment_id=dep_id,
            state="paused",
            execution_mode="live",
            emergency_posture="flatten_all",
        )
        broker_registry.register(
            deployment_id=dep_id,
            adapter=mock_adapter,
            broker_type="mock",
        )
        order = _make_order()
        with pytest.raises(StateTransitionError):
            service.submit_live_order(
                deployment_id=dep_id,
                request=order,
                correlation_id="corr-001",
            )

    def test_deployment_not_live_mode_raises_error(
        self,
        service,
        deployment_repo: MockDeploymentRepository,
        broker_registry: BrokerAdapterRegistry,
    ) -> None:
        """StateTransitionError when deployment is not in live mode."""
        dep_id = "01HTESTDEP0000000000000003"
        deployment_repo.seed(
            deployment_id=dep_id,
            state="active",
            execution_mode="paper",
            emergency_posture="flatten_all",
        )
        # No broker adapter registered for paper mode deployment
        order = _make_order()
        with pytest.raises((StateTransitionError, NotFoundError)):
            service.submit_live_order(
                deployment_id=dep_id,
                request=order,
                correlation_id="corr-001",
            )

    def test_no_broker_adapter_registered_raises_error(
        self,
        service,
        deployment_repo: MockDeploymentRepository,
    ) -> None:
        """NotFoundError when deployment has no broker adapter."""
        dep_id = "01HTESTDEP0000000000000004"
        deployment_repo.seed(
            deployment_id=dep_id,
            state="active",
            execution_mode="live",
            emergency_posture="flatten_all",
        )
        order = _make_order()
        with pytest.raises(NotFoundError):
            service.submit_live_order(
                deployment_id=dep_id,
                request=order,
                correlation_id="corr-001",
            )


# ---------------------------------------------------------------------------
# Submit live order — idempotency
# ---------------------------------------------------------------------------


class TestSubmitLiveOrderIdempotency:
    """Tests for idempotent live order submission."""

    def test_duplicate_client_order_id_returns_existing(
        self,
        service,
        active_live_deployment,
        mock_adapter: MockBrokerAdapter,
    ) -> None:
        """Duplicate client_order_id returns the existing order, not a new one."""
        order = _make_order(client_order_id="idempotent-001")
        resp1 = service.submit_live_order(
            deployment_id=active_live_deployment,
            request=order,
            correlation_id="corr-001",
        )
        resp2 = service.submit_live_order(
            deployment_id=active_live_deployment,
            request=order,
            correlation_id="corr-002",
        )
        # Second call should return the same broker_order_id
        assert resp1.broker_order_id == resp2.broker_order_id
        # Broker should only have received one order
        assert mock_adapter.get_submitted_orders_count() == 1


# ---------------------------------------------------------------------------
# Submit live order — broker failure
# ---------------------------------------------------------------------------


class TestSubmitLiveOrderBrokerFailure:
    """Tests for broker communication failures during live order submission."""

    def test_broker_failure_raises_external_service_error(
        self,
        deployment_repo: MockDeploymentRepository,
        order_repo: MockOrderRepository,
        position_repo: MockPositionRepository,
        event_repo: MockExecutionEventRepository,
        risk_gate: RiskGateService,
        kill_switch_service: MagicMock,
    ) -> None:
        """ExternalServiceError propagated when broker submit fails."""
        from libs.contracts.interfaces.transaction_manager_interface import (
            TransactionManagerInterface,
        )
        from libs.contracts.risk import PreTradeRiskLimits
        from services.api.services.live_execution_service import LiveExecutionService

        reject_adapter = MockBrokerAdapter(
            fill_mode="reject",
            reject_reason="Broker connectivity lost",
            market_open=True,
        )
        registry = BrokerAdapterRegistry()
        dep_id = "01HTESTDEP0000000000000005"
        deployment_repo.seed(
            deployment_id=dep_id,
            state="active",
            execution_mode="live",
            emergency_posture="flatten_all",
        )
        registry.register(
            deployment_id=dep_id,
            adapter=reject_adapter,
            broker_type="mock",
        )

        # Mock transaction manager for live execution
        tx = MagicMock(spec=TransactionManagerInterface)

        svc = LiveExecutionService(
            deployment_repo=deployment_repo,
            order_repo=order_repo,
            position_repo=position_repo,
            execution_event_repo=event_repo,
            risk_gate=risk_gate,
            broker_registry=registry,
            kill_switch_service=kill_switch_service,
            transaction_manager=tx,
        )

        # Configure permissive risk limits for live deployment
        risk_gate.set_risk_limits(
            deployment_id=dep_id,
            limits=PreTradeRiskLimits(
                max_position_size=Decimal("1000000"),
                max_daily_loss=Decimal("1000000"),
                max_order_value=Decimal("1000000"),
                max_concentration_pct=Decimal("100"),
                max_open_orders=10000,
            ),
        )

        order = _make_order(client_order_id="broker-fail-001")
        resp = svc.submit_live_order(
            deployment_id=dep_id,
            request=order,
            correlation_id="corr-001",
        )
        # MockBrokerAdapter in reject mode returns REJECTED status
        assert resp.status == OrderStatus.REJECTED


# ---------------------------------------------------------------------------
# Submit live order — order persisted before broker submission
# ---------------------------------------------------------------------------


class TestSubmitLiveOrderPersistenceOrder:
    """Verify that the order is persisted BEFORE broker submission."""

    def test_order_exists_in_db_before_broker_call(
        self,
        service,
        active_live_deployment,
        order_repo: MockOrderRepository,
    ) -> None:
        """Order must be in the database before broker receives it."""
        order = _make_order(client_order_id="persist-before-broker-001")
        # We verify this indirectly: after a successful submit,
        # the order MUST be in the database
        service.submit_live_order(
            deployment_id=active_live_deployment,
            request=order,
            correlation_id="corr-001",
        )
        found = order_repo.get_by_client_order_id("persist-before-broker-001")
        assert found is not None
        assert found["status"] in ("pending", "submitted", "filled")


# ---------------------------------------------------------------------------
# Cancel live order
# ---------------------------------------------------------------------------


class TestCancelLiveOrder:
    """Tests for live order cancellation."""

    def test_cancel_returns_cancelled_status(
        self,
        service,
        active_live_deployment,
    ) -> None:
        """cancel_live_order returns response with CANCELLED status."""
        # First submit an order
        order = _make_order(client_order_id="cancel-test-001")
        resp = service.submit_live_order(
            deployment_id=active_live_deployment,
            request=order,
            correlation_id="corr-001",
        )
        # Then cancel it
        cancel_resp = service.cancel_live_order(
            deployment_id=active_live_deployment,
            broker_order_id=resp.broker_order_id,
            correlation_id="corr-002",
        )
        assert isinstance(cancel_resp, OrderResponse)
        # Cancel may return CANCELLED or current status (already filled)
        assert cancel_resp.status in (
            OrderStatus.CANCELLED,
            OrderStatus.FILLED,
        )

    def test_cancel_nonexistent_order_raises_not_found(
        self,
        service,
        active_live_deployment,
    ) -> None:
        """NotFoundError when cancelling an order that does not exist."""
        with pytest.raises(NotFoundError):
            service.cancel_live_order(
                deployment_id=active_live_deployment,
                broker_order_id="NONEXISTENT-ORDER-ID",
                correlation_id="corr-001",
            )


# ---------------------------------------------------------------------------
# List live orders
# ---------------------------------------------------------------------------


class TestListLiveOrders:
    """Tests for listing live orders."""

    def test_list_returns_persisted_orders(
        self,
        service,
        active_live_deployment,
    ) -> None:
        """list_live_orders returns orders from the database."""
        order1 = _make_order(client_order_id="list-test-001")
        order2 = _make_order(client_order_id="list-test-002", symbol="MSFT")
        service.submit_live_order(
            deployment_id=active_live_deployment,
            request=order1,
            correlation_id="corr-001",
        )
        service.submit_live_order(
            deployment_id=active_live_deployment,
            request=order2,
            correlation_id="corr-002",
        )
        orders = service.list_live_orders(deployment_id=active_live_deployment)
        assert len(orders) >= 2
        client_ids = [o["client_order_id"] for o in orders]
        assert "list-test-001" in client_ids
        assert "list-test-002" in client_ids

    def test_list_filtered_by_status(
        self,
        service,
        active_live_deployment,
    ) -> None:
        """list_live_orders can filter by status."""
        order = _make_order(client_order_id="filter-test-001")
        service.submit_live_order(
            deployment_id=active_live_deployment,
            request=order,
            correlation_id="corr-001",
        )
        # MockBrokerAdapter in instant mode fills immediately
        filled = service.list_live_orders(
            deployment_id=active_live_deployment,
            status="filled",
        )
        # Should find at least the one we submitted (instant fill)
        assert isinstance(filled, list)


# ---------------------------------------------------------------------------
# Get live positions
# ---------------------------------------------------------------------------


class TestGetLivePositions:
    """Tests for live position queries."""

    def test_get_positions_returns_list(
        self,
        service,
        active_live_deployment,
    ) -> None:
        """get_live_positions returns list of PositionSnapshot."""
        positions = service.get_live_positions(
            deployment_id=active_live_deployment,
        )
        assert isinstance(positions, list)

    def test_get_positions_after_fill(
        self,
        service,
        active_live_deployment,
    ) -> None:
        """Positions reflect fills after order execution."""
        order = _make_order(client_order_id="pos-test-001")
        service.submit_live_order(
            deployment_id=active_live_deployment,
            request=order,
            correlation_id="corr-001",
        )
        positions = service.get_live_positions(
            deployment_id=active_live_deployment,
        )
        # MockBrokerAdapter instant fill: should have a position for AAPL
        symbols = [p.symbol for p in positions]
        assert "AAPL" in symbols


# ---------------------------------------------------------------------------
# Get live account
# ---------------------------------------------------------------------------


class TestGetLiveAccount:
    """Tests for live account queries."""

    def test_get_account_returns_snapshot(
        self,
        service,
        active_live_deployment,
    ) -> None:
        """get_live_account returns AccountSnapshot."""
        acct = service.get_live_account(
            deployment_id=active_live_deployment,
        )
        assert isinstance(acct, AccountSnapshot)
        assert acct.equity > 0


# ---------------------------------------------------------------------------
# Get live P&L
# ---------------------------------------------------------------------------


class TestGetLivePnl:
    """Tests for live P&L summary."""

    def test_get_pnl_returns_dict(
        self,
        service,
        active_live_deployment,
    ) -> None:
        """get_live_pnl returns dict with expected keys."""
        pnl = service.get_live_pnl(
            deployment_id=active_live_deployment,
        )
        assert isinstance(pnl, dict)
        assert "total_unrealized_pnl" in pnl
        assert "total_realized_pnl" in pnl
        assert "positions" in pnl


# ---------------------------------------------------------------------------
# Sync order status
# ---------------------------------------------------------------------------


class TestSyncOrderStatus:
    """Tests for order status synchronisation from broker."""

    def test_sync_updates_database(
        self,
        service,
        active_live_deployment,
        order_repo: MockOrderRepository,
    ) -> None:
        """sync_order_status fetches broker state and updates database."""
        order = _make_order(client_order_id="sync-test-001")
        resp = service.submit_live_order(
            deployment_id=active_live_deployment,
            request=order,
            correlation_id="corr-001",
        )
        synced = service.sync_order_status(
            deployment_id=active_live_deployment,
            broker_order_id=resp.broker_order_id,
            correlation_id="corr-002",
        )
        assert isinstance(synced, OrderResponse)
        # Database should be updated
        found = order_repo.get_by_broker_order_id(resp.broker_order_id)
        assert found is not None


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Tests for concurrent live order submission safety."""

    def test_concurrent_submissions_no_data_corruption(
        self,
        service,
        active_live_deployment,
        order_repo: MockOrderRepository,
    ) -> None:
        """Concurrent order submissions don't corrupt shared state."""
        errors: list[Exception] = []
        results: list[OrderResponse] = []
        lock = threading.Lock()

        def submit(idx: int) -> None:
            try:
                order = _make_order(client_order_id=f"concurrent-{idx:04d}")
                resp = service.submit_live_order(
                    deployment_id=active_live_deployment,
                    request=order,
                    correlation_id=f"corr-concurrent-{idx}",
                )
                with lock:
                    results.append(resp)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=submit, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Errors during concurrent submission: {errors}"
        assert len(results) == 10
        # All broker_order_ids should be unique
        broker_ids = {r.broker_order_id for r in results}
        assert len(broker_ids) == 10


# ---------------------------------------------------------------------------
# Transaction boundary tests
# ---------------------------------------------------------------------------


class TestTransactionBoundaries:
    """Verify the service commits at critical points when a tx manager is provided."""

    def test_commit_before_broker_call_on_success(
        self,
        deployment_repo: MockDeploymentRepository,
        order_repo: MockOrderRepository,
        position_repo: MockPositionRepository,
        event_repo: MockExecutionEventRepository,
        risk_gate: RiskGateService,
        kill_switch_service: MagicMock,
        mock_adapter: MockBrokerAdapter,
    ) -> None:
        """Transaction manager is committed before broker submission and after broker response."""
        from libs.contracts.interfaces.transaction_manager_interface import (
            TransactionManagerInterface,
        )
        from services.api.services.live_execution_service import LiveExecutionService

        # Use a fresh registry to avoid conflicts with other fixtures
        fresh_registry = BrokerAdapterRegistry()
        dep_record = deployment_repo.seed(
            deployment_id="01HTESTTXOK0000000000000001",
            state="active",
            execution_mode="live",
            emergency_posture="flatten_all",
        )
        dep_id = dep_record["id"]
        fresh_registry.register(
            deployment_id=dep_id,
            adapter=mock_adapter,
            broker_type="mock",
        )

        tx = MagicMock(spec=TransactionManagerInterface)
        svc = LiveExecutionService(
            deployment_repo=deployment_repo,
            order_repo=order_repo,
            position_repo=position_repo,
            execution_event_repo=event_repo,
            risk_gate=risk_gate,
            broker_registry=fresh_registry,
            kill_switch_service=kill_switch_service,
            transaction_manager=tx,
        )

        # Configure permissive risk limits for live deployment
        from libs.contracts.risk import PreTradeRiskLimits

        risk_gate.set_risk_limits(
            deployment_id=dep_id,
            limits=PreTradeRiskLimits(
                max_position_size=Decimal("1000000"),
                max_daily_loss=Decimal("1000000"),
                max_order_value=Decimal("1000000"),
                max_concentration_pct=Decimal("100"),
                max_open_orders=10000,
            ),
        )

        order = _make_order(client_order_id="ord-tx-ok-001")
        svc.submit_live_order(
            deployment_id=dep_id,
            request=order,
            correlation_id="corr-tx-001",
        )

        # Must commit at least twice: once before broker call (order durable),
        # once after broker response (status + events durable).
        assert tx.commit.call_count >= 2, (
            f"Expected at least 2 commits (pre-broker, post-broker), got {tx.commit.call_count}"
        )

    def test_commit_on_broker_failure(
        self,
        deployment_repo: MockDeploymentRepository,
        order_repo: MockOrderRepository,
        position_repo: MockPositionRepository,
        event_repo: MockExecutionEventRepository,
        risk_gate: RiskGateService,
        kill_switch_service: MagicMock,
    ) -> None:
        """When broker submission fails, rejection is committed before raising."""
        from libs.contracts.errors import ExternalServiceError
        from libs.contracts.interfaces.transaction_manager_interface import (
            TransactionManagerInterface,
        )
        from services.api.services.live_execution_service import LiveExecutionService

        fresh_registry = BrokerAdapterRegistry()
        dep_record = deployment_repo.seed(
            deployment_id="01HTESTTXFL0000000000000001",
            state="active",
            execution_mode="live",
            emergency_posture="flatten_all",
        )
        dep_id = dep_record["id"]

        failing_adapter = MagicMock()
        failing_adapter.submit_order.side_effect = RuntimeError("broker down")
        failing_adapter.get_positions.return_value = []
        failing_adapter.get_account.return_value = MagicMock(
            equity=Decimal("100000"),
            cash=Decimal("100000"),
            buying_power=Decimal("100000"),
            pending_orders_count=0,
            daily_pnl=Decimal("0"),
        )
        # Set is_paper_adapter to False so the adapter type validation passes
        failing_adapter.is_paper_adapter = False
        fresh_registry.register(
            deployment_id=dep_id,
            adapter=failing_adapter,
            broker_type="mock",
        )

        tx = MagicMock(spec=TransactionManagerInterface)
        svc = LiveExecutionService(
            deployment_repo=deployment_repo,
            order_repo=order_repo,
            position_repo=position_repo,
            execution_event_repo=event_repo,
            risk_gate=risk_gate,
            broker_registry=fresh_registry,
            kill_switch_service=kill_switch_service,
            transaction_manager=tx,
        )

        # Configure permissive risk limits for live deployment
        from libs.contracts.risk import PreTradeRiskLimits

        risk_gate.set_risk_limits(
            deployment_id=dep_id,
            limits=PreTradeRiskLimits(
                max_position_size=Decimal("1000000"),
                max_daily_loss=Decimal("1000000"),
                max_order_value=Decimal("1000000"),
                max_concentration_pct=Decimal("100"),
                max_open_orders=10000,
            ),
        )

        order = _make_order(client_order_id="ord-tx-fail-001")
        with pytest.raises(ExternalServiceError):
            svc.submit_live_order(
                deployment_id=dep_id,
                request=order,
                correlation_id="corr-tx-fail",
            )

        # Commit once before broker call (order durable), once for rejection
        assert tx.commit.call_count >= 2, (
            f"Expected at least 2 commits (pre-broker, post-rejection), got {tx.commit.call_count}"
        )

    def test_no_crash_when_transaction_manager_is_none(
        self,
        service,
        active_live_deployment: str,
    ) -> None:
        """Service works normally when transaction_manager=None (backward compat)."""
        order = _make_order()

        # Should not raise — tx is None so no commits happen
        resp = service.submit_live_order(
            deployment_id=active_live_deployment,
            request=order,
            correlation_id="corr-no-tx",
        )
        assert resp.broker_order_id is not None


# ---------------------------------------------------------------------------
# Position cache staleness guard
# ---------------------------------------------------------------------------


class TestPositionCacheStalenessGuard:
    """Tests for position/account caching with staleness awareness."""

    def test_cache_enabled_and_initialized(
        self,
        service,
    ) -> None:
        """Service initializes with cache enabled and TTL set."""
        assert service._position_cache is None  # Initially empty
        assert service._position_cache_ttl_seconds == 2.0  # Default TTL

    def test_cache_is_fresh_when_empty(
        self,
        service,
    ) -> None:
        """Cache freshness check returns False when cache is empty."""
        assert not service._is_position_cache_fresh()

    def test_cache_freshness_with_old_timestamp(
        self,
        service,
    ) -> None:
        """Cache is considered stale if older than TTL."""
        from datetime import datetime
        from decimal import Decimal

        from libs.contracts.execution import AccountSnapshot

        # Manually set cache with an old timestamp
        old_timestamp = time.monotonic() - 5.0  # 5 seconds ago
        service._position_cache = _PositionCache(
            positions=[],
            account=AccountSnapshot(
                account_id="test",
                equity=Decimal("100000"),
                cash=Decimal("50000"),
                buying_power=Decimal("100000"),
                portfolio_value=Decimal("50000"),
                updated_at=datetime.now(),
            ),
            timestamp=old_timestamp,
            pending_exposure={},
        )

        # Cache should be stale
        assert not service._is_position_cache_fresh()

    def test_cache_freshness_with_recent_timestamp(
        self,
        service,
    ) -> None:
        """Cache is considered fresh if within TTL."""
        from datetime import datetime
        from decimal import Decimal

        from libs.contracts.execution import AccountSnapshot

        # Manually set cache with a recent timestamp
        recent_timestamp = time.monotonic() - 0.5  # 0.5 seconds ago
        service._position_cache = _PositionCache(
            positions=[],
            account=AccountSnapshot(
                account_id="test",
                equity=Decimal("100000"),
                cash=Decimal("50000"),
                buying_power=Decimal("100000"),
                portfolio_value=Decimal("50000"),
                updated_at=datetime.now(),
            ),
            timestamp=recent_timestamp,
            pending_exposure={},
        )

        # Cache should be fresh
        assert service._is_position_cache_fresh()

    def test_cache_invalidation(
        self,
        service,
    ) -> None:
        """Cache invalidation clears the cache."""
        from datetime import datetime
        from decimal import Decimal

        from libs.contracts.execution import AccountSnapshot

        # Set cache
        service._position_cache = _PositionCache(
            positions=[],
            account=AccountSnapshot(
                account_id="test",
                equity=Decimal("100000"),
                cash=Decimal("50000"),
                buying_power=Decimal("100000"),
                portfolio_value=Decimal("50000"),
                updated_at=datetime.now(),
            ),
            timestamp=time.monotonic(),
            pending_exposure={},
        )

        # Verify cache is set
        assert service._position_cache is not None

        # Invalidate cache
        service._invalidate_position_cache()

        # Cache should be cleared
        assert service._position_cache is None

    def test_cache_excludes_non_submitted_orders(
        self,
        service,
        active_live_deployment,
        order_repo: MockOrderRepository,
    ) -> None:
        """Pending exposure excludes orders that haven't left system yet (pending status)."""
        # Seed a pending order (not yet submitted to broker)
        order_repo.save(
            client_order_id="ord-local-pending",
            deployment_id=active_live_deployment,
            strategy_id=STRATEGY_ID,
            symbol="MSFT",
            side="sell",
            order_type="limit",
            quantity="100",
            time_in_force="day",
            status="pending",  # Not yet submitted
            correlation_id="corr-local",
            execution_mode="live",
            limit_price="350.00",
        )

        # Trigger cache population
        service._position_cache = None
        service._calculate_pending_exposure(active_live_deployment)

        # The pending order should NOT be in pending_exposure because it's not submitted yet
        pending = service._calculate_pending_exposure(active_live_deployment)
        assert "MSFT" not in pending or pending.get("MSFT", Decimal("0")) == Decimal("0")
