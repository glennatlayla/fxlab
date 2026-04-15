"""
Broker adapter interface (port).

Responsibilities:
- Define the abstract contract for broker communication.
- Normalize all broker operations behind a single idempotent interface.
- Enable substitution of real, paper, and shadow adapters without changing
  calling code.

Does NOT:
- Execute any I/O or network calls.
- Contain business logic or risk checks.
- Know about specific broker APIs (Alpaca, IBKR, etc.).

Dependencies:
- libs.contracts.execution: OrderRequest, OrderResponse, OrderFillEvent,
  PositionSnapshot, AccountSnapshot, AdapterDiagnostics.

Error conditions:
- submit_order: raises ExternalServiceError on broker communication failure.
- submit_order: raises TransientError on retriable broker errors (timeout, 5xx).
- cancel_order: raises NotFoundError when broker_order_id is unknown.
- get_order: raises NotFoundError when broker_order_id is unknown.

Example:
    adapter: BrokerAdapterInterface = MockBrokerAdapter()
    response = adapter.submit_order(order_request)
    positions = adapter.get_positions()
    diagnostics = adapter.get_diagnostics()
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.execution import (
    AccountSnapshot,
    AdapterDiagnostics,
    OrderFillEvent,
    OrderRequest,
    OrderResponse,
    PositionSnapshot,
)
from services.api.infrastructure.timeout_config import BrokerTimeoutConfig


class BrokerAdapterInterface(ABC):
    """
    Port interface for broker communication.

    All execution modes (shadow, paper, live) implement this interface.
    The risk gate and execution services depend on this abstraction,
    never on a concrete adapter.

    Implementations:
    - MockBrokerAdapter      — in-memory, configurable fills, for unit tests
    - ShadowBrokerAdapter    — logs decisions, no real execution (M3)
    - PaperBrokerAdapter     — simulated order book with realistic fills (M4)
    - AlpacaBrokerAdapter    — real Alpaca API integration (future)

    Idempotency contract:
    - submit_order() with a previously-seen client_order_id MUST return
      the existing OrderResponse without submitting a new order.

    Lifecycle contract:
    - connect() must be called before any order/data operations.
    - disconnect() must be called during graceful shutdown.
    - All implementations MUST enforce timeouts from get_timeout_config()
      on every external call. A call that exceeds the configured timeout
      MUST raise TimeoutError (wrapped in TransientError for the caller).

    Timeout enforcement:
    - Implementations must use the values from get_timeout_config() as
      hard limits on all network I/O. For HTTP-based adapters, these map
      to httpx/requests timeout parameters. For WebSocket-based adapters,
      stream_heartbeat_s determines the keepalive deadline.
    """

    # ------------------------------------------------------------------
    # Lifecycle methods
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self) -> None:
        """
        Establish connection to the broker.

        Called during adapter registration or application startup.
        Implementations should authenticate, open sessions, and verify
        connectivity. This method is idempotent — calling it on an
        already-connected adapter is a no-op.

        Raises:
            ExternalServiceError: Cannot establish connection.
            TransientError: Temporary connection failure (retriable).
            AuthError: Authentication credentials invalid.

        Example:
            adapter.connect()
            # Adapter is now ready for order operations
        """
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """
        Gracefully close the broker connection.

        Called during adapter deregistration or application shutdown.
        Implementations should close HTTP sessions, WebSocket connections,
        and release any held resources. This method is idempotent —
        calling it on an already-disconnected adapter is a no-op.

        Must NOT raise exceptions. Connection cleanup errors should be
        logged but swallowed to prevent shutdown failures.

        Example:
            adapter.disconnect()
            # Resources released, adapter is inert
        """
        ...

    @abstractmethod
    def get_timeout_config(self) -> BrokerTimeoutConfig:
        """
        Return the timeout configuration for this adapter.

        The returned config determines the maximum time allowed for each
        type of broker operation. All network calls within this adapter
        MUST respect these limits.

        Returns:
            BrokerTimeoutConfig with the timeouts this adapter uses.

        Example:
            config = adapter.get_timeout_config()
            # config.order_timeout_s == 30.0
        """
        ...

    # ------------------------------------------------------------------
    # Order operations
    # ------------------------------------------------------------------

    @abstractmethod
    def submit_order(self, request: OrderRequest) -> OrderResponse:
        """
        Submit an order to the broker.

        Idempotent: if client_order_id has been seen before, returns the
        existing order without re-submitting.

        Args:
            request: Normalized order submission payload.

        Returns:
            OrderResponse with initial status (typically SUBMITTED or PENDING).

        Raises:
            ExternalServiceError: Broker communication failure.
            TransientError: Retriable broker error (timeout, rate limit, 5xx).

        Example:
            resp = adapter.submit_order(order_request)
            # resp.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED)
            # resp.client_order_id == order_request.client_order_id
        """
        ...

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> OrderResponse:
        """
        Request cancellation of an open order.

        Args:
            broker_order_id: Broker-assigned order identifier.

        Returns:
            OrderResponse with updated status (CANCELLED or pending cancel).

        Raises:
            NotFoundError: broker_order_id is unknown.
            ExternalServiceError: Broker communication failure.

        Example:
            resp = adapter.cancel_order("ALPACA-12345")
            # resp.status == OrderStatus.CANCELLED
        """
        ...

    @abstractmethod
    def get_order(self, broker_order_id: str) -> OrderResponse:
        """
        Query the current state of an order.

        Args:
            broker_order_id: Broker-assigned order identifier.

        Returns:
            OrderResponse with current status and fill information.

        Raises:
            NotFoundError: broker_order_id is unknown.
            ExternalServiceError: Broker communication failure.

        Example:
            resp = adapter.get_order("ALPACA-12345")
            # resp.status in OrderStatus
        """
        ...

    @abstractmethod
    def list_open_orders(self) -> list[OrderResponse]:
        """
        List all orders currently open/active at the broker.

        Returns:
            List of OrderResponse for orders with non-terminal status.

        Raises:
            ExternalServiceError: Broker communication failure.

        Example:
            orders = adapter.list_open_orders()
            # all(o.status in (PENDING, SUBMITTED, PARTIAL_FILL) for o in orders)
        """
        ...

    @abstractmethod
    def get_fills(self, broker_order_id: str) -> list[OrderFillEvent]:
        """
        Get all fill events for an order.

        Args:
            broker_order_id: Broker-assigned order identifier.

        Returns:
            List of OrderFillEvent for this order, ordered chronologically.

        Raises:
            NotFoundError: broker_order_id is unknown.
            ExternalServiceError: Broker communication failure.

        Example:
            fills = adapter.get_fills("ALPACA-12345")
            # sum(f.quantity for f in fills) <= order.quantity
        """
        ...

    @abstractmethod
    def get_positions(self) -> list[PositionSnapshot]:
        """
        Get current position snapshot for all held instruments.

        Returns:
            List of PositionSnapshot, one per instrument with non-zero quantity.

        Raises:
            ExternalServiceError: Broker communication failure.

        Example:
            positions = adapter.get_positions()
            # each pos.quantity != 0
        """
        ...

    @abstractmethod
    def get_account(self) -> AccountSnapshot:
        """
        Get current account balance and margin summary.

        Returns:
            AccountSnapshot with equity, cash, buying power, etc.

        Raises:
            ExternalServiceError: Broker communication failure.

        Example:
            acct = adapter.get_account()
            # acct.equity >= 0
        """
        ...

    @abstractmethod
    def get_diagnostics(self) -> AdapterDiagnostics:
        """
        Get adapter health and performance diagnostics.

        Returns:
            AdapterDiagnostics with connection status, latency, error counts.

        Example:
            diag = adapter.get_diagnostics()
            # diag.connection_status == ConnectionStatus.CONNECTED
        """
        ...

    @abstractmethod
    def is_market_open(self) -> bool:
        """
        Check whether the target market is currently in trading hours.

        Returns:
            True if the market is open and accepting orders.

        Example:
            if adapter.is_market_open():
                adapter.submit_order(request)
        """
        ...

    @property
    def is_paper_adapter(self) -> bool:
        """
        Check whether this adapter is a paper or shadow trading adapter.

        Returns:
            True if this adapter does not execute real orders (paper/shadow mode).
            False if this adapter submits real orders to a broker (live/Alpaca/Schwab).

        Safety use case:
            LiveExecutionService uses this to prevent accidental routing of live
            deployments to paper adapters — a critical misconfiguration that could
            cause live orders to disappear silently.

        Example:
            adapter = ShadowBrokerAdapter()
            assert adapter.is_paper_adapter is True

            adapter = AlpacaBrokerAdapter()
            assert adapter.is_paper_adapter is False
        """
        # Default implementation: assume the adapter is production-safe.
        # Override in PaperBrokerAdapter and ShadowBrokerAdapter to return True.
        return False
