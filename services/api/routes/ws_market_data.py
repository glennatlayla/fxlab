"""
WebSocket endpoint for real-time market data streaming (Phase 7 — M3).

Responsibilities:
- Accept authenticated WebSocket connections for a symbol.
- Authenticate via JWT token passed as query parameter.
- Validate JWT secret strength (>= 32 bytes) at connection time.
- Send initial "connected" message on successful connection.
- Maintain connection and respond to client pings.
- Register/deregister connections with a dependency-injected
  WebSocketConnectionManager (keyed by symbol, not deployment_id).
- Propagate correlation_id through all log messages.
- Provide REST /ws/market-data/stats endpoint for connection diagnostics.

Does NOT:
- Produce market data (AlpacaBarStream pushes via the manager's broadcast).
- Contain business logic or indicator calculations.
- Handle order submission.

Dependencies:
- FastAPI WebSocket: WebSocket protocol handling.
- services.api.infrastructure.ws_manager: WebSocketConnectionManager.
- libs.contracts.ws_messages: WsMessage, WsMessageType.
- PyJWT: Token validation for WebSocket authentication.

Error conditions:
- WebSocketDisconnect: Client closed connection (normal).
- Invalid/expired token: Connection closed with code 4008.
- Weak JWT secret (<32 bytes): Connection closed with code 4008.
- Any unhandled error: Connection logged with exc_info.

Example:
    # Client connects to AAPL market data stream:
    ws = new WebSocket("ws://localhost:8000/ws/market-data/AAPL?token=JWT")
    # Receives: { msg_type: "connected", deployment_id: "AAPL", ... }
    # Receives: { msg_type: "market_data_update", deployment_id: "AAPL", payload: {...} }
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from libs.contracts.ws_messages import WsMessage, WsMessageType
from services.api.infrastructure.ws_manager import WebSocketConnectionManager

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["websocket"])

# Minimum JWT secret length in bytes for HS256 security.
_MIN_JWT_SECRET_BYTES = 32


def get_market_data_ws_manager(request_or_ws: Request | WebSocket) -> WebSocketConnectionManager:
    """
    Dependency provider for the market data WebSocket connection manager.

    Retrieves the manager from app.state. If not set (e.g. in tests),
    falls back to creating a new instance on app.state. This allows
    tests to inject their own manager instance.

    Args:
        request_or_ws: Either a Request or WebSocket (both have .app attribute).

    Returns:
        WebSocketConnectionManager instance.

    Example:
        manager = get_market_data_ws_manager(request_or_ws)
    """
    app = request_or_ws.app
    if not hasattr(app.state, "market_data_ws_manager"):
        app.state.market_data_ws_manager = WebSocketConnectionManager()
    return app.state.market_data_ws_manager


def _validate_ws_token(token: str | None, *, correlation_id: str) -> dict[str, Any] | None:
    """
    Validate a JWT token for WebSocket authentication.

    WebSocket connections cannot set HTTP headers, so the token is passed
    as a query parameter. This function validates the token using the same
    secret and algorithm as the REST API auth. Also validates that the
    JWT secret is at least 32 bytes long.

    Args:
        token: JWT token string, or None if not provided.
        correlation_id: Request correlation ID for structured logging.

    Returns:
        Decoded token payload dict if valid, None if invalid.

    Example:
        payload = _validate_ws_token("eyJ...", correlation_id="abc-123")
        # payload["sub"] == "user-001"
    """
    if not token:
        return None

    try:
        import jwt

        secret = os.environ.get("JWT_SECRET_KEY", "")
        if not secret:
            logger.error(
                "ws_auth.no_jwt_secret",
                component="ws_market_data",
                correlation_id=correlation_id,
            )
            return None

        # Validate secret strength — weak secrets allow JWT forgery
        if len(secret.encode("utf-8")) < _MIN_JWT_SECRET_BYTES:
            logger.critical(
                "ws_auth.jwt_secret_too_short",
                component="ws_market_data",
                correlation_id=correlation_id,
                secret_length=len(secret.encode("utf-8")),
                min_required=_MIN_JWT_SECRET_BYTES,
            )
            return None

        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except Exception as exc:
        logger.warning(
            "ws_auth.token_invalid",
            error=str(exc),
            component="ws_market_data",
            correlation_id=correlation_id,
        )
        return None


@router.websocket("/ws/market-data/{symbol}")
async def ws_market_data(websocket: WebSocket, symbol: str) -> None:
    """
    WebSocket endpoint for real-time market data streaming.

    Authenticates the client via JWT token in query parameter, then maintains
    the connection for streaming OHLCV bar updates for a given symbol.

    Protocol:
    1. Client connects with ?token=JWT query parameter.
    2. Server validates token; closes with 4008 if invalid.
    3. Server sends "connected" message with symbol as deployment_id.
    4. Server streams market_data_update messages via broadcast.
    5. Client can send "ping" messages; server responds with "pong".
    6. Connection stays open until client disconnects or server shuts down.

    Args:
        websocket: The WebSocket connection (injected by FastAPI).
        symbol: The ticker symbol to subscribe to for bar updates (e.g. "AAPL").

    Example:
        ws = new WebSocket("ws://host/ws/market-data/AAPL?token=JWT")
    """
    # Generate correlation_id for this connection's lifetime
    correlation_id = str(uuid.uuid4())

    # Normalize symbol to uppercase
    normalized_symbol = symbol.upper().strip()

    # Authenticate via query parameter
    token = websocket.query_params.get("token")
    payload = _validate_ws_token(token, correlation_id=correlation_id)

    if payload is None:
        await websocket.close(code=4008, reason="Authentication required")
        return

    user_id = payload.get("sub", "unknown")

    # Accept the WebSocket connection
    await websocket.accept()

    # Resolve the connection manager via app state (DI)
    manager = get_market_data_ws_manager(websocket)

    logger.info(
        "ws_market_data.connected",
        extra={
            "operation": "ws_market_data_connect",
            "component": "ws_market_data",
            "symbol": normalized_symbol,
            "user_id": user_id,
            "correlation_id": correlation_id,
        },
    )

    # Register with market data connection manager (keyed by symbol)
    await manager.connect(normalized_symbol, websocket)

    try:
        # Send initial "connected" message
        connected_msg = WsMessage(
            msg_type=WsMessageType.CONNECTED,
            deployment_id=normalized_symbol,
            timestamp=datetime.now(tz=timezone.utc),
            payload={
                "user_id": user_id,
                "symbol": normalized_symbol,
                "correlation_id": correlation_id,
                "message": f"Connected to market data stream for {normalized_symbol}",
            },
        )
        await websocket.send_json(connected_msg.model_dump(mode="json"))

        # Keep connection alive, handle client messages
        while True:
            try:
                data = await websocket.receive_text()
                # Handle client ping/pong
                if data == "ping":
                    await websocket.send_text("pong")
            except WebSocketDisconnect:
                break
            except Exception:
                break

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(
            "ws_market_data.error",
            extra={
                "operation": "ws_market_data_error",
                "component": "ws_market_data",
                "symbol": normalized_symbol,
                "user_id": user_id,
                "correlation_id": correlation_id,
                "error": str(exc),
            },
            exc_info=True,
        )
    finally:
        await manager.disconnect(normalized_symbol, websocket)
        logger.info(
            "ws_market_data.disconnected",
            extra={
                "operation": "ws_market_data_disconnect",
                "component": "ws_market_data",
                "symbol": normalized_symbol,
                "user_id": user_id,
                "correlation_id": correlation_id,
            },
        )


@router.get("/ws/market-data/bar-stream/health", tags=["websocket"])
async def ws_bar_stream_health(request: Request) -> dict[str, Any]:
    """
    Return bar stream health for load balancer health checks.

    Returns diagnostics from the AlpacaBarStream instance stored on
    app.state. If no bar stream is configured (e.g. in API-only mode),
    returns a minimal status indicating the stream is not active.

    This endpoint is designed for load balancer health checks — workers
    with unhealthy streams can be removed from the pool.

    Returns:
        Dict with connected, bars_received, last_data_age_seconds,
        circuit_breaker_open, and other diagnostics.

    Example:
        GET /ws/market-data/bar-stream/health
        {
            "status": "healthy",
            "connected": true,
            "bars_received": 12345,
            "last_data_age_seconds": 2.1,
            "circuit_breaker_open": false
        }
    """
    bar_stream = getattr(request.app.state, "bar_stream", None)
    if bar_stream is None:
        return {
            "status": "not_configured",
            "detail": "No bar stream adapter is registered on this worker.",
        }

    diag = bar_stream.diagnostics()

    # Determine health status
    status = "healthy"
    if diag.get("circuit_breaker_open"):
        status = "circuit_breaker_open"
    elif not diag.get("connected"):
        status = "disconnected"
    elif diag.get("last_data_age_seconds") is not None and diag["last_data_age_seconds"] > 120:
        status = "stale_data"

    diag["status"] = status
    return diag


@router.get("/ws/market-data/stats", tags=["websocket"])
async def ws_market_data_stats(request: Request) -> dict[str, Any]:
    """
    Return WebSocket market data connection statistics.

    Provides diagnostic information about active market data WebSocket
    connections for monitoring and debugging purposes.

    Returns:
        Dict with total_connections, symbols list, per-symbol counts,
        and internal manager diagnostics.

    Example:
        GET /ws/market-data/stats
        {
            "total_connections": 5,
            "symbols": ["AAPL", "MSFT"],
            "per_symbol": {"AAPL": 3, "MSFT": 2},
            "manager": {"evictions": 0, "broadcasts": 100, ...}
        }
    """
    manager = get_market_data_ws_manager(request)
    symbols = manager.list_deployments()
    per_symbol = {s: manager.get_connection_count(s) for s in symbols}

    return {
        "total_connections": manager.total_connection_count,
        "symbols": symbols,
        "per_symbol": per_symbol,
        "manager": manager.manager_diagnostics,
    }
