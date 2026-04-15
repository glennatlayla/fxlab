"""
Trade execution reports for regulatory compliance.

Responsibilities:
- Define Pydantic schemas for regulatory compliance reporting.
- Provide models for execution compliance, best execution analysis,
  venue routing statistics, and monthly compliance summaries.
- Support SEC Rule 606, MiFID II, and similar compliance frameworks.

Does NOT:
- Contain business logic for report generation or analysis.
- Perform I/O, database access, or external API calls.
- Know about specific repositories or services.

Dependencies:
- pydantic: BaseModel, Field
- datetime, decimal: standard library types

Error conditions:
- Pydantic ValidationError raised on invalid field values.

Example:
    from libs.contracts.compliance_report import (
        ExecutionComplianceReport,
        BestExecutionReport,
        MonthlySummary,
    )

    report = ExecutionComplianceReport(
        report_id="comp-001",
        date_from=datetime(2026, 4, 1),
        date_to=datetime(2026, 4, 30),
        generated_at=datetime(2026, 5, 1, 10, 0, 0),
        total_orders=500,
        total_filled=475,
        total_cancelled=20,
        total_rejected=5,
        total_volume=Decimal("47500"),
        total_commission=Decimal("475.00"),
        orders=[],
    )
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Execution Compliance Report
# ---------------------------------------------------------------------------


class ComplianceOrderRecord(BaseModel):
    """
    Single order record for compliance execution report.

    Represents a complete order record suitable for regulatory review
    (SEC Rule 606, MiFID II, FINRA, etc.). Includes all required order
    details, execution metrics, and compliance-relevant timestamps.

    Attributes:
        order_id: Client order ID (idempotency key).
        client_order_id: Duplicate of order_id for clarity.
        broker_order_id: Broker-assigned order ID (nullable until acknowledgment).
        symbol: Instrument ticker (e.g., "AAPL", "ES=F").
        side: Order direction: "buy" or "sell".
        order_type: Type: "market", "limit", "stop", "stop_limit".
        quantity: Requested order quantity (must be positive).
        filled_quantity: Cumulative filled quantity (default: 0).
        average_fill_price: Volume-weighted average fill price (optional).
        limit_price: Limit price for limit/stop-limit orders (optional).
        status: Order status (pending, submitted, filled, cancelled, rejected, etc.).
        execution_mode: Execution mode: "shadow", "paper", or "live".
        venue: Execution venue or routing destination (default: empty string).
        submitted_at: When the order was submitted to the broker (optional).
        filled_at: When the order was fully filled (optional).
        cancelled_at: When the order was cancelled (optional).
        commission: Broker commission charged for this order (default: 0).
        correlation_id: Distributed tracing ID for order tracking.

    Example:
        record = ComplianceOrderRecord(
            order_id="ord-001",
            client_order_id="ord-001",
            broker_order_id="ALPACA-12345",
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity=Decimal("100"),
            filled_quantity=Decimal("100"),
            average_fill_price=Decimal("175.50"),
            status="filled",
            execution_mode="live",
            venue="NASDAQ",
            submitted_at=datetime(2026, 4, 11, 10, 0, 0),
            filled_at=datetime(2026, 4, 11, 10, 0, 1),
            commission=Decimal("1.50"),
            correlation_id="corr-abc",
        )
    """

    order_id: str = Field(..., min_length=1, description="Client order ID")
    client_order_id: str = Field(..., min_length=1, description="Duplicate of order_id")
    broker_order_id: str | None = Field(default=None, min_length=1)
    symbol: str = Field(..., min_length=1, max_length=20, description="Instrument ticker")
    side: str = Field(..., min_length=1, description="buy or sell")
    order_type: str = Field(..., min_length=1, description="market, limit, stop, or stop_limit")
    quantity: Decimal = Field(..., gt=0, description="Order quantity")
    filled_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    average_fill_price: Decimal | None = Field(default=None, gt=0)
    limit_price: Decimal | None = Field(default=None, gt=0)
    status: str = Field(..., min_length=1, description="Order status")
    execution_mode: str = Field(..., min_length=1, description="shadow, paper, or live")
    venue: str = Field(
        default="", max_length=50, description="Execution venue or routing destination"
    )
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    cancelled_at: datetime | None = None
    commission: Decimal = Field(default=Decimal("0"), ge=0)
    correlation_id: str = Field(..., min_length=1)

    model_config = {"frozen": True}


class ExecutionComplianceReport(BaseModel):
    """
    Full execution report suitable for regulatory review.

    Aggregate compliance report covering all orders within a date range,
    including summary statistics and per-order details. Designed to support
    SEC Rule 606 (equities), FINRA rules, and MiFID II requirements.

    Attributes:
        report_id: Unique compliance report identifier.
        date_from: Start of reporting period (inclusive).
        date_to: End of reporting period (inclusive).
        generated_at: When the report was generated.
        total_orders: Total number of orders submitted in the period.
        total_filled: Number of fully filled orders.
        total_cancelled: Number of cancelled orders.
        total_rejected: Number of rejected orders.
        total_volume: Sum of all filled quantities.
        total_commission: Sum of all commissions paid.
        orders: List of all order records (ComplianceOrderRecord).

    Example:
        report = ExecutionComplianceReport(
            report_id="comp-2026-04",
            date_from=datetime(2026, 4, 1),
            date_to=datetime(2026, 4, 30),
            generated_at=datetime(2026, 5, 1, 10, 0, 0),
            total_orders=500,
            total_filled=475,
            total_cancelled=20,
            total_rejected=5,
            total_volume=Decimal("47500"),
            total_commission=Decimal("475.00"),
            orders=[...],
        )
    """

    report_id: str = Field(..., min_length=1, description="Unique report identifier")
    date_from: datetime
    date_to: datetime
    generated_at: datetime
    total_orders: int = Field(ge=0)
    total_filled: int = Field(ge=0)
    total_cancelled: int = Field(default=0, ge=0)
    total_rejected: int = Field(default=0, ge=0)
    total_volume: Decimal = Field(default=Decimal("0"), ge=0)
    total_commission: Decimal = Field(default=Decimal("0"), ge=0)
    orders: list[ComplianceOrderRecord] = Field(default_factory=list)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Best Execution Report
# ---------------------------------------------------------------------------


class BestExecutionRecord(BaseModel):
    """
    Best execution analysis for a single filled order.

    Captures price improvement analysis per MiFID II and similar frameworks.
    Compares actual fill price against National Best Bid/Offer (NBBO) and
    limit price to quantify execution quality.

    Attributes:
        order_id: Client order ID.
        symbol: Instrument ticker.
        side: Order direction: "buy" or "sell".
        fill_price: Actual execution price per unit.
        nbbo_bid: National Best Bid at time of fill (optional).
        nbbo_ask: National Best Offer at time of fill (optional).
        nbbo_midpoint: Midpoint of NBBO at time of fill (optional).
        price_improvement: Improvement vs. NBBO midpoint in currency (optional).
                          Positive = better than mid.
        slippage_bps: Basis points slippage vs. limit price (optional).
        fill_latency_ms: Milliseconds from order submission to fill (optional).
        venue: Execution venue or exchange name.
        filled_at: When the order was filled (optional).

    Example:
        record = BestExecutionRecord(
            order_id="ord-001",
            symbol="AAPL",
            side="buy",
            fill_price=Decimal("175.50"),
            nbbo_bid=Decimal("175.45"),
            nbbo_ask=Decimal("175.55"),
            nbbo_midpoint=Decimal("175.50"),
            price_improvement=Decimal("0.00"),
            slippage_bps=Decimal("0"),
            fill_latency_ms=150,
            venue="NASDAQ",
            filled_at=datetime(2026, 4, 11, 10, 0, 1),
        )
    """

    order_id: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1, max_length=20)
    side: str = Field(..., min_length=1, description="buy or sell")
    fill_price: Decimal = Field(..., gt=0)
    nbbo_bid: Decimal | None = Field(default=None, gt=0)
    nbbo_ask: Decimal | None = Field(default=None, gt=0)
    nbbo_midpoint: Decimal | None = Field(default=None, gt=0)
    price_improvement: Decimal | None = Field(
        default=None, description="Positive = better than NBBO mid"
    )
    slippage_bps: Decimal | None = Field(default=None, description="Basis points vs limit price")
    fill_latency_ms: int | None = Field(default=None, ge=0)
    venue: str = Field(default="", max_length=50)
    filled_at: datetime | None = None

    model_config = {"frozen": True}


class BestExecutionReport(BaseModel):
    """
    Aggregate best execution analysis report.

    Summary statistics and detailed records for best execution analysis
    across all filled orders in a period, supporting MiFID II and SEC
    Rule 606(c) compliance reporting.

    Attributes:
        report_id: Unique report identifier.
        date_from: Start of reporting period (inclusive).
        date_to: End of reporting period (inclusive).
        generated_at: When the report was generated.
        total_analyzed: Number of filled orders analyzed.
        avg_price_improvement_bps: Average price improvement in basis points (optional).
        avg_slippage_bps: Average slippage in basis points (optional).
        avg_fill_latency_ms: Average fill latency in milliseconds (optional).
        pct_with_price_improvement: Percentage of orders with positive price improvement (optional).
        records: List of individual BestExecutionRecord entries.

    Example:
        report = BestExecutionReport(
            report_id="best-exec-2026-04",
            date_from=datetime(2026, 4, 1),
            date_to=datetime(2026, 4, 30),
            generated_at=datetime(2026, 5, 1, 10, 0, 0),
            total_analyzed=475,
            avg_price_improvement_bps=Decimal("2.50"),
            avg_slippage_bps=Decimal("1.00"),
            avg_fill_latency_ms=125,
            pct_with_price_improvement=Decimal("65.26"),
            records=[...],
        )
    """

    report_id: str = Field(..., min_length=1)
    date_from: datetime
    date_to: datetime
    generated_at: datetime
    total_analyzed: int = Field(ge=0)
    avg_price_improvement_bps: Decimal | None = Field(default=None)
    avg_slippage_bps: Decimal | None = Field(default=None)
    avg_fill_latency_ms: int | None = Field(default=None, ge=0)
    pct_with_price_improvement: Decimal | None = Field(default=None, ge=0, le=100)
    records: list[BestExecutionRecord] = Field(default_factory=list)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Venue Routing Report
# ---------------------------------------------------------------------------


class VenueRoutingRecord(BaseModel):
    """
    Order routing statistics per venue.

    Aggregates execution metrics by venue to support venue selection analysis
    and regulatory routing disclosures (SEC Rule 606, FINRA Rule 5310).

    Attributes:
        venue: Venue or exchange name/identifier.
        total_orders: Total orders routed to this venue.
        filled_orders: Number of orders that were fully filled at this venue.
        fill_rate: Percentage of orders that filled (filled / total).
        total_volume: Sum of all filled quantities at this venue.
        avg_fill_latency_ms: Average fill latency in milliseconds (optional).

    Example:
        record = VenueRoutingRecord(
            venue="NASDAQ",
            total_orders=250,
            filled_orders=240,
            fill_rate=Decimal("96.00"),
            total_volume=Decimal("24000"),
            avg_fill_latency_ms=110,
        )
    """

    venue: str = Field(..., min_length=1, max_length=50)
    total_orders: int = Field(ge=0)
    filled_orders: int = Field(ge=0)
    fill_rate: Decimal = Field(ge=0, le=100, description="Percentage filled")
    total_volume: Decimal = Field(ge=0)
    avg_fill_latency_ms: int | None = Field(default=None, ge=0)

    model_config = {"frozen": True}


class VenueRoutingReport(BaseModel):
    """
    Venue routing report with per-venue execution statistics.

    Summarizes routing and execution performance across all venues used
    during a reporting period, supporting venue selection transparency
    and regulatory requirements.

    Attributes:
        report_id: Unique report identifier.
        date_from: Start of reporting period (inclusive).
        date_to: End of reporting period (inclusive).
        generated_at: When the report was generated.
        venues: List of VenueRoutingRecord entries, one per venue.

    Example:
        report = VenueRoutingReport(
            report_id="routing-2026-04",
            date_from=datetime(2026, 4, 1),
            date_to=datetime(2026, 4, 30),
            generated_at=datetime(2026, 5, 1, 10, 0, 0),
            venues=[
                VenueRoutingRecord(venue="NASDAQ", ...),
                VenueRoutingRecord(venue="NYSE", ...),
            ],
        )
    """

    report_id: str = Field(..., min_length=1)
    date_from: datetime
    date_to: datetime
    generated_at: datetime
    venues: list[VenueRoutingRecord] = Field(default_factory=list)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Monthly Summary
# ---------------------------------------------------------------------------


class MonthlySummary(BaseModel):
    """
    Monthly compliance summary with aggregate key metrics.

    High-level executive summary of trading activity and compliance metrics
    for a single calendar month. Used for trend analysis and management
    reporting alongside detailed compliance reports.

    Attributes:
        report_id: Unique report identifier.
        month: Reporting month in "YYYY-MM" format.
        generated_at: When the summary was generated.
        total_orders: Total orders submitted during the month.
        total_filled: Number of filled orders.
        total_cancelled: Number of cancelled orders.
        total_rejected: Number of rejected orders.
        total_volume: Sum of all filled quantities.
        total_commission: Sum of all commissions paid.
        fill_rate: Percentage of orders that were filled (filled / total).
        error_rate: Percentage of orders that were rejected (rejected / total).
        unique_symbols: Count of distinct symbols traded.
        unique_venues: Count of distinct venues used.
        avg_fill_latency_ms: Average fill latency in milliseconds (optional).

    Example:
        summary = MonthlySummary(
            report_id="monthly-2026-04",
            month="2026-04",
            generated_at=datetime(2026, 5, 1, 10, 0, 0),
            total_orders=500,
            total_filled=475,
            total_cancelled=20,
            total_rejected=5,
            total_volume=Decimal("47500"),
            total_commission=Decimal("475.00"),
            fill_rate=Decimal("95.00"),
            error_rate=Decimal("1.00"),
            unique_symbols=45,
            unique_venues=3,
            avg_fill_latency_ms=115,
        )
    """

    report_id: str = Field(..., min_length=1)
    month: str = Field(..., description='Reporting month in "YYYY-MM" format (e.g., "2026-04")')
    generated_at: datetime
    total_orders: int = Field(ge=0)
    total_filled: int = Field(ge=0)
    total_cancelled: int = Field(default=0, ge=0)
    total_rejected: int = Field(default=0, ge=0)
    total_volume: Decimal = Field(default=Decimal("0"), ge=0)
    total_commission: Decimal = Field(default=Decimal("0"), ge=0)
    fill_rate: Decimal = Field(ge=0, le=100, description="Percentage filled")
    error_rate: Decimal = Field(ge=0, le=100, description="Percentage rejected")
    unique_symbols: int = Field(ge=0)
    unique_venues: int = Field(ge=0)
    avg_fill_latency_ms: int | None = Field(default=None, ge=0)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "ComplianceOrderRecord",
    "ExecutionComplianceReport",
    "BestExecutionRecord",
    "BestExecutionReport",
    "VenueRoutingRecord",
    "VenueRoutingReport",
    "MonthlySummary",
]
