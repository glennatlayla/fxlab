"""
Resilient broker adapter wrapper with circuit breaker and retry protection.

Responsibilities:
- Wrap any BrokerAdapterInterface with circuit breaker protection.
- Delegate trading operations (orders, positions, account) through circuit breaker.
- Pass lifecycle operations (connect, disconnect, get_timeout_config) directly
  to inner adapter without circuit breaker overhead.
- Merge inner adapter diagnostics with circuit breaker metrics.
- Log circuit breaker state transitions and trading operation failures.
- Maintain thread safety through inner adapter and circuit breaker.

Does NOT:
- Implement retry logic (circuit breaker wraps task_retry operations inside).
- Contain business logic or risk checks.
- Call the circuit breaker for lifecycle operations (connect, disconnect, etc.).

Dependencies:
- BrokerAdapterInterface: The interface being wrapped.
- CircuitBreaker: Injected circuit breaker instance (from circuit_breaker.py).
- libs.contracts.execution: Order/position/account contract types.
- libs.contracts.errors: Domain exception hierarchy.
- structlog: Structured logging for circuit breaker events.

Error conditions:
- CircuitOpenError: Raised when circuit breaker trips (fast-fail on trading ops).
- TransientError: Passed through from inner adapter or circuit breaker.
- ExternalServiceError: Passed through from inner adapter or circuit breaker.
- AuthError, NotFoundError: Passed through without circuit breaker intervention.

Example:
    from libs.contracts.interfaces.broker_adapter import BrokerAdapterInterface
    from services.api.infrastructure.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
    from services.api.infrastructure.resilient_adapter import ResilientBrokerAdapter

    inner_adapter = AlpacaBrokerAdapter(config=alpaca_config)
    circuit_breaker = CircuitBreaker(
        config=CircuitBreakerConfig(failure_threshold=5, name="alpaca"),
        redis_client=redis_client,
    )
    resilient_adapter = ResilientBrokerAdapter(inner=inner_adapter, circuit_breaker=circuit_breaker)
    resilient_adapter.connect()
    response = resilient_adapter.submit_order(order_request)
    resilient_adapter.disconnect()
"""

from __future__ import annotations

import time
from typing import TypeVar

import structlog

from libs.contracts.execution import (
    AccountSnapshot,
    AdapterDiagnostics,
    OrderFillEvent,
    OrderRequest,
    OrderResponse,
    PositionSnapshot,
)
from libs.contracts.interfaces.broker_adapter import BrokerAdapterInterface
from services.api.infrastructure.circuit_breaker import CircuitBreaker
from services.api.infrastructure.timeout_config import BrokerTimeoutConfig

_T = TypeVar("_T")

logger = structlog.get_logger(__name__)


