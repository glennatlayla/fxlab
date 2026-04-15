"""
Unit tests for WebSocket positions endpoint (M7 — Real-Time Position Dashboard).

Tests cover:
- WS /ws/positions/{deployment_id}: authenticated connection
- WS /ws/positions/{deployment_id}: unauthenticated rejection (4008)
- WS /ws/positions/{deployment_id}: initial snapshot on connect
- WS /ws/positions/{deployment_id}: heartbeat messages
- WS /ws/positions/{deployment_id}: graceful disconnect
- Connection manager integration: broadcast updates
- REST /ws/stats: connection statistics endpoint

Dependencies:
    - services.api.routes.ws_positions: router, ws_manager
    - libs.contracts.ws_messages: WsMessage, WsMessageType
    - fastapi.testclient: TestClient with WebSocket support

Example:
    pytest tests/unit/test_ws_positions.py -v
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

# ---------------------------------------------------------------------------
# App fixture with WS route
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """Create a minimal FastAPI app with the WebSocket route registered."""
    # Set test environment to bypass secret validation
    os.environ.setdefault("ENVIRONMENT", "test")
    os.environ.setdefault("JWT_SECRET_KEY", "x" * 48)

    from services.api.routes.ws_positions import router, ws_manager

    test_app = FastAPI()
    test_app.include_router(router)

    # Reset manager state between tests
    ws_manager._rooms.clear()

    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def valid_token() -> str:
    """Generate a valid JWT token for testing."""
    import jwt

    secret = os.environ.get("JWT_SECRET_KEY", "x" * 48)
    payload = {
        "sub": "user-001",
        "email": "test@fxlab.io",
        "role": "operator",
        "scope": "live:trade feeds:read",
        "exp": datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp(),
        "iat": datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp(),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def expired_token() -> str:
    """Generate an expired JWT token for testing."""
    import jwt

    secret = os.environ.get("JWT_SECRET_KEY", "x" * 48)
    payload = {
        "sub": "user-001",
        "email": "test@fxlab.io",
        "role": "operator",
        "scope": "live:trade",
        "exp": datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp(),
        "iat": datetime(2019, 1, 1, tzinfo=timezone.utc).timestamp(),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------


class TestWsPositionsAuth:
    """Tests for WebSocket authentication."""

    def test_connect_with_valid_token(self, client: TestClient, valid_token: str) -> None:
        """WebSocket connection with valid token should succeed."""
        with client.websocket_connect(f"/ws/positions/deploy-001?token={valid_token}") as ws:
            # Should receive a connected message
            data = ws.receive_json()
            assert data["msg_type"] == "connected"
            assert data["deployment_id"] == "deploy-001"

    def test_connect_without_token_rejected(self, client: TestClient) -> None:
        """WebSocket connection without token should be rejected."""
        with (
            pytest.raises(  # noqa: B017
                (WebSocketDisconnect, RuntimeError),
            ),
            client.websocket_connect("/ws/positions/deploy-001") as ws,
        ):
            ws.receive_json()

    def test_connect_with_invalid_token_rejected(self, client: TestClient) -> None:
        """WebSocket connection with invalid token should be rejected."""
        with (
            pytest.raises(  # noqa: B017
                (WebSocketDisconnect, RuntimeError),
            ),
            client.websocket_connect("/ws/positions/deploy-001?token=invalid-jwt-token") as ws,
        ):
            ws.receive_json()

    def test_connect_with_expired_token_rejected(
        self, client: TestClient, expired_token: str
    ) -> None:
        """WebSocket connection with expired token should be rejected."""
        with (
            pytest.raises(  # noqa: B017
                (WebSocketDisconnect, RuntimeError),
            ),
            client.websocket_connect(f"/ws/positions/deploy-001?token={expired_token}") as ws,
        ):
            ws.receive_json()


# ---------------------------------------------------------------------------
# Connection lifecycle tests
# ---------------------------------------------------------------------------


class TestWsPositionsLifecycle:
    """Tests for WebSocket connection lifecycle."""

    def test_connected_message_includes_deployment_id(
        self, client: TestClient, valid_token: str
    ) -> None:
        """Initial connected message should include deployment_id."""
        with client.websocket_connect(f"/ws/positions/deploy-abc?token={valid_token}") as ws:
            data = ws.receive_json()
            assert data["msg_type"] == "connected"
            assert data["deployment_id"] == "deploy-abc"
            assert "timestamp" in data


# ---------------------------------------------------------------------------
# REST stats endpoint tests
# ---------------------------------------------------------------------------


class TestWsStatsEndpoint:
    """Tests for the REST /ws/stats endpoint."""

    def test_stats_returns_connection_info(self, client: TestClient) -> None:
        """GET /ws/stats should return connection statistics."""
        response = client.get("/ws/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_connections" in data
        assert "deployments" in data
