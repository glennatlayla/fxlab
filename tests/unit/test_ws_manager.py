"""
Unit tests for WebSocketConnectionManager (production-grade broadcast).

Tests cover:
- Connect/disconnect lifecycle and room cleanup.
- Concurrent fan-out broadcast via asyncio.gather.
- Per-send timeout enforcement and slow-consumer eviction.
- Dead connection detection and removal.
- Diagnostics: eviction count, broadcast count, send_timeout_s.
- Idempotent disconnect (non-existent connection).

Dependencies:
    - services.api.infrastructure.ws_manager: WebSocketConnectionManager

Example:
    pytest tests/unit/test_ws_manager.py -v
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from libs.contracts.ws_messages import WsMessage, WsMessageType
from services.api.infrastructure.ws_manager import WebSocketConnectionManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def manager() -> WebSocketConnectionManager:
    """Fresh WebSocketConnectionManager for each test."""
    return WebSocketConnectionManager(send_timeout_s=2.0)


@pytest.fixture
def test_message() -> WsMessage:
    """Sample WsMessage for broadcast tests."""
    return WsMessage(
        msg_type=WsMessageType.MARKET_DATA_UPDATE,
        deployment_id="AAPL",
        timestamp=datetime.now(tz=timezone.utc),
        payload={"symbol": "AAPL", "close": "150.75"},
    )


def _make_ws_mock() -> AsyncMock:
    """Create a mock WebSocket with async send_json."""
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# Connect / disconnect tests
# ---------------------------------------------------------------------------


class TestConnectDisconnect:
    """Tests for connection tracking."""

    @pytest.mark.asyncio
    async def test_connect_adds_to_room(self, manager: WebSocketConnectionManager) -> None:
        """connect() should add the websocket to the room."""
        ws = _make_ws_mock()
        await manager.connect("AAPL", ws)

        assert manager.get_connection_count("AAPL") == 1

    @pytest.mark.asyncio
    async def test_connect_multiple_clients(self, manager: WebSocketConnectionManager) -> None:
        """Multiple clients should be tracked in the same room."""
        ws1 = _make_ws_mock()
        ws2 = _make_ws_mock()
        ws3 = _make_ws_mock()

        await manager.connect("AAPL", ws1)
        await manager.connect("AAPL", ws2)
        await manager.connect("AAPL", ws3)

        assert manager.get_connection_count("AAPL") == 3
        assert manager.total_connection_count == 3

    @pytest.mark.asyncio
    async def test_disconnect_removes_from_room(self, manager: WebSocketConnectionManager) -> None:
        """disconnect() should remove the websocket from the room."""
        ws = _make_ws_mock()
        await manager.connect("AAPL", ws)
        await manager.disconnect("AAPL", ws)

        assert manager.get_connection_count("AAPL") == 0

    @pytest.mark.asyncio
    async def test_disconnect_cleans_empty_rooms(self, manager: WebSocketConnectionManager) -> None:
        """disconnect() should clean up empty rooms."""
        ws = _make_ws_mock()
        await manager.connect("AAPL", ws)
        await manager.disconnect("AAPL", ws)

        assert "AAPL" not in manager._rooms

    @pytest.mark.asyncio
    async def test_disconnect_idempotent(self, manager: WebSocketConnectionManager) -> None:
        """disconnect() with non-existent connection should not error."""
        ws = _make_ws_mock()
        await manager.disconnect("UNKNOWN", ws)  # No-op

    @pytest.mark.asyncio
    async def test_list_deployments(self, manager: WebSocketConnectionManager) -> None:
        """list_deployments() should return all active room keys."""
        ws1 = _make_ws_mock()
        ws2 = _make_ws_mock()
        await manager.connect("AAPL", ws1)
        await manager.connect("MSFT", ws2)

        deployments = manager.list_deployments()
        assert "AAPL" in deployments
        assert "MSFT" in deployments


# ---------------------------------------------------------------------------
# Broadcast tests
# ---------------------------------------------------------------------------


class TestBroadcast:
    """Tests for concurrent broadcast with timeout enforcement."""

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_clients(
        self, manager: WebSocketConnectionManager, test_message: WsMessage
    ) -> None:
        """broadcast() should send to all clients in the room."""
        ws1 = _make_ws_mock()
        ws2 = _make_ws_mock()
        await manager.connect("AAPL", ws1)
        await manager.connect("AAPL", ws2)

        await manager.broadcast("AAPL", test_message)

        ws1.send_json.assert_called_once()
        ws2.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_to_empty_room_is_noop(
        self, manager: WebSocketConnectionManager, test_message: WsMessage
    ) -> None:
        """broadcast() to non-existent room should be a no-op."""
        await manager.broadcast("NONEXISTENT", test_message)
        # No error should occur

    @pytest.mark.asyncio
    async def test_dead_connection_evicted_on_broadcast(
        self, manager: WebSocketConnectionManager, test_message: WsMessage
    ) -> None:
        """Dead connections that raise on send should be evicted."""
        ws_good = _make_ws_mock()
        ws_dead = _make_ws_mock()
        ws_dead.send_json.side_effect = ConnectionError("broken pipe")

        await manager.connect("AAPL", ws_good)
        await manager.connect("AAPL", ws_dead)

        await manager.broadcast("AAPL", test_message)

        # Good client should receive message
        ws_good.send_json.assert_called_once()
        # Dead client should be evicted
        assert manager.get_connection_count("AAPL") == 1

    @pytest.mark.asyncio
    async def test_slow_consumer_evicted_on_timeout(self, test_message: WsMessage) -> None:
        """Slow consumers that exceed send timeout should be evicted."""
        # Use very short timeout for test
        manager = WebSocketConnectionManager(send_timeout_s=0.05)

        ws_fast = _make_ws_mock()
        ws_slow = _make_ws_mock()

        async def slow_send(data: dict) -> None:
            await asyncio.sleep(5.0)  # Way longer than 0.05s timeout

        ws_slow.send_json = slow_send

        await manager.connect("AAPL", ws_fast)
        await manager.connect("AAPL", ws_slow)

        await manager.broadcast("AAPL", test_message)

        # Fast client should receive message
        ws_fast.send_json.assert_called_once()
        # Slow client should be evicted
        assert manager.get_connection_count("AAPL") == 1

    @pytest.mark.asyncio
    async def test_broadcast_does_not_block_healthy_clients(self, test_message: WsMessage) -> None:
        """Slow/dead clients should not delay healthy clients."""
        manager = WebSocketConnectionManager(send_timeout_s=0.1)

        ws_fast = _make_ws_mock()
        ws_dead = _make_ws_mock()
        ws_dead.send_json.side_effect = ConnectionError("broken")

        await manager.connect("AAPL", ws_fast)
        await manager.connect("AAPL", ws_dead)

        # Broadcast should complete quickly despite dead client
        await manager.broadcast("AAPL", test_message)

        ws_fast.send_json.assert_called_once()


# ---------------------------------------------------------------------------
# Diagnostics tests
# ---------------------------------------------------------------------------


class TestManagerDiagnostics:
    """Tests for internal diagnostics."""

    @pytest.mark.asyncio
    async def test_initial_diagnostics(self, manager: WebSocketConnectionManager) -> None:
        """Initial diagnostics should show zeros."""
        diag = manager.manager_diagnostics
        assert diag["total_connections"] == 0
        assert diag["room_count"] == 0
        assert diag["evictions"] == 0
        assert diag["broadcasts"] == 0
        assert diag["send_timeout_s"] == 2.0

    @pytest.mark.asyncio
    async def test_eviction_count_increments(self, test_message: WsMessage) -> None:
        """Eviction counter should increment when connections are evicted."""
        manager = WebSocketConnectionManager(send_timeout_s=2.0)

        ws_dead = _make_ws_mock()
        ws_dead.send_json.side_effect = ConnectionError("dead")

        await manager.connect("AAPL", ws_dead)
        await manager.broadcast("AAPL", test_message)

        diag = manager.manager_diagnostics
        assert diag["evictions"] == 1

    @pytest.mark.asyncio
    async def test_broadcast_count_increments(
        self, manager: WebSocketConnectionManager, test_message: WsMessage
    ) -> None:
        """Broadcast counter should increment on each broadcast."""
        ws = _make_ws_mock()
        await manager.connect("AAPL", ws)

        await manager.broadcast("AAPL", test_message)
        await manager.broadcast("AAPL", test_message)

        diag = manager.manager_diagnostics
        assert diag["broadcasts"] == 2
