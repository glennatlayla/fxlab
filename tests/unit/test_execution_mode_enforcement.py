"""
Unit tests for execution mode enforcement safety features.

Covers:
- Environment-level ALLOWED_EXECUTION_MODES enforcement
- Adapter type validation (live mode cannot route to paper/shadow adapters)
- is_paper_adapter property on broker adapters
- ConfigError raised when live trading is disabled or misconfigured

Per production safety requirements:
- Live trading can be completely disabled via ALLOWED_EXECUTION_MODES env var
- Live deployments cannot be accidentally routed to paper/shadow adapters
- All safety checks run before any order submission logic

Example:
    pytest tests/unit/test_execution_mode_enforcement.py -v
"""

from __future__ import annotations

import os
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from libs.contracts.errors import ConfigError
from libs.contracts.execution import (
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)
from libs.contracts.interfaces.transaction_manager_interface import (
    TransactionManagerInterface,
)
from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from libs.contracts.mocks.mock_execution_event_repository import (
    MockExecutionEventRepository,
)
from libs.contracts.mocks.mock_order_repository import MockOrderRepository
from libs.contracts.mocks.mock_position_repository import MockPositionRepository
from libs.contracts.mocks.mock_risk_event_repository import MockRiskEventRepository
from libs.contracts.risk import PreTradeRiskLimits
from services.api.infrastructure.broker_registry import BrokerAdapterRegistry
from services.api.services.live_execution_service import LiveExecutionService
from services.api.services.risk_gate_service import RiskGateService

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEP_ID = "01HENFORCE0000000000000001"
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


def _make_order(
    *,
    client_order_id: str = "ord-enforce-001",
    symbol: str = "AAPL",
    side: OrderSide = OrderSide.BUY,
    quantity: Decimal = Decimal("100"),
    execution_mode: str = "live",
) -> OrderRequest:
    """Helper to create a standard live order request."""
    from libs.contracts.execution import ExecutionMode

    return OrderRequest(
        client_order_id=client_order_id,
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        time_in_force=TimeInForce.DAY,
        deployment_id=DEP_ID,
        strategy_id=STRATEGY_ID,
        correlation_id="corr-enforce-test-001",
        execution_mode=ExecutionMode(execution_mode),
    )


# ---------------------------------------------------------------------------
# Environment-level ALLOWED_EXECUTION_MODES enforcement
# ---------------------------------------------------------------------------


