"""
Market data stream interface (port).

Responsibilities:
- Define the abstract contract for real-time market data streaming.
- Support subscribing to trade updates for multiple symbols.
- Support registering callbacks for price update delivery.
- Define lifecycle methods (start, stop, health check).

Does NOT:
- Implement WebSocket logic or broker-specific protocols.
- Manage reconnection strategies (implementation detail).
- Contain business logic.

Dependencies:
- None (pure interface).

Example:
    stream: MarketStreamInterface = AlpacaMarketStream(config=config)
    stream.register_callback(my_price_handler)
    stream.subscribe(["AAPL", "MSFT"])
    stream.start()
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from libs.contracts.execution import PriceUpdate

# Type alias for price update callback functions
PriceCallback = Callable[[PriceUpdate], None]


class MarketStreamInterface(ABC):
    """
    Port interface for real-time market data streaming.

    Responsibilities:
    - Connect to a market data stream and receive trade/quote updates.
    - Dispatch normalized PriceUpdate events to registered callbacks.
    - Manage connection lifecycle (start, stop, reconnect).
    - Report stream health via diagnostics.

    Does NOT:
    - Persist price data (callback consumers decide).
    - Contain order management or trading logic.
    - Know about specific broker protocols.

    Example:
        stream = SomeBrokerMarketStream(config=config)
        stream.register_callback(lambda update: print(update.price))
        stream.subscribe(["AAPL", "MSFT"])
        stream.start()
        # ... later ...
        stream.stop()
    """

    @abstractmethod
    def start(self) -> None:
        """
        Start the market data stream connection.

        Begins the WebSocket connection in a background thread.
        Subscribes to any previously registered symbols.

        Raises:
            ExternalServiceError: If initial connection fails.
        """
        ...

    @abstractmethod
    def stop(self) -> None:
        """
        Stop the market data stream and close the connection.

        Idempotent. Does not raise on errors.
        """
        ...

    @abstractmethod
    def subscribe(self, symbols: list[str]) -> None:
        """
        Subscribe to price updates for the given symbols.

        Can be called before or after start(). Symbols are additive.

        Args:
            symbols: List of ticker symbols to subscribe to.
        """
        ...

    @abstractmethod
    def unsubscribe(self, symbols: list[str]) -> None:
        """
        Unsubscribe from price updates for the given symbols.

        Args:
            symbols: List of ticker symbols to unsubscribe from.
        """
        ...

    @abstractmethod
    def register_callback(self, callback: PriceCallback) -> None:
        """
        Register a callback to receive PriceUpdate events.

        Multiple callbacks can be registered. Each receives every update.

        Args:
            callback: Function accepting a PriceUpdate argument.
        """
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the stream is currently connected and receiving data."""
        ...

    @abstractmethod
    def diagnostics(self) -> dict[str, Any]:
        """
        Return stream health diagnostics.

        Returns:
            Dict with keys: connected, subscribed_symbols, messages_received,
            last_message_at, reconnect_count, errors.
        """
        ...