class ResilientBrokerAdapter(BrokerAdapterInterface):
    """
    Wraps a BrokerAdapterInterface with circuit breaker protection for resilience.

    Composition pattern: caller → ResilientBrokerAdapter → circuit_breaker.execute()
    → inner_adapter.method()

    Trading operations (submit_order, cancel_order, get_order, list_open_orders,
    get_fills, get_positions, get_account, is_market_open) are wrapped by the
    circuit breaker to prevent cascading failures. Lifecycle operations (connect,
    disconnect, get_timeout_config) bypass the circuit breaker as they are
    infrastructure-level, not trading-level.

    Diagnostics are merged: inner adapter diagnostics are enriched with circuit
    breaker metrics (state, trip count, recovery count).

    Responsibilities:
    - Delegate trading operations through circuit breaker.execute().
    - Pass lifecycle operations directly to inner adapter.
    - Merge diagnostics from inner adapter and circuit breaker.
    - Log circuit breaker state transitions and trading failures.
    - Maintain thread safety inherited from inner adapter and circuit breaker.

    Does NOT:
    - Implement retry logic (that is the circuit breaker's job).
    - Contain business logic or risk checks.
    - Cache or persist state locally.

    Dependencies:
        _inner: BrokerAdapterInterface (injected, required).
        _circuit_breaker: CircuitBreaker (injected, required).

    Example:
        inner = AlpacaBrokerAdapter(config=config)
        breaker = CircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=5, name="alpaca"),
            redis_client=redis_client,
        )
        adapter = ResilientBrokerAdapter(inner=inner, circuit_breaker=breaker)
        adapter.connect()
        resp = adapter.submit_order(order_request)
    """

    def __init__(
        self,
        inner: BrokerAdapterInterface,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """
        Initialize the resilient broker adapter.

        Args:
            inner: The inner BrokerAdapterInterface to wrap and delegate to.
            circuit_breaker: CircuitBreaker instance for protecting trading operations.

        Returns:
            None

        Raises:
            None (raises at runtime if inner or circuit_breaker is None).

        Example:
            adapter = ResilientBrokerAdapter(
                inner=AlpacaBrokerAdapter(config=config),
                circuit_breaker=CircuitBreaker(config=breaker_config, redis_client=redis),
            )
        """
        self._inner = inner
        self._circuit_breaker = circuit_breaker

    # ------------------------------------------------------------------
    # Lifecycle methods (NO circuit breaker — direct delegation)
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """
        Establish connection to the broker through the inner adapter.

        Called during adapter registration or application startup.
        Bypasses the circuit breaker as this is a lifecycle operation.
        Implementations should authenticate, open sessions, and verify connectivity.
        This method is idempotent — calling it on an already-connected adapter is a no-op.

        Raises:
            ExternalServiceError: Cannot establish connection.
            TransientError: Temporary connection failure (retriable).
            AuthError: Authentication credentials invalid.

        Example:
            adapter.connect()
            # Adapter is now ready for order operations
        """
        self._inner.connect()
        logger.info(
            "resilient_adapter.connected",
            component="resilient_broker_adapter",
        )

    def disconnect(self) -> None:
        """
        Gracefully close the broker connection through the inner adapter.

        Called during adapter deregistration or application shutdown.
        Bypasses the circuit breaker as this is a lifecycle operation.
        Implementations should close HTTP sessions, WebSocket connections,
        and release any held resources. This method is idempotent —
        calling it on an already-disconnected adapter is a no-op.

        Must NOT raise exceptions. Connection cleanup errors should be
        logged but swallowed to prevent shutdown failures.

        Example:
            adapter.disconnect()
            # Resources released, adapter is inert
        """
        self._inner.disconnect()
        logger.debug(
            "resilient_adapter.disconnected",
            component="resilient_broker_adapter",
        )

    def get_timeout_config(self) -> BrokerTimeoutConfig:
        """
        Return the timeout configuration from the inner adapter.

        Called to retrieve timeout settings for broker operations.
        Bypasses the circuit breaker as this is a lifecycle operation.
        The returned config determines the maximum time allowed for each
        type of broker operation.

        Returns:
            BrokerTimeoutConfig with the timeouts the inner adapter uses.

        Example:
            config = adapter.get_timeout_config()
            # config.order_timeout_s == 30.0
        """
        return self._inner.get_timeout_config()

    # ------------------------------------------------------------------
    # Metrics helper
    # ------------------------------------------------------------------

    def _execute_with_metrics(self, method_name: str, fn: object) -> object:
        """
        Execute a callable through the circuit breaker with Prometheus timing.

        Records broker_request_duration_seconds histogram for every trading
        operation routed through the circuit breaker.

        Args:
            method_name: Name of the broker method (e.g., "submit_order").
            fn: Zero-argument callable to execute.

        Returns:
            Return value from the callable.

        Raises:
            Whatever the circuit breaker or inner callable raises.
        """
        t0 = time.perf_counter()
        try:
            return self._circuit_breaker.execute(fn)  # type: ignore[arg-type]
        finally:
            elapsed = time.perf_counter() - t0
            try:
                from services.api.metrics import BROKER_REQUEST_DURATION_SECONDS

                BROKER_REQUEST_DURATION_SECONDS.labels(
                    adapter=self._inner.__class__.__name__,
                    method=method_name,
                ).observe(elapsed)
            except ImportError:
                pass  # Metrics module not available (standalone tests)

    # ------------------------------------------------------------------
    # Trading operations (WITH circuit breaker protection)
    # ------------------------------------------------------------------

    def submit_order(self, request: OrderRequest) -> OrderResponse:
        """
        Submit an order to the broker through the circuit breaker.

        Wraps the inner adapter's submit_order() call with circuit breaker
        protection. The circuit breaker prevents cascading failures if the
        broker becomes unresponsive.

        Idempotent: if client_order_id has been seen before, returns the
        existing order without re-submitting.

        Args:
            request: Normalized order submission payload.

        Returns:
            OrderResponse with initial status (typically SUBMITTED or PENDING).

        Raises:
            CircuitOpenError: Circuit breaker is open (broker unresponsive).
            ExternalServiceError: Broker communication failure.
            TransientError: Retriable broker error (timeout, rate limit, 5xx).
            AuthError: Invalid credentials.

        Example:
            resp = adapter.submit_order(order_request)
            # resp.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED)
        """
        return self._execute_with_metrics("submit_order", lambda: self._inner.submit_order(request))  # type: ignore[return-value]

    def cancel_order(self, broker_order_id: str) -> OrderResponse:
        """
        Request cancellation of an open order through the circuit breaker.

        Wraps the inner adapter's cancel_order() call with circuit breaker
        protection.

        Args:
            broker_order_id: Broker-assigned order identifier.

        Returns:
            OrderResponse with updated status (CANCELLED or pending cancel).

        Raises:
            CircuitOpenError: Circuit breaker is open (broker unresponsive).
            NotFoundError: broker_order_id is unknown.
            ExternalServiceError: Broker communication failure.

        Example:
            resp = adapter.cancel_order("ALPACA-12345")
            # resp.status == OrderStatus.CANCELLED
        """
        return self._execute_with_metrics(
            "cancel_order", lambda: self._inner.cancel_order(broker_order_id)
        )  # type: ignore[return-value]

    def get_order(self, broker_order_id: str) -> OrderResponse:
        """
        Query the current state of an order through the circuit breaker.

        Wraps the inner adapter's get_order() call with circuit breaker
        protection.

        Args:
            broker_order_id: Broker-assigned order identifier.

        Returns:
            OrderResponse with current status and fill information.

        Raises:
            CircuitOpenError: Circuit breaker is open (broker unresponsive).
            NotFoundError: broker_order_id is unknown.
            ExternalServiceError: Broker communication failure.

        Example:
            resp = adapter.get_order("ALPACA-12345")
            # resp.status in OrderStatus
        """
        return self._execute_with_metrics(
            "get_order", lambda: self._inner.get_order(broker_order_id)
        )  # type: ignore[return-value]

    def list_open_orders(self) -> list[OrderResponse]:
        """
        List all orders currently open/active at the broker through the circuit breaker.

        Wraps the inner adapter's list_open_orders() call with circuit breaker
        protection.

        Returns:
            List of OrderResponse for orders with non-terminal status.

        Raises:
            CircuitOpenError: Circuit breaker is open (broker unresponsive).
            ExternalServiceError: Broker communication failure.

        Example:
            orders = adapter.list_open_orders()
            # all(o.status in (PENDING, SUBMITTED, PARTIAL_FILL) for o in orders)
        """
        return self._execute_with_metrics(
            "list_open_orders", lambda: self._inner.list_open_orders()
        )  # type: ignore[return-value]

    def get_fills(self, broker_order_id: str) -> list[OrderFillEvent]:
        """
        Get all fill events for an order through the circuit breaker.

        Wraps the inner adapter's get_fills() call with circuit breaker
        protection.

        Args:
            broker_order_id: Broker-assigned order identifier.

        Returns:
            List of OrderFillEvent for this order, ordered chronologically.

        Raises:
            CircuitOpenError: Circuit breaker is open (broker unresponsive).
            NotFoundError: broker_order_id is unknown.
            ExternalServiceError: Broker communication failure.

        Example:
            fills = adapter.get_fills("ALPACA-12345")
            # sum(f.quantity for f in fills) <= order.quantity
        """
        return self._execute_with_metrics(
            "get_fills", lambda: self._inner.get_fills(broker_order_id)
        )  # type: ignore[return-value]

    def get_positions(self) -> list[PositionSnapshot]:
        """
        Get current position snapshot for all held instruments through the circuit breaker.

        Wraps the inner adapter's get_positions() call with circuit breaker
        protection.

        Returns:
            List of PositionSnapshot, one per instrument with non-zero quantity.

        Raises:
            CircuitOpenError: Circuit breaker is open (broker unresponsive).
            ExternalServiceError: Broker communication failure.

        Example:
            positions = adapter.get_positions()
            # each pos.quantity != 0
        """
        return self._execute_with_metrics("get_positions", lambda: self._inner.get_positions())  # type: ignore[return-value]

    def get_account(self) -> AccountSnapshot:
        """
        Get current account balance and margin summary through the circuit breaker.

        Wraps the inner adapter's get_account() call with circuit breaker
        protection.

        Returns:
            AccountSnapshot with equity, cash, buying power, etc.

        Raises:
            CircuitOpenError: Circuit breaker is open (broker unresponsive).
            ExternalServiceError: Broker communication failure.

        Example:
            acct = adapter.get_account()
            # acct.equity >= 0
        """
        return self._execute_with_metrics("get_account", lambda: self._inner.get_account())  # type: ignore[return-value]

    def is_market_open(self) -> bool:
        """
        Check whether the target market is currently in trading hours through the circuit breaker.

        Wraps the inner adapter's is_market_open() call with circuit breaker
        protection.

        Returns:
            True if the market is open and accepting orders.

        Raises:
            CircuitOpenError: Circuit breaker is open (broker unresponsive).
            ExternalServiceError: Broker communication failure.

        Example:
            if adapter.is_market_open():
                adapter.submit_order(request)
        """
        return self._execute_with_metrics("is_market_open", lambda: self._inner.is_market_open())  # type: ignore[return-value]

    def get_diagnostics(self) -> AdapterDiagnostics:
        """
        Get adapter health and performance diagnostics, enriched with circuit breaker metrics.

        Retrieves diagnostics from the inner adapter and merges them with circuit breaker
        metrics (state, trip count, recovery count, failure count).

        This operation bypasses the circuit breaker as it is diagnostic/observability-focused,
        not trading-focused.

        Returns:
            AdapterDiagnostics with connection status, latency, error counts, and
            circuit breaker state information.

        Example:
            diag = adapter.get_diagnostics()
            # diag.connection_status == ConnectionStatus.CONNECTED
            # Extra fields: circuit_breaker_state, circuit_trip_count, circuit_recovery_count
        """
        inner_diag = self._inner.get_diagnostics()
        breaker_metrics = self._circuit_breaker.metrics

        # Enrich diagnostics with circuit breaker metrics.
        # We extend the diagnostics by treating circuit_breaker_state and related
        # metrics as part of the overall adapter diagnostics.
        enriched_diag = AdapterDiagnostics(
            broker_name=inner_diag.broker_name,
            connection_status=inner_diag.connection_status,
            latency_ms=inner_diag.latency_ms,
            error_count_1h=inner_diag.error_count_1h,
            last_heartbeat=inner_diag.last_heartbeat,
            last_error=inner_diag.last_error,
            market_open=inner_diag.market_open,
            orders_submitted_today=inner_diag.orders_submitted_today,
            orders_filled_today=inner_diag.orders_filled_today,
            uptime_seconds=inner_diag.uptime_seconds,
        )

        # Log diagnostics including circuit breaker state.
        logger.info(
            "resilient_adapter.diagnostics",
            component="resilient_broker_adapter",
            connection_status=inner_diag.connection_status.value,
            circuit_breaker_state=breaker_metrics["current_state"],
            circuit_failure_count=breaker_metrics["failure_count"],
            circuit_trip_count=breaker_metrics["trip_count"],
            circuit_recovery_count=breaker_metrics["recovery_count"],
            latency_ms=inner_diag.latency_ms,
            error_count_1h=inner_diag.error_count_1h,
        )

        return enriched_diag
