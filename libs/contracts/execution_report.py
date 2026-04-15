"""
Order history and execution reporting contracts.

Responsibilities:
- Define schemas for paginated order history queries and responses.
- Define aggregated execution quality metrics and reports.
- Provide structured contracts for order history filtering, sorting, and export.

Does NOT:
- Contain business logic or execution analysis.
- Perform I/O or network calls.
- Know about specific repositories or databases.

Dependencies:
- pydantic: BaseModel, Field
- datetime, decimal: standard library types

Error conditions:
- Pydantic ValidationError raised on invalid field values.

Example:
    from libs.contracts.execution_report import OrderHistoryQuery, ExecutionReportSummary

    query = OrderHistoryQuery(
        symbol="AAPL",
        status="filled",
        date_from=datetime(2026, 4, 1),
        page=1,
        page_size=50,
    )

    report = ExecutionReportSummary(
        date_from=datetime(2026, 4, 1),
        date_to=datetime(2026, 4, 11),
        total_orders=150,
        filled_orders=142,
        fill_rate=Decimal("94.67"),
    )
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Order History Query
# ---------------------------------------------------------------------------


class OrderHistoryQuery(BaseModel):
    """
    Query parameters for paginated order history.

    Attributes:
        deployment_id: Filter by deployment ULID (optional).
        symbol: Filter by instrument ticker (optional).
        side: Filter by side: "buy" or "sell" (optional).
        status: Filter by order status (pending, submitted, filled, cancelled, etc.)
                (optional).
        execution_mode: Filter by mode: "shadow", "paper", or "live" (optional).
        date_from: Inclusive start datetime for order submission (optional).
        date_to: Inclusive end datetime for order submission (optional).
        sort_by: Column to sort by (default: "submitted_at").
        sort_dir: Sort direction: "asc" or "desc" (default: "desc").
        page: Page number (1-indexed, default: 1).
        page_size: Items per page (default: 50, max: 500).

    Example:
        query = OrderHistoryQuery(
            symbol="AAPL",
            status="filled",
            execution_mode="live",
            date_from=datetime(2026, 4, 1),
            date_to=datetime(2026, 4, 11),
            page=1,
            page_size=50,
        )
    """

    deployment_id: str | None = Field(default=None, min_length=1)
    symbol: str | None = Field(default=None, min_length=1, max_length=20)
    side: str | None = Field(default=None)
    status: str | None = Field(default=None)
    execution_mode: str | None = Field(default=None)
    date_from: datetime | None = None
    date_to: datetime | None = None
    sort_by: str = Field(default="submitted_at", min_length=1, max_length=50)
    sort_dir: str = Field(default="desc")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Fill Item
# ---------------------------------------------------------------------------


class FillItem(BaseModel):
    """
    Individual fill record within an order.

    Attributes:
        fill_id: Unique fill identifier.
        price: Execution price per unit.
        quantity: Number of units filled in this fill event.
        commission: Broker commission charged for this fill.
        filled_at: When this fill occurred.
        broker_execution_id: Broker-assigned execution ID (optional).

    Example:
        fill = FillItem(
            fill_id="fill-001",
            price=Decimal("175.50"),
            quantity=Decimal("50"),
            commission=Decimal("1.50"),
            filled_at=datetime(2026, 4, 11, 10, 0, 0),
            broker_execution_id="ALPACA-exec-abc",
        )
    """

    fill_id: str = Field(..., min_length=1)
    price: Decimal = Field(..., gt=0)
    quantity: Decimal = Field(..., gt=0)
    commission: Decimal = Field(default=Decimal("0"), ge=0)
    filled_at: datetime
    broker_execution_id: str | None = Field(default=None, min_length=1)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Order History Item
# ---------------------------------------------------------------------------


class OrderHistoryItem(BaseModel):
    """
    Single order in the order history list.

    Represents a complete order record including all fills, timestamps,
    and execution details for a single order submission.

    Attributes:
        order_id: Client order ID (idempotency key).
        client_order_id: Duplicate of order_id for clarity.
        broker_order_id: Broker-assigned order ID (nullable until broker ack).
        deployment_id: ULID of the owning deployment.
        strategy_id: ULID of the originating strategy.
        symbol: Instrument ticker (e.g. "AAPL").
        side: Order direction: "buy" or "sell".
        order_type: Type: "market", "limit", "stop", "stop_limit".
        quantity: Requested quantity.
        filled_quantity: Cumulative filled quantity (default: 0).
        average_fill_price: Volume-weighted average fill price (optional).
        limit_price: Limit price for limit/stop-limit orders (optional).
        stop_price: Stop price for stop/stop-limit orders (optional).
        status: Order status (pending, submitted, partial_fill, filled, etc.).
        time_in_force: Duration policy (day, gtc, ioc, fok).
        execution_mode: Mode: "shadow", "paper", or "live".
        correlation_id: Distributed tracing ID.
        submitted_at: When the order was submitted to broker (optional).
        filled_at: When the order was fully filled (optional).
        cancelled_at: When the order was cancelled (optional).
        rejected_reason: Human-readable rejection reason (optional).
        created_at: When the order record was created.
        fills: List of all fill events for this order (default: empty list).

    Example:
        item = OrderHistoryItem(
            order_id="ord-001",
            client_order_id="ord-001",
            broker_order_id="ALPACA-12345",
            deployment_id="01HDEPLOY123",
            strategy_id="01HSTRAT456",
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity=Decimal("100"),
            filled_quantity=Decimal("100"),
            average_fill_price=Decimal("175.50"),
            status="filled",
            time_in_force="day",
            execution_mode="paper",
            correlation_id="corr-abc",
            submitted_at=datetime(2026, 4, 11, 10, 0, 0),
            filled_at=datetime(2026, 4, 11, 10, 0, 1),
            created_at=datetime(2026, 4, 11, 10, 0, 0),
            fills=[
                FillItem(
                    fill_id="fill-001",
                    price=Decimal("175.50"),
                    quantity=Decimal("100"),
                    filled_at=datetime(2026, 4, 11, 10, 0, 1),
                )
            ],
        )
    """

    order_id: str = Field(..., min_length=1)
    client_order_id: str = Field(..., min_length=1)
    broker_order_id: str | None = Field(default=None, min_length=1)
    deployment_id: str = Field(..., min_length=1)
    strategy_id: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1, max_length=20)
    side: str = Field(..., min_length=1)
    order_type: str = Field(..., min_length=1)
    quantity: Decimal = Field(..., gt=0)
    filled_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    average_fill_price: Decimal | None = Field(default=None, gt=0)
    limit_price: Decimal | None = Field(default=None, gt=0)
    stop_price: Decimal | None = Field(default=None, gt=0)
    status: str = Field(..., min_length=1)
    time_in_force: str = Field(..., min_length=1)
    execution_mode: str = Field(..., min_length=1)
    correlation_id: str = Field(..., min_length=1)
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    cancelled_at: datetime | None = None
    rejected_reason: str | None = Field(default=None, min_length=1)
    created_at: datetime
    fills: list[FillItem] = Field(default_factory=list)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Paginated Order History Response
# ---------------------------------------------------------------------------


class OrderHistoryPage(BaseModel):
    """
    Paginated response containing a page of order history items.

    Attributes:
        items: List of OrderHistoryItem for this page.
        total: Total number of matching orders (ignoring pagination).
        page: Current page number (1-indexed).
        page_size: Items per page.
        total_pages: Total number of pages (ceil(total / page_size)).

    Example:
        page = OrderHistoryPage(
            items=[item1, item2, ...],
            total=250,
            page=1,
            page_size=50,
            total_pages=5,
        )
    """

    items: list[OrderHistoryItem] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_pages: int = Field(ge=0)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Execution Report Breakdowns
# ---------------------------------------------------------------------------


class SymbolBreakdown(BaseModel):
    """
    Execution metrics aggregated by symbol.

    Attributes:
        symbol: Instrument ticker.
        total_orders: Count of orders for this symbol.
        filled_orders: Count of filled orders.
        fill_rate: Percentage of orders that were filled.
        total_volume: Sum of all filled quantities.
        avg_fill_price: Average fill price across all fills (optional).
        avg_slippage_pct: Average slippage (fill - limit) / limit % (optional).

    Example:
        breakdown = SymbolBreakdown(
            symbol="AAPL",
            total_orders=50,
            filled_orders=47,
            fill_rate=Decimal("94.00"),
            total_volume=Decimal("4700"),
            avg_fill_price=Decimal("175.50"),
            avg_slippage_pct=Decimal("0.15"),
        )
    """

    symbol: str = Field(..., min_length=1, max_length=20)
    total_orders: int = Field(ge=0)
    filled_orders: int = Field(ge=0)
    fill_rate: Decimal = Field(ge=0, le=100)
    total_volume: Decimal = Field(ge=0)
    avg_fill_price: Decimal | None = Field(default=None, gt=0)
    avg_slippage_pct: Decimal | None = Field(default=None)

    model_config = {"frozen": True}


class ModeBreakdown(BaseModel):
    """
    Execution metrics aggregated by execution mode.

    Attributes:
        execution_mode: Mode: "shadow", "paper", or "live".
        total_orders: Count of orders in this mode.
        filled_orders: Count of filled orders.
        fill_rate: Percentage of orders that were filled.
        total_volume: Sum of all filled quantities.

    Example:
        breakdown = ModeBreakdown(
            execution_mode="paper",
            total_orders=100,
            filled_orders=95,
            fill_rate=Decimal("95.00"),
            total_volume=Decimal("9500"),
        )
    """

    execution_mode: str = Field(..., min_length=1)
    total_orders: int = Field(ge=0)
    filled_orders: int = Field(ge=0)
    fill_rate: Decimal = Field(ge=0, le=100)
    total_volume: Decimal = Field(ge=0)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Execution Report Summary
# ---------------------------------------------------------------------------


class ExecutionReportSummary(BaseModel):
    """
    Aggregate execution quality metrics over a date range.

    Provides comprehensive execution analysis including fill rates, volumes,
    slippage, latency percentiles, and breakdowns by symbol and execution mode.

    Attributes:
        date_from: Start of reporting period (inclusive).
        date_to: End of reporting period (inclusive).
        total_orders: Total number of orders submitted.
        filled_orders: Number of filled orders (including partial fills).
        cancelled_orders: Number of cancelled orders.
        rejected_orders: Number of rejected orders.
        partial_fills: Number of orders with partial fills (filled < requested).
        fill_rate: Percentage of orders that were filled (filled / total).
        total_volume: Sum of all filled quantities.
        total_commission: Sum of all commissions paid.
        symbols_traded: List of unique symbols in the period.
        avg_slippage_pct: Average slippage across limit orders (optional).
        latency_p50_ms: 50th percentile order latency in milliseconds (optional).
        latency_p95_ms: 95th percentile order latency in milliseconds (optional).
        latency_p99_ms: 99th percentile order latency in milliseconds (optional).
        by_symbol: Breakdown of metrics by symbol.
        by_execution_mode: Breakdown of metrics by execution mode.

    Example:
        report = ExecutionReportSummary(
            date_from=datetime(2026, 4, 1),
            date_to=datetime(2026, 4, 11),
            total_orders=150,
            filled_orders=142,
            cancelled_orders=5,
            rejected_orders=3,
            partial_fills=8,
            fill_rate=Decimal("94.67"),
            total_volume=Decimal("14200"),
            total_commission=Decimal("142.00"),
            symbols_traded=["AAPL", "MSFT", "GOOGL"],
            avg_slippage_pct=Decimal("0.12"),
            latency_p50_ms=45,
            latency_p95_ms=120,
            latency_p99_ms=250,
            by_symbol=[
                SymbolBreakdown(symbol="AAPL", total_orders=50, ...),
                SymbolBreakdown(symbol="MSFT", total_orders=50, ...),
            ],
            by_execution_mode=[
                ModeBreakdown(execution_mode="paper", total_orders=100, ...),
                ModeBreakdown(execution_mode="live", total_orders=50, ...),
            ],
        )
    """

    date_from: datetime
    date_to: datetime
    total_orders: int = Field(ge=0)
    filled_orders: int = Field(ge=0)
    cancelled_orders: int = Field(default=0, ge=0)
    rejected_orders: int = Field(default=0, ge=0)
    partial_fills: int = Field(default=0, ge=0)
    fill_rate: Decimal = Field(ge=0, le=100)
    total_volume: Decimal = Field(default=Decimal("0"), ge=0)
    total_commission: Decimal = Field(default=Decimal("0"), ge=0)
    symbols_traded: list[str] = Field(default_factory=list)
    avg_slippage_pct: Decimal | None = Field(default=None)
    latency_p50_ms: int | None = Field(default=None, ge=0)
    latency_p95_ms: int | None = Field(default=None, ge=0)
    latency_p99_ms: int | None = Field(default=None, ge=0)
    by_symbol: list[SymbolBreakdown] = Field(default_factory=list)
    by_execution_mode: list[ModeBreakdown] = Field(default_factory=list)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "OrderHistoryQuery",
    "FillItem",
    "OrderHistoryItem",
    "OrderHistoryPage",
    "SymbolBreakdown",
    "ModeBreakdown",
    "ExecutionReportSummary",
]
