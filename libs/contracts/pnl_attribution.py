"""
P&L attribution and performance tracking contracts.

Responsibilities:
- Define schemas for P&L summary, timeseries, attribution, and comparison.
- Define query parameters for P&L retrieval.
- Provide structured data contracts for strategy-level performance metrics.

Does NOT:
- Contain business logic or P&L calculations.
- Perform I/O or network calls.
- Know about specific repositories or databases.

Dependencies:
- pydantic: BaseModel, Field
- datetime, decimal: standard library types

Error conditions:
- Pydantic ValidationError raised on invalid field values.

Example:
    from libs.contracts.pnl_attribution import PnlSummary, PnlTimeseriesPoint

    summary = PnlSummary(
        deployment_id="01HDEPLOY123",
        total_realized_pnl=Decimal("1250.50"),
        total_unrealized_pnl=Decimal("340.25"),
        total_commission=Decimal("52.00"),
        total_fees=Decimal("0"),
        net_pnl=Decimal("1538.75"),
        positions_count=5,
        win_rate=Decimal("65.0"),
        sharpe_ratio=Decimal("1.42"),
        max_drawdown_pct=Decimal("4.2"),
    )
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# P&L Snapshot (persisted daily)
# ---------------------------------------------------------------------------


class PnlSnapshotRecord(BaseModel):
    """
    A single daily P&L snapshot record as returned from the repository.

    Represents the P&L state of a deployment at a specific date. Snapshots
    are created daily and provide the building blocks for timeseries, equity
    curves, drawdown calculations, and historical performance attribution.

    Attributes:
        id: ULID primary key.
        deployment_id: Deployment this snapshot belongs to.
        snapshot_date: Date of the snapshot (date only, no time component).
        realized_pnl: Cumulative realized P&L at snapshot time.
        unrealized_pnl: Unrealized P&L (mark-to-market) at snapshot time.
        commission: Cumulative commissions paid through snapshot date.
        fees: Cumulative fees paid through snapshot date.
        positions_count: Number of open positions at snapshot time.
        created_at: When the snapshot record was persisted.

    Example:
        snapshot = PnlSnapshotRecord(
            id="01HSNAP001ABC",
            deployment_id="01HDEPLOY123",
            snapshot_date=date(2026, 4, 12),
            realized_pnl=Decimal("1250.50"),
            unrealized_pnl=Decimal("340.25"),
            commission=Decimal("52.00"),
            fees=Decimal("0"),
            positions_count=5,
            created_at=datetime(2026, 4, 12, 23, 59, 0),
        )
    """

    id: str = Field(..., min_length=1)
    deployment_id: str = Field(..., min_length=1)
    snapshot_date: date
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    commission: Decimal = Field(default=Decimal("0"))
    fees: Decimal = Field(default=Decimal("0"))
    positions_count: int = Field(default=0, ge=0)
    created_at: datetime | None = None

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# P&L Summary
# ---------------------------------------------------------------------------


class PnlSummary(BaseModel):
    """
    Aggregate P&L summary for a deployment.

    Provides a high-level view of the deployment's financial performance
    including realized/unrealized P&L, commissions, performance metrics
    (Sharpe ratio, max drawdown, win rate), and position counts.

    Attributes:
        deployment_id: Deployment this summary describes.
        total_realized_pnl: Sum of all realized P&L across closed positions.
        total_unrealized_pnl: Current mark-to-market unrealized P&L.
        total_commission: Total commissions paid across all fills.
        total_fees: Total exchange/regulatory fees paid.
        net_pnl: Total realized + unrealized - commissions - fees.
        positions_count: Number of currently open positions.
        total_trades: Total number of completed trades (round trips).
        winning_trades: Number of profitable trades.
        losing_trades: Number of unprofitable trades.
        win_rate: Percentage of trades that were profitable (0-100).
        sharpe_ratio: Annualized Sharpe ratio (risk-adjusted return).
        max_drawdown_pct: Maximum peak-to-trough drawdown percentage.
        avg_win: Average profit on winning trades.
        avg_loss: Average loss on losing trades.
        profit_factor: Gross profit / gross loss ratio (None if no losses).
        date_from: Earliest snapshot date in the calculation window.
        date_to: Latest snapshot date in the calculation window.

    Example:
        summary = PnlSummary(
            deployment_id="01HDEPLOY123",
            total_realized_pnl=Decimal("1250.50"),
            total_unrealized_pnl=Decimal("340.25"),
            total_commission=Decimal("52.00"),
            total_fees=Decimal("0"),
            net_pnl=Decimal("1538.75"),
            positions_count=5,
            total_trades=20,
            winning_trades=13,
            losing_trades=7,
            win_rate=Decimal("65.0"),
            sharpe_ratio=Decimal("1.42"),
            max_drawdown_pct=Decimal("4.2"),
        )
    """

    deployment_id: str = Field(..., min_length=1)
    total_realized_pnl: Decimal
    total_unrealized_pnl: Decimal
    total_commission: Decimal = Field(default=Decimal("0"))
    total_fees: Decimal = Field(default=Decimal("0"))
    net_pnl: Decimal
    positions_count: int = Field(default=0, ge=0)
    total_trades: int = Field(default=0, ge=0)
    winning_trades: int = Field(default=0, ge=0)
    losing_trades: int = Field(default=0, ge=0)
    win_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    sharpe_ratio: Decimal | None = None
    max_drawdown_pct: Decimal | None = None
    avg_win: Decimal | None = None
    avg_loss: Decimal | None = None
    profit_factor: Decimal | None = None
    date_from: date | None = None
    date_to: date | None = None

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# P&L Timeseries Point
# ---------------------------------------------------------------------------


class PnlTimeseriesPoint(BaseModel):
    """
    A single data point in a P&L timeseries.

    Used for equity curve rendering, drawdown analysis, and period-over-period
    P&L comparisons. Each point represents the P&L state at a specific date.

    Attributes:
        snapshot_date: Date of this data point.
        realized_pnl: Cumulative realized P&L at this date.
        unrealized_pnl: Unrealized P&L at this date.
        net_pnl: Realized + unrealized P&L.
        cumulative_pnl: Running cumulative P&L including all prior periods.
        daily_pnl: Change in net P&L from previous day.
        commission: Cumulative commissions through this date.
        fees: Cumulative fees through this date.
        positions_count: Open positions at this date.
        drawdown_pct: Current drawdown from peak as percentage.

    Example:
        point = PnlTimeseriesPoint(
            snapshot_date=date(2026, 4, 12),
            realized_pnl=Decimal("1250.50"),
            unrealized_pnl=Decimal("340.25"),
            net_pnl=Decimal("1590.75"),
            cumulative_pnl=Decimal("1590.75"),
            daily_pnl=Decimal("85.25"),
            commission=Decimal("52.00"),
            drawdown_pct=Decimal("0"),
        )
    """

    snapshot_date: date
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    net_pnl: Decimal
    cumulative_pnl: Decimal
    daily_pnl: Decimal = Field(default=Decimal("0"))
    commission: Decimal = Field(default=Decimal("0"))
    fees: Decimal = Field(default=Decimal("0"))
    positions_count: int = Field(default=0, ge=0)
    drawdown_pct: Decimal = Field(default=Decimal("0"))

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# P&L Attribution by Symbol
# ---------------------------------------------------------------------------


class SymbolAttribution(BaseModel):
    """
    P&L contribution breakdown for a single symbol within a deployment.

    Quantifies how much each traded symbol contributes to the overall
    strategy P&L, enabling identification of best/worst performing
    instruments.

    Attributes:
        symbol: Instrument ticker (e.g. "AAPL").
        realized_pnl: Realized P&L from closed positions in this symbol.
        unrealized_pnl: Current unrealized P&L for open positions.
        net_pnl: Total P&L for this symbol.
        contribution_pct: Percentage contribution to total deployment P&L.
        total_trades: Number of completed trades in this symbol.
        winning_trades: Number of profitable trades in this symbol.
        win_rate: Win rate for this symbol (0-100).
        total_volume: Total quantity traded in this symbol.
        commission: Total commissions paid for this symbol.

    Example:
        attr = SymbolAttribution(
            symbol="AAPL",
            realized_pnl=Decimal("500.00"),
            unrealized_pnl=Decimal("120.00"),
            net_pnl=Decimal("620.00"),
            contribution_pct=Decimal("40.3"),
            total_trades=8,
            winning_trades=6,
            win_rate=Decimal("75.0"),
            total_volume=Decimal("800"),
            commission=Decimal("16.00"),
        )
    """

    symbol: str = Field(..., min_length=1, max_length=20)
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    net_pnl: Decimal
    contribution_pct: Decimal
    total_trades: int = Field(default=0, ge=0)
    winning_trades: int = Field(default=0, ge=0)
    win_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    total_volume: Decimal = Field(default=Decimal("0"), ge=0)
    commission: Decimal = Field(default=Decimal("0"), ge=0)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# P&L Attribution Report
# ---------------------------------------------------------------------------


class PnlAttributionReport(BaseModel):
    """
    Per-symbol P&L attribution for a deployment.

    Aggregates performance by symbol, showing which instruments contribute
    most (or least) to the strategy's returns.

    Attributes:
        deployment_id: Deployment this attribution describes.
        date_from: Start of analysis period.
        date_to: End of analysis period.
        total_net_pnl: Total net P&L across all symbols.
        by_symbol: Per-symbol P&L attribution breakdowns.

    Example:
        report = PnlAttributionReport(
            deployment_id="01HDEPLOY123",
            date_from=date(2026, 4, 1),
            date_to=date(2026, 4, 12),
            total_net_pnl=Decimal("1538.75"),
            by_symbol=[
                SymbolAttribution(symbol="AAPL", ...),
                SymbolAttribution(symbol="MSFT", ...),
            ],
        )
    """

    deployment_id: str = Field(..., min_length=1)
    date_from: date | None = None
    date_to: date | None = None
    total_net_pnl: Decimal
    by_symbol: list[SymbolAttribution] = Field(default_factory=list)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Strategy Comparison
# ---------------------------------------------------------------------------


class StrategyComparisonEntry(BaseModel):
    """
    P&L metrics for a single deployment in a comparison view.

    Used to compare multiple deployments/strategies side-by-side on
    key performance metrics.

    Attributes:
        deployment_id: Deployment ULID.
        strategy_name: Human-readable strategy name (optional).
        net_pnl: Net P&L for the comparison period.
        total_realized_pnl: Realized P&L for the comparison period.
        total_unrealized_pnl: Unrealized P&L at end of period.
        total_commission: Total commissions for the period.
        win_rate: Win rate percentage.
        sharpe_ratio: Annualized Sharpe ratio.
        max_drawdown_pct: Maximum drawdown percentage.
        total_trades: Total completed trades.

    Example:
        entry = StrategyComparisonEntry(
            deployment_id="01HDEPLOY123",
            strategy_name="Momentum Alpha",
            net_pnl=Decimal("1538.75"),
            win_rate=Decimal("65.0"),
            sharpe_ratio=Decimal("1.42"),
        )
    """

    deployment_id: str = Field(..., min_length=1)
    strategy_name: str | None = None
    net_pnl: Decimal
    total_realized_pnl: Decimal = Field(default=Decimal("0"))
    total_unrealized_pnl: Decimal = Field(default=Decimal("0"))
    total_commission: Decimal = Field(default=Decimal("0"))
    win_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    sharpe_ratio: Decimal | None = None
    max_drawdown_pct: Decimal | None = None
    total_trades: int = Field(default=0, ge=0)

    model_config = {"frozen": True}


class PnlComparisonReport(BaseModel):
    """
    Side-by-side strategy/deployment comparison report.

    Attributes:
        date_from: Start of comparison period.
        date_to: End of comparison period.
        entries: One entry per deployment being compared.

    Example:
        comparison = PnlComparisonReport(
            date_from=date(2026, 4, 1),
            date_to=date(2026, 4, 12),
            entries=[
                StrategyComparisonEntry(deployment_id="01HDEPLOY123", ...),
                StrategyComparisonEntry(deployment_id="01HDEPLOY456", ...),
            ],
        )
    """

    date_from: date | None = None
    date_to: date | None = None
    entries: list[StrategyComparisonEntry] = Field(default_factory=list)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Query Parameters
# ---------------------------------------------------------------------------


class PnlTimeseriesQuery(BaseModel):
    """
    Query parameters for P&L timeseries retrieval.

    Attributes:
        deployment_id: Deployment ULID (required).
        date_from: Start date for timeseries (inclusive).
        date_to: End date for timeseries (inclusive).
        granularity: Aggregation granularity: "daily", "weekly", or "monthly".

    Example:
        query = PnlTimeseriesQuery(
            deployment_id="01HDEPLOY123",
            date_from=date(2026, 4, 1),
            date_to=date(2026, 4, 12),
            granularity="daily",
        )
    """

    deployment_id: str = Field(..., min_length=1)
    date_from: date
    date_to: date
    granularity: str = Field(default="daily")

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "PnlSnapshotRecord",
    "PnlSummary",
    "PnlTimeseriesPoint",
    "SymbolAttribution",
    "PnlAttributionReport",
    "StrategyComparisonEntry",
    "PnlComparisonReport",
    "PnlTimeseriesQuery",
]
