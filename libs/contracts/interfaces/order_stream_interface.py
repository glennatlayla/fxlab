"""
Order update stream interface (port).

Responsibilities:
- Define the abstract contract for real-time order update streaming.
- Support registering callbacks for order lifecycle event delivery.
- Define lifecycle methods (start, stop, health check).

Does NOT:
- Implement WebSocket logic or broker-specific protocols.
- Persist order events directly (callback consumers handle that).
- Update order status in repositories (service layer responsibility).
- Contain business logic.

Dependencies:
- None (pure interface).

Example:
    stream: OrderStreamInterface = AlpacaOrderStream(config=config)
    stream.register_callback(my_event_handler)
    stream.start()
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from libs.contracts.execution import OrderEvent

# Type alias for order event callback functions
OrderEventCallback = Callable[[OrderEvent], None]


class OrderStreamInterface(ABC):
    """
    Port interface for real-time order update streaming.

    Responsibilities:
    - Connect to an order update stream and receive lifecycle events.
    - Dispatch normalized OrderEvent instances to registered callbacks.
    - Manage connection lifecycle (start, stop, reconnect).
    - Report stream health via diagnostics.

    Does NOT:
    - Persist order events (callback consumers or repository handles that).
    - Update order status in repositories directly (service layer responsibility).
    - Know about specific broker protocols.

    Example:
        stream = SomeBrokerOrderStream(config=config)
        stream.register_callback(my_handler)
        stream.start()
        # ... later ...
        stream.stop()
    """

    @abstractmethod
    def start(self) -> None:
        """
        Start the order update stream connection.

        Begins the WebSocket connection in a background thread.

        Raises:
            ExternalServiceError: If initial connection or authentication fails.
        """
        ...

    @abstractmethod
    def stop(self) -> None:
        """
        Stop the order update stream and close the connection.

        Idempotent. Does not raise on errors.
        """
        ...

    @abstractmethod
    def register_callback(self, callback: OrderEventCallback) -> None:
        """
        Register a callback to receive OrderEvent instances.

        Multiple callbacks can be registered. Each receives every event.

        Args:
            callback: Function accepting an OrderEvent argument.
        """
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the stream is currently connected."""
        ...

    @abstractmethod
    def diagnostics(self) -> dict[str, Any]:
        """
        Return stream health diagnostics.

        Returns:
            Dict with keys: connected, events_received, last_event_at,
            reconnect_count, errors.
        """
        ...
