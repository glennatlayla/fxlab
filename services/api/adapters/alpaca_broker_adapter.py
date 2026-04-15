"""
Alpaca Trading API v2 broker adapter.

Responsibilities:
- Implement BrokerAdapterInterface for Alpaca's REST API.
- Submit, cancel, and query orders via Alpaca endpoints.
- Query positions and account data.
- Map Alpaca order states to normalized OrderStatus enum.
- Enforce configured timeouts on all HTTP calls.
- Retry on 429/5xx with exponential backoff; fail fast on 4xx.

Does NOT:
- Contain business logic or risk checks.
- Handle WebSocket streaming (see alpaca_market_stream.py for that).
- Manage API credentials (loaded from AlpacaConfig).

Dependencies:
- httpx: HTTP client with timeout support.
- libs.contracts.alpaca_config: AlpacaConfig for credentials and URLs.
- libs.contracts.execution: Order/position/account contract types.
- libs.contracts.errors: Domain exception hierarchy.
- services.api.infrastructure.timeout_config: BrokerTimeoutConfig.
- services.api.infrastructure.task_retry: Retry with backoff.

Error conditions:
- AuthError: 401/403 from Alpaca (invalid API key or insufficient permissions).
- NotFoundError: 404 from Alpaca (order ID does not exist).
- TransientError: 429/5xx from Alpaca (retriable).
- ExternalServiceError: Other unexpected Alpaca errors.
- TimeoutError: Wrapped in TransientError when HTTP call exceeds timeout.

Example:
    from libs.contracts.alpaca_config import AlpacaConfig

    config = AlpacaConfig.paper(api_key="AK...", api_secret="...")
    adapter = AlpacaBrokerAdapter(config=config)
    adapter.connect()
    response = adapter.submit_order(order_request)
    adapter.disconnect()
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
import structlog

from libs.contracts.alpaca_config import AlpacaConfig
from libs.contracts.errors import (
    AuthError,
    ExternalServiceError,
    NotFoundError,
    TransientError,
)
from libs.contracts.execution import (
    AccountSnapshot,
    AdapterDiagnostics,
    ConnectionStatus,
    ExecutionMode,
    OrderFillEvent,
    OrderRequest,
    OrderResponse,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    TimeInForce,
)
from libs.contracts.interfaces.broker_adapter import BrokerAdapterInterface
from services.api.infrastructure.task_retry import TaskRetryConfig, with_retry
from services.api.infrastructure.timeout_config import BrokerTimeoutConfig

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Alpaca → domain state mapping
# ---------------------------------------------------------------------------

_ALPACA_STATUS_MAP: dict[str, OrderStatus] = {
    "new": OrderStatus.SUBMITTED,
    "accepted": OrderStatus.SUBMITTED,
    "pending_new": OrderStatus.PENDING,
    "accepted_for_bidding": OrderStatus.PENDING,
    "partially_filled": OrderStatus.PARTIAL_FILL,
    "filled": OrderStatus.FILLED,
    "done_for_day": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELLED,
    "pending_cancel": OrderStatus.SUBMITTED,  # still active until confirmed
    "expired": OrderStatus.EXPIRED,
    "replaced": OrderStatus.CANCELLED,  # old order is replaced → cancelled
    "pending_replace": OrderStatus.SUBMITTED,
    "stopped": OrderStatus.FILLED,
    "rejected": OrderStatus.REJECTED,
    "suspended": OrderStatus.PENDING,
    "calculated": OrderStatus.PENDING,
    "held": OrderStatus.PENDING,
}

_ALPACA_SIDE_MAP: dict[str, OrderSide] = {
    "buy": OrderSide.BUY,
    "sell": OrderSide.SELL,
}

_ALPACA_ORDER_TYPE_MAP: dict[str, OrderType] = {
    "market": OrderType.MARKET,
    "limit": OrderType.LIMIT,
    "stop": OrderType.STOP,
    "stop_limit": OrderType.STOP_LIMIT,
}

_ALPACA_TIF_MAP: dict[str, TimeInForce] = {
    "day": TimeInForce.DAY,
    "gtc": TimeInForce.GTC,
    "ioc": TimeInForce.IOC,
    "fok": TimeInForce.FOK,
}

# Retry config for Alpaca API calls (429, 5xx)
_ALPACA_RETRY = TaskRetryConfig(
    max_retries=3,
    base_delay_seconds=1.0,
    max_delay_seconds=16.0,
    exponential_base=2.0,
    jitter=True,
)


class AlpacaBrokerAdapter(BrokerAdapterInterface):
    """
    Alpaca Trading API v2 broker adapter (REST).

    Implements BrokerAdapterInterface for real order submission, cancellation,
    and position/account queries against Alpaca's REST API.

    All HTTP calls use configurable timeouts from BrokerTimeoutConfig.
    Transient failures (429, 5xx) are retried with exponential backoff.
    Permanent failures (400, 401, 403, 404, 422) raise domain exceptions
    without retry.

    Responsibilities:
    - Submit and cancel orders via Alpaca REST endpoints.
    - Query order status, positions, and account info.
    - Map Alpaca order states to normalized OrderStatus.
    - Enforce timeouts on all HTTP operations.
    - Track error counts and latency for diagnostics.

    Does NOT:
    - Handle WebSocket streaming.
    - Contain risk or business logic.
    - Store orders locally (Alpaca is the source of truth).

    Dependencies:
        config: AlpacaConfig with API credentials and URLs.
        timeout_config: BrokerTimeoutConfig for HTTP timeouts.

    Example:
        config = AlpacaConfig.paper(api_key="AK...", api_secret="...")
        adapter = AlpacaBrokerAdapter(config=config)
        adapter.connect()
        resp = adapter.submit_order(request)
    """

    def __init__(
        self,
        *,
        config: AlpacaConfig,
        timeout_config: BrokerTimeoutConfig | None = None,
        execution_mode: ExecutionMode = ExecutionMode.PAPER,
    ) -> None:
        """
        Initialize the Alpaca broker adapter.

        Args:
            config: Alpaca API configuration with credentials and base URL.
            timeout_config: HTTP timeout configuration. Uses defaults if None.
            execution_mode: Execution mode for order responses (paper or live).

        Example:
            adapter = AlpacaBrokerAdapter(
                config=AlpacaConfig.paper(api_key="AK...", api_secret="..."),
            )
        """
        self._config = config
        self._timeout_config = timeout_config or BrokerTimeoutConfig()
        self._execution_mode = execution_mode
        self._client: httpx.Client | None = None
        self._connected_at: datetime | None = None
        self._error_count_1h: int = 0
        self._last_error: str | None = None
        self._last_heartbeat: datetime | None = None
        self._orders_submitted_today: int = 0
        self._orders_filled_today: int = 0

    # ------------------------------------------------------------------
    # Lifecycle methods
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """
        Establish HTTP client connection to Alpaca.

        Creates an httpx.Client with configured timeouts and auth headers.
        Validates connectivity by calling GET /v2/clock.

        Raises:
            ExternalServiceError: Cannot reach Alpaca API.
            AuthError: Invalid API credentials.

        Example:
            adapter.connect()
        """
        if self._client is not None:
            return  # Idempotent

        self._client = httpx.Client(
            headers=self._config.auth_headers,
            timeout=httpx.Timeout(
                connect=self._timeout_config.connect_timeout_s,
                read=self._timeout_config.read_timeout_s,
                write=self._timeout_config.read_timeout_s,
                pool=self._timeout_config.connect_timeout_s,
            ),
        )

        # Validate connectivity
        try:
            resp = self._client.get(self._config.clock_url)
            self._handle_error_response(resp, operation="connect")
            self._connected_at = datetime.now(tz=timezone.utc)
            self._last_heartbeat = self._connected_at

            logger.info(
                "alpaca.connected",
                base_url=self._config.base_url,
                component="alpaca_broker_adapter",
            )
        except (AuthError, ExternalServiceError):
            self._client.close()
            self._client = None
            raise
        except Exception as exc:
            self._client.close()
            self._client = None
            raise ExternalServiceError(f"Failed to connect to Alpaca: {exc}") from exc

    def disconnect(self) -> None:
        """
        Close the HTTP client connection.

        Idempotent. Does not raise on errors.

        Example:
            adapter.disconnect()
        """
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                logger.warning(
                    "alpaca.disconnect_error",
                    component="alpaca_broker_adapter",
                    exc_info=True,
                )
            finally:
                self._client = None

            logger.debug(
                "alpaca.disconnected",
                component="alpaca_broker_adapter",
            )

    def get_timeout_config(self) -> BrokerTimeoutConfig:
        """
        Return the timeout configuration for this adapter.

        Returns:
            BrokerTimeoutConfig used by this adapter instance.

        Example:
            config = adapter.get_timeout_config()
        """
        return self._timeout_config

    # ------------------------------------------------------------------
    # Order operations
    # ------------------------------------------------------------------

    def submit_order(self, request: OrderRequest) -> OrderResponse:
        """
        Submit an order to Alpaca via POST /v2/orders.

        Idempotent: Alpaca deduplicates on client_order_id.

        Args:
            request: Normalized order submission payload.

        Returns:
            OrderResponse with Alpaca-assigned broker_order_id and initial status.

        Raises:
            ExternalServiceError: Alpaca communication failure.
            TransientError: 429 or 5xx (after retry exhaustion).
            AuthError: Invalid credentials.

        Example:
            resp = adapter.submit_order(order_request)
        """
        client = self._ensure_connected()

        payload: dict[str, Any] = {
            "symbol": request.symbol,
            "qty": str(request.quantity),
            "side": request.side.value,
            "type": request.order_type.value,
            "time_in_force": request.time_in_force.value,
            "client_order_id": request.client_order_id,
        }

        if request.limit_price is not None:
            payload["limit_price"] = str(request.limit_price)
        if request.stop_price is not None:
            payload["stop_price"] = str(request.stop_price)

        def _do_submit() -> httpx.Response:
            return client.post(
                self._config.orders_url,
                json=payload,
                timeout=httpx.Timeout(
                    connect=self._timeout_config.connect_timeout_s,
                    read=self._timeout_config.order_timeout_s,
                    write=self._timeout_config.order_timeout_s,
                    pool=self._timeout_config.connect_timeout_s,
                ),
            )

        resp = self._call_with_retry(_do_submit, "submit_order")
        data = resp.json()

        self._orders_submitted_today += 1

        return self._map_order_response(data, request.correlation_id)

    def cancel_order(self, broker_order_id: str) -> OrderResponse:
        """
        Cancel an order via DELETE /v2/orders/{id}.

        Args:
            broker_order_id: Alpaca-assigned order ID.

        Returns:
            OrderResponse with updated cancellation status.

        Raises:
            NotFoundError: Order ID unknown to Alpaca.
            ExternalServiceError: Alpaca communication failure.

        Example:
            resp = adapter.cancel_order("alpaca-order-id")
        """
        client = self._ensure_connected()
        url = f"{self._config.orders_url}/{broker_order_id}"

        def _do_cancel() -> httpx.Response:
            return client.delete(
                url,
                timeout=httpx.Timeout(
                    connect=self._timeout_config.connect_timeout_s,
                    read=self._timeout_config.cancel_timeout_s,
                    write=self._timeout_config.cancel_timeout_s,
                    pool=self._timeout_config.connect_timeout_s,
                ),
            )

        resp = self._call_with_retry(_do_cancel, "cancel_order")

        # Alpaca returns 204 No Content on successful cancel request,
        # so we need to re-fetch the order to get updated state.
        if resp.status_code == 204:
            return self.get_order(broker_order_id)

        data = resp.json()
        return self._map_order_response(data, correlation_id="")

    def get_order(self, broker_order_id: str) -> OrderResponse:
        """
        Query order state via GET /v2/orders/{id}.

        Args:
            broker_order_id: Alpaca-assigned order ID.

        Returns:
            OrderResponse with current status.

        Raises:
            NotFoundError: Order ID unknown to Alpaca.
            ExternalServiceError: Alpaca communication failure.

        Example:
            resp = adapter.get_order("alpaca-order-id")
        """
        client = self._ensure_connected()
        url = f"{self._config.orders_url}/{broker_order_id}"

        def _do_get() -> httpx.Response:
            return client.get(url)

        resp = self._call_with_retry(_do_get, "get_order")
        data = resp.json()
        return self._map_order_response(data, correlation_id="")

    def list_open_orders(self) -> list[OrderResponse]:
        """
        List open orders via GET /v2/orders?status=open.

        Returns:
            List of OrderResponse for all non-terminal orders.

        Raises:
            ExternalServiceError: Alpaca communication failure.

        Example:
            orders = adapter.list_open_orders()
        """
        client = self._ensure_connected()

        def _do_list() -> httpx.Response:
            return client.get(
                self._config.orders_url,
                params={"status": "open"},
            )

        resp = self._call_with_retry(_do_list, "list_open_orders")
        data = resp.json()
        return [self._map_order_response(o, correlation_id="") for o in data]

    def get_fills(self, broker_order_id: str) -> list[OrderFillEvent]:
        """
        Get fill events for an order via GET /v2/orders/{id}.

        Alpaca includes fill info in the order response. We extract
        filled_qty and filled_avg_price to construct a single fill event.

        Args:
            broker_order_id: Alpaca-assigned order ID.

        Returns:
            List of OrderFillEvent (typically one for full fills).

        Raises:
            NotFoundError: Order ID unknown to Alpaca.

        Example:
            fills = adapter.get_fills("alpaca-order-id")
        """
        client = self._ensure_connected()
        url = f"{self._config.orders_url}/{broker_order_id}"

        def _do_get() -> httpx.Response:
            return client.get(url)

        resp = self._call_with_retry(_do_get, "get_fills")
        data = resp.json()

        filled_qty = Decimal(str(data.get("filled_qty", "0")))
        if filled_qty <= 0:
            return []

        filled_avg_price = Decimal(str(data.get("filled_avg_price", "0")))
        filled_at_str = data.get("filled_at")
        filled_at = (
            self._parse_timestamp(filled_at_str) or datetime.now(tz=timezone.utc)
            if filled_at_str
            else datetime.now(tz=timezone.utc)
        )

        side_str = data.get("side", "buy")
        side = _ALPACA_SIDE_MAP.get(side_str, OrderSide.BUY)

        fill = OrderFillEvent(
            fill_id=f"{broker_order_id}-fill-1",
            order_id=data.get("client_order_id", ""),
            broker_order_id=broker_order_id,
            symbol=data.get("symbol", ""),
            side=side,
            price=filled_avg_price,
            quantity=filled_qty,
            commission=Decimal("0"),
            filled_at=filled_at,
            broker_execution_id=data.get("id"),
            correlation_id="",
        )
        return [fill]

    def get_positions(self) -> list[PositionSnapshot]:
        """
        Get all positions via GET /v2/positions.

        Returns:
            List of PositionSnapshot for all held instruments.

        Raises:
            ExternalServiceError: Alpaca communication failure.

        Example:
            positions = adapter.get_positions()
        """
        client = self._ensure_connected()

        def _do_get() -> httpx.Response:
            return client.get(self._config.positions_url)

        resp = self._call_with_retry(_do_get, "get_positions")
        data = resp.json()

        return [self._map_position(p) for p in data]

    def get_account(self) -> AccountSnapshot:
        """
        Get account info via GET /v2/account.

        Returns:
            AccountSnapshot with equity, cash, and buying power.

        Raises:
            ExternalServiceError: Alpaca communication failure.

        Example:
            account = adapter.get_account()
        """
        client = self._ensure_connected()

        def _do_get() -> httpx.Response:
            return client.get(self._config.account_url)

        resp = self._call_with_retry(_do_get, "get_account")
        data = resp.json()

        return AccountSnapshot(
            account_id=data.get("id", ""),
            equity=Decimal(str(data.get("equity", "0"))),
            cash=Decimal(str(data.get("cash", "0"))),
            buying_power=Decimal(str(data.get("buying_power", "0"))),
            portfolio_value=Decimal(str(data.get("portfolio_value", "0"))),
            daily_pnl=Decimal("0"),
            pending_orders_count=0,
            positions_count=0,
            updated_at=datetime.now(tz=timezone.utc),
        )

    def get_diagnostics(self) -> AdapterDiagnostics:
        """
        Get adapter health diagnostics.

        Calls GET /v2/clock to measure latency and check market state.

        Returns:
            AdapterDiagnostics with connection status, latency, and error counts.

        Example:
            diag = adapter.get_diagnostics()
        """
        start = time.monotonic()
        market_open = False

        try:
            client = self._ensure_connected()
            resp = client.get(self._config.clock_url)
            latency_ms = int((time.monotonic() - start) * 1000)

            if resp.status_code == 200:
                data = resp.json()
                market_open = data.get("is_open", False)
                self._last_heartbeat = datetime.now(tz=timezone.utc)
                conn_status = ConnectionStatus.CONNECTED
            else:
                conn_status = ConnectionStatus.ERROR
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            conn_status = ConnectionStatus.DISCONNECTED
            self._last_error = str(exc)
            self._error_count_1h += 1

        uptime = 0
        if self._connected_at:
            uptime = int((datetime.now(tz=timezone.utc) - self._connected_at).total_seconds())

        return AdapterDiagnostics(
            broker_name="alpaca",
            connection_status=conn_status,
            latency_ms=latency_ms,
            error_count_1h=self._error_count_1h,
            last_heartbeat=self._last_heartbeat,
            last_error=self._last_error,
            market_open=market_open,
            orders_submitted_today=self._orders_submitted_today,
            orders_filled_today=self._orders_filled_today,
            uptime_seconds=uptime,
        )

    def is_market_open(self) -> bool:
        """
        Check if US equities market is open via GET /v2/clock.

        Returns:
            True if the market is currently in trading hours.

        Raises:
            ExternalServiceError: Alpaca communication failure.

        Example:
            if adapter.is_market_open():
                adapter.submit_order(request)
        """
        client = self._ensure_connected()

        def _do_clock() -> httpx.Response:
            return client.get(self._config.clock_url)

        resp = self._call_with_retry(_do_clock, "is_market_open")
        data = resp.json()
        return bool(data.get("is_open", False))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> httpx.Client:
        """
        Return the active httpx client, raising if not connected.

        Returns:
            The active httpx.Client instance.

        Raises:
            ExternalServiceError: Adapter has not been connected.
        """
        if self._client is None:
            raise ExternalServiceError(
                "AlpacaBrokerAdapter is not connected. Call connect() first."
            )
        return self._client

    def _call_with_retry(
        self,
        fn: Any,
        operation: str,
    ) -> httpx.Response:
        """
        Execute an HTTP call with retry on transient failures.

        Wraps the function with retry logic. On success, validates the
        response status code and raises domain exceptions for errors.

        Args:
            fn: Callable returning httpx.Response.
            operation: Operation name for logging.

        Returns:
            httpx.Response with successful status code.

        Raises:
            TransientError: After retry exhaustion on 429/5xx.
            AuthError: On 401/403.
            NotFoundError: On 404.
            ExternalServiceError: On other HTTP errors.
        """
        try:
            resp = with_retry(fn, _ALPACA_RETRY, logger)
        except (httpx.TimeoutException, TimeoutError) as exc:
            self._error_count_1h += 1
            self._last_error = f"Timeout during {operation}: {exc}"
            raise TransientError(f"Alpaca API timeout during {operation}: {exc}") from exc
        except (httpx.ConnectError, ConnectionError, OSError) as exc:
            self._error_count_1h += 1
            self._last_error = f"Connection error during {operation}: {exc}"
            raise TransientError(f"Alpaca API connection error during {operation}: {exc}") from exc

        self._handle_error_response(resp, operation=operation)
        return resp

    def _handle_error_response(
        self,
        resp: httpx.Response,
        *,
        operation: str,
    ) -> None:
        """
        Check HTTP response and raise domain exceptions for errors.

        Args:
            resp: httpx.Response to check.
            operation: Operation name for error messages.

        Raises:
            AuthError: On 401/403.
            NotFoundError: On 404.
            TransientError: On 429/5xx.
            ExternalServiceError: On other 4xx errors.
        """
        if resp.status_code < 400:
            return

        # Extract Alpaca error message
        try:
            body = resp.json()
            msg = body.get("message", resp.text)
        except Exception:
            msg = resp.text

        self._error_count_1h += 1
        self._last_error = f"{operation}: HTTP {resp.status_code} — {msg}"

        if resp.status_code in (401, 403):
            raise AuthError(f"Alpaca authentication failed during {operation}: {msg}")

        if resp.status_code == 404:
            raise NotFoundError(f"Alpaca resource not found during {operation}: {msg}")

        if resp.status_code == 422:
            raise ExternalServiceError(f"Alpaca rejected request during {operation}: {msg}")

        if resp.status_code == 429 or resp.status_code >= 500:
            raise TransientError(
                f"Alpaca transient error during {operation}: HTTP {resp.status_code} — {msg}"
            )

        raise ExternalServiceError(
            f"Alpaca error during {operation}: HTTP {resp.status_code} — {msg}"
        )

    def _map_order_response(
        self,
        data: dict[str, Any],
        correlation_id: str,
    ) -> OrderResponse:
        """
        Map Alpaca order JSON to normalized OrderResponse.

        Args:
            data: Alpaca order JSON dict.
            correlation_id: Correlation ID to propagate.

        Returns:
            Normalized OrderResponse.
        """
        alpaca_status = data.get("status", "new")
        status = _ALPACA_STATUS_MAP.get(alpaca_status, OrderStatus.PENDING)

        if status == OrderStatus.FILLED:
            self._orders_filled_today += 1

        side_str = data.get("side", "buy")
        side = _ALPACA_SIDE_MAP.get(side_str, OrderSide.BUY)

        type_str = data.get("type", "market")
        order_type = _ALPACA_ORDER_TYPE_MAP.get(type_str, OrderType.MARKET)

        tif_str = data.get("time_in_force", "day")
        tif = _ALPACA_TIF_MAP.get(tif_str, TimeInForce.DAY)

        submitted_at = self._parse_timestamp(data.get("submitted_at"))
        filled_at = self._parse_timestamp(data.get("filled_at"))
        cancelled_at = self._parse_timestamp(data.get("canceled_at"))

        filled_qty = Decimal(str(data.get("filled_qty", "0")))
        avg_price_raw = data.get("filled_avg_price")
        avg_price = Decimal(str(avg_price_raw)) if avg_price_raw else None

        limit_raw = data.get("limit_price")
        limit_price = Decimal(str(limit_raw)) if limit_raw else None

        stop_raw = data.get("stop_price")
        stop_price = Decimal(str(stop_raw)) if stop_raw else None

        return OrderResponse(
            client_order_id=data.get("client_order_id", ""),
            broker_order_id=data.get("id"),
            symbol=data.get("symbol", ""),
            side=side,
            order_type=order_type,
            quantity=Decimal(str(data.get("qty", "0"))),
            filled_quantity=filled_qty,
            average_fill_price=avg_price,
            status=status,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=tif,
            submitted_at=submitted_at,
            filled_at=filled_at,
            cancelled_at=cancelled_at,
            rejected_reason=data.get("reject_reason"),
            correlation_id=correlation_id or data.get("client_order_id", ""),
            execution_mode=self._execution_mode,
        )

    def _map_position(self, data: dict[str, Any]) -> PositionSnapshot:
        """
        Map Alpaca position JSON to normalized PositionSnapshot.

        Args:
            data: Alpaca position JSON dict.

        Returns:
            Normalized PositionSnapshot.
        """
        return PositionSnapshot(
            symbol=data.get("symbol", ""),
            quantity=Decimal(str(data.get("qty", "0"))),
            average_entry_price=Decimal(str(data.get("avg_entry_price", "0"))),
            market_price=Decimal(str(data.get("current_price", "0"))),
            market_value=Decimal(str(data.get("market_value", "0"))),
            unrealized_pnl=Decimal(str(data.get("unrealized_pl", "0"))),
            realized_pnl=Decimal("0"),
            cost_basis=Decimal(str(data.get("cost_basis", "0"))),
            updated_at=datetime.now(tz=timezone.utc),
        )

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        """
        Parse an ISO 8601 timestamp string from Alpaca.

        Args:
            value: ISO 8601 timestamp string, or None.

        Returns:
            datetime instance, or None if value is None/empty.
        """
        if not value:
            return None
        try:
            # Python 3.10 fromisoformat() does not support the 'Z' suffix
            # that Alpaca uses for UTC timestamps. Normalize before parsing.
            normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
            return datetime.fromisoformat(normalized)
        except (ValueError, TypeError):
            return None
