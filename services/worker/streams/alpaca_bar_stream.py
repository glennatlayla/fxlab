"""
Alpaca real-time bar (candle) WebSocket stream adapter — Phase 7 M3.

Responsibilities:
- Connect to Alpaca's real-time market data WebSocket for bar streaming.
- Authenticate with API key/secret via the Alpaca auth protocol.
- Subscribe to 1-minute bar updates for configured symbols.
- Normalize incoming bar messages into Candle contracts.
- Persist received candles via the market data repository (with timeout).
- Dispatch Candle events to registered callbacks.
- Reconnect with exponential backoff and circuit breaker on disconnect.
- Monitor heartbeat and trigger reconnect on data silence.
- Deduplicate bars to prevent replay bugs on reconnect.

Does NOT:
- Handle trade-level data (use AlpacaMarketStream for that).
- Contain business logic or risk management.
- Know about order management.
- Aggregate or resample bars (Alpaca provides pre-aggregated 1-min bars).

Dependencies:
- websocket-client: Synchronous WebSocket library (daemon thread).
- libs.contracts.alpaca_config.AlpacaConfig: API credentials and URLs.
- libs.contracts.market_data.Candle, CandleInterval: output contract.
- libs.contracts.interfaces.market_data_repository: persistence port.
- libs.contracts.interfaces.bar_stream_interface: BarStreamInterface port.
- structlog: Structured logging.

Error conditions:
- ExternalServiceError: Connection or authentication failures.
- CircuitBreakerOpenError: Circuit breaker tripped after repeated failures.
- Transient failures on disconnect: automatic reconnect with backoff.
- Bad callbacks: individual callback exceptions logged but do not kill the stream.
- Repository timeout: candle not persisted, but still dispatched to callbacks.

Example:
    from libs.contracts.alpaca_config import AlpacaConfig

    config = AlpacaConfig.paper(api_key="AK...", api_secret="...")
    stream = AlpacaBarStream(config=config, market_data_repo=repo)
    stream.register_bar_callback(lambda candle: broadcast(candle))
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
from collections import OrderedDict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog
import websocket

from libs.contracts.alpaca_config import AlpacaConfig
from libs.contracts.errors import ExternalServiceError
from libs.contracts.interfaces.bar_stream_interface import (
    BarCallback,
    BarStreamInterface,
)
from libs.contracts.interfaces.market_data_repository import (
    MarketDataRepositoryInterface,
)
from libs.contracts.market_data import Candle, CandleInterval

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Reconnect backoff
_INITIAL_BACKOFF_S = 1.0
_MAX_BACKOFF_S = 60.0
_BACKOFF_MULTIPLIER = 2.0

# Circuit breaker
_CIRCUIT_BREAKER_THRESHOLD = 5  # consecutive failures before tripping
_CIRCUIT_BREAKER_RECOVERY_S = 300.0  # 5 minutes before auto-reset attempt

# Repository persistence
_REPO_TIMEOUT_S = 2.0  # max seconds to wait for upsert_candles

# Bar deduplication
_DEDUP_CACHE_MAX_SIZE = 2000  # recent (symbol, interval, timestamp) tuples


class CircuitBreakerOpenError(ExternalServiceError):
    """
    Raised when the circuit breaker is open after repeated connection failures.

    The stream will not attempt further reconnections until the recovery
    period elapses or the circuit is manually reset.

    Example:
        try:
            stream.start()
        except CircuitBreakerOpenError:
            logger.critical("Bar stream circuit breaker is open")
    """


class AlpacaBarStream(BarStreamInterface):
    """
    Alpaca real-time bar stream over WebSocket.

    Connects to Alpaca's market data streaming WebSocket and subscribes
    to the ``bars`` channel for 1-minute OHLCV candle updates. Incoming
    bars are normalized to the Candle contract, persisted to the market
    data repository, and dispatched to registered callbacks.

    Production safeguards:
    - Heartbeat watchdog: forces reconnect if no data received within
      heartbeat_timeout_s (detects stale-but-connected feeds).
    - Circuit breaker: after _CIRCUIT_BREAKER_THRESHOLD consecutive
      failures, stops reconnection attempts and logs CRITICAL.
      Auto-recovers after _CIRCUIT_BREAKER_RECOVERY_S, or call
      reset_circuit() for manual recovery.
    - Repository timeout: upsert_candles() calls are guarded by a
      _REPO_TIMEOUT_S deadline to prevent database latency from
      blocking the stream.
    - Bar deduplication: recently-seen (symbol, interval, timestamp)
      tuples are tracked to prevent duplicate callback dispatch
      on reconnect replay.
    - Thread shutdown: uses threading.Event for cooperative cancellation,
      verifies thread exit, and logs CRITICAL if join times out.

    Responsibilities:
    - Authenticate via Alpaca key/secret on the WebSocket connection.
    - Subscribe to the ``bars`` channel (not ``trades``).
    - Normalize Alpaca bar JSON into Candle contracts.
    - Persist candles via repository (if provided, with timeout).
    - Dispatch to registered callbacks (errors in one callback do not
      affect others).
    - Reconnect with exponential backoff and circuit breaker.
    - Track diagnostics (bars received, reconnect count, uptime).

    Does NOT:
    - Handle trade-level or quote-level data.
    - Aggregate or resample bars.
    - Contain business logic.

    Dependencies:
    - AlpacaConfig (injected): API credentials and stream URL.
    - MarketDataRepositoryInterface (injected, optional): candle persistence.

    Example:
        stream = AlpacaBarStream(config=config, market_data_repo=repo)
        stream.register_bar_callback(my_handler)
        stream.subscribe(["AAPL"])
        stream.start()
    """

    def __init__(
        self,
        *,
        config: AlpacaConfig,
        market_data_repo: MarketDataRepositoryInterface | None = None,
        heartbeat_timeout_s: float = 60.0,
        repo_timeout_s: float = _REPO_TIMEOUT_S,
    ) -> None:
        """
        Initialize the Alpaca bar stream.

        Args:
            config: Alpaca API configuration with credentials.
            market_data_repo: Optional repository for persisting received candles.
            heartbeat_timeout_s: Seconds without data before triggering reconnect.
                Set to 0 to disable heartbeat monitoring.
            repo_timeout_s: Max seconds to wait for repository upsert_candles().

        Example:
            stream = AlpacaBarStream(config=config, heartbeat_timeout_s=60)
        """
        self._config = config
        self._market_data_repo = market_data_repo
        self._heartbeat_timeout_s = heartbeat_timeout_s
        self._repo_timeout_s = repo_timeout_s

        # Thread-safe state (§0.6: all shared mutable state under lock)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._callbacks: list[BarCallback] = []
        self._subscribed_symbols: set[str] = set()
        self._running = False
        self._connected = False

        # Diagnostics counters (protected by _lock)
        self._bars_received = 0
        self._bars_deduplicated = 0
        self._reconnect_count = 0
        self._errors = 0
        self._repo_timeouts = 0
        self._started_at: float | None = None
        self._last_data_at: float | None = None  # monotonic clock for heartbeat
        self._last_bar_at: datetime | None = None  # wall-clock for diagnostics

        # Circuit breaker state (protected by _lock)
        self._consecutive_failures = 0
        self._circuit_open = False
        self._circuit_opened_at: float | None = None

        # Bar deduplication LRU cache (protected by _lock)
        # Key: (symbol, interval, timestamp_iso) -> True
        self._dedup_cache: OrderedDict[tuple[str, str, str], bool] = OrderedDict()

        # WebSocket and thread references
        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public interface (BarStreamInterface)
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the bar stream in a background daemon thread.

        Connects to Alpaca's WebSocket endpoint and begins receiving bar
        data. Subscribes to any previously registered symbols. Also starts
        a heartbeat watchdog thread that monitors data freshness.

        Raises:
            ExternalServiceError: If already running.
            CircuitBreakerOpenError: If circuit breaker is open.

        Example:
            stream.start()
        """
        with self._lock:
            if self._running:
                raise ExternalServiceError("Bar stream is already running")
            if self._circuit_open:
                elapsed = time.monotonic() - (self._circuit_opened_at or 0)
                if elapsed < _CIRCUIT_BREAKER_RECOVERY_S:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker is open — tripped {elapsed:.0f}s ago after "
                        f"{_CIRCUIT_BREAKER_THRESHOLD} consecutive failures. "
                        f"Auto-recovery in {_CIRCUIT_BREAKER_RECOVERY_S - elapsed:.0f}s "
                        f"or call reset_circuit()."
                    )
                # Recovery period elapsed — auto-reset
                self._circuit_open = False
                self._consecutive_failures = 0
                logger.info(
                    "Circuit breaker auto-reset after recovery period",
                    extra={
                        "operation": "start",
                        "component": "AlpacaBarStream",
                    },
                )
            self._running = True
            self._started_at = time.monotonic()
            self._stop_event.clear()

        logger.info(
            "Bar stream starting",
            extra={
                "operation": "start",
                "component": "AlpacaBarStream",
                "symbols": sorted(self._subscribed_symbols),
                "heartbeat_timeout_s": self._heartbeat_timeout_s,
            },
        )

        self._thread = threading.Thread(
            target=self._run_loop,
            name="alpaca-bar-stream",
            daemon=True,
        )
        self._thread.start()

        # Start heartbeat watchdog if enabled
        if self._heartbeat_timeout_s > 0:
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_watchdog,
                name="alpaca-bar-heartbeat",
                daemon=True,
            )
            self._heartbeat_thread.start()

    def stop(self) -> None:
        """
        Stop the bar stream and close the WebSocket.

        Uses threading.Event for cooperative cancellation. Verifies
        thread exit and logs CRITICAL if join times out.

        Idempotent — safe to call multiple times.

        Example:
            stream.stop()
        """
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._connected = False

        # Signal all threads to stop
        self._stop_event.set()

        # Close the WebSocket if it's open
        if self._ws is not None:
            with contextlib.suppress(Exception):
                self._ws.close()

        # Wait for the main thread to finish
        join_timeout = 10.0
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=join_timeout)
            if self._thread.is_alive():
                logger.critical(
                    "Bar stream thread did not exit within timeout — possible resource leak",
                    extra={
                        "operation": "stop",
                        "component": "AlpacaBarStream",
                        "join_timeout_s": join_timeout,
                    },
                )

        # Wait for heartbeat thread
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=5.0)

        logger.info(
            "Bar stream stopped",
            extra={
                "operation": "stop",
                "component": "AlpacaBarStream",
                "bars_received": self._bars_received,
            },
        )

    def subscribe(self, symbols: list[str]) -> None:
        """
        Subscribe to bar updates for the given symbols.

        Symbols are normalized to uppercase and added to the subscription
        set. If the stream is already connected, sends a subscribe message
        immediately.

        Args:
            symbols: Ticker symbols to subscribe to (e.g. ["AAPL", "MSFT"]).

        Example:
            stream.subscribe(["AAPL", "MSFT"])
        """
        normalized = {s.upper().strip() for s in symbols if s.strip()}
        if not normalized:
            return

        with self._lock:
            self._subscribed_symbols |= normalized

        # If connected, send subscribe message now
        if self._ws is not None and self._connected:
            self._send_subscribe()

        logger.debug(
            "Bar stream symbols subscribed",
            extra={
                "operation": "subscribe",
                "component": "AlpacaBarStream",
                "symbols": sorted(normalized),
            },
        )

    def unsubscribe(self, symbols: list[str]) -> None:
        """
        Unsubscribe from bar updates for the given symbols.

        Args:
            symbols: Ticker symbols to unsubscribe from.

        Example:
            stream.unsubscribe(["MSFT"])
        """
        normalized = {s.upper().strip() for s in symbols if s.strip()}
        if not normalized:
            return

        with self._lock:
            self._subscribed_symbols -= normalized

        if self._ws is not None and self._connected:
            msg = {
                "action": "unsubscribe",
                "bars": sorted(normalized),
            }
            try:
                self._ws.send(json.dumps(msg))
            except Exception as exc:
                logger.warning(
                    "Bar stream unsubscribe send error",
                    extra={
                        "operation": "unsubscribe",
                        "component": "AlpacaBarStream",
                        "error": str(exc),
                    },
                )

    def register_bar_callback(self, callback: BarCallback) -> None:
        """
        Register a callback to receive Candle events.

        Thread-safe. Multiple callbacks can be registered. Callbacks should
        be registered before start() is called — callbacks added while the
        stream is running may miss bars that are currently being dispatched.

        Args:
            callback: Function accepting a Candle argument.

        Example:
            stream.register_bar_callback(lambda c: print(c.close))
        """
        with self._lock:
            self._callbacks.append(callback)

    def is_connected(self) -> bool:
        """
        Return True if the stream is connected and authenticated.

        Returns:
            Connection status.
        """
        with self._lock:
            return self._connected

    def diagnostics(self) -> dict[str, Any]:
        """
        Return stream health diagnostics.

        Returns:
            Dict with connection status, subscription info, counters,
            circuit breaker state, and timing information.

        Example:
            diag = stream.diagnostics()
            # {"connected": True, "bars_received": 42, ...}
        """
        with self._lock:
            uptime = 0.0
            if self._started_at is not None:
                uptime = time.monotonic() - self._started_at

            last_data_age_s: float | None = None
            if self._last_data_at is not None:
                last_data_age_s = round(time.monotonic() - self._last_data_at, 1)

            return {
                "connected": self._connected,
                "subscribed_symbols": sorted(self._subscribed_symbols),
                "bars_received": self._bars_received,
                "bars_deduplicated": self._bars_deduplicated,
                "last_bar_at": (self._last_bar_at.isoformat() if self._last_bar_at else None),
                "last_data_age_seconds": last_data_age_s,
                "reconnect_count": self._reconnect_count,
                "errors": self._errors,
                "repo_timeouts": self._repo_timeouts,
                "uptime_seconds": round(uptime, 1),
                "circuit_breaker_open": self._circuit_open,
                "consecutive_failures": self._consecutive_failures,
            }

    def reset_circuit(self) -> None:
        """
        Manually reset the circuit breaker.

        Use this when an operator has confirmed the broker is available
        again and wants to force a reconnection attempt.

        Example:
            stream.reset_circuit()
            stream.start()
        """
        with self._lock:
            self._circuit_open = False
            self._consecutive_failures = 0
            self._circuit_opened_at = None

        logger.info(
            "Circuit breaker manually reset",
            extra={
                "operation": "reset_circuit",
                "component": "AlpacaBarStream",
            },
        )

    # ------------------------------------------------------------------
    # Private: Heartbeat watchdog
    # ------------------------------------------------------------------

    def _heartbeat_watchdog(self) -> None:
        """
        Background thread that monitors data freshness.

        If no bar data has been received within heartbeat_timeout_s while
        the stream is connected, forces a reconnect by closing the
        WebSocket. This detects stale-but-connected feeds where Alpaca
        stops sending data without closing the connection.

        Checks every heartbeat_timeout_s / 3 seconds for responsiveness.
        """
        check_interval = max(self._heartbeat_timeout_s / 3.0, 1.0)

        while not self._stop_event.wait(timeout=check_interval):
            with self._lock:
                if not self._running:
                    break
                if not self._connected:
                    continue
                if self._last_data_at is None:
                    # Haven't received first bar yet — allow extra time
                    continue

                age = time.monotonic() - self._last_data_at

            if age > self._heartbeat_timeout_s:
                logger.warning(
                    "Heartbeat timeout — no data received, forcing reconnect",
                    extra={
                        "operation": "_heartbeat_watchdog",
                        "component": "AlpacaBarStream",
                        "last_data_age_s": round(age, 1),
                        "heartbeat_timeout_s": self._heartbeat_timeout_s,
                    },
                )
                # Force reconnect by closing WebSocket
                if self._ws is not None:
                    with contextlib.suppress(Exception):
                        self._ws.close()

    # ------------------------------------------------------------------
    # Private: WebSocket lifecycle
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """
        Main reconnect loop running in a daemon thread.

        Connects to the Alpaca WebSocket and enters the receive loop.
        On disconnect, waits with exponential backoff and retries.
        Circuit breaker trips after _CIRCUIT_BREAKER_THRESHOLD consecutive
        failures. Exits when stop_event is set or circuit breaker trips.
        """
        backoff = _INITIAL_BACKOFF_S

        while not self._stop_event.is_set():
            with self._lock:
                if not self._running:
                    break
                if self._circuit_open:
                    break

            try:
                self._connect_and_run()
                # Successful connection resets backoff and failure counter
                backoff = _INITIAL_BACKOFF_S
                with self._lock:
                    self._consecutive_failures = 0
            except ExternalServiceError:
                # Fatal errors (auth failure) — don't retry
                with self._lock:
                    self._running = False
                break
            except Exception as exc:
                with self._lock:
                    self._connected = False
                    self._reconnect_count += 1
                    self._consecutive_failures += 1

                    if self._consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD:
                        self._circuit_open = True
                        self._circuit_opened_at = time.monotonic()
                        self._running = False
                        logger.critical(
                            "Circuit breaker OPEN — bar stream stopped after "
                            f"{_CIRCUIT_BREAKER_THRESHOLD} consecutive failures. "
                            "Operator intervention required: call reset_circuit() "
                            "or wait for auto-recovery.",
                            extra={
                                "operation": "_run_loop",
                                "component": "AlpacaBarStream",
                                "consecutive_failures": self._consecutive_failures,
                                "last_error": str(exc),
                                "recovery_s": _CIRCUIT_BREAKER_RECOVERY_S,
                            },
                        )
                        break

                logger.warning(
                    "Bar stream connection failed, will retry",
                    extra={
                        "operation": "_run_loop",
                        "component": "AlpacaBarStream",
                        "error": str(exc),
                        "backoff_s": backoff,
                        "consecutive_failures": self._consecutive_failures,
                    },
                )

            if self._stop_event.is_set():
                break

            # Exponential backoff — interruptible via stop_event
            self._stop_event.wait(timeout=backoff)
            backoff = min(backoff * _BACKOFF_MULTIPLIER, _MAX_BACKOFF_S)

    def _connect_and_run(self) -> None:
        """
        Create WebSocket connection, authenticate, subscribe, and receive.

        This method blocks until the WebSocket disconnects or an error
        occurs. Uses websocket-client's run_forever with ping/pong for
        keepalive.

        Raises:
            ExternalServiceError: On authentication failure.
        """
        url = self._config.market_data_stream_url
        logger.info(
            "Bar stream connecting",
            extra={
                "operation": "_connect_and_run",
                "component": "AlpacaBarStream",
                "url": url,
            },
        )

        self._ws = websocket.WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        # run_forever blocks until the connection closes
        self._ws.run_forever(
            ping_interval=30,
            ping_timeout=10,
        )

    def _on_open(self, ws: Any) -> None:
        """Handle WebSocket connection opened — send authentication."""
        logger.debug(
            "Bar stream WebSocket opened, authenticating",
            extra={
                "operation": "_on_open",
                "component": "AlpacaBarStream",
            },
        )
        auth_msg = {
            "action": "auth",
            "key": self._config.api_key,
            "secret": self._config.api_secret,
        }
        ws.send(json.dumps(auth_msg))

    def _on_message(self, ws: Any, message: str) -> None:
        """
        Handle incoming WebSocket messages.

        Updates the heartbeat timestamp on every message (including control
        messages) to detect stale feeds. Routes messages by type.

        Message types from Alpaca:
        - [{"T": "success", "msg": "connected"}] — connection ack
        - [{"T": "success", "msg": "authenticated"}] — auth ack
        - [{"T": "b", ...}] — bar data
        - [{"T": "subscription", ...}] — subscription confirmation
        - [{"T": "error", ...}] — error messages

        Args:
            ws: WebSocket connection.
            message: Raw JSON message string.
        """
        # Update heartbeat on every message
        with self._lock:
            self._last_data_at = time.monotonic()

        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning(
                "Bar stream received non-JSON message",
                extra={
                    "operation": "_on_message",
                    "component": "AlpacaBarStream",
                },
            )
            return

        # Alpaca sends arrays of messages
        if not isinstance(data, list):
            data = [data]

        for msg in data:
            msg_type = msg.get("T", "")

            if msg_type == "success":
                self._handle_success(msg)
            elif msg_type == "b":
                self._process_bar_message(msg)
            elif msg_type == "subscription":
                logger.debug(
                    "Bar stream subscription confirmed",
                    extra={
                        "operation": "_on_message",
                        "component": "AlpacaBarStream",
                        "bars": msg.get("bars", []),
                    },
                )
            elif msg_type == "error":
                self._handle_error(msg)

    def _on_error(self, ws: Any, error: Exception) -> None:
        """Handle WebSocket error."""
        with self._lock:
            self._errors += 1

        logger.warning(
            "Bar stream WebSocket error",
            extra={
                "operation": "_on_error",
                "component": "AlpacaBarStream",
                "error": str(error),
            },
        )

    def _on_close(self, ws: Any, close_status_code: int | None, close_msg: str | None) -> None:
        """Handle WebSocket connection closed."""
        with self._lock:
            self._connected = False

        logger.info(
            "Bar stream WebSocket closed",
            extra={
                "operation": "_on_close",
                "component": "AlpacaBarStream",
                "status_code": close_status_code,
                "close_msg": close_msg,
            },
        )

    # ------------------------------------------------------------------
    # Private: Message processing
    # ------------------------------------------------------------------

    def _handle_success(self, msg: dict[str, Any]) -> None:
        """
        Handle Alpaca success messages (connected, authenticated).

        On authentication success, marks as connected, resets the
        heartbeat timer, and sends the subscribe message for all
        registered symbols.

        Args:
            msg: Alpaca success message dict.
        """
        success_msg = msg.get("msg", "")

        if success_msg == "authenticated":
            with self._lock:
                self._connected = True
                self._last_data_at = time.monotonic()

            logger.info(
                "Bar stream authenticated",
                extra={
                    "operation": "_handle_success",
                    "component": "AlpacaBarStream",
                },
            )
            self._send_subscribe()

        elif success_msg == "connected":
            logger.debug(
                "Bar stream connected to Alpaca",
                extra={
                    "operation": "_handle_success",
                    "component": "AlpacaBarStream",
                },
            )

    def _handle_error(self, msg: dict[str, Any]) -> None:
        """
        Handle Alpaca error messages.

        Auth failure (code 402) is fatal — raises ExternalServiceError
        which will be caught by _run_loop and stop the stream without
        further retry.

        Args:
            msg: Alpaca error message dict.
        """
        error_code = msg.get("code", 0)
        error_msg = msg.get("msg", "unknown error")

        with self._lock:
            self._errors += 1

        logger.error(
            "Bar stream received error from Alpaca",
            extra={
                "operation": "_handle_error",
                "component": "AlpacaBarStream",
                "error_code": error_code,
                "error_msg": error_msg,
            },
        )

        # Auth failure (code 402) — fatal, do not reconnect
        if error_code == 402:
            raise ExternalServiceError(f"Alpaca bar stream authentication failed: {error_msg}")

    def _process_bar_message(self, msg: dict[str, Any]) -> None:
        """
        Process an Alpaca bar message: parse, dedup, persist, dispatch.

        Steps:
        1. Parse raw JSON into a Candle contract.
        2. Check deduplication cache — skip if already seen.
        3. Persist to repository (with timeout) if available.
        4. Dispatch to all registered callbacks.

        Args:
            msg: Alpaca bar message dict.
        """
        try:
            candle = self._parse_bar(msg)
        except Exception as exc:
            logger.warning(
                "Bar stream failed to parse bar message",
                extra={
                    "operation": "_process_bar_message",
                    "component": "AlpacaBarStream",
                    "error": str(exc),
                    "symbol": msg.get("S", "unknown"),
                },
            )
            with self._lock:
                self._errors += 1
            return

        # Deduplication check
        dedup_key = (candle.symbol, candle.interval.value, candle.timestamp.isoformat())
        with self._lock:
            if dedup_key in self._dedup_cache:
                self._bars_deduplicated += 1
                logger.debug(
                    "Bar stream duplicate bar skipped",
                    extra={
                        "operation": "_process_bar_message",
                        "component": "AlpacaBarStream",
                        "symbol": candle.symbol,
                        "timestamp": candle.timestamp.isoformat(),
                    },
                )
                return

            # Add to dedup cache (LRU eviction)
            self._dedup_cache[dedup_key] = True
            if len(self._dedup_cache) > _DEDUP_CACHE_MAX_SIZE:
                self._dedup_cache.popitem(last=False)

            # Update diagnostics
            self._bars_received += 1
            self._last_bar_at = candle.timestamp

        # Persist to repository if available (with timeout)
        if self._market_data_repo is not None:
            self._persist_candle(candle)

        # Dispatch to callbacks — errors in one must not affect others
        with self._lock:
            callbacks = list(self._callbacks)

        for cb in callbacks:
            try:
                cb(candle)
            except Exception as exc:
                logger.warning(
                    "Bar stream callback error",
                    extra={
                        "operation": "_process_bar_message",
                        "component": "AlpacaBarStream",
                        "callback": getattr(cb, "__name__", str(cb)),
                        "error": str(exc),
                    },
                )

    def _persist_candle(self, candle: Candle) -> None:
        """
        Persist a candle to the repository with a timeout guard.

        If the repository call takes longer than _repo_timeout_s, the
        call is abandoned and the bar is still dispatched to callbacks.
        This prevents database latency from blocking the stream.

        Args:
            candle: The Candle to persist.
        """
        result_holder: list[Exception | None] = [None]
        completed = threading.Event()

        def _do_upsert() -> None:
            try:
                assert self._market_data_repo is not None  # noqa: S101
                self._market_data_repo.upsert_candles([candle])
            except Exception as exc:
                result_holder[0] = exc
            finally:
                completed.set()

        upsert_thread = threading.Thread(
            target=_do_upsert,
            name="bar-stream-upsert",
            daemon=True,
        )
        upsert_thread.start()

        if not completed.wait(timeout=self._repo_timeout_s):
            with self._lock:
                self._repo_timeouts += 1
            logger.error(
                "Repository upsert timed out — candle not persisted",
                extra={
                    "operation": "_persist_candle",
                    "component": "AlpacaBarStream",
                    "symbol": candle.symbol,
                    "timeout_s": self._repo_timeout_s,
                },
            )
            return

        if result_holder[0] is not None:
            logger.warning(
                "Bar stream failed to persist candle",
                extra={
                    "operation": "_persist_candle",
                    "component": "AlpacaBarStream",
                    "symbol": candle.symbol,
                    "error": str(result_holder[0]),
                },
            )

    @staticmethod
    def _parse_bar(msg: dict[str, Any]) -> Candle:
        """
        Parse an Alpaca bar JSON message into a Candle contract.

        Args:
            msg: Raw Alpaca bar message with fields: S, o, h, l, c, v, t, n, vw.

        Returns:
            Candle with CandleInterval.M1 (Alpaca streams 1-min bars).

        Raises:
            ValueError: If required fields are missing or malformed.
            InvalidOperation: If price values cannot be parsed as Decimal.

        Example:
            candle = AlpacaBarStream._parse_bar({"S": "AAPL", "o": 150.0, ...})
        """
        symbol = msg.get("S")
        if not symbol:
            raise ValueError("Bar message missing symbol (S)")

        timestamp_str = msg.get("t")
        if not timestamp_str:
            raise ValueError("Bar message missing timestamp (t)")

        # Parse ISO 8601 timestamp
        ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        # Parse OHLCV values
        open_val = Decimal(str(msg.get("o", 0)))
        high_val = Decimal(str(msg.get("h", 0)))
        low_val = Decimal(str(msg.get("l", 0)))
        close_val = Decimal(str(msg.get("c", 0)))
        volume = int(msg.get("v", 0))

        # Optional fields
        vwap = None
        if "vw" in msg and msg["vw"] is not None:
            with contextlib.suppress(InvalidOperation, ValueError):
                vwap = Decimal(str(msg["vw"]))

        trade_count = msg.get("n")
        if trade_count is not None:
            trade_count = int(trade_count)

        return Candle(
            symbol=symbol.upper(),
            interval=CandleInterval.M1,
            open=open_val,
            high=high_val,
            low=low_val,
            close=close_val,
            volume=volume,
            vwap=vwap,
            trade_count=trade_count,
            timestamp=ts,
        )

    def _send_subscribe(self) -> None:
        """
        Send the bar subscription message for all registered symbols.

        Thread-safe — reads subscribed symbols under lock.
        """
        with self._lock:
            symbols = sorted(self._subscribed_symbols)

        if not symbols or self._ws is None:
            return

        msg = {
            "action": "subscribe",
            "bars": symbols,
        }

        try:
            self._ws.send(json.dumps(msg))
            logger.info(
                "Bar stream subscription sent",
                extra={
                    "operation": "_send_subscribe",
                    "component": "AlpacaBarStream",
                    "symbols": symbols,
                },
            )
        except Exception as exc:
            logger.warning(
                "Bar stream subscribe send error",
                extra={
                    "operation": "_send_subscribe",
                    "component": "AlpacaBarStream",
                    "error": str(exc),
                },
            )
