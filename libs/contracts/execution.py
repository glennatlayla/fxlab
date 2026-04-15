"""
Normalized execution contracts for broker adapter layer.

Responsibilities:
- Define the canonical order, fill, position, and account data structures
  used across all execution modes (shadow, paper, live).
- Provide Pydantic schemas for runtime validation of broker adapter I/O.
- Normalize heterogeneous broker responses into a single model family.

Does NOT:
- Contain business logic or execution orchestration.
- Know about specific broker APIs (Alpaca, Interactive Brokers, etc.).
- Perform I/O or network calls.

Dependencies:
- pydantic: BaseModel, Field, validator
- datetime, decimal: standard library types

Error conditions:
- Pydantic ValidationError raised on invalid field values.

Example:
    from libs.contracts.execution import OrderRequest, OrderSide, OrderType

    req = OrderRequest(
        client_order_id="ord-001",
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("100"),
        time_in_force=TimeInForce.DAY,
        deployment_id="01DEPLOY...",
        strategy_id="01STRAT...",
        correlation_id="corr-abc",
        execution_mode=ExecutionMode.PAPER,
    )
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OrderSide(str, Enum):
    """Order direction."""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Order type classification."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class TimeInForce(str, Enum):
    """Order time-in-force policy."""

    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"


class OrderStatus(str, Enum):
    """
    Normalized order lifecycle status.

    Transitions:
        pending → submitted → partial_fill → filled
        pending → submitted → cancelled
        pending → submitted → rejected
        pending → submitted → expired
    """

    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL_FILL = "partial_fill"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ExecutionMode(str, Enum):
    """Deployment execution mode."""

    SHADOW = "shadow"
    PAPER = "paper"
    LIVE = "live"


class ConnectionStatus(str, Enum):
    """Broker adapter connection state."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Order schemas
# ---------------------------------------------------------------------------


class OrderRequest(BaseModel):
    """
    Normalized order submission payload.

    The client_order_id enforces idempotency: if the broker adapter receives
    a duplicate client_order_id it must return the existing order rather than
    submitting a new one.

    Attributes:
        client_order_id: Unique idempotency key set by the caller.
        symbol: Instrument ticker (e.g. "AAPL", "ES=F").
        side: BUY or SELL.
        order_type: MARKET, LIMIT, STOP, or STOP_LIMIT.
        quantity: Number of units. Must be positive.
        limit_price: Required for LIMIT and STOP_LIMIT orders.
        stop_price: Required for STOP and STOP_LIMIT orders.
        time_in_force: Duration policy (DAY, GTC, IOC, FOK).
        deployment_id: ULID of the owning deployment.
        strategy_id: ULID of the originating strategy.
        correlation_id: Distributed tracing ID propagated from the signal.
        execution_mode: Which execution mode produced this order.
        metadata: Optional extra context (signal details, regime state, etc.).

    Example:
        req = OrderRequest(
            client_order_id="ord-001",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            time_in_force=TimeInForce.DAY,
            deployment_id="01DEPLOY...",
            strategy_id="01STRAT...",
            correlation_id="corr-abc",
            execution_mode=ExecutionMode.PAPER,
        )
    """

    client_order_id: str = Field(
        ..., min_length=1, max_length=255, description="Unique idempotency key"
    )
    symbol: str = Field(..., min_length=1, max_length=50, description="Instrument ticker")
    side: OrderSide
    order_type: OrderType
    quantity: Decimal = Field(..., gt=0, description="Order quantity (must be positive)")
    limit_price: Decimal | None = Field(
        default=None, gt=0, description="Limit price (required for LIMIT/STOP_LIMIT)"
    )
    stop_price: Decimal | None = Field(
        default=None, gt=0, description="Stop price (required for STOP/STOP_LIMIT)"
    )
    time_in_force: TimeInForce = Field(default=TimeInForce.DAY)
    deployment_id: str = Field(..., min_length=1, max_length=26)
    strategy_id: str = Field(..., min_length=1, max_length=26)
    correlation_id: str = Field(..., min_length=1, max_length=255)
    execution_mode: ExecutionMode
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_price_requirements(self) -> OrderRequest:
        """
        Validate conditional price requirements based on order_type.

        - LIMIT and STOP_LIMIT require limit_price.
        - STOP and STOP_LIMIT require stop_price.
        """
        if self.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and self.limit_price is None:
            raise ValueError(f"limit_price is required for {self.order_type} orders")
        if self.order_type in (OrderType.STOP, OrderType.STOP_LIMIT) and self.stop_price is None:
            raise ValueError(f"stop_price is required for {self.order_type} orders")
        return self

    model_config = {"frozen": True}


