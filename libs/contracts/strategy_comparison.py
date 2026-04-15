"""
Strategy comparison and ranking contracts (Phase 7 — M13).

Responsibilities:
- Define ranking criteria for strategy comparison.
- Define request / result value objects for the comparison service.
- Provide immutable, frozen Pydantic models for all DTOs.

Does NOT:
- Compute metrics (service responsibility).
- Fetch P&L data (PnlAttributionService responsibility).
- Persist results (caller responsibility).

Dependencies:
- pydantic: BaseModel, Field.
- Standard library: Decimal, datetime, enum.

Error conditions:
- ValidationError: invalid field values (Pydantic enforcement).

Example:
    request = StrategyComparisonRequest(
        deployment_ids=["01HDEPLOY00000000000000001", "01HDEPLOY00000000000000002"],
        ranking_criteria=StrategyRankingCriteria.SHARPE_RATIO,
    )
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class StrategyRankingCriteria(str, Enum):  # noqa: UP042 — StrEnum needs 3.11+
    """
    Available criteria for ranking strategies.

    Each criterion maps to a metric computed from P&L timeseries data.
    Higher values rank better for all criteria except MAX_DRAWDOWN
    (where less negative is better).
    """

    SHARPE_RATIO = "sharpe_ratio"
    SORTINO_RATIO = "sortino_ratio"
    CALMAR_RATIO = "calmar_ratio"
    MAX_DRAWDOWN = "max_drawdown"
    WIN_RATE = "win_rate"
    PROFIT_FACTOR = "profit_factor"
    NET_PNL = "net_pnl"
    RISK_ADJUSTED_RETURN = "risk_adjusted_return"


class StrategyComparisonRequest(BaseModel):
    """
    Request to compare multiple strategies.

    Attributes:
        deployment_ids: List of deployment IDs to compare (2–50).
        date_from: Start date for the comparison period (optional).
        date_to: End date for the comparison period (optional).
        ranking_criteria: Metric to rank strategies by.

    Example:
        request = StrategyComparisonRequest(
            deployment_ids=["01HDEPLOY00000000000000001", "01HDEPLOY00000000000000002"],
            ranking_criteria=StrategyRankingCriteria.SHARPE_RATIO,
        )
    """

    model_config = {"frozen": True}

    deployment_ids: list[str] = Field(
        ...,
        min_length=2,
        max_length=50,
        description="Deployment IDs to compare.",
    )
    date_from: date | None = Field(
        default=None,
        description="Comparison period start (inclusive).",
    )
    date_to: date | None = Field(
        default=None,
        description="Comparison period end (inclusive).",
    )
    ranking_criteria: StrategyRankingCriteria = Field(
        default=StrategyRankingCriteria.SHARPE_RATIO,
        description="Metric to rank strategies by.",
    )


class StrategyMetrics(BaseModel):
    """
    Expanded performance metrics for a single strategy / deployment.

    Includes standard and advanced risk-adjusted metrics computed from
    the P&L timeseries.

    Attributes:
        deployment_id: Deployment identifier.
        strategy_name: Human-readable strategy name.
        net_pnl: Total net P&L.
        total_trades: Number of trades executed.
        winning_trades: Number of winning trades.
        win_rate: Fraction of winning trades (0-1).
        sharpe_ratio: Annualized Sharpe ratio.
        sortino_ratio: Annualized Sortino ratio (downside deviation).
        calmar_ratio: Annualized return / max drawdown.
        max_drawdown_pct: Maximum drawdown as percentage (negative).
        profit_factor: Gross profit / gross loss.
        risk_adjusted_return: Sharpe × sqrt(252).
        annualized_return_pct: Annualized return percentage.
        total_commission: Total commissions paid.

    Example:
        metrics = StrategyMetrics(
            deployment_id="01HDEPLOY00000000000000001",
            strategy_name="Momentum Alpha",
            net_pnl=Decimal("15000.00"),
            sharpe_ratio=Decimal("1.45"),
            sortino_ratio=Decimal("2.10"),
        )
    """

    model_config = {"frozen": True}

    deployment_id: str = Field(..., min_length=1)
    strategy_name: str = Field(default="")
    net_pnl: Decimal = Field(default=Decimal("0"))
    total_trades: int = Field(default=0, ge=0)
    winning_trades: int = Field(default=0, ge=0)
    win_rate: Decimal = Field(default=Decimal("0"), ge=0.0, le=1.0)
    sharpe_ratio: Decimal = Field(default=Decimal("0"))
    sortino_ratio: Decimal = Field(default=Decimal("0"))
    calmar_ratio: Decimal = Field(default=Decimal("0"))
    max_drawdown_pct: Decimal = Field(default=Decimal("0"), le=0.0)
    profit_factor: Decimal = Field(default=Decimal("0"), ge=0.0)
    risk_adjusted_return: Decimal = Field(default=Decimal("0"))
    annualized_return_pct: Decimal = Field(default=Decimal("0"))
    total_commission: Decimal = Field(default=Decimal("0"), ge=0.0)


class StrategyRank(BaseModel):
    """
    Ranked strategy in a comparison result.

    Attributes:
        rank: Position in the ranking (1 = best).
        metrics: Full metrics for this strategy.

    Example:
        rank = StrategyRank(rank=1, metrics=metrics)
    """

    model_config = {"frozen": True}

    rank: int = Field(..., ge=1)
    metrics: StrategyMetrics


class StrategyComparisonResult(BaseModel):
    """
    Result of a strategy comparison.

    Contains ranked strategies and the full comparison matrix
    (all strategies × all metrics).

    Attributes:
        rankings: Strategies ordered by the requested criteria.
        ranking_criteria: The criteria used for ranking.
        comparison_matrix: All strategies with all metrics (unranked order).
        computed_at: Timestamp of when the comparison was computed.

    Example:
        result = StrategyComparisonResult(
            rankings=[rank1, rank2],
            ranking_criteria=StrategyRankingCriteria.SHARPE_RATIO,
            comparison_matrix=[metrics1, metrics2],
        )
    """

    model_config = {"frozen": True}

    rankings: list[StrategyRank] = Field(default_factory=list)
    ranking_criteria: StrategyRankingCriteria = Field(
        default=StrategyRankingCriteria.SHARPE_RATIO,
    )
    comparison_matrix: list[StrategyMetrics] = Field(default_factory=list)
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
