"""
Unit tests for WebSocket market data endpoint (Phase 7 — M3).

Tests cover:
- WS /ws/market-data/{symbol}: authenticated connection
- WS /ws/market-data/{symbol}: unauthenticated rejection (4008)
- WS /ws/market-data/{symbol}: expired token rejection
- WS /ws/market-data/{symbol}: initial connected message with correlation_id
- WS /ws/market-data/{symbol}: symbol normalization to uppercase
- WS /ws/market-data/{symbol}: weak JWT secret rejection
- REST /ws/market-data/stats: connection statistics with manager diagnostics
- REST /ws/market-data/bar-stream/health: bar stream health endpoint
- DI: manager resolved from app.state, not module-level global

Dependencies:
    - services.api.routes.ws_market_data: router, get_market_data_ws_manager
    - services.api.infrastructure.ws_manager: WebSocketConnectionManager
    - libs.contracts.ws_messages: WsMessage, WsMessageType
    - fastapi.testclient: TestClient with WebSocket support

Example:
    pytest tests/unit/test_ws_market_data.py -v
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from services.api.infrastructure.ws_manager import WebSocketConnectionManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """Create a minimal FastAPI app with the market data WebSocket route."""
    os.environ["ENVIRONMENT"] = "test"
    os.environ["JWT_SECRET_KEY"] = "x" * 48  # 48 bytes > 32 byte min

    from services.api.routes.ws_market_data import router

    test_app = FastAPI()
    test_app.include_router(router)

    # Inject a fresh manager via app.state (DI pattern)
    test_app.state.market_data_ws_manager = WebSocketConnectionManager()

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
        "scope": "market_data:read",
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
        "scope": "market_data:read",
        "exp": datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp(),
        "iat": datetime(2019, 1, 1, tzinfo=timezone.utc).timestamp(),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------


class TestWsMarketDataAuth:
    """Tests for WebSocket market data authentication."""

    def test_connect_with_valid_token(self, client: TestClient, valid_token: str) -> None:
        """WebSocket connection with valid token should succeed."""
        with client.websocket_connect(f"/ws/market-data/AAPL?token={valid_token}") as ws:
            data = ws.receive_json()
            assert data["msg_type"] == "connected"
            assert data["deployment_id"] == "AAPL"

    def test_connect_without_token_rejected(self, client: TestClient) -> None:
        """WebSocket connection without token should be rejected."""
        with (
            pytest.raises(
                (WebSocketDisconnect, RuntimeError),
            ),
            client.websocket_connect("/ws/market-data/AAPL") as ws,
        ):
            ws.receive_json()

    def test_connect_with_invalid_token_rejected(self, client: TestClient) -> None:
        """WebSocket connection with invalid token should be rejected."""
        with (
            pytest.raises(
                (WebSocketDisconnect, RuntimeError),
            ),
            client.websocket_connect("/ws/market-data/AAPL?token=invalid-jwt-token") as ws,
        ):
            ws.receive_json()

    def test_connect_with_expired_token_rejected(
        self, client: TestClient, expired_token: str
    ) -> None:
        """WebSocket connection with expired token should be rejected."""
        with (
            pytest.raises(
                (WebSocketDisconnect, RuntimeError),
            ),
            client.websocket_connect(f"/ws/market-data/AAPL?token={expired_token}") as ws,
        ):
            ws.receive_json()

    def test_weak_jwt_secret_rejects_connection(self, client: TestClient) -> None:
        """Connection should be rejected when JWT secret is too short."""
        import jwt

        # Create a token with the weak secret
        weak_secret = "short"
        original_secret = os.environ.get("JWT_SECRET_KEY", "")
        os.environ["JWT_SECRET_KEY"] = weak_secret

        token = jwt.encode(
            {
                "sub": "user-001",
                "exp": datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp(),
            },
            weak_secret,
            algorithm="HS256",
        )

        try:
            with (
                pytest.raises(
                    (WebSocketDisconnect, RuntimeError),
                ),
                client.websocket_connect(f"/ws/market-data/AAPL?token={token}") as ws,
            ):
                ws.receive_json()
        finally:
            os.environ["JWT_SECRET_KEY"] = original_secret


# ---------------------------------------------------------------------------
# Connection lifecycle tests
# ---------------------------------------------------------------------------


class TestWsMarketDataLifecycle:
    """Tests for WebSocket connection lifecycle."""

    def test_connected_message_includes_symbol_and_correlation_id(
        self, client: TestClient, valid_token: str
    ) -> None:
        """Initial connected message should include symbol and correlation_id."""
        with client.websocket_connect(f"/ws/market-data/MSFT?token={valid_token}") as ws:
            data = ws.receive_json()
            assert data["msg_type"] == "connected"
            assert data["deployment_id"] == "MSFT"
            assert "timestamp" in data
            assert data["payload"]["symbol"] == "MSFT"
            # correlation_id should be present and non-empty
            assert "correlation_id" in data["payload"]
            assert len(data["payload"]["correlation_id"]) > 0

    def test_symbol_normalized_to_uppercase(self, client: TestClient, valid_token: str) -> None:
        """Lowercase symbol in URL should be normalized to uppercase."""
        with client.websocket_connect(f"/ws/market-data/aapl?token={valid_token}") as ws:
            data = ws.receive_json()
            assert data["deployment_id"] == "AAPL"
            assert data["payload"]["symbol"] == "AAPL"


# ---------------------------------------------------------------------------
# REST stats endpoint tests
# ---------------------------------------------------------------------------


class TestWsMarketDataStats:
    """Tests for the REST /ws/market-data/stats endpoint."""

    def test_stats_returns_empty_when_no_connections(self, client: TestClient) -> None:
        """GET /ws/market-data/stats should return zero connections initially."""
        response = client.get("/ws/market-data/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_connections"] == 0
        assert data["symbols"] == []
        assert data["per_symbol"] == {}
        # Manager diagnostics should be present
        assert "manager" in data
        assert "evictions" in data["manager"]
        assert "broadcasts" in data["manager"]
        assert "send_timeout_s" in data["manager"]

    def test_stats_returns_connection_info(self, client: TestClient, valid_token: str) -> None:
        """GET /ws/market-data/stats should return connection statistics."""
        response = client.get("/ws/market-data/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_connections" in data
        assert "symbols" in data
        assert "per_symbol" in data


# ---------------------------------------------------------------------------
# Bar stream health endpoint tests
# ---------------------------------------------------------------------------


class TestBarStreamHealth:
    """Tests for /ws/market-data/bar-stream/health endpoint."""

    def test_health_not_configured_when_no_bar_stream(self, client: TestClient) -> None:
        """Health endpoint should return not_configured when no bar stream."""
        response = client.get("/ws/market-data/bar-stream/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_configured"

    def test_health_returns_diagnostics_when_bar_stream_present(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """Health endpoint should return diagnostics from bar stream."""
        # Inject a mock bar stream
        mock_stream = MagicMock()
        mock_stream.diagnostics.return_value = {
            "connected": True,
            "subscribed_symbols": ["AAPL"],
            "bars_received": 42,
            "bars_deduplicated": 1,
            "last_bar_at": "2026-04-13T16:00:00+00:00",
            "last_data_age_seconds": 2.5,
            "reconnect_count": 0,
            "errors": 0,
            "repo_timeouts": 0,
            "uptime_seconds": 3600.0,
            "circuit_breaker_open": False,
            "consecutive_failures": 0,
        }
        app.state.bar_stream = mock_stream

        response = client.get("/ws/market-data/bar-stream/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["connected"] is True
        assert data["bars_received"] == 42

    def test_health_reports_circuit_breaker_open(self, app: FastAPI, client: TestClient) -> None:
        """Health should report circuit_breaker_open status."""
        mock_stream = MagicMock()
        mock_stream.diagnostics.return_value = {
            "connected": False,
            "circuit_breaker_open": True,
            "last_data_age_seconds": None,
        }
        app.state.bar_stream = mock_stream

        response = client.get("/ws/market-data/bar-stream/health")
        data = response.json()
        assert data["status"] == "circuit_breaker_open"

    def test_health_reports_stale_data(self, app: FastAPI, client: TestClient) -> None:
        """Health should report stale_data when last bar is too old."""
        mock_stream = MagicMock()
        mock_stream.diagnostics.return_value = {
            "connected": True,
            "circuit_breaker_open": False,
            "last_data_age_seconds": 200.0,
        }
        app.state.bar_stream = mock_stream

        response = client.get("/ws/market-data/bar-stream/health")
        data = response.json()
        assert data["status"] == "stale_data"

    def test_health_reports_disconnected(self, app: FastAPI, client: TestClient) -> None:
        """Health should report disconnected when stream is not connected."""
        mock_stream = MagicMock()
        mock_stream.diagnostics.return_value = {
            "connected": False,
            "circuit_breaker_open": False,
            "last_data_age_seconds": None,
        }
        app.state.bar_stream = mock_stream

        response = client.get("/ws/market-data/bar-stream/health")
        data = response.json()
        assert data["status"] == "disconnected"


# ---------------------------------------------------------------------------
# Dependency injection tests
# ---------------------------------------------------------------------------


class TestDependencyInjection:
    """Tests for connection manager DI via app.state."""

    def test_manager_resolved_from_app_state(
        self, app: FastAPI, client: TestClient, valid_token: str
    ) -> None:
        """Manager should be resolved from app.state, not module-level."""
        manager = app.state.market_data_ws_manager
        assert isinstance(manager, WebSocketConnectionManager)
        assert manager.total_connection_count == 0

        with client.websocket_connect(f"/ws/market-data/AAPL?token={valid_token}") as ws:
            ws.receive_json()
            # While connected, manager should have 1 connection
            assert manager.get_connection_count("AAPL") == 1

        # After disconnect, room should be cleaned
        assert manager.get_connection_count("AAPL") == 0
