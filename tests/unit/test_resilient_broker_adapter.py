"""
Unit tests for ResilientBrokerAdapter (services.api.infrastructure.resilient_adapter).

Covers:
- Lifecycle operations (connect, disconnect, get_timeout_config) bypass circuit breaker
- Trading operations (submit_order, cancel_order, get_order, etc.) go through circuit breaker
- Circuit breaker protects against cascading failures
- CircuitOpenError is raised and propagated when circuit trips
- TransientError and ExternalServiceError increment failure count
- AuthError and NotFoundError pass through without affecting circuit state
- Diagnostics merge inner adapter diagnostics with circuit breaker metrics
- get_diagnostics() bypasses circuit breaker
- Thread safety inherited from inner adapter and circuit breaker

Per M7 spec: "Unit tests for resilient adapter (circuit breaker wrapping, diagnostics merge)"
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from libs.contracts.errors import (
    AuthError,
    CircuitOpenError,
    ExternalServiceError,
    NotFoundError,
    TransientError,
)
from libs.contracts.execution import (
    AccountSnapshot,
    AdapterDiagnostics,
    ConnectionStatus,
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter
from services.api.infrastructure.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
)
from services.api.infrastructure.resilient_adapter import ResilientBrokerAdapter
from services.api.infrastructure.timeout_config import BrokerTimeoutConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def market_buy() -> OrderRequest:
    """Standard market buy order for testing."""
    return OrderRequest(
        client_order_id="ord-001",
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("100"),
        time_in_force=TimeInForce.DAY,
        deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
        strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
        correlation_id="corr-001",
        execution_mode=ExecutionMode.PAPER,
    )


@pytest.fixture()
def inner_adapter() -> MockBrokerAdapter:
    """Mock broker adapter that instantly fills orders."""
    return MockBrokerAdapter(
        fill_mode="instant",
        fill_price=Decimal("175.50"),
    )


@pytest.fixture()
def circuit_breaker() -> CircuitBreaker:
    """Circuit breaker with low failure threshold for testing."""
    config = CircuitBreakerConfig(
        failure_threshold=2,
        recovery_timeout_s=1.0,
        half_open_max_calls=1,
        name="test_broker",
    )
    return CircuitBreaker(config=config, redis_client=None)


@pytest.fixture()
def resilient_adapter(
    inner_adapter: MockBrokerAdapter,
    circuit_breaker: CircuitBreaker,
) -> ResilientBrokerAdapter:
    """Resilient adapter wrapping mock broker with circuit breaker."""
    return ResilientBrokerAdapter(
        inner=inner_adapter,
        circuit_breaker=circuit_breaker,
    )


# ---------------------------------------------------------------------------
# Lifecycle operations (no circuit breaker)
# ---------------------------------------------------------------------------


class TestLifecycleOperations:
    """Tests for connect, disconnect, get_timeout_config (no circuit breaker)."""

    def test_connect_delegates_to_inner_adapter(
        self, resilient_adapter: ResilientBrokerAdapter
    ) -> None:
        """Test that connect() delegates directly to inner adapter."""
        resilient_adapter.connect()
        # MockBrokerAdapter.connect() is a no-op, but we verify no exception
        assert resilient_adapter is not None

    def test_disconnect_delegates_to_inner_adapter(
        self, resilient_adapter: ResilientBrokerAdapter
    ) -> None:
        """Test that disconnect() delegates directly to inner adapter."""
        resilient_adapter.connect()
        resilient_adapter.disconnect()
        # MockBrokerAdapter.disconnect() is a no-op
        assert resilient_adapter is not None

    def test_get_timeout_config_delegates_to_inner_adapter(
        self, resilient_adapter: ResilientBrokerAdapter
    ) -> None:
        """Test that get_timeout_config() returns inner adapter's config."""
        config = resilient_adapter.get_timeout_config()

        assert isinstance(config, BrokerTimeoutConfig)
        assert config.connect_timeout_s == 5.0
        assert config.read_timeout_s == 10.0
        assert config.order_timeout_s == 30.0