class TestEnvironmentExecutionModeEnforcement:
    """Tests for environment-level execution mode restriction."""

    def test_service_init_stores_allowed_modes(
        self,
        deployment_repo: MockDeploymentRepository,
        order_repo: MockOrderRepository,
        position_repo: MockPositionRepository,
        event_repo: MockExecutionEventRepository,
        risk_gate: RiskGateService,
        broker_registry: BrokerAdapterRegistry,
        kill_switch_service: MagicMock,
    ) -> None:
        """Service constructor stores allowed modes from environment."""
        with patch.dict(os.environ, {"ALLOWED_EXECUTION_MODES": "shadow,paper"}):
            service = LiveExecutionService(
                deployment_repo=deployment_repo,
                order_repo=order_repo,
                position_repo=position_repo,
                execution_event_repo=event_repo,
                risk_gate=risk_gate,
                broker_registry=broker_registry,
                kill_switch_service=kill_switch_service,
            )
            # Verify service stores the allowed modes
            assert hasattr(service, "_allowed_modes")
            assert "shadow" in service._allowed_modes
            assert "paper" in service._allowed_modes
            assert "live" not in service._allowed_modes

    def test_service_init_default_allows_all_modes(
        self,
        deployment_repo: MockDeploymentRepository,
        order_repo: MockOrderRepository,
        position_repo: MockPositionRepository,
        event_repo: MockExecutionEventRepository,
        risk_gate: RiskGateService,
        broker_registry: BrokerAdapterRegistry,
        kill_switch_service: MagicMock,
    ) -> None:
        """Default (no env var) allows all modes for backward compatibility."""
        # Ensure env var is not set
        with patch.dict(os.environ, {}, clear=False):
            if "ALLOWED_EXECUTION_MODES" in os.environ:
                del os.environ["ALLOWED_EXECUTION_MODES"]
            service = LiveExecutionService(
                deployment_repo=deployment_repo,
                order_repo=order_repo,
                position_repo=position_repo,
                execution_event_repo=event_repo,
                risk_gate=risk_gate,
                broker_registry=broker_registry,
                kill_switch_service=kill_switch_service,
            )
            # Default should allow all modes
            assert "shadow" in service._allowed_modes
            assert "paper" in service._allowed_modes
            assert "live" in service._allowed_modes

    def test_submit_live_order_raises_error_when_live_disabled(
        self,
        deployment_repo: MockDeploymentRepository,
        order_repo: MockOrderRepository,
        position_repo: MockPositionRepository,
        event_repo: MockExecutionEventRepository,
        risk_gate: RiskGateService,
        broker_registry: BrokerAdapterRegistry,
        kill_switch_service: MagicMock,
        mock_adapter: MockBrokerAdapter,
    ) -> None:
        """ConfigError raised when live mode is disabled in environment."""
        # Create deployment
        dep_id = "01HENFORCE0000000000000002"
        deployment_repo.seed(
            deployment_id=dep_id,
            state="active",
            execution_mode="live",
            emergency_posture="flatten_all",
        )
        broker_registry.register(
            deployment_id=dep_id,
            adapter=mock_adapter,
            broker_type="mock",
        )

        # Create service with live mode disabled
        with patch.dict(os.environ, {"ALLOWED_EXECUTION_MODES": "shadow,paper"}):
            service = LiveExecutionService(
                deployment_repo=deployment_repo,
                order_repo=order_repo,
                position_repo=position_repo,
                execution_event_repo=event_repo,
                risk_gate=risk_gate,
                broker_registry=broker_registry,
                kill_switch_service=kill_switch_service,
            )

            order = _make_order(client_order_id="live-disabled-001")
            with pytest.raises(ConfigError) as exc_info:
                service.submit_live_order(
                    deployment_id=dep_id,
                    request=order,
                    correlation_id="corr-001",
                )
            assert "live" in str(exc_info.value).lower()
            assert "disabled" in str(exc_info.value).lower()

    def test_submit_live_order_succeeds_when_live_enabled(
        self,
        deployment_repo: MockDeploymentRepository,
        order_repo: MockOrderRepository,
        position_repo: MockPositionRepository,
        event_repo: MockExecutionEventRepository,
        risk_gate: RiskGateService,
        broker_registry: BrokerAdapterRegistry,
        kill_switch_service: MagicMock,
        mock_adapter: MockBrokerAdapter,
    ) -> None:
        """Live order succeeds when live mode is explicitly enabled."""
        # Create deployment
        dep_id = "01HENFORCE0000000000000003"
        deployment_repo.seed(
            deployment_id=dep_id,
            state="active",
            execution_mode="live",
            emergency_posture="flatten_all",
        )
        broker_registry.register(
            deployment_id=dep_id,
            adapter=mock_adapter,
            broker_type="mock",
        )

        # Create service with live mode enabled
        with patch.dict(os.environ, {"ALLOWED_EXECUTION_MODES": "shadow,paper,live"}):
            # Mock transaction manager for live execution
            tx = MagicMock(spec=TransactionManagerInterface)

            service = LiveExecutionService(
                deployment_repo=deployment_repo,
                order_repo=order_repo,
                position_repo=position_repo,
                execution_event_repo=event_repo,
                risk_gate=risk_gate,
                broker_registry=broker_registry,
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

            order = _make_order(client_order_id="live-enabled-001")
            # Should not raise ConfigError
            resp = service.submit_live_order(
                deployment_id=dep_id,
                request=order,
                correlation_id="corr-001",
            )
            assert resp is not None
            assert resp.broker_order_id is not None

    def test_no_order_persisted_when_live_mode_disabled(
        self,
        deployment_repo: MockDeploymentRepository,
        order_repo: MockOrderRepository,
        position_repo: MockPositionRepository,
        event_repo: MockExecutionEventRepository,
        risk_gate: RiskGateService,
        broker_registry: BrokerAdapterRegistry,
        kill_switch_service: MagicMock,
        mock_adapter: MockBrokerAdapter,
    ) -> None:
        """No order persisted when ConfigError raised due to disabled live mode."""
        dep_id = "01HENFORCE0000000000000004"
        deployment_repo.seed(
            deployment_id=dep_id,
            state="active",
            execution_mode="live",
            emergency_posture="flatten_all",
        )
        broker_registry.register(
            deployment_id=dep_id,
            adapter=mock_adapter,
            broker_type="mock",
        )

        with patch.dict(os.environ, {"ALLOWED_EXECUTION_MODES": "shadow,paper"}):
            service = LiveExecutionService(
                deployment_repo=deployment_repo,
                order_repo=order_repo,
                position_repo=position_repo,
                execution_event_repo=event_repo,
                risk_gate=risk_gate,
                broker_registry=broker_registry,
                kill_switch_service=kill_switch_service,
            )

            order = _make_order(client_order_id="should-not-persist-001")
            with pytest.raises(ConfigError):
                service.submit_live_order(
                    deployment_id=dep_id,
                    request=order,
                    correlation_id="corr-001",
                )
            # Order should NOT be in database
            assert order_repo.get_by_client_order_id("should-not-persist-001") is None


# ---------------------------------------------------------------------------
# Adapter type validation (is_paper_adapter property)
# ---------------------------------------------------------------------------


class TestAdapterTypeValidation:
    """Tests for is_paper_adapter property and adapter type validation."""

    def test_mock_adapter_is_not_paper(self, mock_adapter: MockBrokerAdapter) -> None:
        """MockBrokerAdapter.is_paper_adapter returns False."""
        assert hasattr(mock_adapter, "is_paper_adapter")
        assert mock_adapter.is_paper_adapter is False

    def test_paper_adapter_is_paper(self) -> None:
        """PaperBrokerAdapter.is_paper_adapter returns True."""
        from libs.broker.paper_broker_adapter import PaperBrokerAdapter

        adapter = PaperBrokerAdapter(
            market_prices={"AAPL": Decimal("175.50")},
            initial_equity=Decimal("1000000"),
        )
        assert hasattr(adapter, "is_paper_adapter")
        assert adapter.is_paper_adapter is True

    def test_live_deployment_with_paper_adapter_raises_error(
        self,
        deployment_repo: MockDeploymentRepository,
        order_repo: MockOrderRepository,
        position_repo: MockPositionRepository,
        event_repo: MockExecutionEventRepository,
        risk_gate: RiskGateService,
        broker_registry: BrokerAdapterRegistry,
        kill_switch_service: MagicMock,
    ) -> None:
        """ConfigError raised when live deployment routed to paper adapter."""
        from libs.broker.paper_broker_adapter import PaperBrokerAdapter

        dep_id = "01HENFORCE0000000000000005"
        deployment_repo.seed(
            deployment_id=dep_id,
            state="active",
            execution_mode="live",
            emergency_posture="flatten_all",
        )

        # Register PAPER adapter for a LIVE deployment (misconfiguration)
        paper_adapter = PaperBrokerAdapter(
            market_prices={"AAPL": Decimal("175.50")},
            initial_equity=Decimal("1000000"),
        )
        broker_registry.register(
            deployment_id=dep_id,
            adapter=paper_adapter,
            broker_type="paper",
        )

        # Mock transaction manager for live execution
        # This is needed to pass the tx check so we can test the adapter type validation
        tx = MagicMock(spec=TransactionManagerInterface)

        service = LiveExecutionService(
            deployment_repo=deployment_repo,
            order_repo=order_repo,
            position_repo=position_repo,
            execution_event_repo=event_repo,
            risk_gate=risk_gate,
            broker_registry=broker_registry,
            kill_switch_service=kill_switch_service,
            transaction_manager=tx,
        )

        order = _make_order(client_order_id="live-paper-mismatch-001")
        with pytest.raises(ConfigError) as exc_info:
            service.submit_live_order(
                deployment_id=dep_id,
                request=order,
                correlation_id="corr-001",
            )
        assert "live" in str(exc_info.value).lower()
        assert "paper" in str(exc_info.value).lower()

    def test_live_deployment_with_mock_adapter_succeeds(
        self,
        deployment_repo: MockDeploymentRepository,
        order_repo: MockOrderRepository,
        position_repo: MockPositionRepository,
        event_repo: MockExecutionEventRepository,
        risk_gate: RiskGateService,
        broker_registry: BrokerAdapterRegistry,
        kill_switch_service: MagicMock,
        mock_adapter: MockBrokerAdapter,
    ) -> None:
        """Live deployment with mock adapter (not paper) succeeds."""
        dep_id = "01HENFORCE0000000000000006"
        deployment_repo.seed(
            deployment_id=dep_id,
            state="active",
            execution_mode="live",
            emergency_posture="flatten_all",
        )

        broker_registry.register(
            deployment_id=dep_id,
            adapter=mock_adapter,
            broker_type="mock",
        )

        # Mock transaction manager for live execution
        tx = MagicMock(spec=TransactionManagerInterface)

        service = LiveExecutionService(
            deployment_repo=deployment_repo,
            order_repo=order_repo,
            position_repo=position_repo,
            execution_event_repo=event_repo,
            risk_gate=risk_gate,
            broker_registry=broker_registry,
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

        order = _make_order(client_order_id="live-mock-success-001")
        # Should not raise ConfigError
        resp = service.submit_live_order(
            deployment_id=dep_id,
            request=order,
            correlation_id="corr-001",
        )
        assert resp is not None
        assert resp.broker_order_id is not None

    def test_paper_deployment_with_paper_adapter_succeeds(
        self,
        deployment_repo: MockDeploymentRepository,
        order_repo: MockOrderRepository,
        position_repo: MockPositionRepository,
        event_repo: MockExecutionEventRepository,
        risk_gate: RiskGateService,
        broker_registry: BrokerAdapterRegistry,
        kill_switch_service: MagicMock,
    ) -> None:
        """Paper deployment with paper adapter succeeds (no error)."""
        from libs.broker.paper_broker_adapter import PaperBrokerAdapter

        dep_id = "01HENFORCE0000000000000007"
        deployment_repo.seed(
            deployment_id=dep_id,
            state="active",
            execution_mode="paper",
            emergency_posture="flatten_all",
        )

        paper_adapter = PaperBrokerAdapter(
            market_prices={"AAPL": Decimal("175.50")},
            initial_equity=Decimal("1000000"),
        )
        broker_registry.register(
            deployment_id=dep_id,
            adapter=paper_adapter,
            broker_type="paper",
        )

        service = LiveExecutionService(
            deployment_repo=deployment_repo,
            order_repo=order_repo,
            position_repo=position_repo,
            execution_event_repo=event_repo,
            risk_gate=risk_gate,
            broker_registry=broker_registry,
            kill_switch_service=kill_switch_service,
        )

        from libs.contracts.errors import StateTransitionError

        order = _make_order(client_order_id="paper-paper-success-001")
        # Paper deployment can use paper adapter without error from adapter type check.
        # However, submit_live_order will fail with StateTransitionError because
        # the deployment is not in live mode (expected behavior).
        with pytest.raises(StateTransitionError):
            service.submit_live_order(
                deployment_id=dep_id,
                request=order,
                correlation_id="corr-001",
            )
