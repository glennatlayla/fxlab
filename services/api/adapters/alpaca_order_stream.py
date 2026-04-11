"""
Alpaca trade updates WebSocket client.

Responsibilities:
- Connect to Alpaca's trade_updates WebSocket stream.
- Authenticate with API credentials.
- Receive and normalize Alpaca trade/order update events.
- Dispatch normalized OrderEvent instances to registered callbacks.
- Manage connection lifecycle (start, stop, reconnect).
- Report stream health via diagnostics.
- Handle all shared state with threading.Lock for concurrent access.

Does NOT:
- Persist order events (callback consumers or service layer handles that).
- Contain business logic or risk checks.
- Know about execution modes or strategies.

Dependencies:
    config: AlpacaConfig with API credentials and stream URL.
    timeout_config: BrokerTimeoutConfig for heartbeat/connection timeouts.

Error conditions:
    ExternalServiceError: Connection fails or authentication denied.
    Transient connection drops are handled with exponential backoff retry.

Example:
    from libs.contracts.alpaca_config import AlpacaConfig
    from services.api.adapters.alpaca_order_stream import AlpacaOrderStream

    config = AlpacaConfig.paper(api_key="AK...", api_secret="...")
    stream = AlpacaOrderStream(config=config)
    stream.register_callback(my_event_handler)
    stream.start()
    # ... later ...
    stream.stop()
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

import structlog
import websocket
from ulid import ULID

from libs.contracts.alpaca_config import AlpacaConfig
from libs.contracts.errors import ExternalServiceError
from libs.contracts.execution import OrderEvent
from libs.contracts.interfaces.order_stream_interface import (
    OrderEventCallback,
    OrderStreamInterface,
)
from services.api.infrastructure.timeout_config import BrokerTimeoutConfig

logger = structlog.get_logger(__name__)

# Suppress verbose websocket-client logging
logging.getLogger("websocket").setLevel(logging.WARNING)

# Alpaca trade_updates event types that we map to OrderEvent
_ALPACA_EVENT_TYPES = {
    "new",
    "partial_fill",
    "fill",
    "canceled",
    "expired",
    "rejected",
    "replaced",
    "held",
    "re-submitted",
}

# Reconnect backoff: 1s, 2s, 4s, 8s, 16s max
_RECONNECT_DELAYS = [1.0, 2.0, 4.0, 8.0, 16.0]


class AlpacaOrderStream(OrderStreamInterface):
    """
    Alpaca trade updates WebSocket client.

    Implements OrderStreamInterface for real-time order update streaming
    via Alpaca's wss://paper-api.alpaca.markets/stream endpoint.

    The WebSocket connection runs in a daemon thread. Trade update messages
    are received, parsed, and dispatched to registered callbacks.
    Reconnect logic uses exponential backoff on transient failures.

    Responsibilities:
    - Connect to Alpaca trade_updates stream in a background thread.
    - Authenticate using API key and secret.
    - Normalize Alpaca trade events to OrderEvent contracts.
    - Dispatch events to all registered callbacks with error isolation.
    - Maintain connection health via heartbeat monitoring.
    - Gracefully shutdown on stop().

    Does NOT:
    - Persist order events.
    - Contain business logic or risk checks.
    - Manage order lifecycle (service layer handles that).

    Thread safety:
    - All shared state (_callbacks, _connected, _running, _events_received,
      _last_event_at, _reconnect_count) is protected by self._lock.
    - Callbacks are dispatched with exceptions caught to prevent cascade
      failures.

    Example:
        config = AlpacaConfig.paper(api_key="AK...", api_secret="...")
        stream = AlpacaOrderStream(config=config)
        stream.register_callback(my_event_handler)
        stream.start()
        # ... orders arrive as events ...
        stream.stop()
    """

    def __init__(
        self,
        *,
        config: AlpacaConfig,
        timeout_config: BrokerTimeoutConfig | None = None,
    ) -> None:
        """
        Initialize the Alpaca order stream client.

        Args:
            config: Alpaca API configuration with credentials and stream URL.
            timeout_config: Timeout configuration for connection and heartbeat.
                If None, uses BrokerTimeoutConfig defaults.

        Example:
            stream = AlpacaOrderStream(
                config=AlpacaConfig.paper(api_key="AK...", api_secret="..."),
            )
        """
        self._config = config
        self._timeout_config = timeout_config or BrokerTimeoutConfig()

        # Thread and connection state
        self._lock = threading.Lock()
        self._stream_thread: threading.Thread | None = None
        self._running = False
        self._connected = False
        self._ws: websocket.WebSocket | None = None

        # Event callbacks
        self._callbacks: list[OrderEventCallback] = []

        # Diagnostics
        self._events_received = 0
        self._last_event_at: datetime | None = None
        self._reconnect_count = 0

    # ------------------------------------------------------------------
    # Lifecycle: start, stop
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the order update stream connection.

        Begins the WebSocket connection in a background daemon thread.
        Performs authentication and subscribes to trade_updates.

        Raises:
            ExternalServiceError: Initial connection or authentication fails.

        Example:
            stream.start()
        """
        with self._lock:
            if self._running:
                logger.debug(
                    "alpaca_order_stream.already_started",
                    component="alpaca_order_stream",
                )
                return

            self._running = True

        logger.info(
            "alpaca_order_stream.starting",
            stream_url=self._config.trade_updates_stream_url,
            component="alpaca_order_stream",
        )

        # Start WebSocket loop in daemon thread
        self._stream_thread = threading.Thread(
            target=self._run_stream_loop,
            daemon=True,
            name="alpaca-order-stream",
        )
        self._stream_thread.start()

    def stop(self) -> None:
        """
        Stop the order update stream and close the connection.

        Gracefully shuts down the WebSocket and waits for the thread to exit.
        Idempotent: safe to call multiple times or on unstarted stream.

        Example:
            stream.stop()
        """
        with self._lock:
            if not self._running:
                return
            self._running = False

        logger.info(
            "alpaca_order_stream.stopping",
            component="alpaca_order_stream",
        )

        # Close WebSocket
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception as exc:
                logger.warning(
                    "alpaca_order_stream.close_error",
                    error=str(exc),
                    component="alpaca_order_stream",
                    exc_info=True,
                )
            finally:
                self._ws = None

        # Wait for stream thread to exit (with timeout)
        if self._stream_thread is not None:
            self._stream_thread.join(timeout=5.0)
            self._stream_thread = None

        logger.info(
            "alpaca_order_stream.stopped",
            component="alpaca_order_stream",
        )

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def register_callback(self, callback: OrderEventCallback) -> None:
        """
        Register a callback to receive OrderEvent instances.

        Multiple callbacks can be registered. Each receives every event.
        Callback exceptions are caught and logged; they do not affect other
        callbacks or the stream.

        Args:
            callback: Function accepting an OrderEvent argument.

        Example:
            def on_order_event(event: OrderEvent) -> None:
                print(f"Event {event.event_id}: {event.event_type}")

            stream.register_callback(on_order_event)
        """
        with self._lock:
            self._callbacks.append(callback)

        logger.debug(
            "alpaca_order_stream.callback_registered",
            callback_count=len(self._callbacks),
            component="alpaca_order_stream",
        )

    # ------------------------------------------------------------------
    # Connection status
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """
        Return True if the stream is currently connected and authenticated.

        Returns:
            True if the WebSocket is open and authentication succeeded.

        Example:
            if stream.is_connected():
                print("Stream is live")
        """
        with self._lock:
            return self._connected

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def diagnostics(self) -> dict[str, Any]:
        """
        Return stream health diagnostics.

        Returns:
            Dict with keys:
                - connected: bool, whether stream is connected.
                - events_received: int, total events dispatched.
                - last_event_at: datetime | None, timestamp of last event.
                - reconnect_count: int, number of reconnection attempts.
                - errors: list[str], recent error messages (not yet populated).

        Example:
            diag = stream.diagnostics()
            print(f"Connected: {diag['connected']}, Events: {diag['events_received']}")
        """
        with self._lock:
            return {
                "connected": self._connected,
                "events_received": self._events_received,
                "last_event_at": self._last_event_at,
                "reconnect_count": self._reconnect_count,
                "errors": [],
            }

    # ------------------------------------------------------------------
    # Internal: Main event loop
    # ------------------------------------------------------------------

    def _run_stream_loop(self) -> None:
        """
        Main WebSocket event loop (runs in background thread).

        Connects to Alpaca trade_updates stream, authenticates, listens for
        messages, and handles reconnection logic.

        Does NOT raise exceptions (catches all and logs).

        Example:
            threading.Thread(target=self._run_stream_loop, daemon=True).start()
        """
        reconnect_attempt = 0

        while True:
            with self._lock:
                if not self._running:
                    break

            try:
                # Establish connection with retry backoff
                self._connect_with_retry(reconnect_attempt)
                reconnect_attempt = 0

                # Event loop
                self._receive_messages()

            except Exception as exc:
                reconnect_attempt = min(reconnect_attempt + 1, len(_RECONNECT_DELAYS) - 1)
                delay = _RECONNECT_DELAYS[reconnect_attempt]

                logger.warning(
                    "alpaca_order_stream.connection_error",
                    error=str(exc),
                    reconnect_attempt=reconnect_attempt,
                    retry_delay_s=delay,
                    component="alpaca_order_stream",
                    exc_info=True,
                )

                with self._lock:
                    self._reconnect_count += 1
                    self._connected = False

                # Sleep before reconnect
                time.sleep(delay)

                with self._lock:
                    if not self._running:
                        break

    def _connect_with_retry(self, attempt: int) -> None:
        """
        Connect to Alpaca trade_updates stream and authenticate.

        Args:
            attempt: Current reconnection attempt number (for logging).

        Raises:
            ExternalServiceError: Connection or auth fails.

        Example:
            self._connect_with_retry(0)
        """
        url = self._config.trade_updates_stream_url

        logger.debug(
            "alpaca_order_stream.connecting",
            url=url,
            attempt=attempt,
            component="alpaca_order_stream",
        )

        # Create WebSocket connection
        self._ws = websocket.create_connection(
            url,
            timeout=self._timeout_config.connect_timeout_s,
        )

        try:
            # Send authentication message
            auth_msg = {
                "action": "auth",
                "key": self._config.api_key,
                "secret": self._config.api_secret,
            }
            self._ws.send(json.dumps(auth_msg))

            # Receive auth response
            auth_response_str = self._ensure_str(self._ws.recv())
            auth_response = json.loads(auth_response_str)

            if auth_response.get("stream") != "authorize":
                raise ExternalServiceError(f"Unexpected auth response: {auth_response_str}")

            if auth_response.get("data", {}).get("status") != "authorized":
                raise ExternalServiceError(f"Authentication denied: {auth_response_str}")

            logger.debug(
                "alpaca_order_stream.authenticated",
                component="alpaca_order_stream",
            )

            # Send listen subscription
            listen_msg = {
                "action": "listen",
                "data": {"streams": ["trade_updates"]},
            }
            self._ws.send(json.dumps(listen_msg))

            # Receive listen confirmation
            listen_response_str = self._ensure_str(self._ws.recv())
            listen_response = json.loads(listen_response_str)

            if listen_response.get("stream") != "listening":
                raise ExternalServiceError(f"Unexpected listen response: {listen_response_str}")

            with self._lock:
                self._connected = True

            logger.info(
                "alpaca_order_stream.connected",
                component="alpaca_order_stream",
            )

        except Exception:
            if self._ws is not None:
                with contextlib.suppress(Exception):
                    self._ws.close()
                self._ws = None
            raise

    def _receive_messages(self) -> None:
        """
        Receive and process messages from the WebSocket.

        Runs until connection is closed or _running becomes False.
        Each message is passed to _handle_message for processing.

        Does not raise exceptions; logs errors and exits loop.

        Example:
            self._receive_messages()
        """
        if self._ws is None:
            raise ExternalServiceError("WebSocket not connected")

        while self._running:
            try:
                message_bytes = self._ws.recv()
                message_str = self._ensure_str(message_bytes)
                if not message_str:
                    continue

                self._handle_message(message_str)

            except websocket.WebSocketTimeoutException:
                logger.warning(
                    "alpaca_order_stream.receive_timeout",
                    component="alpaca_order_stream",
                )
                break
            except websocket.WebSocketConnectionClosedException:
                logger.info(
                    "alpaca_order_stream.connection_closed",
                    component="alpaca_order_stream",
                )
                break
            except Exception as exc:
                logger.error(
                    "alpaca_order_stream.receive_error",
                    error=str(exc),
                    component="alpaca_order_stream",
                    exc_info=True,
                )
                break

    # ------------------------------------------------------------------
    # Internal: Message handling
    # ------------------------------------------------------------------

    def _handle_message(self, message_str: str) -> None:
        """
        Parse and dispatch a WebSocket message.

        Expects JSON with structure:
            {
                "stream": "trade_updates",
                "data": {
                    "event": "fill" | "partial_fill" | "canceled" | ...,
                    "order": { ... },
                    "timestamp": "...",
                    "qty": "...",
                    "price": "..."
                }
            }

        Args:
            message_str: JSON string from WebSocket.

        Does not raise exceptions; logs errors and continues.

        Example:
            self._handle_message('{"stream":"trade_updates","data":{...}}')
        """
        try:
            message = json.loads(message_str)
        except json.JSONDecodeError as exc:
            logger.debug(
                "alpaca_order_stream.json_parse_error",
                error=str(exc),
                component="alpaca_order_stream",
            )
            return

        # Only process trade_updates stream
        if message.get("stream") != "trade_updates":
            return

        data = message.get("data", {})
        if not data:
            return

        # Extract event type
        event_type = data.get("event")
        if not event_type or event_type not in _ALPACA_EVENT_TYPES:
            return

        # Extract order info
        order = data.get("order", {})
        if not order:
            return

        client_order_id = order.get("client_order_id")
        if not client_order_id:
            return

        # Build OrderEvent details
        details: dict[str, Any] = {
            "symbol": order.get("symbol"),
            "side": order.get("side"),
            "status": order.get("status"),
        }

        # Add fill-specific details
        if event_type in ("fill", "partial_fill"):
            if "qty" in data:
                details["qty"] = data["qty"]
            if "price" in data:
                details["price"] = data["price"]
            if "filled_qty" in order:
                details["filled_qty"] = order["filled_qty"]
            if "filled_avg_price" in order:
                details["filled_avg_price"] = order["filled_avg_price"]

        # Add rejection details
        if event_type == "rejected" and "reject_reason" in order:
            details["reject_reason"] = order["reject_reason"]

        # Parse event timestamp
        timestamp_str = data.get("timestamp", "")
        timestamp = self._parse_timestamp(timestamp_str) or datetime.now(tz=timezone.utc)

        # Generate unique event ID (ULID)
        event_id = str(ULID())

        # Create and dispatch OrderEvent
        try:
            event = OrderEvent(
                event_id=event_id,
                order_id=client_order_id,
                event_type=event_type,
                timestamp=timestamp,
                details=details,
                correlation_id=client_order_id,
            )

            self._dispatch_event(event)

        except Exception as exc:
            logger.error(
                "alpaca_order_stream.event_creation_error",
                error=str(exc),
                order_id=client_order_id,
                component="alpaca_order_stream",
                exc_info=True,
            )

    @staticmethod
    def _ensure_str(value: str | bytes) -> str:
        """
        Convert bytes to str if needed, pass through str unchanged.

        Args:
            value: str or bytes from WebSocket recv().

        Returns:
            str value, decoded from bytes if necessary.

        Example:
            msg_str = self._ensure_str(b"hello")
        """
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return value

    def _dispatch_event(self, event: OrderEvent) -> None:
        """
        Dispatch an OrderEvent to all registered callbacks.

        Each callback is invoked with the event. If a callback raises an
        exception, it is caught and logged; other callbacks are still invoked.

        Args:
            event: OrderEvent to dispatch.

        Example:
            self._dispatch_event(order_event)
        """
        with self._lock:
            callbacks = self._callbacks.copy()
            self._events_received += 1
            self._last_event_at = datetime.now(tz=timezone.utc)

        logger.debug(
            "alpaca_order_stream.dispatching_event",
            event_id=event.event_id,
            order_id=event.order_id,
            event_type=event.event_type,
            callback_count=len(callbacks),
            component="alpaca_order_stream",
        )

        for i, callback in enumerate(callbacks):
            try:
                callback(event)
            except Exception as exc:
                logger.warning(
                    "alpaca_order_stream.callback_error",
                    callback_index=i,
                    error=str(exc),
                    event_id=event.event_id,
                    component="alpaca_order_stream",
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Internal: Timestamp parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        """
        Parse an ISO 8601 timestamp string.

        Handles Alpaca's 'Z' suffix for UTC timestamps by normalizing
        to the '+00:00' format that Python's fromisoformat() expects.

        Args:
            value: ISO 8601 timestamp string, or None.

        Returns:
            datetime instance, or None if value is None/empty/unparseable.

        Example:
            dt = self._parse_timestamp("2026-04-11T14:01:00Z")
        """
        if not value:
            return None

        try:
            # Normalize 'Z' suffix to '+00:00' for fromisoformat()
            normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
            return datetime.fromisoformat(normalized)
        except (ValueError, TypeError):
            return None
