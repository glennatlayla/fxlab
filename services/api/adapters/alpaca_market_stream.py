"""
Alpaca Market Data WebSocket stream adapter.

Responsibilities:
- Connect to Alpaca's real-time market data stream via WebSocket.
- Authenticate and subscribe to trade symbols.
- Receive and normalize trade messages into PriceUpdate contracts.
- Manage connection lifecycle (start, stop, reconnect).
- Dispatch price updates to registered callbacks.
- Report stream health via diagnostics.

Does NOT:
- Persist price data (callback consumers decide).
- Contain trading logic or risk checks.
- Know about broker REST API or order management.

Dependencies:
- websocket-client: Synchronous WebSocket library.
- libs.contracts.alpaca_config: AlpacaConfig with API credentials.
- libs.contracts.execution: PriceUpdate contract model.
- libs.contracts.errors: Domain exception types.
- services.api.infrastructure.timeout_config: BrokerTimeoutConfig for heartbeat.
- structlog: Structured logging.

Error conditions:
- ExternalServiceError: Connection or authentication failures.
- Transient failures on disconnect: automatic reconnect with exponential backoff.
- Bad callbacks: individual callback exceptions logged but do not kill the stream.

Example:
    from libs.contracts.alpaca_config import AlpacaConfig

    config = AlpacaConfig.paper(api_key="AK...", api_secret="...")
    stream = AlpacaMarketStream(config=config)
    stream.register_callback(lambda update: print(f"{update.symbol}: {update.price}"))
    stream.subscribe(["AAPL", "MSFT"])
    stream.start()
    # ... stream runs in daemon thread ...
    stream.stop()
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
import websocket

from libs.contracts.alpaca_config import AlpacaConfig
from libs.contracts.errors import ExternalServiceError
from libs.contracts.execution import PriceUpdate
from libs.contracts.interfaces.market_stream_interface import (
    MarketStreamInterface,
    PriceCallback,
)
from services.api.infrastructure.timeout_config import BrokerTimeoutConfig

logger = structlog.get_logger(__name__)

# Retry configuration for WebSocket reconnection: exponential backoff
# Delays: 1s, 2s, 4s, 8s, 16s (max)
_RECONNECT_DELAYS = [1.0, 2.0, 4.0, 8.0, 16.0]


class AlpacaMarketStream(MarketStreamInterface):
    """
    Alpaca real-time market data WebSocket stream (synchronous adapter).

    Connects to Alpaca's WebSocket endpoint, authenticates with API credentials,
    and streams trade updates. Runs the WebSocket loop in a background daemon thread.

    All shared state (_callbacks, _subscribed_symbols, _running, etc.) is protected
    by threading.Lock to ensure thread safety per §0 of CLAUDE.md.

    Connection lifecycle:
    - start() → spawns daemon thread → attempts WebSocket connection
    - stop() → sets running flag, joins thread, closes WebSocket
    - On disconnect, automatically reconnects with exponential backoff (1s → 16s).

    Heartbeat monitoring:
    - If no message received within stream_heartbeat_s, logs warning but continues.
    - Reconnect count and message counters tracked for diagnostics.

    Responsibilities:
    - Manage WebSocket lifecycle (connect, auth, subscribe, receive, disconnect).
    - Dispatch normalized PriceUpdate events to callbacks.
    - Handle reconnection with exponential backoff on transient failures.
    - Protect shared state with threading.Lock.
    - Log all significant events (connect, disconnect, auth, subscribe, trade).

    Does NOT:
    - Persist price data.
    - Know about order management or trading logic.
    - Retry on permanent failures (auth, bad subscription).

    Example:
        stream = AlpacaMarketStream(config=alpaca_config)
        stream.register_callback(on_price_update)
        stream.subscribe(["AAPL", "MSFT"])
        stream.start()
        time.sleep(10)
        stream.stop()
    """

    def __init__(
        self,
        *,
        config: AlpacaConfig,
        timeout_config: BrokerTimeoutConfig | None = None,
    ) -> None:
        """
        Initialize the Alpaca market data stream.

        Args:
            config: Alpaca API configuration with credentials and data feed.
            timeout_config: Heartbeat timeout configuration. Uses defaults if None.

        Example:
            config = AlpacaConfig.paper(api_key="AK...", api_secret="...")
            stream = AlpacaMarketStream(config=config)
        """
        self._config = config
        self._timeout_config = timeout_config or BrokerTimeoutConfig()

        # Thread-safe shared state (protected by _lock)
        self._lock = threading.Lock()
        self._callbacks: list[PriceCallback] = []
        self._subscribed_symbols: set[str] = set()

        # Connection state
        self._ws: websocket.WebSocket | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._authenticated = False

        # Diagnostics state
        self._messages_received = 0
        self._last_message_at: datetime | None = None
        self._reconnect_count = 0
        self._connected_at: datetime | None = None

    # -----------------------------------------------------------------------
    # Lifecycle: start / stop
    # -----------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the market data stream connection.

        Spawns a daemon thread that connects to Alpaca's WebSocket,
        authenticates, and subscribes to previously registered symbols.

        Raises:
            ExternalServiceError: If initial connection fails.

        Example:
            stream.start()
        """
        with self._lock:
            if self._running:
                return  # Idempotent: already running

            self._running = True

        # Start daemon thread to manage WebSocket loop
        self._thread = threading.Thread(
            target=self._run_websocket_loop,
            daemon=True,
            name="alpaca-market-stream",
        )
        self._thread.start()

        logger.info(
            "alpaca_market_stream.started",
            component="alpaca_market_stream",
            feed=self._config.data_feed,
        )

    def stop(self) -> None:
        """
        Stop the market data stream and close the connection.

        Sets running flag to False, waits for thread to exit gracefully,
        then closes the WebSocket. Idempotent; does not raise on errors.

        Example:
            stream.stop()
        """
        with self._lock:
            self._running = False

        # Wait for the thread to exit gracefully
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        # Close WebSocket if open
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                logger.warning(
                    "alpaca_market_stream.close_error",
                    component="alpaca_market_stream",
                    exc_info=True,
                )
            finally:
                self._ws = None

        with self._lock:
            self._authenticated = False

        logger.info(
            "alpaca_market_stream.stopped",
            component="alpaca_market_stream",
            messages_received=self._messages_received,
        )

    # -----------------------------------------------------------------------
    # Symbol management: subscribe / unsubscribe
    # -----------------------------------------------------------------------

    def subscribe(self, symbols: list[str]) -> None:
        """
        Subscribe to price updates for the given symbols.

        Can be called before or after start(). Symbols are additive.
        If stream is already connected and authenticated, sends subscription
        message immediately. Otherwise, symbols are queued for subscription
        when connection is established.

        Args:
            symbols: List of ticker symbols to subscribe to (e.g. ["AAPL", "MSFT"]).

        Example:
            stream.subscribe(["AAPL", "MSFT"])
            stream.subscribe(["GOOG"])  # Adds to existing subscriptions
        """
        if not symbols:
            return

        with self._lock:
            # Add symbols to subscribed set
            before_count = len(self._subscribed_symbols)
            self._subscribed_symbols.update(s.upper() for s in symbols)
            after_count = len(self._subscribed_symbols)

            # If stream is already authenticated, send subscription message now
            if self._authenticated and self._ws is not None:
                self._send_subscription_message()

        if after_count > before_count:
            logger.info(
                "alpaca_market_stream.subscribe",
                symbols=sorted(symbols),
                total_subscribed=after_count,
                component="alpaca_market_stream",
            )

    def unsubscribe(self, symbols: list[str]) -> None:
        """
        Unsubscribe from price updates for the given symbols.

        Args:
            symbols: List of ticker symbols to unsubscribe from.

        Example:
            stream.unsubscribe(["AAPL"])
        """
        if not symbols:
            return

        with self._lock:
            before_count = len(self._subscribed_symbols)
            self._subscribed_symbols.difference_update(s.upper() for s in symbols)
            after_count = len(self._subscribed_symbols)

            # If stream is authenticated, send unsubscription message
            if self._authenticated and self._ws is not None:
                msg = {
                    "action": "unsubscribe",
                    "trades": [s.upper() for s in symbols],
                }
                try:
                    self._ws.send(json.dumps(msg))
                except Exception as exc:
                    logger.warning(
                        "alpaca_market_stream.unsubscribe_send_error",
                        error=str(exc),
                        component="alpaca_market_stream",
                        exc_info=True,
                    )

        if after_count < before_count:
            logger.info(
                "alpaca_market_stream.unsubscribe",
                symbols=sorted(symbols),
                total_subscribed=after_count,
                component="alpaca_market_stream",
            )

    # -----------------------------------------------------------------------
    # Callback management
    # -----------------------------------------------------------------------

    def register_callback(self, callback: PriceCallback) -> None:
        """
        Register a callback to receive PriceUpdate events.

        Multiple callbacks can be registered. Each receives every update.
        Callbacks are invoked in the WebSocket thread; they should be
        fast and exception-safe (exceptions are caught and logged).

        Args:
            callback: Function accepting a PriceUpdate argument.

        Example:
            def on_price(update: PriceUpdate):
                print(f"{update.symbol} @ {update.price}")

            stream.register_callback(on_price)
        """
        with self._lock:
            self._callbacks.append(callback)

        logger.debug(
            "alpaca_market_stream.callback_registered",
            callback=callback.__name__ if hasattr(callback, "__name__") else str(callback),
            component="alpaca_market_stream",
        )

    # -----------------------------------------------------------------------
    # Health / status
    # -----------------------------------------------------------------------

    def is_connected(self) -> bool:
        """
        Return True if the stream is currently connected and authenticated.

        Returns:
            True if WebSocket is open and authentication succeeded.

        Example:
            if stream.is_connected():
                print("Stream is active")
        """
        with self._lock:
            return self._authenticated and self._ws is not None

    def diagnostics(self) -> dict[str, Any]:
        """
        Return stream health diagnostics.

        Returns:
            Dict with keys:
            - connected (bool): Is WebSocket authenticated and open.
            - subscribed_symbols (list[str]): Currently subscribed symbols.
            - messages_received (int): Total trade messages received.
            - last_message_at (str | None): ISO 8601 timestamp of last message.
            - reconnect_count (int): Number of reconnection attempts.
            - uptime_seconds (int): Seconds since stream started.

        Example:
            diag = stream.diagnostics()
            print(diag["connected"], diag["messages_received"])
        """
        with self._lock:
            last_msg_str = None
            if self._last_message_at:
                last_msg_str = self._last_message_at.isoformat()

            uptime = 0
            if self._connected_at:
                uptime = int((datetime.now(tz=timezone.utc) - self._connected_at).total_seconds())

            return {
                "connected": self._authenticated and self._ws is not None,
                "subscribed_symbols": sorted(self._subscribed_symbols),
                "messages_received": self._messages_received,
                "last_message_at": last_msg_str,
                "reconnect_count": self._reconnect_count,
                "uptime_seconds": uptime,
            }

    # -----------------------------------------------------------------------
    # Internal: WebSocket loop (runs in daemon thread)
    # -----------------------------------------------------------------------

    def _run_websocket_loop(self) -> None:
        """
        Main WebSocket event loop (runs in daemon thread).

        Manages connection lifecycle: connect, authenticate, subscribe, receive
        messages, and reconnect on failure. Runs until _running is set to False.

        Does not raise; logs all errors and reconnects up to max retry limit.
        """
        reconnect_attempt = 0

        while True:
            with self._lock:
                if not self._running:
                    break

            try:
                # Attempt to establish and maintain WebSocket connection
                self._connect_and_run()
                reconnect_attempt = 0  # Reset on successful connection
            except Exception as exc:
                logger.error(
                    "alpaca_market_stream.connection_error",
                    error=str(exc),
                    reconnect_attempt=reconnect_attempt,
                    component="alpaca_market_stream",
                    exc_info=True,
                )

                with self._lock:
                    self._authenticated = False
                    if self._ws is not None:
                        with contextlib.suppress(Exception):
                            self._ws.close()
                        self._ws = None

                # Check if we should continue trying
                with self._lock:
                    if not self._running:
                        break

                # Exponential backoff
                if reconnect_attempt < len(_RECONNECT_DELAYS):
                    delay = _RECONNECT_DELAYS[reconnect_attempt]
                else:
                    delay = _RECONNECT_DELAYS[-1]

                with self._lock:
                    self._reconnect_count += 1

                logger.warning(
                    "alpaca_market_stream.reconnecting",
                    delay_seconds=delay,
                    reconnect_count=self._reconnect_count,
                    component="alpaca_market_stream",
                )

                time.sleep(delay)
                reconnect_attempt += 1

    def _connect_and_run(self) -> None:
        """
        Connect to Alpaca WebSocket and run the message receive loop.

        Raises on connection/auth failure or when _running is set to False.
        """
        # Create WebSocket connection
        url = self._config.market_data_stream_url
        self._ws = websocket.WebSocket()

        logger.info(
            "alpaca_market_stream.connecting",
            url=url,
            component="alpaca_market_stream",
        )

        try:
            self._ws.connect(
                url,
                header={"User-Agent": "FXLab-AlpacaMarketStream/1.0"},
            )
        except Exception as exc:
            raise ExternalServiceError(f"Failed to connect to Alpaca WebSocket: {exc}") from exc

        with self._lock:
            self._connected_at = datetime.now(tz=timezone.utc)

        logger.info(
            "alpaca_market_stream.connected",
            url=url,
            component="alpaca_market_stream",
        )

        # Authenticate
        auth_msg = {
            "action": "auth",
            "key": self._config.api_key,
            "secret": self._config.api_secret,
        }

        try:
            self._ws.send(json.dumps(auth_msg))
        except Exception as exc:
            raise ExternalServiceError(f"Failed to send auth message: {exc}") from exc

        # Wait for auth response
        try:
            response = self._ws.recv()
            data = json.loads(response)

            if (
                data.get("stream") == "authorization"
                and data.get("data", {}).get("status") != "authorized"
            ):
                raise ExternalServiceError(
                    f"Authorization failed: {data.get('data', {}).get('message', 'unknown error')}"
                )
        except json.JSONDecodeError as exc:
            raise ExternalServiceError(f"Invalid auth response: {exc}") from exc
        except Exception as exc:
            raise ExternalServiceError(f"Auth failed: {exc}") from exc

        with self._lock:
            self._authenticated = True

        logger.info(
            "alpaca_market_stream.authenticated",
            feed=self._config.data_feed,
            component="alpaca_market_stream",
        )

        # Subscribe to symbols
        with self._lock:
            if self._subscribed_symbols:
                self._send_subscription_message()

        # Main message receive loop
        self._receive_loop()

    def _send_subscription_message(self) -> None:
        """
        Send subscription message for current symbols (must hold lock).

        This is called while holding _lock, so we can safely access
        _subscribed_symbols and _ws.
        """
        if not self._subscribed_symbols or self._ws is None:
            return

        msg = {
            "action": "subscribe",
            "trades": sorted(self._subscribed_symbols),
        }

        try:
            self._ws.send(json.dumps(msg))
            logger.info(
                "alpaca_market_stream.subscription_sent",
                symbols=sorted(self._subscribed_symbols),
                component="alpaca_market_stream",
            )
        except Exception as exc:
            logger.warning(
                "alpaca_market_stream.subscription_send_error",
                error=str(exc),
                component="alpaca_market_stream",
                exc_info=True,
            )
            raise

    def _receive_loop(self) -> None:
        """
        Main message receive loop.

        Runs until _running is False or WebSocket closes.
        Processes trade messages and dispatches to callbacks.
        Monitors heartbeat; logs warning if no message within timeout.
        """
        self._ws.settimeout(self._timeout_config.stream_heartbeat_s)
        last_heartbeat_check = time.time()

        while True:
            with self._lock:
                if not self._running:
                    break

            try:
                # recv() blocks with timeout
                message = self._ws.recv()
                if not message:
                    break

                now = time.time()
                last_heartbeat_check = now

                # Parse and process the message
                try:
                    data = json.loads(message)
                    self._handle_message(data)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "alpaca_market_stream.invalid_message",
                        error=str(exc),
                        component="alpaca_market_stream",
                    )
            except websocket.WebSocketTimeoutException:
                # Check if we've exceeded heartbeat timeout
                now = time.time()
                elapsed = now - last_heartbeat_check
                if elapsed > self._timeout_config.stream_heartbeat_s:
                    logger.warning(
                        "alpaca_market_stream.heartbeat_timeout",
                        elapsed_seconds=elapsed,
                        timeout_seconds=self._timeout_config.stream_heartbeat_s,
                        component="alpaca_market_stream",
                    )
                    # Don't break; continue and try to reconnect naturally
            except websocket.WebSocketConnectionClosedException:
                logger.info(
                    "alpaca_market_stream.connection_closed",
                    component="alpaca_market_stream",
                )
                break
            except Exception as exc:
                logger.error(
                    "alpaca_market_stream.receive_error",
                    error=str(exc),
                    component="alpaca_market_stream",
                    exc_info=True,
                )
                break

    def _handle_message(self, data: Any) -> None:
        """
        Process a message received from Alpaca WebSocket.

        Expects either:
        - A list of trade messages: [{"T": "t", "S": "AAPL", "p": 185.50, ...}]
        - A status message: {"stream": "...", "data": {...}}

        Args:
            data: Parsed JSON message.
        """
        # Handle list of trade messages
        if isinstance(data, list):
            for msg in data:
                self._process_trade_message(msg)
            return

        # Handle status/control messages
        if isinstance(data, dict):
            stream = data.get("stream")
            if stream in ("listening", "authorization", "trades"):
                # Status message; log and ignore
                logger.debug(
                    "alpaca_market_stream.status_message",
                    stream=stream,
                    component="alpaca_market_stream",
                )
                return

            # Unknown message type
            logger.debug(
                "alpaca_market_stream.unknown_message_type",
                component="alpaca_market_stream",
            )

    def _process_trade_message(self, msg: dict[str, Any]) -> None:
        """
        Process a single trade message and dispatch to callbacks.

        Trade message format from Alpaca:
        {
            "T": "t",           # Message type: "t" for trade
            "S": "AAPL",        # Symbol
            "p": 185.50,        # Price
            "s": 100,           # Size
            "t": "2026-04-11T14:30:00Z",  # Timestamp (ISO 8601)
            "c": ["@"],         # Conditions
        }

        Args:
            msg: Trade message dict.
        """
        try:
            # Extract and validate fields
            msg_type = msg.get("T")
            if msg_type != "t":
                # Not a trade message; skip
                return

            symbol = msg.get("S", "").upper()
            price_raw = msg.get("p")
            size = msg.get("s", 0)
            timestamp_str = msg.get("t")
            conditions = msg.get("c", [])

            if not symbol or price_raw is None or timestamp_str is None:
                logger.warning(
                    "alpaca_market_stream.incomplete_trade_message",
                    component="alpaca_market_stream",
                )
                return

            # Parse price and timestamp
            try:
                price = Decimal(str(price_raw))
                timestamp = self._parse_timestamp(timestamp_str)
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "alpaca_market_stream.parse_error",
                    error=str(exc),
                    component="alpaca_market_stream",
                )
                return

            # Create PriceUpdate contract
            update = PriceUpdate(
                symbol=symbol,
                price=price,
                size=int(size) if size else 0,
                timestamp=timestamp,
                feed=self._config.data_feed,
                conditions=conditions,
            )

            # Update diagnostics
            with self._lock:
                self._messages_received += 1
                self._last_message_at = datetime.now(tz=timezone.utc)

            logger.debug(
                "alpaca_market_stream.trade_received",
                symbol=symbol,
                price=str(price),
                size=size,
                component="alpaca_market_stream",
            )

            # Dispatch to all callbacks
            with self._lock:
                callbacks = list(self._callbacks)

            for callback in callbacks:
                try:
                    callback(update)
                except Exception as exc:
                    logger.error(
                        "alpaca_market_stream.callback_error",
                        callback=callback.__name__
                        if hasattr(callback, "__name__")
                        else str(callback),
                        error=str(exc),
                        component="alpaca_market_stream",
                        exc_info=True,
                    )
                    # Continue dispatching to other callbacks

        except Exception as exc:
            logger.error(
                "alpaca_market_stream.trade_processing_error",
                error=str(exc),
                component="alpaca_market_stream",
                exc_info=True,
            )

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        """
        Parse an ISO 8601 timestamp string from Alpaca.

        Alpaca uses 'Z' suffix for UTC timestamps. This method normalizes
        and parses the timestamp into a timezone-aware datetime.

        Args:
            value: ISO 8601 timestamp string (e.g. "2026-04-11T14:30:00Z").

        Returns:
            datetime instance with UTC timezone.

        Raises:
            ValueError: If timestamp cannot be parsed.

        Example:
            dt = AlpacaMarketStream._parse_timestamp("2026-04-11T14:30:00Z")
            # dt.tzinfo == timezone.utc
        """
        if not value:
            raise ValueError("Empty timestamp")

        # Alpaca uses 'Z' suffix; Python's fromisoformat() doesn't accept it pre-3.11
        # Normalize to '+00:00' format
        normalized = value.rstrip("Z") + "+00:00" if value.endswith("Z") else value

        try:
            return datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"Cannot parse timestamp '{value}': {exc}") from exc
