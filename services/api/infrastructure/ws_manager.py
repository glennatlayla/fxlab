"""
WebSocket connection manager with production-grade broadcast.

Responsibilities:
- Track active WebSocket connections grouped by room key (deployment_id or symbol).
- Fan-out broadcast messages to all clients concurrently using asyncio.TaskGroup.
- Enforce per-send timeout to prevent one slow client from blocking others.
- Evict clients that exceed the send timeout (slow-consumer protection).
- Provide connection count and deployment listing for diagnostics.
- Thread-safe and async-safe for concurrent access from multiple handlers.

Does NOT:
- Authenticate WebSocket connections (that is the route's job).
- Generate message payloads (services produce WsMessage instances).
- Manage the WebSocket lifecycle (FastAPI/Starlette handle that).
- Persist connection state (in-memory only; connections are ephemeral).

Dependencies:
- asyncio.Lock: Async-safe connection tracking.
- structlog: Structured logging for connection events.
- libs.contracts.ws_messages: WsMessage for broadcast payload typing.

Error conditions:
- Dead/slow connections are evicted during broadcast (logged at WARNING).
- No exceptions propagate from broadcast — callers are never blocked by WS errors.

Example:
    manager = WebSocketConnectionManager(send_timeout_s=2.0)
    await manager.connect("deploy-001", websocket)
    await manager.broadcast("deploy-001", ws_message)
    await manager.disconnect("deploy-001", websocket)
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from libs.contracts.ws_messages import WsMessage

logger = structlog.get_logger(__name__)

# Default timeout for individual WebSocket send operations.
# If a client's TCP buffer is full (e.g. WiFi drop, slow consumer),
# the send will be cancelled after this timeout rather than blocking
# the entire broadcast loop.
_DEFAULT_SEND_TIMEOUT_S = 2.0


class WebSocketConnectionManager:
    """
    Async-safe WebSocket connection manager with deployment-scoped rooms.

    Tracks active WebSocket connections grouped by room key (deployment_id
    or symbol). Supports concurrent fan-out broadcasting with per-client
    send timeouts. Slow or dead connections are detected and evicted during
    broadcast without interrupting other clients.

    Responsibilities:
    - Manage room_key -> set[WebSocket] mapping.
    - Broadcast WsMessage to all clients in a room concurrently.
    - Enforce per-send timeout to prevent slow-consumer deadlocks.
    - Evict dead/slow connections automatically.
    - Track connection counts for diagnostics.
    - Clean up empty rooms when last client disconnects.

    Does NOT:
    - Authenticate connections.
    - Generate message payloads.
    - Persist state across restarts.

    Dependencies:
    - asyncio.Lock for async-safe mutations.
    - structlog for structured logging.

    Example:
        manager = WebSocketConnectionManager(send_timeout_s=2.0)
        await manager.connect("AAPL", ws)
        await manager.broadcast("AAPL", message)
        await manager.disconnect("AAPL", ws)
    """

    def __init__(self, *, send_timeout_s: float = _DEFAULT_SEND_TIMEOUT_S) -> None:
        """
        Initialize the connection manager.

        Args:
            send_timeout_s: Max seconds to wait for each individual send_json()
                call. Clients that exceed this are evicted as slow consumers.
                Default 2.0 seconds.

        Example:
            manager = WebSocketConnectionManager(send_timeout_s=3.0)
        """
        self._rooms: dict[str, set[Any]] = {}
        self._lock = asyncio.Lock()
        self._send_timeout_s = send_timeout_s

        # Diagnostics counters
        self._evictions = 0
        self._broadcast_count = 0

    async def connect(self, room_key: str, websocket: Any) -> None:
        """
        Register a WebSocket connection for a room.

        Args:
            room_key: The room to subscribe to (deployment_id, symbol, etc.).
            websocket: The WebSocket connection (FastAPI WebSocket instance).

        Example:
            await manager.connect("deploy-001", websocket)
        """
        async with self._lock:
            if room_key not in self._rooms:
                self._rooms[room_key] = set()
            self._rooms[room_key].add(websocket)

        logger.info(
            "ws_manager.client_connected",
            room_key=room_key,
            total_clients=self.get_connection_count(room_key),
            component="ws_manager",
        )

    async def disconnect(self, room_key: str, websocket: Any) -> None:
        """
        Remove a WebSocket connection from a room.

        Idempotent: removing a non-existent connection is a no-op.
        Empty rooms are cleaned up automatically.

        Args:
            room_key: The room to unsubscribe from.
            websocket: The WebSocket connection to remove.

        Example:
            await manager.disconnect("deploy-001", websocket)
        """
        async with self._lock:
            if room_key in self._rooms:
                self._rooms[room_key].discard(websocket)
                if not self._rooms[room_key]:
                    del self._rooms[room_key]

        logger.debug(
            "ws_manager.client_disconnected",
            room_key=room_key,
            component="ws_manager",
        )

    async def broadcast(self, room_key: str, message: WsMessage) -> None:
        """
        Send a message to all clients in a room concurrently.

        Each send is wrapped in asyncio.wait_for() with self._send_timeout_s.
        Clients that timeout or error are evicted from the room. This ensures
        one slow client cannot block delivery to other clients.

        Sends are dispatched concurrently via asyncio.gather() so that N
        healthy clients each get the message in O(1) wall-clock time, not O(N).

        Args:
            room_key: The room to broadcast to.
            message: The WsMessage to send (serialized to JSON dict).

        Example:
            await manager.broadcast("deploy-001", ws_message)
        """
        async with self._lock:
            clients = list(self._rooms.get(room_key, set()))

        if not clients:
            return

        self._broadcast_count += 1

        # Serialize once, send to all
        data = message.model_dump(mode="json")
        evicted: list[Any] = []

        async def _send_one(ws: Any) -> None:
            """Send to a single client with timeout; mark for eviction on failure."""
            try:
                await asyncio.wait_for(
                    ws.send_json(data),
                    timeout=self._send_timeout_s,
                )
            except TimeoutError:
                evicted.append(ws)
                logger.warning(
                    "ws_manager.slow_consumer_evicted",
                    room_key=room_key,
                    reason="send_timeout",
                    timeout_s=self._send_timeout_s,
                    component="ws_manager",
                )
            except Exception:
                evicted.append(ws)
                logger.debug(
                    "ws_manager.dead_connection_detected",
                    room_key=room_key,
                    component="ws_manager",
                )

        # Fan-out concurrently — each send is independent
        await asyncio.gather(
            *(_send_one(ws) for ws in clients),
            return_exceptions=True,
        )

        # Remove evicted connections
        if evicted:
            async with self._lock:
                room = self._rooms.get(room_key)
                if room:
                    for ws in evicted:
                        room.discard(ws)
                        self._evictions += 1
                    if not room:
                        del self._rooms[room_key]

    def get_connection_count(self, room_key: str) -> int:
        """
        Return the number of active connections for a room.

        Args:
            room_key: The room to query.

        Returns:
            Number of active WebSocket connections.

        Example:
            count = manager.get_connection_count("deploy-001")
        """
        return len(self._rooms.get(room_key, set()))

    def list_deployments(self) -> list[str]:
        """
        Return all room keys with active WebSocket connections.

        Returns:
            List of room key strings.

        Example:
            rooms = manager.list_deployments()
        """
        return list(self._rooms.keys())

    @property
    def total_connection_count(self) -> int:
        """
        Return the total number of active connections across all rooms.

        Returns:
            Total number of WebSocket connections.

        Example:
            total = manager.total_connection_count
        """
        return sum(len(clients) for clients in self._rooms.values())

    @property
    def manager_diagnostics(self) -> dict[str, Any]:
        """
        Return internal diagnostics for this manager instance.

        Returns:
            Dict with total_connections, room_count, evictions, broadcasts.

        Example:
            diag = manager.manager_diagnostics
        """
        return {
            "total_connections": self.total_connection_count,
            "room_count": len(self._rooms),
            "evictions": self._evictions,
            "broadcasts": self._broadcast_count,
            "send_timeout_s": self._send_timeout_s,
        }
