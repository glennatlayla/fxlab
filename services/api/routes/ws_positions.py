"""
WebSocket endpoint for real-time position dashboard (M7).

Responsibilities:
- Accept authenticated WebSocket connections for a deployment.
- Authenticate via JWT token passed as query parameter.
- Send initial "connected" message on successful connection.
- Maintain connection and respond to client pings.
- Register/deregister connections with the WebSocketConnectionManager.
- Provide REST /ws/stats endpoint for connection diagnostics.

Does NOT:
- Contain business logic or P&L calculations.
- Generate position or order update messages (services push via manager).
- Handle order submission (that is the live route's job).

Dependencies:
- FastAPI WebSocket: WebSocket protocol handling.
- services.api.infrastructure.ws_manager: WebSocketConnectionManager.
- libs.contracts.ws_messages: WsMessage, WsMessageType.
- PyJWT: Token validation for WebSocket authentication.

Error conditions:
- WebSocketDisconnect: Client closed connection (normal).
- Invalid/expired token: Connection closed with code 4008.
- Any unhandled error: Connection closed with code 4500.

Example:
    # Client connects:
    ws = new WebSocket("ws://localhost:8000/ws/positions/deploy-001?token=JWT")
    # Receives: { msg_type: "connected", deployment_id: "deploy-001", ... }
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from libs.contracts.ws_messages import WsMessage, WsMessageType
from services.api.infrastructure.ws_manager import WebSocketConnectionManager

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["websocket"])

# Module-level connection manager — shared across all WS connections.
# In production, this is the singleton that services use to broadcast updates.
ws_manager = WebSocketConnectionManager()


def _validate_ws_token(token: str | None) -> dict[str, Any] | None:
    """
    Validate a JWT token for WebSocket authentication.

    WebSocket connections cannot set HTTP headers, so the token is passed
    as a query parameter. This function validates the token using the same
    secret and algorithm as the REST API auth.

    Args:
        token: JWT token string, or None if not provided.

    Returns:
        Decoded token payload dict if valid, None if invalid.

    Example:
        payload = _validate_ws_token("eyJ...")
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
                component="ws_positions",
            )
            return None

        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except Exception as exc:
        logger.warning(
            "ws_auth.token_invalid",
            error=str(exc),
            component="ws_positions",
        )
        return None


@router.websocket("/ws/positions/{deployment_id}")
async def ws_positions(websocket: WebSocket, deployment_id: str) -> None:
    """
    WebSocket endpoint for real-time position updates.

    Authenticates the client via JWT token in query parameter, then maintains
    the connection for streaming position, order, and P&L updates.

    Protocol:
    1. Client connects with ?token=JWT query parameter.
    2. Server validates token; closes with 4008 if invalid.
    3. Server sends "connected" message with deployment_id.
    4. Server streams updates via WebSocketConnectionManager broadcast.
    5. Client can send "ping" messages; server responds with "pong".
    6. Connection stays open until client disconnects or server shuts down.

    Args:
        websocket: The WebSocket connection (injected by FastAPI).
        deployment_id: The deployment to subscribe to for updates.

    Example:
        ws = new WebSocket("ws://host/ws/positions/deploy-001?token=JWT")
    """
    # Authenticate via query parameter
    token = websocket.query_params.get("token")
    payload = _validate_ws_token(token)

    if payload is None:
        await websocket.close(code=4008, reason="Authentication required")
        return

    user_id = payload.get("sub", "unknown")

    # Accept the WebSocket connection
    await websocket.accept()

    logger.info(
        "ws_positions.connected",
        deployment_id=deployment_id,
        user_id=user_id,
        component="ws_positions",
    )

    # Register with connection manager
    await ws_manager.connect(deployment_id, websocket)

    try:
        # Send initial "connected" message
        connected_msg = WsMessage(
            msg_type=WsMessageType.CONNECTED,
            deployment_id=deployment_id,
            timestamp=datetime.now(tz=timezone.utc),
            payload={
                "user_id": user_id,
                "message": "Connected to position stream",
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
            "ws_positions.error",
            deployment_id=deployment_id,
            user_id=user_id,
            error=str(exc),
            component="ws_positions",
            exc_info=True,
        )
    finally:
        await ws_manager.disconnect(deployment_id, websocket)
        logger.info(
            "ws_positions.disconnected",
            deployment_id=deployment_id,
            user_id=user_id,
            component="ws_positions",
        )


@router.get("/ws/stats", tags=["websocket"])
async def ws_stats() -> dict[str, Any]:
    """
    Return WebSocket connection statistics.

    Provides diagnostic information about active WebSocket connections
    for monitoring and debugging purposes.

    Returns:
        Dict with total_connections, deployments list, and per-deployment counts.

    Example:
        GET /ws/stats
        {
            "total_connections": 5,
            "deployments": ["deploy-001", "deploy-002"],
            "per_deployment": {"deploy-001": 3, "deploy-002": 2}
        }
    """
    deployments = ws_manager.list_deployments()
    per_deployment = {d: ws_manager.get_connection_count(d) for d in deployments}

    return {
        "total_connections": ws_manager.total_connection_count,
        "deployments": deployments,
        "per_deployment": per_deployment,
    }
