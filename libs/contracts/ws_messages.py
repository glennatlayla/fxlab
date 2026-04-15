"""
WebSocket message contracts for real-time position dashboard.

Responsibilities:
- Define the canonical message types for WebSocket communication between
  the API server and frontend dashboard clients.
- Provide Pydantic schemas for runtime validation of all WS messages.
- Ensure type safety and schema consistency across the streaming boundary.

Does NOT:
- Implement WebSocket transport or connection management.
- Contain business logic or execute trades.
- Handle authentication (that is the route/middleware's job).

Dependencies:
- pydantic: BaseModel, Field for schema definition.
- libs.contracts.execution: OrderResponse, PositionSnapshot, AccountSnapshot.

Error conditions:
- Pydantic ValidationError raised on invalid message construction.

Example:
    from libs.contracts.ws_messages import WsMessage, WsPositionUpdate

    msg = WsMessage(
        msg_type="position_update",
        deployment_id="01HDEPLOY...",
        payload=WsPositionUpdate(positions=[...]),
    )
    await websocket.send_json(msg.model_dump())
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class WsMessageType(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """WebSocket message type discriminator."""

    POSITION_UPDATE = "position_update"
    ORDER_UPDATE = "order_update"
    ACCOUNT_UPDATE = "account_update"
    FILL_EVENT = "fill_event"
    PNL_UPDATE = "pnl_update"
    HEARTBEAT = "heartbeat"
    ERROR = "error"
    CONNECTED = "connected"
    MARKET_DATA_UPDATE = "market_data_update"


class WsPositionItem(BaseModel):
    """Single position in a WebSocket position update."""

    symbol: str
    quantity: Decimal
    average_entry_price: Decimal
    market_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal = Field(default=Decimal("0"))

    model_config = {"frozen": True}


class WsPositionUpdate(BaseModel):
    """Payload for position_update messages."""

    positions: list[WsPositionItem]
    total_positions: int = 0

    model_config = {"frozen": True}


class WsOrderUpdate(BaseModel):
    """Payload for order_update messages."""

    client_order_id: str
    broker_order_id: str | None = None
    symbol: str
    side: str
    order_type: str
    quantity: Decimal
    filled_quantity: Decimal = Field(default=Decimal("0"))
    average_fill_price: Decimal | None = None
    status: str
    submitted_at: datetime | None = None

    model_config = {"frozen": True}


class WsAccountUpdate(BaseModel):
    """Payload for account_update messages."""

    equity: Decimal
    cash: Decimal
    buying_power: Decimal
    portfolio_value: Decimal
    daily_pnl: Decimal = Field(default=Decimal("0"))
    pending_orders_count: int = 0
    positions_count: int = 0

    model_config = {"frozen": True}


class WsFillEvent(BaseModel):
    """Payload for fill_event messages."""

    fill_id: str
    order_id: str
    symbol: str
    side: str
    price: Decimal
    quantity: Decimal
    filled_at: datetime

    model_config = {"frozen": True}


class WsPnlUpdate(BaseModel):
    """Payload for pnl_update messages."""

    total_unrealized_pnl: Decimal
    total_realized_pnl: Decimal
    daily_pnl: Decimal
    total_equity: Decimal

    model_config = {"frozen": True}


class WsMarketDataUpdate(BaseModel):
    """Payload for market_data_update messages (real-time candle bars)."""

    symbol: str
    interval: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = 0
    vwap: Decimal | None = None
    trade_count: int | None = None
    timestamp: datetime

    model_config = {"frozen": True}


class WsMessage(BaseModel):
    """
    Top-level WebSocket message envelope.

    Every message sent over the WebSocket connection is wrapped in this
    envelope. The msg_type discriminator determines the payload schema.

    Attributes:
        msg_type: Message type discriminator.
        deployment_id: Deployment this message pertains to.
        timestamp: Server timestamp when the message was created.
        payload: Type-specific payload dict (serialized from typed models).

    Example:
        msg = WsMessage(
            msg_type=WsMessageType.POSITION_UPDATE,
            deployment_id="01HDEPLOY...",
            payload={"positions": [...], "total_positions": 5},
        )
    """

    msg_type: WsMessageType
    deployment_id: str
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


__all__ = [
    "WsAccountUpdate",
    "WsFillEvent",
    "WsMarketDataUpdate",
    "WsMessage",
    "WsMessageType",
    "WsOrderUpdate",
    "WsPnlUpdate",
    "WsPositionItem",
    "WsPositionUpdate",
]
