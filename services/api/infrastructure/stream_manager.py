"""
Thread-safe lifecycle manager for market data and order update streams.

Responsibilities:
- Register and deregister market data streams per deployment.
- Register and deregister order update streams per deployment.
- Start and stop streams when deployments are activated/deactivated.
- Register price update and order event callbacks on streams.
- Aggregate stream health diagnostics across all deployments.
- Support graceful shutdown of all streams.
- Enforce thread-safety for all operations via threading.Lock.

Does NOT:
- Contain business logic, risk checks, or trading logic.
- Know about specific broker stream implementations.
- Persist stream state durably (streams are ephemeral; re-established on restart).
- Modify stream configuration after registration.

Dependencies:
- libs.contracts.interfaces.market_stream_interface.MarketStreamInterface.
- libs.contracts.interfaces.order_stream_interface.OrderStreamInterface.
- libs.contracts.interfaces.market_stream_interface.PriceCallback.
- libs.contracts.interfaces.order_stream_interface.OrderEventCallback.
- libs.contracts.errors.NotFoundError.
- threading: Thread safety via Lock.
- structlog: Structured logging.

Error conditions:
- NotFoundError: deployment_id not found in registry.
- ValueError: duplicate deployment_id registration attempt.
- ExternalServiceError: stream.start() fails.

Example:
    manager = StreamManager()
    manager.register_market_stream("dep-001", alpaca_market_stream)
    manager.register_order_stream("dep-001", alpaca_order_stream)
    manager.start_streams("dep-001")
    manager.add_price_callback("dep-001", my_price_handler)
    # ... later during shutdown ...
    manager.stop_all()
"""

from __future__ import annotations

import threading
from typing import Any

import structlog

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.market_stream_interface import (
    MarketStreamInterface,
    PriceCallback,
)
from libs.contracts.interfaces.order_stream_interface import (
    OrderEventCallback,
    OrderStreamInterface,
)

logger = structlog.get_logger(__name__)