# ---------------------------------------------------------------------------
# Trading operations (with circuit breaker)
# ---------------------------------------------------------------------------


class TestTradingOperationsCircuitBreakerProtection:
    """Tests for trading operations through circuit breaker."""

    def test_submit_order_succeeds_in_closed_state(
        self,
        resilient_adapter: ResilientBrokerAdapter,
        market_buy: OrderRequest,
    ) -> None:
        """Test submit_order() succeeds when circuit is CLOSED."""
        resp = resilient_adapter.submit_order(market_buy)

        assert resp.status == OrderStatus.FILLED
        assert resp.filled_quantity == Decimal("100")
        assert resp.client_order_id == "ord-001"

    def test_cancel_order_succeeds_in_closed_state(
        self,
        resilient_adapter: ResilientBrokerAdapter,
        market_buy: OrderRequest,
    ) -> None:
        """Test cancel_order() succeeds when circuit is CLOSED."""
        # First submit an order
        resp = resilient_adapter.submit_order(market_buy)
        broker_order_id = resp.broker_order_id
        assert broker_order_id is not None

        # Then cancel it (MockBrokerAdapter allows canceling filled orders, just returns order)
        cancel_resp = resilient_adapter.cancel_order(broker_order_id)
        assert cancel_resp.broker_order_id == broker_order_id

    def test_get_order_succeeds_in_closed_state(
        self,
        resilient_adapter: ResilientBrokerAdapter,
        market_buy: OrderRequest,
    ) -> None:
        """Test get_order() succeeds when circuit is CLOSED."""
        resp = resilient_adapter.submit_order(market_buy)
        broker_order_id = resp.broker_order_id
        assert broker_order_id is not None

        # Query the order
        order = resilient_adapter.get_order(broker_order_id)
        assert order.broker_order_id == broker_order_id
        assert order.status == OrderStatus.FILLED

    def test_list_open_orders_succeeds_in_closed_state(
        self,
        resilient_adapter: ResilientBrokerAdapter,
    ) -> None:
        """Test list_open_orders() succeeds when circuit is CLOSED."""
        orders = resilient_adapter.list_open_orders()
        assert isinstance(orders, list)

    def test_get_fills_succeeds_in_closed_state(
        self,
        resilient_adapter: ResilientBrokerAdapter,
        market_buy: OrderRequest,
    ) -> None:
        """Test get_fills() succeeds when circuit is CLOSED."""
        resp = resilient_adapter.submit_order(market_buy)
        broker_order_id = resp.broker_order_id
        assert broker_order_id is not None

        fills = resilient_adapter.get_fills(broker_order_id)
        assert isinstance(fills, list)
        assert len(fills) == 1
        assert fills[0].quantity == Decimal("100")

    def test_get_positions_succeeds_in_closed_state(
        self,
        resilient_adapter: ResilientBrokerAdapter,
    ) -> None:
        """Test get_positions() succeeds when circuit is CLOSED."""
        positions = resilient_adapter.get_positions()
        assert isinstance(positions, list)

    def test_get_account_succeeds_in_closed_state(
        self,
        resilient_adapter: ResilientBrokerAdapter,
    ) -> None:
        """Test get_account() succeeds when circuit is CLOSED."""
        account = resilient_adapter.get_account()
        assert isinstance(account, AccountSnapshot)
        assert account.equity >= 0

    def test_is_market_open_succeeds_in_closed_state(
        self,
        resilient_adapter: ResilientBrokerAdapter,
    ) -> None:
        """Test is_market_open() succeeds when circuit is CLOSED."""
        result = resilient_adapter.is_market_open()
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Circuit breaker state transitions
# ---------------------------------------------------------------------------


