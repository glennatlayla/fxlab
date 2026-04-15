"""
Portfolio allocation contracts and value objects (Phase 8 M12).

Responsibilities:
- Define portfolio allocation method enumeration.
- Define strategy allocation configuration and snapshot models.
- Define portfolio configuration and snapshot models.
- Define rebalance frequency and allocation result models.
- Provide frozen Pydantic models for immutable value objects.

Does NOT:
- Execute allocation logic (PortfolioAllocationEngine responsibility).
- Manage execution loops (PortfolioOrchestrator responsibility).
- Persist results (caller / repository responsibility).

Dependencies:
- pydantic: BaseModel, Field.
- Standard library: datetime, decimal, enum.

Error conditions:
- ValidationError: invalid field values (Pydantic enforcement).

Example:
    config = PortfolioConfig(
        portfolio_id="pf-001",
        name="Multi-Strategy Alpha",
        total_capital=Decimal("1000000"),
        allocation_method=AllocationMethod.RISK_PARITY,
        rebalance_frequency=RebalanceFrequency.DAILY,
        strategy_configs=[
            StrategyAllocationConfig(strategy_id="ma-cross", deployment_id="dep-1"),
        ],
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class AllocationMethod(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """
    Portfolio capital allocation methods.

    - EQUAL_WEIGHT: Divide capital equally among active strategies.
    - RISK_PARITY: Allocate inversely proportional to strategy volatility.
    - INVERSE_VOLATILITY: Similar to risk parity, uses rolling volatility.
    - KELLY_OPTIMAL: Uses per-strategy win rate and avg win/loss ratio.
    - FIXED: User-specified weights applied directly.

    Example:
        method = AllocationMethod.RISK_PARITY
    """

    EQUAL_WEIGHT = "equal_weight"
    RISK_PARITY = "risk_parity"
    INVERSE_VOLATILITY = "inverse_volatility"
    KELLY_OPTIMAL = "kelly_optimal"
    FIXED = "fixed"


class RebalanceFrequency(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """
    Rebalance trigger frequency.

    - DAILY: Rebalance once per trading day.
    - WEEKLY: Rebalance once per week.
    - MONTHLY: Rebalance once per month.
    - ON_THRESHOLD: Rebalance when drift exceeds configured threshold.

    Example:
        freq = RebalanceFrequency.ON_THRESHOLD
    """

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    ON_THRESHOLD = "on_threshold"


class StrategyAllocationConfig(BaseModel):
    """
    Configuration for a single strategy within a portfolio.

    Attributes:
        strategy_id: Unique identifier of the signal strategy.
        deployment_id: Identifier of the deployment/execution instance.
        fixed_weight: User-specified weight (used when method is FIXED). 0.0-1.0.
        max_drawdown_limit: Per-strategy maximum drawdown cap (fractional, e.g. 0.20 = 20%).
        enabled: Whether this strategy is active in the portfolio.

    Example:
        config = StrategyAllocationConfig(
            strategy_id="ma-cross",
            deployment_id="dep-1",
            fixed_weight=0.5,
            max_drawdown_limit=0.15,
        )
    """

    model_config = {"frozen": True}

    strategy_id: str = Field(description="Signal strategy identifier.")
    deployment_id: str = Field(description="Deployment/execution instance identifier.")
    fixed_weight: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="User-specified weight for FIXED allocation method.",
    )
    max_drawdown_limit: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        description="Per-strategy max drawdown cap as fraction (e.g. 0.20 = 20%).",
    )
    enabled: bool = Field(default=True, description="Whether strategy is active.")


class StrategyAllocation(BaseModel):
    """
    Current allocation state for a single strategy.

    Represents the computed allocation at a point in time, including
    target vs current weight and the capital actually allocated.

    Attributes:
        strategy_id: Strategy identifier.
        deployment_id: Deployment identifier.
        target_weight: Computed target weight (0.0-1.0).
        current_weight: Actual current weight based on equity.
        capital_allocated: Capital amount allocated to this strategy.
        max_drawdown_limit: Per-strategy drawdown cap.

    Example:
        alloc = StrategyAllocation(
            strategy_id="ma-cross",
            deployment_id="dep-1",
            target_weight=0.5,
            current_weight=0.48,
            capital_allocated=Decimal("500000"),
            max_drawdown_limit=0.15,
        )
    """

    model_config = {"frozen": True}

    strategy_id: str = Field(description="Strategy identifier.")
    deployment_id: str = Field(description="Deployment identifier.")
    target_weight: float = Field(ge=0.0, le=1.0, description="Computed target weight.")
    current_weight: float = Field(ge=0.0, le=1.0, description="Actual current weight.")
    capital_allocated: Decimal = Field(ge=0, description="Capital allocated to strategy.")
    max_drawdown_limit: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        description="Per-strategy max drawdown cap.",
    )


class PortfolioConfig(BaseModel):
    """
    Configuration for a multi-strategy portfolio.

    Defines the allocation method, rebalance rules, strategy set, and
    portfolio-level risk constraints.

    Attributes:
        portfolio_id: Unique portfolio identifier.
        name: Human-readable portfolio name.
        total_capital: Total capital available for allocation.
        allocation_method: Method for computing strategy weights.
        rebalance_frequency: When rebalancing is triggered.
        rebalance_threshold: Drift percentage to trigger rebalance (for ON_THRESHOLD).
        strategy_configs: List of strategy allocation configurations.
        max_total_leverage: Maximum total portfolio leverage (1.0 = no leverage).
        max_correlation_between_strategies: Alert threshold for strategy correlation.

    Example:
        config = PortfolioConfig(
            portfolio_id="pf-001",
            name="Alpha Portfolio",
            total_capital=Decimal("1000000"),
            allocation_method=AllocationMethod.EQUAL_WEIGHT,
            rebalance_frequency=RebalanceFrequency.DAILY,
            strategy_configs=[
                StrategyAllocationConfig(strategy_id="s1", deployment_id="d1"),
                StrategyAllocationConfig(strategy_id="s2", deployment_id="d2"),
            ],
        )
    """

    model_config = {"frozen": True}

    portfolio_id: str = Field(description="Unique portfolio identifier.")
    name: str = Field(description="Human-readable portfolio name.")
    total_capital: Decimal = Field(ge=0, description="Total capital for allocation.")
    allocation_method: AllocationMethod = Field(
        default=AllocationMethod.EQUAL_WEIGHT,
        description="Method for computing strategy weights.",
    )
    rebalance_frequency: RebalanceFrequency = Field(
        default=RebalanceFrequency.DAILY,
        description="Rebalance trigger frequency.",
    )
    rebalance_threshold: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Drift threshold for ON_THRESHOLD rebalancing.",
    )
    strategy_configs: list[StrategyAllocationConfig] = Field(
        default_factory=list,
        description="Strategy allocation configurations.",
    )
    max_total_leverage: float = Field(
        default=1.0,
        ge=0.0,
        description="Maximum total portfolio leverage.",
    )
    max_correlation_between_strategies: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        description="Correlation threshold for strategy pairs.",
    )


class PortfolioSnapshot(BaseModel):
    """
    Point-in-time snapshot of a portfolio's allocation state.

    Captures the equity, P&L, individual allocations, and strategy
    correlations at a specific timestamp.

    Attributes:
        portfolio_id: Portfolio identifier.
        timestamp: When this snapshot was captured.
        total_equity: Total portfolio equity.
        total_pnl: Total P&L since inception.
        allocations: Per-strategy allocation state.
        strategy_correlations: Pairwise return correlations between strategies.

    Example:
        snapshot = PortfolioSnapshot(
            portfolio_id="pf-001",
            timestamp=datetime.now(timezone.utc),
            total_equity=Decimal("1050000"),
            total_pnl=Decimal("50000"),
            allocations=[...],
        )
    """

    model_config = {"frozen": True}

    portfolio_id: str = Field(description="Portfolio identifier.")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Snapshot timestamp (UTC).",
    )
    total_equity: Decimal = Field(ge=0, description="Total portfolio equity.")
    total_pnl: Decimal = Field(default=Decimal("0"), description="Total P&L.")
    allocations: list[StrategyAllocation] = Field(
        default_factory=list,
        description="Per-strategy allocations.",
    )
    strategy_correlations: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description="Pairwise strategy return correlations.",
    )


class StrategyPerformanceInput(BaseModel):
    """
    Performance data for a strategy, used as input to allocation engines.

    Provides the metrics needed by various allocation methods:
    volatility for risk parity, win_rate/avg_win_loss for Kelly, etc.

    Attributes:
        strategy_id: Strategy identifier.
        deployment_id: Deployment identifier.
        volatility: Annualised return volatility (std dev of returns * sqrt(252)).
        returns: List of recent periodic returns (daily or per-trade).
        win_rate: Fraction of winning trades (0.0-1.0).
        avg_win_loss_ratio: Average winning trade / average losing trade magnitude.
        current_equity: Current equity in this strategy.
        max_drawdown: Maximum drawdown experienced.

    Example:
        perf = StrategyPerformanceInput(
            strategy_id="ma-cross",
            deployment_id="dep-1",
            volatility=0.18,
            win_rate=0.55,
            avg_win_loss_ratio=1.5,
            current_equity=Decimal("500000"),
            max_drawdown=0.08,
        )
    """

    model_config = {"frozen": True}

    strategy_id: str = Field(description="Strategy identifier.")
    deployment_id: str = Field(description="Deployment identifier.")
    volatility: float = Field(
        default=0.0,
        ge=0.0,
        description="Annualised return volatility.",
    )
    returns: list[float] = Field(
        default_factory=list,
        description="Recent periodic returns.",
    )
    win_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Fraction of winning trades.",
    )
    avg_win_loss_ratio: float = Field(
        default=0.0,
        ge=0.0,
        description="Average winning trade / average losing trade magnitude.",
    )
    current_equity: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Current equity in this strategy.",
    )
    max_drawdown: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Maximum drawdown experienced.",
    )


class AllocationResult(BaseModel):
    """
    Result of a portfolio allocation computation.

    Contains the computed allocations and any constraint violations detected.

    Attributes:
        config: Portfolio configuration used.
        allocations: Computed per-strategy allocations.
        total_weight: Sum of all target weights (should be ≤ 1.0).
        leverage_utilised: Actual leverage after allocation.
        constrained: Whether any constraints were applied (leverage, drawdown).
        constraint_notes: Human-readable notes about constraint adjustments.
        computed_at: When the allocation was computed.

    Example:
        result = AllocationResult(
            config=config,
            allocations=[...],
            total_weight=1.0,
            leverage_utilised=1.0,
        )
    """

    model_config = {"frozen": True}

    config: PortfolioConfig
    allocations: list[StrategyAllocation] = Field(default_factory=list)
    total_weight: float = Field(default=0.0, ge=0.0)
    leverage_utilised: float = Field(default=0.0, ge=0.0)
    constrained: bool = Field(
        default=False,
        description="Whether constraints were applied.",
    )
    constraint_notes: list[str] = Field(
        default_factory=list,
        description="Notes about constraint adjustments.",
    )
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