class StreamManager:
    """
    Thread-safe lifecycle manager for market and order update streams.

    Manages the registration, lifecycle (start/stop), and health monitoring
    of market data and order update streams across all active deployments.
    All operations are protected by threading.Lock for safe use in concurrent
    ASGI environments.

    Responsibilities:
    - Store deployment_id → stream mappings for market and order streams.
    - Enforce one market stream and one order stream per deployment_id.
    - Start and stop streams as deployments are activated/deactivated.
    - Register price update and order event callbacks on streams.
    - Aggregate stream health diagnostics across all deployments.
    - Support graceful shutdown, ensuring all streams receive cleanup attempts.

    Does NOT:
    - Create streams (that is the caller's responsibility).
    - Persist stream state (streams are ephemeral runtime resources).
    - Apply business logic or risk policies.

    Attributes:
        _market_streams: Dict mapping deployment_id → MarketStreamInterface.
        _order_streams: Dict mapping deployment_id → OrderStreamInterface.
        _lock: Threading lock for concurrent access safety.

    Example:
        manager = StreamManager()
        manager.register_market_stream("dep-001", stream)
        manager.start_streams("dep-001")
        manager.add_price_callback("dep-001", callback)
        manager.stop_all()  # graceful shutdown
    """

    def __init__(self) -> None:
        """Initialize empty stream registries with thread safety lock."""
        self._market_streams: dict[str, MarketStreamInterface] = {}
        self._order_streams: dict[str, OrderStreamInterface] = {}
        self._lock = threading.Lock()

    def register_market_stream(self, deployment_id: str, stream: MarketStreamInterface) -> None:
        """
        Register a market data stream for a deployment.

        Stores the stream in the registry. The stream is NOT started;
        call start_streams() to begin receiving market data.

        Args:
            deployment_id: ULID of the deployment.
            stream: MarketStreamInterface implementation to register.

        Raises:
            ValueError: deployment_id already has a registered market stream.
                        Deregister the existing stream first.

        Example:
            manager.register_market_stream("dep-001", alpaca_market_stream)
        """
        with self._lock:
            if deployment_id in self._market_streams:
                raise ValueError(
                    f"Deployment {deployment_id} already has a registered market stream. "
                    "Deregister the existing stream before registering a new one."
                )
            self._market_streams[deployment_id] = stream

        logger.info(
            "stream_manager.market_stream_registered",
            deployment_id=deployment_id,
            component="stream_manager",
        )

    def register_order_stream(self, deployment_id: str, stream: OrderStreamInterface) -> None:
        """
        Register an order update stream for a deployment.

        Stores the stream in the registry. The stream is NOT started;
        call start_streams() to begin receiving order updates.

        Args:
            deployment_id: ULID of the deployment.
            stream: OrderStreamInterface implementation to register.

        Raises:
            ValueError: deployment_id already has a registered order stream.
                        Deregister the existing stream first.

        Example:
            manager.register_order_stream("dep-001", alpaca_order_stream)
        """
        with self._lock:
            if deployment_id in self._order_streams:
                raise ValueError(
                    f"Deployment {deployment_id} already has a registered order stream. "
                    "Deregister the existing stream before registering a new one."
                )
            self._order_streams[deployment_id] = stream

        logger.info(
            "stream_manager.order_stream_registered",
            deployment_id=deployment_id,
            component="stream_manager",
        )

    def start_streams(self, deployment_id: str) -> None:
        """
        Start both market and order streams for a deployment.

        If either stream is missing or start() fails, the exception propagates
        and the streams are left in their current state (partially started if
        one started before the other failed). Callers should ensure both
        streams are registered before calling start_streams().

        Args:
            deployment_id: ULID of the deployment.

        Raises:
            NotFoundError: market or order stream not registered for deployment.
            ExternalServiceError: stream.start() fails (connection, auth, etc).

        Example:
            manager.start_streams("dep-001")
            # Market and order streams are now connected and receiving updates.
        """
        with self._lock:
            market_stream = self._market_streams.get(deployment_id)
            order_stream = self._order_streams.get(deployment_id)

        if market_stream is None:
            raise NotFoundError(f"No market stream registered for deployment {deployment_id}")
        if order_stream is None:
            raise NotFoundError(f"No order stream registered for deployment {deployment_id}")

        logger.info(
            "stream_manager.starting_streams",
            deployment_id=deployment_id,
            component="stream_manager",
        )

        market_stream.start()
        order_stream.start()

        logger.info(
            "stream_manager.streams_started",
            deployment_id=deployment_id,
            component="stream_manager",
        )

    def stop_streams(self, deployment_id: str) -> None:
        """
        Stop both market and order streams for a deployment.

        Calls stop() on both streams. Exceptions from stop() are logged
        but swallowed — stop_streams() always succeeds to prevent resource
        leaks. If either stream is missing, a NotFoundError is raised before
        attempting any stops.

        Args:
            deployment_id: ULID of the deployment.

        Raises:
            NotFoundError: market or order stream not registered for deployment.

        Example:
            manager.stop_streams("dep-001")
            # Both streams are gracefully shut down.
        """
        with self._lock:
            market_stream = self._market_streams.get(deployment_id)
            order_stream = self._order_streams.get(deployment_id)

        if market_stream is None:
            raise NotFoundError(f"No market stream registered for deployment {deployment_id}")
        if order_stream is None:
            raise NotFoundError(f"No order stream registered for deployment {deployment_id}")

        logger.info(
            "stream_manager.stopping_streams",
            deployment_id=deployment_id,
            component="stream_manager",
        )

        try:
            market_stream.stop()
        except Exception:
            logger.warning(
                "stream_manager.market_stream_stop_error",
                deployment_id=deployment_id,
                component="stream_manager",
                exc_info=True,
            )

        try:
            order_stream.stop()
        except Exception:
            logger.warning(
                "stream_manager.order_stream_stop_error",
                deployment_id=deployment_id,
                component="stream_manager",
                exc_info=True,
            )

        logger.info(
            "stream_manager.streams_stopped",
            deployment_id=deployment_id,
            component="stream_manager",
        )

    def stop_all(self) -> None:
        """
        Stop all streams across all deployments. Used for graceful shutdown.

        Iterates over all registered deployments and calls stop_streams()
        on each. Exceptions from individual stop_streams() calls are caught
        and logged to ensure all streams receive cleanup attempts even if
        some fail. Always completes without raising.

        Example:
            manager.stop_all()
            # All streams across all deployments are gracefully shut down.
        """
        with self._lock:
            deployment_ids = list(self._market_streams.keys())

        logger.info(
            "stream_manager.stopping_all_streams",
            deployment_count=len(deployment_ids),
            component="stream_manager",
        )

        for deployment_id in deployment_ids:
            try:
                self.stop_streams(deployment_id)
            except Exception:
                logger.warning(
                    "stream_manager.stop_all_deployment_error",
                    deployment_id=deployment_id,
                    component="stream_manager",
                    exc_info=True,
                )

        logger.info(
            "stream_manager.all_streams_stopped",
            deployment_count=len(deployment_ids),
            component="stream_manager",
        )

    def add_price_callback(self, deployment_id: str, callback: PriceCallback) -> None:
        """
        Register a price update callback on a deployment's market stream.

        Multiple callbacks can be registered; each receives every price update.

        Args:
            deployment_id: ULID of the deployment.
            callback: Function accepting a PriceUpdate argument.

        Raises:
            NotFoundError: market stream not registered for deployment.

        Example:
            manager.add_price_callback("dep-001", lambda update: print(update.price))
        """
        with self._lock:
            market_stream = self._market_streams.get(deployment_id)

        if market_stream is None:
            raise NotFoundError(f"No market stream registered for deployment {deployment_id}")

        market_stream.register_callback(callback)

        logger.info(
            "stream_manager.price_callback_registered",
            deployment_id=deployment_id,
            component="stream_manager",
        )

    def add_order_callback(self, deployment_id: str, callback: OrderEventCallback) -> None:
        """
        Register an order event callback on a deployment's order stream.

        Multiple callbacks can be registered; each receives every order event.

        Args:
            deployment_id: ULID of the deployment.
            callback: Function accepting an OrderEvent argument.

        Raises:
            NotFoundError: order stream not registered for deployment.

        Example:
            manager.add_order_callback("dep-001", my_order_handler)
        """
        with self._lock:
            order_stream = self._order_streams.get(deployment_id)

        if order_stream is None:
            raise NotFoundError(f"No order stream registered for deployment {deployment_id}")

        order_stream.register_callback(callback)

        logger.info(
            "stream_manager.order_callback_registered",
            deployment_id=deployment_id,
            component="stream_manager",
        )

    def diagnostics(self) -> dict[str, Any]:
        """
        Aggregated health diagnostics for all streams across deployments.

        Returns a snapshot of the health status of all registered streams.
        Each deployment includes diagnostics from both its market and order
        streams.

        Returns:
            Dict with structure:
            {
                "deployments": {
                    "<deployment_id>": {
                        "market_stream": {...},  # from market_stream.diagnostics()
                        "order_stream": {...},   # from order_stream.diagnostics()
                    },
                    ...
                },
                "total_deployments": <int>,
            }

        Example:
            health = manager.diagnostics()
            for dep_id, streams in health["deployments"].items():
                if not streams["market_stream"]["connected"]:
                    alert(f"Market stream down for {dep_id}")
        """
        with self._lock:
            deployment_ids = list(self._market_streams.keys())
            market_streams_copy = self._market_streams.copy()
            order_streams_copy = self._order_streams.copy()

        deployments_health: dict[str, Any] = {}
        for deployment_id in deployment_ids:
            market_stream = market_streams_copy.get(deployment_id)
            order_stream = order_streams_copy.get(deployment_id)

            deployment_health: dict[str, Any] = {}
            if market_stream:
                deployment_health["market_stream"] = market_stream.diagnostics()
            if order_stream:
                deployment_health["order_stream"] = order_stream.diagnostics()

            deployments_health[deployment_id] = deployment_health

        return {
            "deployments": deployments_health,
            "total_deployments": len(deployment_ids),
        }

    def is_deployment_streaming(self, deployment_id: str) -> bool:
        """
        Check if both market and order streams are registered for a deployment.

        Returns True only if both streams exist and are connected. Does NOT
        check if they were successfully started.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            True if both market and order streams are registered.

        Example:
            if manager.is_deployment_streaming("dep-001"):
                print("Both streams are registered")
        """
        with self._lock:
            has_market = deployment_id in self._market_streams
            has_order = deployment_id in self._order_streams

        return has_market and has_order
