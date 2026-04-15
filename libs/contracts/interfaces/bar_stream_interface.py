"""
Bar-level market data stream interface (port) — Phase 7 M3.

Responsibilities:
- Define the abstract contract for real-time bar/candle streaming.
- Support subscribing to bar updates for multiple symbols.
- Support registering callbacks for bar delivery.
- Define lifecycle methods (start, stop, health check).

Does NOT:
- Implement WebSocket logic or broker-specific protocols.
- Manage reconnection strategies (implementation detail).
- Contain business logic.
- Know about order management or trading.

Dependencies:
- libs.contracts.market_data.Candle: the bar data contract.

Error conditions:
- ExternalServiceError: on connection failures (implementation raises).

Example:
    stream: BarStreamInterface = AlpacaBarStream(config=config)
    stream.register_bar_callback(my_candle_handler)
    stream.subscribe(["AAPL", "MSFT"])
    stream.start()
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from libs.contracts.market_data import Candle

# Type alias for bar/candle update callback functions
BarCallback = Callable[[Candle], None]


class BarStreamInterface(ABC):
    """
    Port interface for real-time bar (candle) streaming.

    Responsibilities:
    - Connect to a market data bar stream and receive OHLCV candle updates.
    - Dispatch normalized Candle events to registered callbacks.
    - Manage connection lifecycle (start, stop, reconnect).
    - Report stream health via diagnostics.

    Does NOT:
    - Persist candle data (callback consumers decide).
    - Contain order management or trading logic.
    - Know about specific broker protocols.

    Example:
        stream = SomeBrokerBarStream(config=config)
        stream.register_bar_callback(lambda candle: persist(candle))
        stream.subscribe(["AAPL", "MSFT"])
        stream.start()
        # ... later ...
        stream.stop()
    """

    @abstractmethod
    def start(self) -> None:
        """
        Start the bar data stream connection.

        Begins the WebSocket connection in a background thread.
        Subscribes to any previously registered symbols.

        Raises:
            ExternalServiceError: If initial connection fails.
        """
        ...

    @abstractmethod
    def stop(self) -> None:
        """
        Stop the bar data stream and close the connection.

        Idempotent. Does not raise on errors.
        """
        ...

    @abstractmethod
    def subscribe(self, symbols: list[str]) -> None:
        """
        Subscribe to bar updates for the given symbols.

        Can be called before or after start(). Symbols are additive.

        Args:
            symbols: List of ticker symbols to subscribe to.
        """
        ...

    @abstractmethod
    def unsubscribe(self, symbols: list[str]) -> None:
        """
        Unsubscribe from bar updates for the given symbols.

        Args:
            symbols: List of ticker symbols to unsubscribe from.
        """
        ...

    @abstractmethod
    def register_bar_callback(self, callback: BarCallback) -> None:
        """
        Register a callback to receive Candle events.

        Multiple callbacks can be registered. Each receives every bar update.

        Args:
            callback: Function accepting a Candle argument.
        """
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the stream is connected and receiving bar data."""
        ...

    @abstractmethod
    def diagnostics(self) -> dict[str, Any]:
        """
        Return stream health diagnostics.

        Returns:
            Dict with keys: connected, subscribed_symbols, bars_received,
            last_bar_at, reconnect_count, uptime_seconds, errors.
        """
        ...
