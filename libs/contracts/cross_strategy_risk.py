"""
Cross-strategy risk aggregation contracts (Phase 8 M14).

Responsibilities:
- Define portfolio-level VaR result models.
- Define marginal VaR decomposition models.
- Define strategy correlation matrix models.
- Define drawdown synchronization detection models.
- Define capital optimization suggestion models.

Does NOT:
- Implement risk calculations (CrossStrategyRiskService responsibility).
- Persist results (caller / repository responsibility).
- Execute trades or rebalancing.

Dependencies:
- pydantic: BaseModel, Field.
- Standard library: datetime, decimal, enum.

Error conditions:
- ValidationError: invalid field values (Pydantic enforcement).

Example:
    var_result = PortfolioVaR(
        portfolio_id="pf-001",
        var_95=Decimal("25000"),
        var_99=Decimal("40000"),
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class VaRMethod(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """
    Value at Risk computation method.

    - HISTORICAL: Historical simulation from return data.
    - PARAMETRIC: Assumes normal distribution, uses mean/std.

    Example:
        method = VaRMethod.HISTORICAL
    """

    HISTORICAL = "historical"
    PARAMETRIC = "parametric"


class PortfolioVaR(BaseModel):
    """
    Portfolio-level Value at Risk result.

    Attributes:
        portfolio_id: Portfolio identifier.
        method: VaR computation method used.
        var_95: 95% VaR — maximum expected loss with 95% confidence.
        var_99: 99% VaR — maximum expected loss with 99% confidence.
        total_equity: Total portfolio equity at computation time.
        lookback_days: Number of days of return data used.
        computed_at: When the VaR was computed.

    Example:
        var = PortfolioVaR(
            portfolio_id="pf-001",
            var_95=Decimal("25000"),
            var_99=Decimal("40000"),
            total_equity=Decimal("1000000"),
        )
    """

    model_config = {"frozen": True}

    portfolio_id: str
    method: VaRMethod = Field(default=VaRMethod.HISTORICAL)
    var_95: Decimal = Field(ge=0, description="95% VaR (positive = loss amount).")
    var_99: Decimal = Field(ge=0, description="99% VaR (positive = loss amount).")
    total_equity: Decimal = Field(ge=0, description="Total portfolio equity.")
    lookback_days: int = Field(default=252, ge=1)
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class MarginalVaR(BaseModel):
    """
    Per-strategy marginal VaR contribution.

    Measures how much each strategy contributes to the total portfolio VaR.

    Attributes:
        strategy_id: Strategy identifier.
        marginal_var_95: Strategy's contribution to 95% VaR.
        marginal_var_99: Strategy's contribution to 99% VaR.
        pct_contribution: Fraction of total VaR contributed (0.0-1.0).

    Example:
        mvar = MarginalVaR(
            strategy_id="ma-cross",
            marginal_var_95=Decimal("15000"),
            marginal_var_99=Decimal("25000"),
            pct_contribution=0.60,
        )
    """

    model_config = {"frozen": True}

    strategy_id: str
    marginal_var_95: Decimal = Field(ge=0)
    marginal_var_99: Decimal = Field(ge=0)
    pct_contribution: float = Field(ge=0.0, le=1.0)


class MarginalVaRResult(BaseModel):
    """
    Complete marginal VaR decomposition for a portfolio.

    Attributes:
        portfolio_id: Portfolio identifier.
        portfolio_var: Total portfolio VaR.
        marginal_vars: Per-strategy marginal VaR contributions.
        computed_at: When computed.

    Example:
        result = MarginalVaRResult(
            portfolio_id="pf-001",
            portfolio_var=portfolio_var,
            marginal_vars=[...],
        )
    """

    model_config = {"frozen": True}

    portfolio_id: str
    portfolio_var: PortfolioVaR
    marginal_vars: list[MarginalVaR] = Field(default_factory=list)
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class CorrelationMatrix(BaseModel):
    """
    Pairwise correlation matrix for strategy returns.

    Attributes:
        portfolio_id: Portfolio identifier.
        strategy_ids: Ordered list of strategy identifiers.
        matrix: 2D correlation matrix as list of lists (row-major).
        lookback_days: Number of days of return data used.
        high_correlation_pairs: Strategy pairs exceeding correlation threshold.
        computed_at: When computed.

    Example:
        corr = CorrelationMatrix(
            portfolio_id="pf-001",
            strategy_ids=["s1", "s2"],
            matrix=[[1.0, 0.3], [0.3, 1.0]],
        )
    """

    model_config = {"frozen": True}

    portfolio_id: str
    strategy_ids: list[str] = Field(default_factory=list)
    matrix: list[list[float]] = Field(default_factory=list)
    lookback_days: int = Field(default=60, ge=1)
    high_correlation_pairs: list[tuple[str, str, float]] = Field(default_factory=list)
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class DrawdownSyncEvent(BaseModel):
    """
    Detected synchronized drawdown event across multiple strategies.

    Attributes:
        portfolio_id: Portfolio identifier.
        strategy_ids: Strategies experiencing simultaneous drawdown.
        avg_drawdown: Average drawdown across the affected strategies.
        max_drawdown: Maximum drawdown among the affected strategies.
        correlation_during_event: Return correlation during the event period.
        detected_at: When the event was detected.

    Example:
        event = DrawdownSyncEvent(
            portfolio_id="pf-001",
            strategy_ids=["s1", "s2"],
            avg_drawdown=0.08,
            max_drawdown=0.12,
        )
    """

    model_config = {"frozen": True}

    portfolio_id: str
    strategy_ids: list[str] = Field(default_factory=list)
    avg_drawdown: float = Field(ge=0.0, le=1.0)
    max_drawdown: float = Field(ge=0.0, le=1.0)
    correlation_during_event: float = Field(default=0.0)
    detected_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class OptimizationSuggestion(BaseModel):
    """
    Capital allocation optimization suggestion.

    Computed from mean-variance optimisation (Markowitz efficient frontier).

    Attributes:
        portfolio_id: Portfolio identifier.
        suggested_weights: Strategy → suggested weight mapping.
        expected_return: Expected portfolio return at suggested weights.
        expected_volatility: Expected portfolio volatility at suggested weights.
        sharpe_ratio: Expected Sharpe ratio at suggested weights.
        current_weights: Current strategy weights for comparison.
        method: Optimization method used.
        computed_at: When computed.

    Example:
        suggestion = OptimizationSuggestion(
            portfolio_id="pf-001",
            suggested_weights={"s1": 0.6, "s2": 0.4},
            expected_return=0.15,
            expected_volatility=0.12,
            sharpe_ratio=1.25,
        )
    """

    model_config = {"frozen": True}

    portfolio_id: str
    suggested_weights: dict[str, float] = Field(default_factory=dict)
    expected_return: float = Field(default=0.0)
    expected_volatility: float = Field(default=0.0, ge=0.0)
    sharpe_ratio: float = Field(default=0.0)
    current_weights: dict[str, float] = Field(default_factory=dict)
    method: str = Field(default="mean_variance")
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
