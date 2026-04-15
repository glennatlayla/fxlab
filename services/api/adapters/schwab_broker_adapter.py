"""
Schwab Trading API broker adapter.

Responsibilities:
- Implement BrokerAdapterInterface for the Schwab Trader API.
- Submit, cancel, and query orders via Schwab REST endpoints.
- Query positions and account data.
- Map Schwab order states to normalized OrderStatus enum.
- Enforce configured timeouts on all HTTP calls.
- Retry on 429/5xx with exponential backoff; fail fast on 4xx.
- Inject OAuth Bearer tokens via SchwabOAuthManager on every request.

Does NOT:
- Contain business logic or risk checks.
- Handle WebSocket streaming (Schwab does not offer public WS for orders).
- Manage OAuth credentials directly (SchwabOAuthManager does that).
- Perform the initial OAuth authorization code flow.

Dependencies:
- httpx: HTTP client with timeout support.
- libs.contracts.schwab_config: SchwabConfig for URLs and account hash.
- libs.contracts.execution: Order/position/account contract types.
- libs.contracts.errors: Domain exception hierarchy.
- services.api.infrastructure.schwab_auth: SchwabOAuthManager for tokens.
- services.api.infrastructure.timeout_config: BrokerTimeoutConfig.
- services.api.infrastructure.task_retry: Retry with backoff.

Error conditions:
- AuthError: 401/403 from Schwab (invalid/expired token or insufficient permissions).
- NotFoundError: 404 from Schwab (order ID does not exist).
- TransientError: 429/5xx from Schwab (retriable).
- ExternalServiceError: Other unexpected Schwab errors.
- TimeoutError: Wrapped in TransientError when HTTP call exceeds timeout.

Example:
    from libs.contracts.schwab_config import SchwabConfig
    from services.api.infrastructure.schwab_auth import SchwabOAuthManager

    config = SchwabConfig.paper(
        client_id="app-abc", client_secret="secret", account_hash="HASH"
    )
    oauth = SchwabOAuthManager(config=config)
    oauth.initialize(refresh_token="rt-from-secret-store")
    adapter = SchwabBrokerAdapter(config=config, oauth_manager=oauth)
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
from libs.contracts.schwab_config import SchwabConfig
from services.api.infrastructure.schwab_auth import SchwabOAuthManager
from services.api.infrastructure.task_retry import TaskRetryConfig, with_retry
from services.api.infrastructure.timeout_config import BrokerTimeoutConfig

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Schwab → domain state mapping
# ---------------------------------------------------------------------------

_SCHWAB_STATUS_MAP: dict[str, OrderStatus] = {
    # Active / working
    "WORKING": OrderStatus.SUBMITTED,
    "ACCEPTED": OrderStatus.SUBMITTED,
    "PENDING_CANCEL": OrderStatus.SUBMITTED,
    "PENDING_REPLACE": OrderStatus.SUBMITTED,
    "AWAITING_UR_OUT": OrderStatus.SUBMITTED,
    # Pending / queued
    "PENDING_ACTIVATION": OrderStatus.PENDING,
    "QUEUED": OrderStatus.PENDING,
    "NEW": OrderStatus.PENDING,
    "AWAITING_PARENT_ORDER": OrderStatus.PENDING,
    "AWAITING_CONDITION": OrderStatus.PENDING,
    "AWAITING_STOP_CONDITION": OrderStatus.PENDING,
    "AWAITING_MANUAL_REVIEW": OrderStatus.PENDING,
    "AWAITING_RELEASE_TIME": OrderStatus.PENDING,
    "PENDING_ACKNOWLEDGEMENT": OrderStatus.PENDING,
    "UNKNOWN": OrderStatus.PENDING,
    # Terminal
    "FILLED": OrderStatus.FILLED,
    "CANCELED": OrderStatus.CANCELLED,
    "REPLACED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    "EXPIRED": OrderStatus.EXPIRED,
}

_SCHWAB_SIDE_MAP: dict[str, OrderSide] = {
    "BUY": OrderSide.BUY,
    "BUY_TO_COVER": OrderSide.BUY,
    "SELL": OrderSide.SELL,
    "SELL_SHORT": OrderSide.SELL,
}

_SCHWAB_ORDER_TYPE_MAP: dict[str, OrderType] = {
    "MARKET": OrderType.MARKET,
    "LIMIT": OrderType.LIMIT,
    "STOP": OrderType.STOP,
    "STOP_LIMIT": OrderType.STOP_LIMIT,
}

_SCHWAB_TIF_MAP: dict[str, TimeInForce] = {
    "DAY": TimeInForce.DAY,
    "GOOD_TILL_CANCEL": TimeInForce.GTC,
    "FILL_OR_KILL": TimeInForce.FOK,
}

# Domain → Schwab order type mapping for submission
_DOMAIN_ORDER_TYPE_TO_SCHWAB: dict[str, str] = {
    "market": "MARKET",
    "limit": "LIMIT",
    "stop": "STOP",
    "stop_limit": "STOP_LIMIT",
}

# Domain → Schwab instruction mapping for submission
_DOMAIN_SIDE_TO_SCHWAB: dict[str, str] = {
    "buy": "BUY",
    "sell": "SELL",
}

# Domain → Schwab duration mapping for submission
_DOMAIN_TIF_TO_SCHWAB: dict[str, str] = {
    "day": "DAY",
    "gtc": "GOOD_TILL_CANCEL",
    "ioc": "IMMEDIATE_OR_CANCEL",
    "fok": "FILL_OR_KILL",
}

# Retry config for Schwab API calls (429, 5xx)
_SCHWAB_RETRY = TaskRetryConfig(
    max_retries=3,
    base_delay_seconds=1.0,
    max_delay_seconds=16.0,
    exponential_base=2.0,
    jitter=True,
)


class SchwabBrokerAdapter(BrokerAdapterInterface):
    """
    Schwab Trading API broker adapter (REST).

    Implements BrokerAdapterInterface for order submission, cancellation,
    and position/account queries against the Schwab Trader API v1.

    All HTTP calls use configurable timeouts from BrokerTimeoutConfig.
    Transient failures (429, 5xx) are retried with exponential backoff.
    Permanent failures (400, 401, 403, 404) raise domain exceptions
    without retry.

    OAuth Bearer tokens are obtained from SchwabOAuthManager and injected
    into every request header. Tokens auto-refresh transparently.

    Responsibilities:
    - Submit and cancel orders via Schwab REST endpoints.
    - Query order status, positions, and account info.
    - Map Schwab order states to normalized OrderStatus.
    - Enforce timeouts on all HTTP operations.
    - Track error counts and latency for diagnostics.

    Does NOT:
    - Handle the OAuth authorization code flow.
    - Contain risk or business logic.
    - Store orders locally (Schwab is the source of truth).

    Dependencies:
        config: SchwabConfig with account hash and URLs.
        oauth_manager: SchwabOAuthManager for Bearer token injection.
        timeout_config: BrokerTimeoutConfig for HTTP timeouts.

    Example:
        config = SchwabConfig.paper(
            client_id="app-id", client_secret="secret", account_hash="HASH"
        )
        oauth = SchwabOAuthManager(config=config)
        oauth.initialize(refresh_token="rt-from-store")
        adapter = SchwabBrokerAdapter(config=config, oauth_manager=oauth)
        adapter.connect()
        resp = adapter.submit_order(request)
    """

    def __init__(
        self,
        *,
        config: SchwabConfig,
        oauth_manager: SchwabOAuthManager,
        timeout_config: BrokerTimeoutConfig | None = None,
        execution_mode: ExecutionMode = ExecutionMode.LIVE,
    ) -> None:
        """
        Initialize the Schwab broker adapter.

        Args:
            config: Schwab API configuration with account hash and URLs.
            oauth_manager: OAuth manager providing Bearer tokens.
            timeout_config: HTTP timeout configuration. Uses defaults if None.
            execution_mode: Execution mode for order responses (paper or live).

        Example:
            adapter = SchwabBrokerAdapter(
                config=SchwabConfig.paper(...),
                oauth_manager=oauth,
            )
        """
        self._config = config
        self._oauth = oauth_manager
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
        Establish HTTP client connection to Schwab.

        Creates an httpx.Client with configured timeouts. Validates
        connectivity by calling GET on the account endpoint.

        Raises:
            ExternalServiceError: Cannot reach Schwab API.
            AuthError: Invalid OAuth credentials.

        Example:
            adapter.connect()
        """
        if self._client is not None:
            return  # Idempotent

        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=self._timeout_config.connect_timeout_s,
                read=self._timeout_config.read_timeout_s,
                write=self._timeout_config.read_timeout_s,
                pool=self._timeout_config.connect_timeout_s,
            ),
        )

        # Validate connectivity via account endpoint
        try:
            token = self._oauth.get_access_token()
            resp = self._client.get(
                self._config.account_url,
                headers={"Authorization": f"Bearer {token}"},
            )
            self._handle_error_response(resp, operation="connect")
            self._connected_at = datetime.now(tz=timezone.utc)
            self._last_heartbeat = self._connected_at

            logger.info(
                "schwab.connected",
                base_url=self._config.base_url,
                component="schwab_broker_adapter",
            )
        except (AuthError, ExternalServiceError):
            self._client.close()
            self._client = None
            raise
        except Exception as exc:
            self._client.close()
            self._client = None
            raise ExternalServiceError(f"Failed to connect to Schwab: {exc}") from exc

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
                    "schwab.disconnect_error",
                    component="schwab_broker_adapter",
                    exc_info=True,
                )
            finally:
                self._client = None

            logger.debug(
                "schwab.disconnected",
                component="schwab_broker_adapter",
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
        Submit an order to Schwab via POST /accounts/{hash}/orders.

        Schwab returns 201 Created on success. The response Location header
        contains the new order URL. We follow up with a GET to retrieve the
        full order response with Schwab-assigned orderId.

        Args:
            request: Normalized order submission payload.

        Returns:
            OrderResponse with Schwab-assigned broker_order_id and initial status.

        Raises:
            ExternalServiceError: Schwab communication failure.
            TransientError: 429 or 5xx (after retry exhaustion).
            AuthError: Invalid OAuth credentials.

        Example:
            resp = adapter.submit_order(order_request)
        """
        client = self._ensure_connected()

        # Build Schwab order payload
        instruction = _DOMAIN_SIDE_TO_SCHWAB.get(request.side.value, request.side.value.upper())
        schwab_order_type = _DOMAIN_ORDER_TYPE_TO_SCHWAB.get(
            request.order_type.value, request.order_type.value.upper()
        )
        duration = _DOMAIN_TIF_TO_SCHWAB.get(request.time_in_force.value, "DAY")

        payload: dict[str, Any] = {
            "orderType": schwab_order_type,
            "session": "NORMAL",
            "duration": duration,
            "orderStrategyType": "SINGLE",
            "orderLegCollection": [
                {
                    "instruction": instruction,
                    "quantity": float(request.quantity),
                    "instrument": {
                        "symbol": request.symbol,
                        "assetType": "EQUITY",
                    },
                }
            ],
        }

        if request.limit_price is not None:
            payload["price"] = str(request.limit_price)
        if request.stop_price is not None:
            payload["stopPrice"] = str(request.stop_price)

        def _do_submit() -> httpx.Response:
            token = self._oauth.get_access_token()
            return client.post(
                self._config.orders_url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=httpx.Timeout(
                    connect=self._timeout_config.connect_timeout_s,
                    read=self._timeout_config.order_timeout_s,
                    write=self._timeout_config.order_timeout_s,
                    pool=self._timeout_config.connect_timeout_s,
                ),
            )

        resp = self._call_with_retry(_do_submit, "submit_order")

        self._orders_submitted_today += 1

        # Schwab returns 201 with Location header, or the order body directly
        if resp.status_code == 201:
            # Try to get order from Location header or response body
            location = resp.headers.get("location", "")
            if location and resp.content and len(resp.content) > 2:
                data = resp.json()
            elif location:
                # Follow Location header to get full order
                order_resp = self._authenticated_get(location)
                data = order_resp.json()
            else:
                # Fallback: return what we can from the response
                data = resp.json() if resp.content and len(resp.content) > 2 else {}
        else:
            data = resp.json()

        return self._map_order_response(data, request)

    def cancel_order(self, broker_order_id: str) -> OrderResponse:
        """
        Cancel an order via DELETE /accounts/{hash}/orders/{orderId}.

        Args:
            broker_order_id: Schwab-assigned order ID.

        Returns:
            OrderResponse with updated cancellation status.

        Raises:
            NotFoundError: Order ID unknown to Schwab.
            ExternalServiceError: Schwab communication failure.

        Example:
            resp = adapter.cancel_order("12345678")
        """
        client = self._ensure_connected()
        url = f"{self._config.orders_url}/{broker_order_id}"

        def _do_cancel() -> httpx.Response:
            token = self._oauth.get_access_token()
            return client.delete(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=httpx.Timeout(
                    connect=self._timeout_config.connect_timeout_s,
                    read=self._timeout_config.cancel_timeout_s,
                    write=self._timeout_config.cancel_timeout_s,
                    pool=self._timeout_config.connect_timeout_s,
                ),
            )

        self._call_with_retry(_do_cancel, "cancel_order")

        # Re-fetch order to get updated state
        return self.get_order(broker_order_id)

    def get_order(self, broker_order_id: str) -> OrderResponse:
        """
        Query order state via GET /accounts/{hash}/orders/{orderId}.

        Args:
            broker_order_id: Schwab-assigned order ID.

        Returns:
            OrderResponse with current status.

        Raises:
            NotFoundError: Order ID unknown to Schwab.
            ExternalServiceError: Schwab communication failure.

        Example:
            resp = adapter.get_order("12345678")
        """
        client = self._ensure_connected()
        url = f"{self._config.orders_url}/{broker_order_id}"

        def _do_get() -> httpx.Response:
            token = self._oauth.get_access_token()
            return client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )

        resp = self._call_with_retry(_do_get, "get_order")
        data = resp.json()
        return self._map_order_response(data)

    def list_open_orders(self) -> list[OrderResponse]:
        """
        List open orders via GET /accounts/{hash}/orders with status filter.

        Returns:
            List of OrderResponse for all non-terminal orders.

        Raises:
            ExternalServiceError: Schwab communication failure.

        Example:
            orders = adapter.list_open_orders()
        """
        client = self._ensure_connected()

        def _do_list() -> httpx.Response:
            token = self._oauth.get_access_token()
            return client.get(
                self._config.orders_url,
                params={"status": "WORKING"},
                headers={"Authorization": f"Bearer {token}"},
            )

        resp = self._call_with_retry(_do_list, "list_open_orders")
        data = resp.json()

        if isinstance(data, list):
            return [self._map_order_response(o) for o in data]
        return []

    def get_fills(self, broker_order_id: str) -> list[OrderFillEvent]:
        """
        Get fill events for an order via GET /accounts/{hash}/orders/{orderId}.

        Schwab includes fill info in orderActivityCollection. Each EXECUTION
        activity may contain multiple executionLegs.

        Args:
            broker_order_id: Schwab-assigned order ID.

        Returns:
            List of OrderFillEvent ordered chronologically.

        Raises:
            NotFoundError: Order ID unknown to Schwab.

        Example:
            fills = adapter.get_fills("12345678")
        """
        client = self._ensure_connected()
        url = f"{self._config.orders_url}/{broker_order_id}"

        def _do_get() -> httpx.Response:
            token = self._oauth.get_access_token()
            return client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )

        resp = self._call_with_retry(_do_get, "get_fills")
        data = resp.json()

        fills: list[OrderFillEvent] = []
        activities = data.get("orderActivityCollection", [])

        # Extract symbol and side from order legs
        legs = data.get("orderLegCollection", [])
        symbol = ""
        side = OrderSide.BUY
        if legs:
            first_leg = legs[0]
            symbol = first_leg.get("instrument", {}).get("symbol", "")
            instruction = first_leg.get("instruction", "BUY")
            side = _SCHWAB_SIDE_MAP.get(instruction, OrderSide.BUY)

        fill_idx = 0
        for activity in activities:
            if activity.get("activityType") != "EXECUTION":
                continue

            execution_legs = activity.get("executionLegs", [])
            for leg in execution_legs:
                fill_idx += 1
                price = Decimal(str(leg.get("price", "0")))
                quantity = Decimal(str(leg.get("quantity", "0")))

                if quantity <= 0:
                    continue

                filled_at_str = leg.get("time")
                filled_at = self._parse_timestamp(filled_at_str) or datetime.now(tz=timezone.utc)

                fill = OrderFillEvent(
                    fill_id=f"{broker_order_id}-fill-{fill_idx}",
                    order_id=data.get("tag", "").replace("API_TOS:", ""),
                    broker_order_id=str(data.get("orderId", broker_order_id)),
                    symbol=symbol,
                    side=side,
                    price=price,
                    quantity=quantity,
                    commission=Decimal("0"),
                    filled_at=filled_at,
                    broker_execution_id=str(data.get("orderId", "")),
                    correlation_id="",
                )
                fills.append(fill)

        return fills

    def get_positions(self) -> list[PositionSnapshot]:
        """
        Get all positions via GET /accounts/{hash}?fields=positions.

        Returns:
            List of PositionSnapshot for all held instruments.

        Raises:
            ExternalServiceError: Schwab communication failure.

        Example:
            positions = adapter.get_positions()
        """
        client = self._ensure_connected()

        def _do_get() -> httpx.Response:
            token = self._oauth.get_access_token()
            return client.get(
                self._config.positions_url,
                headers={"Authorization": f"Bearer {token}"},
            )

        resp = self._call_with_retry(_do_get, "get_positions")
        data = resp.json()

        securities = data.get("securitiesAccount", {})
        positions_raw = securities.get("positions", [])

        return [self._map_position(p) for p in positions_raw]

    def get_account(self) -> AccountSnapshot:
        """
        Get account info via GET /accounts/{hash}.

        Returns:
            AccountSnapshot with equity, cash, and buying power.

        Raises:
            ExternalServiceError: Schwab communication failure.

        Example:
            account = adapter.get_account()
        """
        client = self._ensure_connected()

        def _do_get() -> httpx.Response:
            token = self._oauth.get_access_token()
            return client.get(
                self._config.account_url,
                headers={"Authorization": f"Bearer {token}"},
            )

        resp = self._call_with_retry(_do_get, "get_account")
        data = resp.json()

        securities = data.get("securitiesAccount", {})
        balances = securities.get("currentBalances", {})
        positions = securities.get("positions", [])

        return AccountSnapshot(
            account_id=str(securities.get("accountNumber", "")),
            equity=Decimal(str(balances.get("liquidationValue", "0"))),
            cash=Decimal(str(balances.get("cashBalance", "0"))),
            buying_power=Decimal(str(balances.get("buyingPower", "0"))),
            portfolio_value=Decimal(str(balances.get("liquidationValue", "0"))),
            daily_pnl=Decimal("0"),
            pending_orders_count=0,
            positions_count=len(positions),
            updated_at=datetime.now(tz=timezone.utc),
        )

    def get_diagnostics(self) -> AdapterDiagnostics:
        """
        Get adapter health diagnostics.

        Calls GET on the account endpoint to measure latency and check status.

        Returns:
            AdapterDiagnostics with connection status, latency, and error counts.

        Example:
            diag = adapter.get_diagnostics()
        """
        start = time.monotonic()

        try:
            client = self._ensure_connected()
            token = self._oauth.get_access_token()
            resp = client.get(
                self._config.account_url,
                headers={"Authorization": f"Bearer {token}"},
            )
            latency_ms = int((time.monotonic() - start) * 1000)

            if resp.status_code == 200:
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
            broker_name="schwab",
            connection_status=conn_status,
            latency_ms=latency_ms,
            error_count_1h=self._error_count_1h,
            last_heartbeat=self._last_heartbeat,
            last_error=self._last_error,
            market_open=False,
            orders_submitted_today=self._orders_submitted_today,
            orders_filled_today=self._orders_filled_today,
            uptime_seconds=uptime,
        )

    def is_market_open(self) -> bool:
        """
        Check if US equities market is open via Schwab market hours endpoint.

        Uses GET /marketdata/v1/markets with market=equity.

        Returns:
            True if the market is currently in trading hours.

        Raises:
            ExternalServiceError: Schwab communication failure.

        Example:
            if adapter.is_market_open():
                adapter.submit_order(request)
        """
        client = self._ensure_connected()

        # Schwab market hours endpoint is under the marketdata API
        market_url = f"{self._config.base_url}/../marketdata/v1/markets"
        # Normalize double dots in URL path
        market_url = market_url.replace("/trader/v1/../", "/")

        def _do_market() -> httpx.Response:
            token = self._oauth.get_access_token()
            return client.get(
                market_url,
                params={"markets": "equity"},
                headers={"Authorization": f"Bearer {token}"},
            )

        resp = self._call_with_retry(_do_market, "is_market_open")
        data = resp.json()

        # Schwab returns nested structure: { equity: { EQ: { isOpen: bool } } }
        equity = data.get("equity", {})
        for _market_key, market_data in equity.items():
            if isinstance(market_data, dict):
                return bool(market_data.get("isOpen", False))

        return False

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
                "SchwabBrokerAdapter is not connected. Call connect() first."
            )
        return self._client

    def _authenticated_get(self, url: str) -> httpx.Response:
        """
        Perform an authenticated GET request.

        Args:
            url: Full URL to GET.

        Returns:
            httpx.Response from the GET request.

        Raises:
            ExternalServiceError: Communication failure.
        """
        client = self._ensure_connected()
        token = self._oauth.get_access_token()

        def _do_get() -> httpx.Response:
            return client.get(url, headers={"Authorization": f"Bearer {token}"})

        return self._call_with_retry(_do_get, "authenticated_get")

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
            resp = with_retry(fn, _SCHWAB_RETRY, logger)
        except (httpx.TimeoutException, TimeoutError) as exc:
            self._error_count_1h += 1
            self._last_error = f"Timeout during {operation}: {exc}"
            raise TransientError(f"Schwab API timeout during {operation}: {exc}") from exc
        except (httpx.ConnectError, ConnectionError, OSError) as exc:
            self._error_count_1h += 1
            self._last_error = f"Connection error during {operation}: {exc}"
            raise TransientError(f"Schwab API connection error during {operation}: {exc}") from exc

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

        # Extract Schwab error message
        try:
            body = resp.json()
            msg = body.get("error", body.get("message", resp.text))
        except Exception:
            msg = resp.text

        self._error_count_1h += 1
        self._last_error = f"{operation}: HTTP {resp.status_code} — {msg}"

        if resp.status_code in (401, 403):
            raise AuthError(f"Schwab authentication failed during {operation}: {msg}")

        if resp.status_code == 404:
            raise NotFoundError(f"Schwab resource not found during {operation}: {msg}")

        if resp.status_code == 422:
            raise ExternalServiceError(f"Schwab rejected request during {operation}: {msg}")

        if resp.status_code == 429 or resp.status_code >= 500:
            raise TransientError(
                f"Schwab transient error during {operation}: HTTP {resp.status_code} — {msg}"
            )

        raise ExternalServiceError(
            f"Schwab error during {operation}: HTTP {resp.status_code} — {msg}"
        )

    def _map_order_response(
        self,
        data: dict[str, Any],
        request: OrderRequest | None = None,
    ) -> OrderResponse:
        """
        Map Schwab order JSON to normalized OrderResponse.

        Args:
            data: Schwab order JSON dict.
            request: Original OrderRequest if available (for client_order_id).

        Returns:
            Normalized OrderResponse.
        """
        schwab_status = data.get("status", "UNKNOWN")
        status = _SCHWAB_STATUS_MAP.get(schwab_status, OrderStatus.PENDING)

        if status == OrderStatus.FILLED:
            self._orders_filled_today += 1

        # Extract symbol and side from orderLegCollection
        legs = data.get("orderLegCollection", [])
        symbol = ""
        side = OrderSide.BUY
        if legs:
            first_leg = legs[0]
            symbol = first_leg.get("instrument", {}).get("symbol", "")
            instruction = first_leg.get("instruction", "BUY")
            side = _SCHWAB_SIDE_MAP.get(instruction, OrderSide.BUY)

        # Order type mapping
        schwab_type = data.get("orderType", "MARKET")
        order_type = _SCHWAB_ORDER_TYPE_MAP.get(schwab_type, OrderType.MARKET)

        # Time in force mapping
        schwab_tif = data.get("duration", "DAY")
        tif = _SCHWAB_TIF_MAP.get(schwab_tif, TimeInForce.DAY)

        # Quantities
        quantity = Decimal(str(data.get("quantity", "0")))
        filled_qty = Decimal(str(data.get("filledQuantity", "0")))

        # Average fill price from execution activities
        avg_price = self._extract_average_fill_price(data)

        # Timestamps
        entered_time = self._parse_timestamp(data.get("enteredTime"))
        close_time = self._parse_timestamp(data.get("closeTime"))

        # Client order ID from tag (Schwab uses tag field for client tracking)
        tag = data.get("tag", "")
        client_order_id = tag.replace("API_TOS:", "") if tag else ""
        if request:
            client_order_id = request.client_order_id

        # Prices
        price_raw = data.get("price")
        limit_price = Decimal(str(price_raw)) if price_raw else None

        stop_raw = data.get("stopPrice")
        stop_price = Decimal(str(stop_raw)) if stop_raw else None

        correlation_id = ""
        if request:
            correlation_id = request.correlation_id

        return OrderResponse(
            client_order_id=client_order_id,
            broker_order_id=str(data.get("orderId", "")),
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            filled_quantity=filled_qty,
            average_fill_price=avg_price,
            status=status,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=tif,
            submitted_at=entered_time,
            filled_at=close_time if status == OrderStatus.FILLED else None,
            cancelled_at=close_time if status == OrderStatus.CANCELLED else None,
            rejected_reason=None,
            correlation_id=correlation_id or client_order_id,
            execution_mode=self._execution_mode,
        )

    def _extract_average_fill_price(self, data: dict[str, Any]) -> Decimal | None:
        """
        Calculate volume-weighted average fill price from Schwab execution activities.

        Args:
            data: Schwab order JSON dict.

        Returns:
            Average fill price, or None if no fills.
        """
        total_qty = Decimal("0")
        total_value = Decimal("0")

        activities = data.get("orderActivityCollection", [])
        for activity in activities:
            if activity.get("activityType") != "EXECUTION":
                continue
            for leg in activity.get("executionLegs", []):
                qty = Decimal(str(leg.get("quantity", "0")))
                price = Decimal(str(leg.get("price", "0")))
                if qty > 0 and price > 0:
                    total_qty += qty
                    total_value += qty * price

        if total_qty > 0:
            return total_value / total_qty
        return None

    def _map_position(self, data: dict[str, Any]) -> PositionSnapshot:
        """
        Map Schwab position JSON to normalized PositionSnapshot.

        Args:
            data: Schwab position JSON dict from securitiesAccount.positions.

        Returns:
            Normalized PositionSnapshot.
        """
        instrument = data.get("instrument", {})
        symbol = instrument.get("symbol", "")

        quantity = Decimal(str(data.get("longQuantity", 0)))
        short_qty = Decimal(str(data.get("shortQuantity", 0)))
        if short_qty > 0:
            quantity = -short_qty

        avg_price = Decimal(str(data.get("averagePrice", "0")))
        market_value = Decimal(str(data.get("marketValue", "0")))
        unrealized_pnl = Decimal(str(data.get("longOpenProfitLoss", "0")))

        # Compute market price from market value and quantity
        market_price = Decimal("0")
        if quantity != 0:
            market_price = abs(market_value / quantity)

        cost_basis = abs(avg_price * quantity)

        return PositionSnapshot(
            symbol=symbol,
            quantity=quantity,
            average_entry_price=avg_price,
            market_price=market_price,
            market_value=market_value,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=Decimal("0"),
            cost_basis=cost_basis,
            updated_at=datetime.now(tz=timezone.utc),
        )

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        """
        Parse an ISO 8601 timestamp string from Schwab.

        Schwab uses format like "2026-04-11T14:00:00+0000".

        Args:
            value: ISO 8601 timestamp string, or None.

        Returns:
            datetime instance, or None if value is None/empty.
        """
        if not value:
            return None
        try:
            # Schwab uses +0000 format (no colon). Python 3.10 fromisoformat
            # does not handle this. Insert colon if needed.
            if value.endswith("+0000") or value.endswith("-0000"):
                value = value[:-2] + ":00"
            elif len(value) > 5 and value[-5] in ("+", "-") and ":" not in value[-5:]:
                # e.g. +0400 → +04:00
                value = value[:-2] + ":" + value[-2:]

            normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
            return datetime.fromisoformat(normalized)
        except (ValueError, TypeError):
            return None
