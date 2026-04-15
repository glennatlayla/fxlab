"""
Walk-forward analysis contracts and value objects (Phase 8 M10).

Responsibilities:
- Define walk-forward configuration parameters.
- Define per-window result with in-sample and out-of-sample metrics.
- Define aggregate walk-forward result with stability scoring.
- Define optimization metric enumeration.
- Provide frozen Pydantic models for immutable value objects.

Does NOT:
- Execute walk-forward analysis (WalkForwardEngine responsibility).
- Run backtests (BacktestEngine responsibility).
- Compute indicators (IndicatorEngine responsibility).

Dependencies:
- pydantic: BaseModel, Field.
- Standard library: Decimal, datetime, date, enum.
- libs.contracts.backtest: BacktestInterval.

Error conditions:
- ValidationError: invalid field values (Pydantic enforcement).

Example:
    config = WalkForwardConfig(
        strategy_id="ma-crossover",
        signal_strategy_id="ma-crossover",
        symbols=["AAPL"],
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        interval=BacktestInterval.ONE_DAY,
        in_sample_bars=200,
        out_of_sample_bars=50,
        step_bars=50,
        parameter_grid={"fast_period": [10, 20], "slow_period": [50, 100]},
        optimization_metric=OptimizationMetric.SHARPE,
    )
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from libs.contracts.backtest import BacktestInterval


class OptimizationMetric(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """
    Metrics available for walk-forward optimization.

    Each metric defines what the optimizer maximizes (or minimizes for drawdown)
    when searching the parameter grid on in-sample data.

    Example:
        metric = OptimizationMetric.SHARPE
    """

    SHARPE = "sharpe"
    SORTINO = "sortino"
    CALMAR = "calmar"
    PROFIT_FACTOR = "profit_factor"
    MAX_DRAWDOWN = "max_drawdown"
    TOTAL_RETURN = "total_return"


class WalkForwardConfig(BaseModel):
    """
    Configuration for a walk-forward analysis run.

    Specifies how to split the data into rolling windows, what parameter
    combinations to evaluate, and which metric to optimize.

    Attributes:
        strategy_id: ID of the strategy being optimized.
        signal_strategy_id: ID of the signal strategy implementation.
        symbols: Universe of symbols to test.
        start_date: Overall start date for the analysis.
        end_date: Overall end date for the analysis.
        interval: Bar interval for backtests.
        in_sample_bars: Number of bars in each training window.
        out_of_sample_bars: Number of bars in each validation window.
        step_bars: Number of bars to advance the window each iteration.
        parameter_grid: Dict of parameter_name → list of values to search.
        optimization_metric: Which metric to optimize.
        initial_equity: Starting equity for each backtest run.

    Example:
        config = WalkForwardConfig(
            strategy_id="ma-crossover",
            signal_strategy_id="ma-crossover",
            symbols=["AAPL"],
            start_date=date(2024, 1, 1),
            end_date=date(2025, 12, 31),
            interval=BacktestInterval.ONE_DAY,
            in_sample_bars=200,
            out_of_sample_bars=50,
            step_bars=50,
            parameter_grid={"fast_period": [10, 20]},
            optimization_metric=OptimizationMetric.SHARPE,
        )
    """

    model_config = {"frozen": True}

    strategy_id: str = Field(..., min_length=1, description="Strategy ID.")
    signal_strategy_id: str = Field(..., min_length=1, description="Signal strategy ID.")
    symbols: list[str] = Field(..., min_length=1, description="Universe of symbols.")
    start_date: date = Field(..., description="Overall analysis start date.")
    end_date: date = Field(..., description="Overall analysis end date.")
    interval: BacktestInterval = Field(
        default=BacktestInterval.ONE_DAY,
        description="Bar interval.",
    )
    in_sample_bars: int = Field(
        ...,
        ge=10,
        le=10000,
        description="Bars per training window.",
    )
    out_of_sample_bars: int = Field(
        ...,
        ge=5,
        le=5000,
        description="Bars per validation window.",
    )
    step_bars: int = Field(
        ...,
        ge=1,
        le=5000,
        description="Bars to advance window each iteration.",
    )
    parameter_grid: dict[str, list[Any]] = Field(
        ...,
        description="Parameter name → list of candidate values.",
    )
    optimization_metric: OptimizationMetric = Field(
        default=OptimizationMetric.SHARPE,
        description="Metric to optimize.",
    )
    initial_equity: Decimal = Field(
        default=Decimal("100000"),
        gt=0.0,
        description="Starting equity per backtest run.",
    )


class WalkForwardWindowResult(BaseModel):
    """
    Result for a single walk-forward window.

    Contains the optimal parameters found on in-sample data and the
    corresponding metric values on both in-sample and out-of-sample periods.

    Attributes:
        window_index: Zero-based index of this window.
        in_sample_start: Start date of the training period.
        in_sample_end: End date of the training period.
        out_of_sample_start: Start date of the validation period.
        out_of_sample_end: End date of the validation period.
        best_params: Optimal parameter combination from grid search.
        in_sample_metric: Best metric value on training data.
        out_of_sample_metric: Metric value with best params on validation data.
        parameter_combinations_tested: Number of param combos evaluated.

    Example:
        window = WalkForwardWindowResult(
            window_index=0,
            in_sample_start=date(2024, 1, 1),
            in_sample_end=date(2024, 10, 1),
            out_of_sample_start=date(2024, 10, 2),
            out_of_sample_end=date(2024, 12, 31),
            best_params={"fast_period": 20, "slow_period": 50},
            in_sample_metric=1.85,
            out_of_sample_metric=1.20,
        )
    """

    model_config = {"frozen": True}

    window_index: int = Field(..., ge=0)
    in_sample_start: date
    in_sample_end: date
    out_of_sample_start: date
    out_of_sample_end: date
    best_params: dict[str, Any] = Field(default_factory=dict)
    in_sample_metric: float = Field(default=0.0)
    out_of_sample_metric: float = Field(default=0.0)
    parameter_combinations_tested: int = Field(default=0, ge=0)


class WalkForwardResult(BaseModel):
    """
    Aggregate result of a walk-forward analysis.

    Contains per-window results, overall out-of-sample performance,
    parameter stability assessment, and consensus parameters.

    Attributes:
        config: Walk-forward configuration used.
        windows: Per-window results in chronological order.
        aggregate_oos_metric: Mean out-of-sample metric across all windows.
        stability_score: How consistent optimal parameters were (0-1).
            1.0 = identical parameters in every window.
            0.0 = completely different parameters each window.
        best_consensus_params: Most frequently optimal parameter combination.
        total_backtests_run: Total number of backtests executed.
        completed_at: When the analysis completed.

    Example:
        result = WalkForwardResult(
            config=config,
            windows=[window1, window2, window3],
            aggregate_oos_metric=1.35,
            stability_score=0.75,
            best_consensus_params={"fast_period": 20, "slow_period": 50},
            total_backtests_run=24,
        )
    """

    model_config = {"frozen": True}

    config: WalkForwardConfig
    windows: list[WalkForwardWindowResult] = Field(default_factory=list)
    aggregate_oos_metric: float = Field(default=0.0)
    stability_score: float = Field(default=0.0, ge=0.0, le=1.0)
    best_consensus_params: dict[str, Any] = Field(default_factory=dict)
    total_backtests_run: int = Field(default=0, ge=0)
    completed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
