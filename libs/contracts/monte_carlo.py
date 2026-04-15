"""
Monte Carlo simulation contracts and value objects (Phase 8 M11).

Responsibilities:
- Define Monte Carlo simulation configuration.
- Define simulation result with confidence intervals and ruin probability.
- Define simulation method enumeration.
- Provide frozen Pydantic models for immutable value objects.

Does NOT:
- Execute simulations (MonteCarloEngine responsibility).
- Run backtests (BacktestEngine responsibility).
- Persist results (caller responsibility).

Dependencies:
- pydantic: BaseModel, Field.
- Standard library: datetime, enum.

Error conditions:
- ValidationError: invalid field values (Pydantic enforcement).

Example:
    config = MonteCarloConfig(
        num_simulations=10000,
        method=SimulationMethod.TRADE_RESAMPLE,
        confidence_levels=[0.05, 0.25, 0.50, 0.75, 0.95],
        ruin_threshold=0.50,
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class SimulationMethod(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """
    Monte Carlo simulation methods.

    - TRADE_RESAMPLE: Shuffle trade sequence and replay.
    - RETURN_BOOTSTRAP: Resample daily/bar returns with replacement.

    Example:
        method = SimulationMethod.TRADE_RESAMPLE
    """

    TRADE_RESAMPLE = "trade_resample"
    RETURN_BOOTSTRAP = "return_bootstrap"


class MonteCarloConfig(BaseModel):
    """
    Configuration for a Monte Carlo simulation run.

    Attributes:
        num_simulations: Number of Monte Carlo iterations.
        method: Simulation method (trade resample or return bootstrap).
        confidence_levels: Percentile levels for confidence intervals.
        ruin_threshold: Equity fraction below which a simulation counts as ruin.
            E.g., 0.50 means ruin if equity drops below 50% of initial.
        random_seed: Optional seed for reproducibility.

    Example:
        config = MonteCarloConfig(
            num_simulations=10000,
            confidence_levels=[0.05, 0.25, 0.50, 0.75, 0.95],
        )
    """

    model_config = {"frozen": True}

    num_simulations: int = Field(
        default=10000,
        ge=100,
        le=1_000_000,
        description="Number of simulation iterations.",
    )
    method: SimulationMethod = Field(
        default=SimulationMethod.TRADE_RESAMPLE,
        description="Simulation method.",
    )
    confidence_levels: list[float] = Field(
        default=[0.05, 0.25, 0.50, 0.75, 0.95],
        description="Percentile levels for confidence intervals.",
    )
    ruin_threshold: float = Field(
        default=0.50,
        ge=0.0,
        le=1.0,
        description="Equity fraction below which simulation is ruin.",
    )
    random_seed: int | None = Field(
        default=None,
        description="Random seed for reproducibility.",
    )


class MonteCarloResult(BaseModel):
    """
    Result of a Monte Carlo simulation.

    Contains confidence intervals for key metrics and probability of ruin.

    Attributes:
        config: Simulation configuration used.
        num_trades: Number of trades in the source backtest.
        equity_percentiles: Percentile label → final equity value.
        max_drawdown_percentiles: Percentile label → max drawdown value.
        sharpe_percentiles: Percentile label → Sharpe ratio value.
        probability_of_ruin: Fraction of simulations below ruin threshold.
        mean_final_equity: Mean final equity across all simulations.
        median_final_equity: Median final equity across all simulations.
        longest_losing_streak_percentiles: Percentile label → streak length.
        completed_at: When the simulation completed.

    Example:
        result = MonteCarloResult(
            config=config,
            num_trades=42,
            equity_percentiles={"p5": 85000.0, "p50": 115000.0, "p95": 145000.0},
            probability_of_ruin=0.03,
            mean_final_equity=115000.0,
            median_final_equity=114500.0,
        )
    """

    model_config = {"frozen": True}

    config: MonteCarloConfig
    num_trades: int = Field(default=0, ge=0)
    equity_percentiles: dict[str, float] = Field(default_factory=dict)
    max_drawdown_percentiles: dict[str, float] = Field(default_factory=dict)
    sharpe_percentiles: dict[str, float] = Field(default_factory=dict)
    probability_of_ruin: float = Field(default=0.0, ge=0.0, le=1.0)
    mean_final_equity: float = Field(default=0.0)
    median_final_equity: float = Field(default=0.0)
    longest_losing_streak_percentiles: dict[str, float] = Field(default_factory=dict)
    completed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