class OrderResponse(BaseModel):
    """
    Normalized broker order acknowledgment / status response.

    Returned by the adapter on submit, cancel, and query operations.

    Attributes:
        client_order_id: Echoed idempotency key.
        broker_order_id: Broker-assigned order identifier (nullable until broker ack).
        symbol: Instrument ticker.
        side: Order direction.
        order_type: Order type.
        quantity: Requested quantity.
        filled_quantity: Cumulative filled quantity.
        average_fill_price: Volume-weighted average fill price.
        status: Current order lifecycle status.
        limit_price: Limit price (if applicable).
        stop_price: Stop price (if applicable).
        time_in_force: Duration policy.
        submitted_at: When the order was submitted to the broker.
        filled_at: When the order was fully filled (nullable until filled).
        cancelled_at: When the order was cancelled (nullable unless cancelled).
        rejected_reason: Human-readable rejection reason (nullable unless rejected).
        correlation_id: Distributed tracing ID.
        execution_mode: Which execution mode this order belongs to.

    Example:
        resp = OrderResponse(
            client_order_id="ord-001",
            broker_order_id="ALPACA-12345",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            filled_quantity=Decimal("100"),
            average_fill_price=Decimal("175.50"),
            status=OrderStatus.FILLED,
            time_in_force=TimeInForce.DAY,
            submitted_at=datetime(2026, 4, 11, 10, 0, 0),
            filled_at=datetime(2026, 4, 11, 10, 0, 1),
            correlation_id="corr-abc",
            execution_mode=ExecutionMode.PAPER,
        )
    """

    client_order_id: str
    broker_order_id: str | None = None
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    filled_quantity: Decimal = Field(default=Decimal("0"))
    average_fill_price: Decimal | None = None
    status: OrderStatus
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: TimeInForce
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    cancelled_at: datetime | None = None
    rejected_reason: str | None = None
    correlation_id: str
    execution_mode: ExecutionMode

    model_config = {"frozen": True}


class OrderFillEvent(BaseModel):
    """
    Individual fill event for an order.

    A single order may generate multiple fills (partial fills). Each fill
    records the price, quantity, commission, and broker-assigned execution ID.

    Attributes:
        fill_id: Unique fill identifier (broker-assigned or generated).
        order_id: Client order ID this fill belongs to.
        broker_order_id: Broker-assigned order ID.
        symbol: Instrument ticker.
        side: Fill direction.
        price: Execution price per unit.
        quantity: Number of units filled in this event.
        commission: Broker commission charged for this fill.
        filled_at: When this fill occurred.
        broker_execution_id: Broker-assigned execution/trade ID.
        correlation_id: Distributed tracing ID.

    Example:
        fill = OrderFillEvent(
            fill_id="fill-001",
            order_id="ord-001",
            broker_order_id="ALPACA-12345",
            symbol="AAPL",
            side=OrderSide.BUY,
            price=Decimal("175.50"),
            quantity=Decimal("50"),
            commission=Decimal("0.00"),
            filled_at=datetime(2026, 4, 11, 10, 0, 0),
            broker_execution_id="exec-abc",
            correlation_id="corr-abc",
        )
    """

    fill_id: str
    order_id: str
    broker_order_id: str | None = None
    symbol: str
    side: OrderSide
    price: Decimal = Field(..., gt=0)
    quantity: Decimal = Field(..., gt=0)
    commission: Decimal = Field(default=Decimal("0"))
    filled_at: datetime
    broker_execution_id: str | None = None
    correlation_id: str

    model_config = {"frozen": True}


class OrderEvent(BaseModel):
    """
    Lifecycle event in an order's timeline.

    Used to reconstruct the full decision-to-execution chain for debugging
    and compliance replay.

    Attributes:
        event_id: Unique event identifier.
        order_id: Client order ID.
        event_type: Lifecycle event type (submitted, partial_fill, filled,
                    cancelled, rejected, risk_checked, risk_failed).
        timestamp: When the event occurred.
        details: Event-specific context (rejection reason, fill data, etc.).
        correlation_id: Distributed tracing ID.

    Example:
        event = OrderEvent(
            event_id="evt-001",
            order_id="ord-001",
            event_type="submitted",
            timestamp=datetime(2026, 4, 11, 10, 0, 0),
            details={"broker_order_id": "ALPACA-12345"},
            correlation_id="corr-abc",
        )
    """

    event_id: str
    order_id: str
    event_type: str = Field(..., min_length=1, max_length=50)
    timestamp: datetime
    details: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Price update schema (real-time market data)
# ---------------------------------------------------------------------------


class PriceUpdate(BaseModel):
    """
    Normalized real-time price update from a market data stream.

    Represents a single trade or quote update received via WebSocket.
    Used to feed paper/shadow adapters with live market prices.

    Attributes:
        symbol: Instrument ticker (e.g. "AAPL").
        price: Trade or mid price.
        size: Trade size in shares (0 for quote-only).
        timestamp: Exchange timestamp of the trade/quote.
        feed: Data feed source (e.g. "iex", "sip").
        conditions: Trade condition codes from the exchange.

    Example:
        update = PriceUpdate(
            symbol="AAPL",
            price=Decimal("185.50"),
            size=100,
            timestamp=datetime(2026, 4, 11, 14, 30, 0, tzinfo=timezone.utc),
            feed="iex",
        )
    """

    symbol: str = Field(..., min_length=1, max_length=10)
    price: Decimal = Field(..., gt=0)
    size: int = Field(default=0, ge=0)
    timestamp: datetime
    feed: str = Field(default="iex", max_length=10)
    conditions: list[str] = Field(default_factory=list)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Position / Account schemas
