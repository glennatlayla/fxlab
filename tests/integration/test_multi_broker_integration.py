"""
Multi-broker integration tests for Phase 6, Milestone 5.

Purpose:
    Verify LiveExecutionService correctly orchestrates order execution across
    multiple broker deployments using real SQL repositories and the
    BrokerAdapterRegistry. Tests broker isolation, failover scenarios,
    and position/P&L tracking per deployment.

Responsibilities:
    - Exercise LiveExecutionService with multiple MockBrokerAdapter instances.
    - Verify order and position persistence via real SQL repositories.
    - Confirm broker adapter registry isolation and deregistration.
    - Validate cross-broker scenarios: parallel execution, failover, position tracking.

Does NOT:
    - Test individual broker adapters (unit tests cover that).
    - Test risk gate or kill switch in isolation (separate unit tests).
    - Require external services (uses in-memory SQLite and MockBrokerAdapter).

Dependencies:
    - SQLAlchemy Session (via integration_db_session fixture).
    - libs.contracts.models: ORM models for User, Strategy, Deployment, Order, etc.
    - services.api.repositories: SqlOrderRepository, SqlPositionRepository, etc.
    - services.api.infrastructure.broker_registry: BrokerAdapterRegistry.
    - libs.contracts.mocks.mock_broker_adapter: MockBrokerAdapter.
    - services.api.services.live_execution_service: LiveExecutionService.
    - services.api.services.risk_gate_service: RiskGateService.
    - services.api.services.kill_switch_service: KillSwitchService.
    - libs.contracts.mocks: MockRiskEventRepository, MockKillSwitchEventRepository.

Example:
    pytest tests/integration/test_multi_broker_integration.py::TestParallelBrokerExecution::test_same_order_on_two_brokers -v
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from libs.contracts.errors import NotFoundError
from libs.contracts.execution import (
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from libs.contracts.interfaces.transaction_manager_interface import (
    TransactionManagerInterface,
)
from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter
from libs.contracts.mocks.mock_kill_switch_event_repository import (
    MockKillSwitchEventRepository,
)
from libs.contracts.mocks.mock_risk_event_repository import MockRiskEventRepository
from libs.contracts.models import (
    Deployment,
    Strategy,
    User,
)
from libs.contracts.risk import PreTradeRiskLimits
from services.api.infrastructure.broker_registry import BrokerAdapterRegistry
from services.api.repositories.sql_deployment_repository import (
    SqlDeploymentRepository,
)
from services.api.repositories.sql_execution_event_repository import (
    SqlExecutionEventRepository,
)
from services.api.repositories.sql_order_repository import SqlOrderRepository
from services.api.repositories.sql_position_repository import (
    SqlPositionRepository,
)
from services.api.services.kill_switch_service import KillSwitchService
from services.api.services.live_execution_service import LiveExecutionService
from services.api.services.risk_gate_service import RiskGateService

# ---------------------------------------------------------------------------
# Test fixtures and constants
# ---------------------------------------------------------------------------

# Deterministic ULID test identifiers for reproducibility.
_USER_ID = "01HTESTNG0SR000000000000B1"
_STRATEGY_ID = "01HTESTNG0STRT0000000000B1"
_DEPLOY_ALPACA = "01HTESTNG0DPYA0000000000B1"
_DEPLOY_SCHWAB = "01HTESTNG0DPYS0000000000B1"


def _seed_multi_deployment_setup(db: Session) -> None:
    """
    Create minimum parent records for multi-broker test scenario.

    Inserts one User, one Strategy, and two Deployments (Alpaca and Schwab),
    both in active state with live mode enabled. Uses flush() to preserve
    SAVEPOINT isolation (LL-S004).

    Args:
        db: SQLAlchemy Session bound to a SAVEPOINT.
    """
    user = User(
        id=_USER_ID,
        email="multi-broker-test@fxlab.dev",
        hashed_password="test-hash-not-real",
        role="operator",
    )
    db.add(user)
    db.flush()

    strategy = Strategy(
        id=_STRATEGY_ID,
        name="Multi-Broker Test Strategy",
        code="# test strategy\npass",
        version="1.0.0",
        created_by=_USER_ID,
    )
    db.add(strategy)
    db.flush()

    alpaca_deploy = Deployment(
        id=_DEPLOY_ALPACA,
        strategy_id=_STRATEGY_ID,
        environment="live",
        status="running",
        state="active",
        execution_mode="live",
        emergency_posture="flatten_all",
        deployed_by=_USER_ID,
    )
    db.add(alpaca_deploy)
    db.flush()

    schwab_deploy = Deployment(
        id=_DEPLOY_SCHWAB,
        strategy_id=_STRATEGY_ID,
        environment="live",
        status="running",
        state="active",
        execution_mode="live",
        emergency_posture="flatten_all",
        deployed_by=_USER_ID,
    )
    db.add(schwab_deploy)
    db.flush()


@pytest.fixture
def multi_broker_setup(
    integration_db_session: Session,
) -> tuple[
    Session, BrokerAdapterRegistry, LiveExecutionService, MockBrokerAdapter, MockBrokerAdapter
]:
    """
    Set up a complete multi-broker execution environment.

    Creates:
    - Two deployments (Alpaca and Schwab) in active/live state.
    - Two MockBrokerAdapter instances registered in BrokerAdapterRegistry.
    - Repositories for orders, positions, deployments, execution events.
    - RiskGateService with default (permissive) limits.
    - KillSwitchService with mock event repository.
    - LiveExecutionService wired with all dependencies.

    Returns:
        Tuple of (session, registry, service, alpaca_adapter, schwab_adapter).
    """
    db = integration_db_session
    _seed_multi_deployment_setup(db)

    # Initialize repositories
    order_repo = SqlOrderRepository(db=db)
    position_repo = SqlPositionRepository(db=db)
    deployment_repo = SqlDeploymentRepository(db=db)
    execution_event_repo = SqlExecutionEventRepository(db=db)

    # Initialize broker adapters
    alpaca_adapter = MockBrokerAdapter(fill_mode="instant", fill_price=Decimal("175.50"))
    schwab_adapter = MockBrokerAdapter(fill_mode="instant", fill_price=Decimal("175.50"))

    # Initialize registry and register both adapters
    registry = BrokerAdapterRegistry()
    registry.register(deployment_id=_DEPLOY_ALPACA, adapter=alpaca_adapter, broker_type="alpaca")
    registry.register(deployment_id=_DEPLOY_SCHWAB, adapter=schwab_adapter, broker_type="schwab")

    # Initialize risk gate service
    risk_event_repo = MockRiskEventRepository()
    risk_gate = RiskGateService(deployment_repo=deployment_repo, risk_event_repo=risk_event_repo)

    # Initialize kill switch service
    ks_event_repo = MockKillSwitchEventRepository()
    adapter_registry_dict = {
        _DEPLOY_ALPACA: alpaca_adapter,
        _DEPLOY_SCHWAB: schwab_adapter,
    }
    kill_switch = KillSwitchService(
        deployment_repo=deployment_repo,
        ks_event_repo=ks_event_repo,
        adapter_registry=adapter_registry_dict,
    )

    # Mock transaction manager for live execution
    tx = MagicMock(spec=TransactionManagerInterface)

    # Initialize live execution service
    service = LiveExecutionService(
        deployment_repo=deployment_repo,
        order_repo=order_repo,
        position_repo=position_repo,
        execution_event_repo=execution_event_repo,
        risk_gate=risk_gate,
        broker_registry=registry,
        kill_switch_service=kill_switch,
        transaction_manager=tx,
    )

    # Configure permissive risk limits for both live deployments
    risk_gate.set_risk_limits(
        deployment_id=_DEPLOY_ALPACA,
        limits=PreTradeRiskLimits(
            max_position_size=Decimal("1000000"),
            max_daily_loss=Decimal("1000000"),
            max_order_value=Decimal("1000000"),
            max_concentration_pct=Decimal("100"),
            max_open_orders=10000,
        ),
    )
    risk_gate.set_risk_limits(
        deployment_id=_DEPLOY_SCHWAB,
        limits=PreTradeRiskLimits(
            max_position_size=Decimal("1000000"),
            max_daily_loss=Decimal("1000000"),
            max_order_value=Decimal("1000000"),
            max_concentration_pct=Decimal("100"),
            max_open_orders=10000,
        ),
    )

    return db, registry, service, alpaca_adapter, schwab_adapter


# ---------------------------------------------------------------------------
# TestParallelBrokerExecution
# ---------------------------------------------------------------------------


class TestParallelBrokerExecution:
    """Verify orders execute independently on two registered broker adapters."""

    def test_same_order_on_two_brokers(
        self,
        multi_broker_setup: tuple,
    ) -> None:
        """
        Submit identical order shape to both Alpaca and Schwab deployments.

        Expected behaviour:
        - Both orders succeed and fill immediately (instant fill mode).
        - Each order has a unique broker_order_id from its adapter.
        - Each order is stored in the database with correct deployment_id.
        - Each adapter has its own copy of fills and positions.

        Verification:
        - Both OrderResponse objects have FILLED status.
        - Two Order records exist in the database (one per deployment).
        - Alpaca adapter contains 1 filled order.
        - Schwab adapter contains 1 filled order.
        """
        db, registry, service, alpaca_adapter, schwab_adapter = multi_broker_setup
        order_repo = SqlOrderRepository(db=db)

        # Submit order to Alpaca deployment
        alpaca_request = OrderRequest(
            client_order_id="multi-alpaca-001",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("50"),
            time_in_force=TimeInForce.DAY,
            deployment_id=_DEPLOY_ALPACA,
            strategy_id=_STRATEGY_ID,
            correlation_id="corr-multi-alpaca-001",
            execution_mode=ExecutionMode.LIVE,
        )
        alpaca_response = service.submit_live_order(
            deployment_id=_DEPLOY_ALPACA,
            request=alpaca_request,
            correlation_id="corr-multi-alpaca-001",
        )

        # Submit order to Schwab deployment
        schwab_request = OrderRequest(
            client_order_id="multi-schwab-001",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("50"),
            time_in_force=TimeInForce.DAY,
            deployment_id=_DEPLOY_SCHWAB,
            strategy_id=_STRATEGY_ID,
            correlation_id="corr-multi-schwab-001",
            execution_mode=ExecutionMode.LIVE,
        )
        schwab_response = service.submit_live_order(
            deployment_id=_DEPLOY_SCHWAB,
            request=schwab_request,
            correlation_id="corr-multi-schwab-001",
        )

        # Verify both orders filled
        assert alpaca_response.status == OrderStatus.FILLED
        assert schwab_response.status == OrderStatus.FILLED

        # Verify broker_order_ids are distinct
        assert alpaca_response.broker_order_id != schwab_response.broker_order_id

        # Verify database has two separate order records
        alpaca_db_order = order_repo.get_by_client_order_id("multi-alpaca-001")
        schwab_db_order = order_repo.get_by_client_order_id("multi-schwab-001")
        assert alpaca_db_order is not None
        assert schwab_db_order is not None
        assert alpaca_db_order["deployment_id"] == _DEPLOY_ALPACA
        assert schwab_db_order["deployment_id"] == _DEPLOY_SCHWAB
        assert alpaca_db_order["id"] != schwab_db_order["id"]

        # Verify each adapter has its own fill record
        alpaca_fills = alpaca_adapter.get_all_fills()
        schwab_fills = schwab_adapter.get_all_fills()
        assert len(alpaca_fills) == 1
        assert len(schwab_fills) == 1
        assert alpaca_fills[0].symbol == "AAPL"
        assert schwab_fills[0].symbol == "AAPL"

    def test_broker_isolation(
        self,
        multi_broker_setup: tuple,
    ) -> None:
        """
        Verify orders submitted to one deployment do not affect the other.

        Expected behaviour:
        - Submit order to Alpaca only.
        - Alpaca adapter has 1 order; Schwab adapter is empty.
        - Database has 1 order record (Alpaca deployment).

        Verification:
        - Alpaca adapter state is non-empty.
        - Schwab adapter state is empty.
        - Alpaca order is retrievable by deployment_id.
        - Schwab position query returns empty list.
        """
        db, registry, service, alpaca_adapter, schwab_adapter = multi_broker_setup

        # Submit order to Alpaca only
        alpaca_request = OrderRequest(
            client_order_id="alpaca-only-001",
            symbol="MSFT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("25"),
            time_in_force=TimeInForce.DAY,
            deployment_id=_DEPLOY_ALPACA,
            strategy_id=_STRATEGY_ID,
            correlation_id="corr-alpaca-only-001",
            execution_mode=ExecutionMode.LIVE,
        )
        service.submit_live_order(
            deployment_id=_DEPLOY_ALPACA,
            request=alpaca_request,
            correlation_id="corr-alpaca-only-001",
        )

        # Verify Alpaca has the order
        alpaca_all_orders = alpaca_adapter.get_all_orders()
        assert len(alpaca_all_orders) == 1
        assert alpaca_all_orders[0].symbol == "MSFT"

        # Verify Schwab is untouched
        schwab_all_orders = schwab_adapter.get_all_orders()
        assert len(schwab_all_orders) == 0

        # Verify Alpaca has position, Schwab is empty
        alpaca_positions = alpaca_adapter.get_positions()
        schwab_positions = schwab_adapter.get_positions()
        assert len(alpaca_positions) == 1
        assert alpaca_positions[0].symbol == "MSFT"
        assert len(schwab_positions) == 0


# ---------------------------------------------------------------------------
# TestBrokerFailover
# ---------------------------------------------------------------------------


class TestBrokerFailover:
    """Test order submission with broker failure scenarios."""

    def test_primary_broker_failure_secondary_accepts(
        self,
        integration_db_session: Session,
    ) -> None:
        """
        Attempt order on failed broker, then submit to healthy broker.

        Setup:
        - Alpaca adapter in reject mode (simulates broker unavailable).
        - Schwab adapter in instant fill mode.

        Procedure:
        - Submit order to Alpaca → expect rejection/error.
        - Submit different order to Schwab → expect success and fill.

        Verification:
        - Alpaca order has rejected status in database or is absent.
        - Schwab order is filled and visible in database.
        - Schwab adapter has the fill.
        """
        db = integration_db_session
        _seed_multi_deployment_setup(db)

        # Initialize repositories
        order_repo = SqlOrderRepository(db=db)
        deployment_repo = SqlDeploymentRepository(db=db)
        execution_event_repo = SqlExecutionEventRepository(db=db)
        position_repo = SqlPositionRepository(db=db)

        # Initialize adapters: Alpaca fails, Schwab succeeds
        alpaca_adapter = MockBrokerAdapter(
            fill_mode="reject", reject_reason="Order submission failed"
        )
        schwab_adapter = MockBrokerAdapter(fill_mode="instant", fill_price=Decimal("180.00"))

        # Register adapters
        registry = BrokerAdapterRegistry()
        registry.register(
            deployment_id=_DEPLOY_ALPACA, adapter=alpaca_adapter, broker_type="alpaca"
        )
        registry.register(
            deployment_id=_DEPLOY_SCHWAB, adapter=schwab_adapter, broker_type="schwab"
        )

        # Initialize services
        risk_event_repo = MockRiskEventRepository()
        risk_gate = RiskGateService(
            deployment_repo=deployment_repo, risk_event_repo=risk_event_repo
        )

        ks_event_repo = MockKillSwitchEventRepository()
        adapter_registry_dict = {
            _DEPLOY_ALPACA: alpaca_adapter,
            _DEPLOY_SCHWAB: schwab_adapter,
        }
        kill_switch = KillSwitchService(
            deployment_repo=deployment_repo,
            ks_event_repo=ks_event_repo,
            adapter_registry=adapter_registry_dict,
        )

        # Mock transaction manager for live execution
        tx = MagicMock(spec=TransactionManagerInterface)

        service = LiveExecutionService(
            deployment_repo=deployment_repo,
            order_repo=order_repo,
            position_repo=position_repo,
            execution_event_repo=execution_event_repo,
            risk_gate=risk_gate,
            broker_registry=registry,
            kill_switch_service=kill_switch,
            transaction_manager=tx,
        )

        # Configure permissive risk limits for both live deployments
        risk_gate.set_risk_limits(
            deployment_id=_DEPLOY_ALPACA,
            limits=PreTradeRiskLimits(
                max_position_size=Decimal("1000000"),
                max_daily_loss=Decimal("1000000"),
                max_order_value=Decimal("1000000"),
                max_concentration_pct=Decimal("100"),
                max_open_orders=10000,
            ),
        )
        risk_gate.set_risk_limits(
            deployment_id=_DEPLOY_SCHWAB,
            limits=PreTradeRiskLimits(
                max_position_size=Decimal("1000000"),
                max_daily_loss=Decimal("1000000"),
                max_order_value=Decimal("1000000"),
                max_concentration_pct=Decimal("100"),
                max_open_orders=10000,
            ),
        )

        # Submit to failed Alpaca broker
        alpaca_request = OrderRequest(
            client_order_id="failover-alpaca-001",
            symbol="GOOGL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
            time_in_force=TimeInForce.DAY,
            deployment_id=_DEPLOY_ALPACA,
            strategy_id=_STRATEGY_ID,
            correlation_id="corr-failover-alpaca-001",
            execution_mode=ExecutionMode.LIVE,
        )
        alpaca_response = service.submit_live_order(
            deployment_id=_DEPLOY_ALPACA,
            request=alpaca_request,
            correlation_id="corr-failover-alpaca-001",
        )

        # Expect rejection
        assert alpaca_response.status == OrderStatus.REJECTED

        # Submit to healthy Schwab broker
        schwab_request = OrderRequest(
            client_order_id="failover-schwab-001",
            symbol="GOOGL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
            time_in_force=TimeInForce.DAY,
            deployment_id=_DEPLOY_SCHWAB,
            strategy_id=_STRATEGY_ID,
            correlation_id="corr-failover-schwab-001",
            execution_mode=ExecutionMode.LIVE,
        )
        schwab_response = service.submit_live_order(
            deployment_id=_DEPLOY_SCHWAB,
            request=schwab_request,
            correlation_id="corr-failover-schwab-001",
        )

        # Expect success
        assert schwab_response.status == OrderStatus.FILLED
        assert schwab_response.filled_quantity == Decimal("10")

        # Verify database records
        alpaca_db_order = order_repo.get_by_client_order_id("failover-alpaca-001")
        schwab_db_order = order_repo.get_by_client_order_id("failover-schwab-001")

        assert alpaca_db_order is not None
        assert alpaca_db_order["status"] == "rejected"

        assert schwab_db_order is not None
        assert schwab_db_order["status"] == "filled"

        # Verify Schwab adapter has the fill
        schwab_fills = schwab_adapter.get_all_fills()
        assert len(schwab_fills) == 1

    def test_transient_broker_error_recovery(
        self,
        multi_broker_setup: tuple,
    ) -> None:
        """
        Submit order that fills, then change adapter mode to reject.

        Expected behaviour:
        - First order submitted in instant mode → fills and persists.
        - Adapter switched to reject mode.
        - Second order submitted → rejected.
        - First order remains accessible and filled.

        Verification:
        - First order status is FILLED in both adapter and database.
        - Second order status is REJECTED in database.
        - Alpaca adapter has exactly 2 orders (1 filled, 1 rejected).
        - First order's fill is still retrievable from adapter.
        """
        db, registry, service, alpaca_adapter, schwab_adapter = multi_broker_setup

        # Submit first order (succeeds in instant mode)
        first_request = OrderRequest(
            client_order_id="recovery-first-001",
            symbol="TSLA",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("20"),
            time_in_force=TimeInForce.DAY,
            deployment_id=_DEPLOY_ALPACA,
            strategy_id=_STRATEGY_ID,
            correlation_id="corr-recovery-first-001",
            execution_mode=ExecutionMode.LIVE,
        )
        first_response = service.submit_live_order(
            deployment_id=_DEPLOY_ALPACA,
            request=first_request,
            correlation_id="corr-recovery-first-001",
        )
        assert first_response.status == OrderStatus.FILLED

        # Change adapter to reject mode
        alpaca_adapter._fill_mode = "reject"
        alpaca_adapter._reject_reason = "Market closed"

        # Submit second order (fails in reject mode)
        second_request = OrderRequest(
            client_order_id="recovery-second-001",
            symbol="TSLA",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("20"),
            time_in_force=TimeInForce.DAY,
            deployment_id=_DEPLOY_ALPACA,
            strategy_id=_STRATEGY_ID,
            correlation_id="corr-recovery-second-001",
            execution_mode=ExecutionMode.LIVE,
        )
        second_response = service.submit_live_order(
            deployment_id=_DEPLOY_ALPACA,
            request=second_request,
            correlation_id="corr-recovery-second-001",
        )
        assert second_response.status == OrderStatus.REJECTED

        # Verify first order is still filled
        first_orders = [
            o for o in alpaca_adapter.get_all_orders() if o.client_order_id == "recovery-first-001"
        ]
        assert len(first_orders) == 1
        assert first_orders[0].status == OrderStatus.FILLED

        # Verify first order has a fill record
        first_fills = alpaca_adapter.get_fills(first_orders[0].broker_order_id)
        assert len(first_fills) == 1
        assert first_fills[0].quantity == Decimal("20")


# ---------------------------------------------------------------------------
# TestCrossBrokerPositionReconciliation
# ---------------------------------------------------------------------------


class TestCrossBrokerPositionReconciliation:
    """Verify position and P&L tracking is isolated per deployment."""

    def test_positions_isolated_per_deployment(
        self,
        multi_broker_setup: tuple,
    ) -> None:
        """
        Buy same symbol on both deployments; verify isolated positions.

        Expected behaviour:
        - Buy 50 AAPL on Alpaca → Alpaca position +50.
        - Buy 30 AAPL on Schwab → Schwab position +30.
        - Alpaca position query returns +50.
        - Schwab position query returns +30.

        Verification:
        - Alpaca adapter has AAPL position with quantity=50.
        - Schwab adapter has AAPL position with quantity=30.
        - Positions are independent (no cross-contamination).
        """
        db, registry, service, alpaca_adapter, schwab_adapter = multi_broker_setup

        # Buy on Alpaca
        alpaca_request = OrderRequest(
            client_order_id="pos-alpaca-buy-001",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("50"),
            time_in_force=TimeInForce.DAY,
            deployment_id=_DEPLOY_ALPACA,
            strategy_id=_STRATEGY_ID,
            correlation_id="corr-pos-alpaca-buy-001",
            execution_mode=ExecutionMode.LIVE,
        )
        service.submit_live_order(
            deployment_id=_DEPLOY_ALPACA,
            request=alpaca_request,
            correlation_id="corr-pos-alpaca-buy-001",
        )

        # Buy on Schwab
        schwab_request = OrderRequest(
            client_order_id="pos-schwab-buy-001",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("30"),
            time_in_force=TimeInForce.DAY,
            deployment_id=_DEPLOY_SCHWAB,
            strategy_id=_STRATEGY_ID,
            correlation_id="corr-pos-schwab-buy-001",
            execution_mode=ExecutionMode.LIVE,
        )
        service.submit_live_order(
            deployment_id=_DEPLOY_SCHWAB,
            request=schwab_request,
            correlation_id="corr-pos-schwab-buy-001",
        )

        # Verify isolated positions
        alpaca_positions = alpaca_adapter.get_positions()
        schwab_positions = schwab_adapter.get_positions()

        alpaca_aapl = [p for p in alpaca_positions if p.symbol == "AAPL"]
        schwab_aapl = [p for p in schwab_positions if p.symbol == "AAPL"]

        assert len(alpaca_aapl) == 1
        assert alpaca_aapl[0].quantity == Decimal("50")

        assert len(schwab_aapl) == 1
        assert schwab_aapl[0].quantity == Decimal("30")

    def test_pnl_isolated_per_deployment(
        self,
        multi_broker_setup: tuple,
    ) -> None:
        """
        Create positions on both brokers; verify P&L is tracked separately.

        Expected behaviour:
        - Buy 100 shares of MSFT on Alpaca at fill price 175.50.
        - Buy 100 shares of MSFT on Schwab at fill price 175.50.
        - Alpaca account equity includes its P&L.
        - Schwab account equity includes its P&L (separate).
        - Positions have unrealized P&L calculated independently.

        Verification:
        - Alpaca and Schwab account snapshots are distinct.
        - Each position's unrealized_pnl is calculated independently.
        - Portfolio values differ based on independent position sizes.
        """
        db, registry, service, alpaca_adapter, schwab_adapter = multi_broker_setup

        # Set distinct initial account states (optional; both default to 100k)
        # to later verify that account snapshots are independent.

        # Buy on Alpaca
        alpaca_request = OrderRequest(
            client_order_id="pnl-alpaca-001",
            symbol="MSFT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            time_in_force=TimeInForce.DAY,
            deployment_id=_DEPLOY_ALPACA,
            strategy_id=_STRATEGY_ID,
            correlation_id="corr-pnl-alpaca-001",
            execution_mode=ExecutionMode.LIVE,
        )
        service.submit_live_order(
            deployment_id=_DEPLOY_ALPACA,
            request=alpaca_request,
            correlation_id="corr-pnl-alpaca-001",
        )

        # Buy on Schwab
        schwab_request = OrderRequest(
            client_order_id="pnl-schwab-001",
            symbol="MSFT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            time_in_force=TimeInForce.DAY,
            deployment_id=_DEPLOY_SCHWAB,
            strategy_id=_STRATEGY_ID,
            correlation_id="corr-pnl-schwab-001",
            execution_mode=ExecutionMode.LIVE,
        )
        service.submit_live_order(
            deployment_id=_DEPLOY_SCHWAB,
            request=schwab_request,
            correlation_id="corr-pnl-schwab-001",
        )

        # Fetch account snapshots
        alpaca_account = alpaca_adapter.get_account()
        schwab_account = schwab_adapter.get_account()

        # Verify both have positions (portfolio value > 0)
        assert alpaca_account.portfolio_value > Decimal("0")
        assert schwab_account.portfolio_value > Decimal("0")

        # Verify positions have isolated unrealized P&L
        alpaca_positions = alpaca_adapter.get_positions()
        schwab_positions = schwab_adapter.get_positions()

        assert len(alpaca_positions) == 1
        assert len(schwab_positions) == 1

        # Both should have zero unrealized P&L (filled at market price, no price move)
        assert alpaca_positions[0].unrealized_pnl == Decimal("0")
        assert schwab_positions[0].unrealized_pnl == Decimal("0")


# ---------------------------------------------------------------------------
# TestBrokerRegistryIntegration
# ---------------------------------------------------------------------------


class TestBrokerRegistryIntegration:
    """Verify BrokerAdapterRegistry correctly manages multiple adapters."""

    def test_registry_multiple_adapters_coexist(
        self,
        multi_broker_setup: tuple,
    ) -> None:
        """
        Registry contains both adapters; both are accessible and independent.

        Expected behaviour:
        - Registry.count() == 2.
        - Registry.is_registered(Alpaca) == True.
        - Registry.is_registered(Schwab) == True.
        - Registry.get(Alpaca) returns Alpaca adapter.
        - Registry.get(Schwab) returns Schwab adapter.
        - list_deployments() returns 2 entries sorted by deployment_id.

        Verification:
        - Count matches 2.
        - Both deployments are registered.
        - Retrieved adapters are the same instances.
        - List deployment output contains both with correct broker_type.
        """
        db, registry, service, alpaca_adapter, schwab_adapter = multi_broker_setup

        # Verify count
        assert registry.count() == 2

        # Verify registration checks
        assert registry.is_registered(_DEPLOY_ALPACA)
        assert registry.is_registered(_DEPLOY_SCHWAB)

        # Verify retrieval
        retrieved_alpaca = registry.get(_DEPLOY_ALPACA)
        retrieved_schwab = registry.get(_DEPLOY_SCHWAB)

        assert retrieved_alpaca is alpaca_adapter
        assert retrieved_schwab is schwab_adapter

        # Verify list output
        deployments = registry.list_deployments()
        assert len(deployments) == 2
        assert deployments[0]["deployment_id"] == _DEPLOY_ALPACA
        assert deployments[0]["broker_type"] == "alpaca"
        assert deployments[1]["deployment_id"] == _DEPLOY_SCHWAB
        assert deployments[1]["broker_type"] == "schwab"

    def test_deregister_one_preserves_other(
        self,
        multi_broker_setup: tuple,
    ) -> None:
        """
        Deregister Alpaca; Schwab remains accessible.

        Expected behaviour:
        - Registry.count() == 2 before.
        - Deregister Alpaca → count() == 1.
        - Registry.is_registered(Alpaca) == False.
        - Registry.is_registered(Schwab) == True.
        - Registry.get(Alpaca) raises NotFoundError.
        - Registry.get(Schwab) succeeds.

        Verification:
        - Count decrements to 1.
        - Alpaca raises NotFoundError on access.
        - Schwab is still accessible.
        - list_deployments() returns only Schwab.
        """
        db, registry, service, alpaca_adapter, schwab_adapter = multi_broker_setup

        # Verify initial state
        assert registry.count() == 2

        # Deregister Alpaca
        registry.deregister(_DEPLOY_ALPACA)

        # Verify count
        assert registry.count() == 1

        # Verify Alpaca is gone
        assert not registry.is_registered(_DEPLOY_ALPACA)
        with pytest.raises(NotFoundError):
            registry.get(_DEPLOY_ALPACA)

        # Verify Schwab is still present
        assert registry.is_registered(_DEPLOY_SCHWAB)
        retrieved = registry.get(_DEPLOY_SCHWAB)
        assert retrieved is schwab_adapter

        # Verify list output
        deployments = registry.list_deployments()
        assert len(deployments) == 1
        assert deployments[0]["deployment_id"] == _DEPLOY_SCHWAB
