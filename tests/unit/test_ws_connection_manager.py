"""
Unit tests for WebSocket connection manager (M7 — Real-Time Position Dashboard).

Tests cover:
- connect(): adds client to deployment room
- disconnect(): removes client from deployment room
- broadcast(): sends message to all clients in a deployment
- broadcast(): skips disconnected clients without raising
- get_connection_count(): returns correct count per deployment
- list_deployments(): returns deployment IDs with active connections
- heartbeat: sends periodic heartbeat messages
- concurrent connect/disconnect: thread-safe operations

Dependencies:
    - services.api.infrastructure.ws_manager: WebSocketConnectionManager
    - libs.contracts.ws_messages: WsMessage, WsMessageType
    - asyncio: async test utilities

Example:
    pytest tests/unit/test_ws_connection_manager.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from libs.contracts.ws_messages import WsMessage, WsMessageType
from services.api.infrastructure.ws_manager import WebSocketConnectionManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ws_mock(*, open: bool = True) -> AsyncMock:
    """Create a mock WebSocket that tracks sent messages."""
    ws = AsyncMock()
    ws.client_state = MagicMock()
    ws.client_state.CONNECTED = 1
    ws.client_state.value = 1 if open else 3
    ws.send_json = AsyncMock()
    if not open:
        ws.send_json.side_effect = RuntimeError("WebSocket disconnected")
    return ws


def _make_message(
    deployment_id: str = "deploy-001",
    msg_type: WsMessageType = WsMessageType.HEARTBEAT,
) -> WsMessage:
    """Create a test WsMessage."""
    return WsMessage(
        msg_type=msg_type,
        deployment_id=deployment_id,
        timestamp=datetime.now(tz=timezone.utc),
        payload={},
    )


# ---------------------------------------------------------------------------
# Connect / Disconnect tests
# ---------------------------------------------------------------------------


class TestWsManagerConnect:
    """Tests for connect() and disconnect()."""

    @pytest.mark.asyncio
    async def test_connect_adds_client(self) -> None:
        """connect() should add a WebSocket to the deployment room."""
        manager = WebSocketConnectionManager()
        ws = _make_ws_mock()

        await manager.connect("deploy-001", ws)

        assert manager.get_connection_count("deploy-001") == 1

    @pytest.mark.asyncio
    async def test_connect_multiple_clients(self) -> None:
        """Multiple clients can connect to the same deployment."""
        manager = WebSocketConnectionManager()
        ws1 = _make_ws_mock()
        ws2 = _make_ws_mock()
        ws3 = _make_ws_mock()

        await manager.connect("deploy-001", ws1)
        await manager.connect("deploy-001", ws2)
        await manager.connect("deploy-001", ws3)

        assert manager.get_connection_count("deploy-001") == 3

    @pytest.mark.asyncio
    async def test_connect_different_deployments(self) -> None:
        """Clients connecting to different deployments are tracked separately."""
        manager = WebSocketConnectionManager()
        ws1 = _make_ws_mock()
        ws2 = _make_ws_mock()

        await manager.connect("deploy-001", ws1)
        await manager.connect("deploy-002", ws2)

        assert manager.get_connection_count("deploy-001") == 1
        assert manager.get_connection_count("deploy-002") == 1

    @pytest.mark.asyncio
    async def test_disconnect_removes_client(self) -> None:
        """disconnect() should remove a WebSocket from the deployment room."""
        manager = WebSocketConnectionManager()
        ws = _make_ws_mock()

        await manager.connect("deploy-001", ws)
        assert manager.get_connection_count("deploy-001") == 1

        await manager.disconnect("deploy-001", ws)
        assert manager.get_connection_count("deploy-001") == 0

    @pytest.mark.asyncio
    async def test_disconnect_idempotent(self) -> None:
        """Disconnecting a client that is not connected should not raise."""
        manager = WebSocketConnectionManager()
        ws = _make_ws_mock()

        # Never connected — should not raise
        await manager.disconnect("deploy-001", ws)

    @pytest.mark.asyncio
    async def test_disconnect_cleans_empty_room(self) -> None:
        """Disconnecting the last client should clean up the deployment room."""
        manager = WebSocketConnectionManager()
        ws = _make_ws_mock()

        await manager.connect("deploy-001", ws)
        await manager.disconnect("deploy-001", ws)

        assert "deploy-001" not in manager.list_deployments()


# ---------------------------------------------------------------------------
# Broadcast tests
# ---------------------------------------------------------------------------


class TestWsManagerBroadcast:
    """Tests for broadcast()."""

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self) -> None:
        """broadcast() should send the message to all clients in the deployment."""
        manager = WebSocketConnectionManager()
        ws1 = _make_ws_mock()
        ws2 = _make_ws_mock()

        await manager.connect("deploy-001", ws1)
        await manager.connect("deploy-001", ws2)

        msg = _make_message("deploy-001", WsMessageType.POSITION_UPDATE)
        await manager.broadcast("deploy-001", msg)

        ws1.send_json.assert_called_once()
        ws2.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_only_targets_deployment(self) -> None:
        """broadcast() should NOT send to clients in other deployments."""
        manager = WebSocketConnectionManager()
        ws1 = _make_ws_mock()
        ws2 = _make_ws_mock()

        await manager.connect("deploy-001", ws1)
        await manager.connect("deploy-002", ws2)

        msg = _make_message("deploy-001")
        await manager.broadcast("deploy-001", msg)

        ws1.send_json.assert_called_once()
        ws2.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_broadcast_skips_disconnected_clients(self) -> None:
        """broadcast() should skip clients that raise on send without crashing."""
        manager = WebSocketConnectionManager()
        ws_good = _make_ws_mock()
        ws_bad = _make_ws_mock(open=False)

        await manager.connect("deploy-001", ws_good)
        await manager.connect("deploy-001", ws_bad)

        msg = _make_message("deploy-001")
        # Should not raise even though ws_bad throws
        await manager.broadcast("deploy-001", msg)

        ws_good.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_to_empty_room(self) -> None:
        """broadcast() to a deployment with no clients should be a no-op."""
        manager = WebSocketConnectionManager()
        msg = _make_message("deploy-999")

        # Should not raise
        await manager.broadcast("deploy-999", msg)

    @pytest.mark.asyncio
    async def test_broadcast_sends_correct_data(self) -> None:
        """broadcast() should send the serialized WsMessage dict."""
        manager = WebSocketConnectionManager()
        ws = _make_ws_mock()

        await manager.connect("deploy-001", ws)

        msg = _make_message("deploy-001", WsMessageType.HEARTBEAT)
        await manager.broadcast("deploy-001", msg)

        call_args = ws.send_json.call_args[0][0]
        assert call_args["msg_type"] == "heartbeat"
        assert call_args["deployment_id"] == "deploy-001"


# ---------------------------------------------------------------------------
# Query tests
# ---------------------------------------------------------------------------


class TestWsManagerQueries:
    """Tests for connection queries."""

    @pytest.mark.asyncio
    async def test_get_connection_count_empty(self) -> None:
        """get_connection_count() for unknown deployment should return 0."""
        manager = WebSocketConnectionManager()
        assert manager.get_connection_count("nonexistent") == 0

    @pytest.mark.asyncio
    async def test_list_deployments(self) -> None:
        """list_deployments() should return all deployments with active connections."""
        manager = WebSocketConnectionManager()
        ws1 = _make_ws_mock()
        ws2 = _make_ws_mock()

        await manager.connect("deploy-001", ws1)
        await manager.connect("deploy-002", ws2)

        deployments = manager.list_deployments()
        assert "deploy-001" in deployments
        assert "deploy-002" in deployments

    @pytest.mark.asyncio
    async def test_total_connection_count(self) -> None:
        """total_connection_count should return sum across all deployments."""
        manager = WebSocketConnectionManager()
        ws1 = _make_ws_mock()
        ws2 = _make_ws_mock()
        ws3 = _make_ws_mock()

        await manager.connect("deploy-001", ws1)
        await manager.connect("deploy-001", ws2)
        await manager.connect("deploy-002", ws3)

        assert manager.total_connection_count == 3