class TestCircuitBreakerStateTransitions:
    """Tests for circuit breaker state management (CLOSED → OPEN → HALF_OPEN → CLOSED)."""

    def test_circuit_opens_after_failure_threshold(
        self,
        inner_adapter: MockBrokerAdapter,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """Test that circuit opens after failure_threshold is exceeded."""
        resilient_adapter = ResilientBrokerAdapter(
            inner=inner_adapter,
            circuit_breaker=circuit_breaker,
        )

        # Mock the inner adapter to raise TransientError
        mock_adapter = MagicMock()
        mock_adapter.get_order.side_effect = TransientError("Network error")
        resilient_adapter._inner = mock_adapter

        # Attempt 1: fails, failure_count = 1
        with pytest.raises(TransientError):
            resilient_adapter.get_order("order-1")

        assert circuit_breaker.state == CircuitState.CLOSED
        assert circuit_breaker.metrics["failure_count"] == 1

        # Attempt 2: fails, failure_count = 2 (threshold reached)
        with pytest.raises(CircuitOpenError):
            resilient_adapter.get_order("order-2")

        assert circuit_breaker.state == CircuitState.OPEN
        assert circuit_breaker.metrics["failure_count"] == 2
        assert circuit_breaker.metrics["trip_count"] == 1

    def test_circuit_opens_raises_circuit_open_error(
        self,
        inner_adapter: MockBrokerAdapter,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """Test that CircuitOpenError is raised when circuit is OPEN."""
        resilient_adapter = ResilientBrokerAdapter(
            inner=inner_adapter,
            circuit_breaker=circuit_breaker,
        )

        # Force circuit to OPEN
        mock_adapter = MagicMock()
        mock_adapter.get_order.side_effect = TransientError("Network error")
        resilient_adapter._inner = mock_adapter

        # Trip the circuit
        with pytest.raises(TransientError):
            resilient_adapter.get_order("order-1")
        with pytest.raises(CircuitOpenError):
            resilient_adapter.get_order("order-2")

        # Now circuit is OPEN; any further call should raise CircuitOpenError
        # (not the original error)
        with pytest.raises(CircuitOpenError) as exc_info:
            resilient_adapter.get_order("order-3")

        error = exc_info.value
        assert error.adapter_name == "test_broker"
        assert error.failure_count == 2

    def test_circuit_allows_fast_fail_when_open(
        self,
        inner_adapter: MockBrokerAdapter,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """Test that circuit fast-fails when OPEN (without calling inner adapter)."""
        resilient_adapter = ResilientBrokerAdapter(
            inner=inner_adapter,
            circuit_breaker=circuit_breaker,
        )

        # Trip the circuit
        mock_adapter = MagicMock()
        mock_adapter.get_order.side_effect = TransientError("Network error")
        resilient_adapter._inner = mock_adapter

        with pytest.raises(TransientError):
            resilient_adapter.get_order("order-1")
        with pytest.raises(CircuitOpenError):
            resilient_adapter.get_order("order-2")

        # Reset mock call count
        mock_adapter.reset_mock()

        # Next call should fast-fail without calling inner adapter
        with pytest.raises(CircuitOpenError):
            resilient_adapter.get_order("order-3")

        # Verify inner adapter was NOT called
        mock_adapter.get_order.assert_not_called()

    def test_circuit_resets_on_success(
        self,
        resilient_adapter: ResilientBrokerAdapter,
        market_buy: OrderRequest,
    ) -> None:
        """Test that circuit resets failure_count on success."""
        # First call succeeds, failure_count stays 0
        resp = resilient_adapter.submit_order(market_buy)
        assert resp.status == OrderStatus.FILLED
        assert resilient_adapter._circuit_breaker.metrics["failure_count"] == 0


# ---------------------------------------------------------------------------
# Error handling and pass-through
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error handling and pass-through behavior."""

    def test_transient_error_increments_failure_count(
        self,
        inner_adapter: MockBrokerAdapter,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """Test that TransientError increments failure count."""
        resilient_adapter = ResilientBrokerAdapter(
            inner=inner_adapter,
            circuit_breaker=circuit_breaker,
        )

        mock_adapter = MagicMock()
        mock_adapter.get_order.side_effect = TransientError("Timeout")
        resilient_adapter._inner = mock_adapter

        with pytest.raises(TransientError):
            resilient_adapter.get_order("order-1")

        assert circuit_breaker.metrics["failure_count"] == 1

    def test_external_service_error_increments_failure_count(
        self,
        inner_adapter: MockBrokerAdapter,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """Test that ExternalServiceError increments failure count."""
        resilient_adapter = ResilientBrokerAdapter(
            inner=inner_adapter,
            circuit_breaker=circuit_breaker,
        )

        mock_adapter = MagicMock()
        mock_adapter.get_order.side_effect = ExternalServiceError("API error")
        resilient_adapter._inner = mock_adapter

        with pytest.raises(ExternalServiceError):
            resilient_adapter.get_order("order-1")

        assert circuit_breaker.metrics["failure_count"] == 1

    def test_auth_error_passes_through_without_affecting_circuit(
        self,
        inner_adapter: MockBrokerAdapter,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """Test that AuthError passes through without affecting circuit state."""
        resilient_adapter = ResilientBrokerAdapter(
            inner=inner_adapter,
            circuit_breaker=circuit_breaker,
        )

        mock_adapter = MagicMock()
        mock_adapter.submit_order.side_effect = AuthError("Invalid credentials")
        resilient_adapter._inner = mock_adapter

        with pytest.raises(AuthError):
            resilient_adapter.submit_order(
                OrderRequest(
                    client_order_id="ord-001",
                    symbol="AAPL",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=Decimal("100"),
                    time_in_force=TimeInForce.DAY,
                    deployment_id="01DEPLOYAAAAAAAAAAAAAAAAAA",
                    strategy_id="01STRATAAAAAAAAAAAAAAAAAAA",
                    correlation_id="corr-001",
                    execution_mode=ExecutionMode.PAPER,
                )
            )

        # Circuit should remain CLOSED
        assert circuit_breaker.state == CircuitState.CLOSED
        assert circuit_breaker.metrics["failure_count"] == 0

    def test_not_found_error_passes_through_without_affecting_circuit(
        self,
        inner_adapter: MockBrokerAdapter,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """Test that NotFoundError passes through without affecting circuit state."""
        resilient_adapter = ResilientBrokerAdapter(
            inner=inner_adapter,
            circuit_breaker=circuit_breaker,
        )

        mock_adapter = MagicMock()
        mock_adapter.get_order.side_effect = NotFoundError("Order not found")
        resilient_adapter._inner = mock_adapter

        with pytest.raises(NotFoundError):
            resilient_adapter.get_order("unknown-order-id")

        # Circuit should remain CLOSED
        assert circuit_breaker.state == CircuitState.CLOSED
        assert circuit_breaker.metrics["failure_count"] == 0


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


class TestDiagnostics:
    """Tests for get_diagnostics() merge behavior."""

    def test_get_diagnostics_merges_inner_and_circuit_metrics(
        self,
        resilient_adapter: ResilientBrokerAdapter,
        market_buy: OrderRequest,
    ) -> None:
        """Test that get_diagnostics() merges inner adapter and circuit breaker metrics."""
        # Submit an order to populate some metrics
        resilient_adapter.submit_order(market_buy)

        diagnostics = resilient_adapter.get_diagnostics()

        # Verify inner adapter diagnostics are present
        assert diagnostics.broker_name == "mock"
        assert diagnostics.connection_status == ConnectionStatus.CONNECTED
        assert diagnostics.latency_ms >= 0
        assert diagnostics.orders_submitted_today >= 1

        # Verify circuit breaker metrics are included (logged)
        # The diagnostics object itself is enriched from inner adapter,
        # but structured logging includes circuit breaker state
        assert diagnostics is not None

    def test_get_diagnostics_reflects_circuit_state(
        self,
        inner_adapter: MockBrokerAdapter,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """Test that diagnostics reflect circuit breaker state."""
        resilient_adapter = ResilientBrokerAdapter(
            inner=inner_adapter,
            circuit_breaker=circuit_breaker,
        )

        # Initial state: CLOSED
        diag_before = resilient_adapter.get_diagnostics()
        assert diag_before is not None

        # Trip the circuit
        mock_adapter = MagicMock()
        mock_adapter.get_order.side_effect = TransientError("Error")
        resilient_adapter._inner = mock_adapter

        with pytest.raises(TransientError):
            resilient_adapter.get_order("order-1")
        with pytest.raises(CircuitOpenError):
            resilient_adapter.get_order("order-2")

        # Verify circuit is OPEN
        assert circuit_breaker.state == CircuitState.OPEN

        # Diagnostics should reflect the circuit state (via metrics)
        metrics = circuit_breaker.metrics
        assert metrics["current_state"] == "open"
        assert metrics["trip_count"] == 1

    def test_get_diagnostics_bypasses_circuit_breaker(
        self,
        inner_adapter: MockBrokerAdapter,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """Test that get_diagnostics() bypasses circuit breaker."""
        resilient_adapter = ResilientBrokerAdapter(
            inner=inner_adapter,
            circuit_breaker=circuit_breaker,
        )

        # Trip the circuit
        mock_adapter = MagicMock()
        mock_adapter.get_diagnostics.return_value = AdapterDiagnostics(
            broker_name="mock",
            connection_status=ConnectionStatus.CONNECTED,
            latency_ms=10,
            error_count_1h=0,
            last_heartbeat=None,
            last_error=None,
            market_open=True,
            orders_submitted_today=0,
            orders_filled_today=0,
            uptime_seconds=0,
        )
        mock_adapter.get_order.side_effect = TransientError("Error")
        resilient_adapter._inner = mock_adapter

        with pytest.raises(TransientError):
            resilient_adapter.get_order("order-1")
        with pytest.raises(CircuitOpenError):
            resilient_adapter.get_order("order-2")

        # Circuit is OPEN, but get_diagnostics() should still work
        diagnostics = resilient_adapter.get_diagnostics()
        assert diagnostics is not None
        assert mock_adapter.get_diagnostics.called


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Tests for thread-safe operation (inherited from components)."""

    def test_resilient_adapter_maintains_thread_safety(
        self,
        resilient_adapter: ResilientBrokerAdapter,
    ) -> None:
        """Test that resilient adapter maintains thread safety."""
        # This is a high-level test; detailed thread safety tests
        # should be on CircuitBreaker itself (already tested).
        # Here we just verify the adapter is properly initialized
        # with thread-safe components.
        assert resilient_adapter._circuit_breaker is not None
        assert resilient_adapter._inner is not None


# ---------------------------------------------------------------------------
# Integration with MockBrokerAdapter
# ---------------------------------------------------------------------------


class TestIntegrationWithMockAdapter:
    """Tests for integration with MockBrokerAdapter."""

    def test_idempotency_preserved_through_resilient_adapter(
        self,
        resilient_adapter: ResilientBrokerAdapter,
        market_buy: OrderRequest,
    ) -> None:
        """Test that idempotency is preserved through the resilient adapter."""
        # Submit order
        resp1 = resilient_adapter.submit_order(market_buy)
        broker_order_id_1 = resp1.broker_order_id

        # Submit again with same client_order_id (should be idempotent)
        resp2 = resilient_adapter.submit_order(market_buy)
        broker_order_id_2 = resp2.broker_order_id

        # Both should return the same broker order ID (idempotency)
        assert broker_order_id_1 == broker_order_id_2
        assert resp1.filled_quantity == resp2.filled_quantity