# ---------------------------------------------------------------------------


class PositionSnapshot(BaseModel):
    """
    Account position state for a single instrument.

    Attributes:
        symbol: Instrument ticker.
        quantity: Current position size (negative for short).
        average_entry_price: Volume-weighted average entry price.
        market_price: Latest market price.
        market_value: quantity × market_price.
        unrealized_pnl: (market_price - average_entry_price) × quantity.
        realized_pnl: Cumulative closed P&L for this symbol.
        cost_basis: Total cost basis.
        updated_at: When this snapshot was taken.

    Example:
        pos = PositionSnapshot(
            symbol="AAPL",
            quantity=Decimal("100"),
            average_entry_price=Decimal("175.00"),
            market_price=Decimal("180.00"),
            market_value=Decimal("18000.00"),
            unrealized_pnl=Decimal("500.00"),
            realized_pnl=Decimal("0.00"),
            cost_basis=Decimal("17500.00"),
            updated_at=datetime(2026, 4, 11, 10, 0, 0),
        )
    """

    symbol: str
    quantity: Decimal
    average_entry_price: Decimal
    market_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal = Field(default=Decimal("0"))
    cost_basis: Decimal
    updated_at: datetime

    model_config = {"frozen": True}


class AccountSnapshot(BaseModel):
    """
    Account-level balance and margin summary.

    Attributes:
        account_id: Broker account identifier.
        equity: Total account equity.
        cash: Available cash balance.
        buying_power: Available buying power (margin-adjusted).
        portfolio_value: Total portfolio market value.
        daily_pnl: Today's realized + unrealized P&L.
        pending_orders_count: Number of open/pending orders.
        positions_count: Number of open positions.
        updated_at: When this snapshot was taken.

    Example:
        acct = AccountSnapshot(
            account_id="ACCT-001",
            equity=Decimal("100000.00"),
            cash=Decimal("50000.00"),
            buying_power=Decimal("200000.00"),
            portfolio_value=Decimal("50000.00"),
            daily_pnl=Decimal("500.00"),
            pending_orders_count=2,
            positions_count=3,
            updated_at=datetime(2026, 4, 11, 10, 0, 0),
        )
    """

    account_id: str
    equity: Decimal
    cash: Decimal
    buying_power: Decimal
    portfolio_value: Decimal
    daily_pnl: Decimal = Field(default=Decimal("0"))
    pending_orders_count: int = Field(default=0, ge=0)
    positions_count: int = Field(default=0, ge=0)
    updated_at: datetime

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Adapter diagnostics
# ---------------------------------------------------------------------------


class AdapterDiagnostics(BaseModel):
    """
    Broker adapter health and performance diagnostics.

    Attributes:
        broker_name: Identifier of the broker adapter (e.g. "alpaca", "paper").
        connection_status: Current connection state.
        latency_ms: Round-trip latency to broker in milliseconds.
        error_count_1h: Number of errors in the last hour.
        last_heartbeat: Timestamp of last successful broker heartbeat.
        last_error: Most recent error message (nullable if no errors).
        market_open: Whether the target market is currently in trading hours.
        orders_submitted_today: Count of orders submitted in current session.
        orders_filled_today: Count of orders filled in current session.
        uptime_seconds: Seconds since adapter initialization.

    Example:
        diag = AdapterDiagnostics(
            broker_name="alpaca",
            connection_status=ConnectionStatus.CONNECTED,
            latency_ms=45,
            error_count_1h=0,
            last_heartbeat=datetime(2026, 4, 11, 10, 0, 0),
            market_open=True,
            orders_submitted_today=15,
            orders_filled_today=12,
            uptime_seconds=3600,
        )
    """

    broker_name: str
    connection_status: ConnectionStatus
    latency_ms: int = Field(ge=0)
    error_count_1h: int = Field(default=0, ge=0)
    last_heartbeat: datetime | None = None
    last_error: str | None = None
    market_open: bool = False
    orders_submitted_today: int = Field(default=0, ge=0)
    orders_filled_today: int = Field(default=0, ge=0)
    uptime_seconds: int = Field(default=0, ge=0)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "OrderSide",
    "OrderType",
    "TimeInForce",
    "OrderStatus",
    "ExecutionMode",
    "ConnectionStatus",
    "OrderRequest",
    "OrderResponse",
    "OrderFillEvent",
    "OrderEvent",
    "PriceUpdate",
    "PositionSnapshot",
    "AccountSnapshot",
    "AdapterDiagnostics",
]
