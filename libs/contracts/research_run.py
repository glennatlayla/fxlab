"""
Research run lifecycle contracts.

Purpose:
    Define the domain contracts for the complete research run lifecycle:
    submission, execution orchestration, status tracking, and result
    retrieval. Bridges the frontend `POST /runs/research` expectation
    with the backend backtest / walk-forward / Monte Carlo engines.

Responsibilities:
    - ResearchRunType enum: the kind of research run (backtest, walk-forward,
      monte carlo, composite pipeline).
    - ResearchRunStatus enum: lifecycle states with terminal detection.
    - ResearchRunConfig: frozen input configuration selecting engine + params.
    - ResearchRunResult: frozen output wrapping engine-specific results.
    - ResearchRunRecord: frozen aggregate combining config, status, result.
    - SubmitResearchRunRequest / ResearchRunResponse: API-layer DTOs.

Does NOT:
    - Contain business logic or orchestration (see ResearchRunService).
    - Perform I/O or database access.
    - Import from service or repository layers.

Dependencies:
    - libs.contracts.backtest.BacktestConfig, BacktestResult
    - libs.contracts.walk_forward.WalkForwardConfig, WalkForwardResult
    - libs.contracts.monte_carlo.MonteCarloConfig, MonteCarloResult

Example:
    config = ResearchRunConfig(
        run_type=ResearchRunType.BACKTEST,
        strategy_id="01HSTRATEGY00000000000001",
        symbols=["AAPL"],
        backtest_config=BacktestConfig(...),
    )
    record = ResearchRunRecord(
        id="01HRUN00000000000000000001",
        config=config,
        status=ResearchRunStatus.PENDING,
        ...
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from libs.contracts.backtest import BacktestConfig, BacktestResult
from libs.contracts.monte_carlo import MonteCarloConfig, MonteCarloResult
from libs.contracts.walk_forward import WalkForwardConfig, WalkForwardResult

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ResearchRunType(str, Enum):  # noqa: UP042 — StrEnum requires 3.11+
    """
    Type of research run determining which engine(s) to invoke.

    Values:
        BACKTEST: Single backtest run using BacktestEngine.
        WALK_FORWARD: Rolling walk-forward analysis using WalkForwardEngine.
        MONTE_CARLO: Statistical validation using MonteCarloEngine
            (requires a completed backtest result as input).
        COMPOSITE: Full pipeline — backtest → monte carlo sequentially.
    """

    BACKTEST = "backtest"
    WALK_FORWARD = "walk_forward"
    MONTE_CARLO = "monte_carlo"
    COMPOSITE = "composite"


class ResearchRunStatus(str, Enum):  # noqa: UP042 — StrEnum requires 3.11+
    """
    Lifecycle status for a research run.

    Terminal states: COMPLETED, FAILED, CANCELLED.
    Non-terminal states: PENDING, QUEUED, RUNNING.

    Values:
        PENDING: Created but not yet queued for execution.
        QUEUED: Accepted into the execution queue.
        RUNNING: Engine is actively processing.
        COMPLETED: Engine finished successfully; result available.
        FAILED: Engine encountered an unrecoverable error.
        CANCELLED: User or system cancelled before completion.
    """

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Terminal states — cancellation and result retrieval logic use this.
_TERMINAL_STATUSES = frozenset(
    {ResearchRunStatus.COMPLETED, ResearchRunStatus.FAILED, ResearchRunStatus.CANCELLED}
)

# Valid state transitions — guards against illegal jumps.
#
# RUNNING -> CANCELLED is permitted so the operator-driven cancellation
# flow (POST /runs/{id}/cancel) can persist a terminal CANCELLED row even
# when the executor task is mid-execution. The pool aborts the in-flight
# asyncio task before the status write so we never race against a worker
# that is still updating the same row.
VALID_STATUS_TRANSITIONS: dict[ResearchRunStatus, frozenset[ResearchRunStatus]] = {
    ResearchRunStatus.PENDING: frozenset({ResearchRunStatus.QUEUED, ResearchRunStatus.CANCELLED}),
    ResearchRunStatus.QUEUED: frozenset({ResearchRunStatus.RUNNING, ResearchRunStatus.CANCELLED}),
    ResearchRunStatus.RUNNING: frozenset(
        {
            ResearchRunStatus.COMPLETED,
            ResearchRunStatus.FAILED,
            ResearchRunStatus.CANCELLED,
        }
    ),
    ResearchRunStatus.COMPLETED: frozenset(),
    ResearchRunStatus.FAILED: frozenset(),
    ResearchRunStatus.CANCELLED: frozenset(),
}


def is_terminal_status(status: ResearchRunStatus) -> bool:
    """
    Check whether a research run status is terminal.

    Args:
        status: The status to check.

    Returns:
        True if the status is COMPLETED, FAILED, or CANCELLED.

    Example:
        >>> is_terminal_status(ResearchRunStatus.COMPLETED)
        True
        >>> is_terminal_status(ResearchRunStatus.RUNNING)
        False
    """
    return status in _TERMINAL_STATUSES


def validate_status_transition(current: ResearchRunStatus, target: ResearchRunStatus) -> bool:
    """
    Check whether a status transition is valid.

    Args:
        current: The current status.
        target: The desired next status.

    Returns:
        True if the transition is allowed, False otherwise.

    Example:
        >>> validate_status_transition(ResearchRunStatus.PENDING, ResearchRunStatus.QUEUED)
        True
        >>> validate_status_transition(ResearchRunStatus.COMPLETED, ResearchRunStatus.RUNNING)
        False
    """
    return target in VALID_STATUS_TRANSITIONS.get(current, frozenset())


class InvalidStatusTransitionError(Exception):
    """Raised when attempting an illegal research run status transition."""

    def __init__(self, current: ResearchRunStatus, target: ResearchRunStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from {current.value} to {target.value}")


# ---------------------------------------------------------------------------
# Configuration contract
# ---------------------------------------------------------------------------


class ResearchRunConfig(BaseModel):
    """
    Input configuration for a research run.

    Selects which engine to use and provides engine-specific parameters.
    Exactly one of backtest_config, walk_forward_config, or monte_carlo_config
    should be populated, matching the run_type.

    Attributes:
        run_type: Determines which engine to invoke.
        strategy_id: ULID of the strategy to research.
        strategy_version_id: Optional specific version; latest if omitted.
        signal_strategy_id: Signal strategy to use for signal generation.
        symbols: Ticker symbols to include in the research.
        initial_equity: Starting capital for backtest simulations.
        backtest_config: Engine config for BACKTEST and COMPOSITE runs.
        walk_forward_config: Engine config for WALK_FORWARD runs.
        monte_carlo_config: Engine config for MONTE_CARLO and COMPOSITE runs.
        metadata: Arbitrary key-value pairs for tagging/filtering.

    Example:
        config = ResearchRunConfig(
            run_type=ResearchRunType.BACKTEST,
            strategy_id="01HSTRATEGY00000000000001",
            symbols=["AAPL", "MSFT"],
            initial_equity=Decimal("100000"),
            backtest_config=BacktestConfig(...),
        )
    """

    model_config = ConfigDict(frozen=True)

    run_type: ResearchRunType
    strategy_id: str = Field(..., min_length=1, description="Strategy ULID")
    strategy_version_id: str | None = Field(
        None, description="Specific strategy version ULID; latest if omitted"
    )
    signal_strategy_id: str | None = Field(
        None, description="Signal strategy ID for signal-based engines"
    )
    symbols: list[str] = Field(..., min_length=1, description="Ticker symbols to research")
    initial_equity: Decimal = Field(
        default=Decimal("100000"),
        gt=0,
        description="Starting capital for simulations",
    )
    backtest_config: BacktestConfig | None = Field(
        None, description="Config for BACKTEST / COMPOSITE runs"
    )
    walk_forward_config: WalkForwardConfig | None = Field(
        None, description="Config for WALK_FORWARD runs"
    )
    monte_carlo_config: MonteCarloConfig | None = Field(
        None, description="Config for MONTE_CARLO / COMPOSITE runs"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary tagging metadata")

    @field_validator("symbols")
    @classmethod
    def _normalise_symbols(cls, v: list[str]) -> list[str]:
        """Uppercase and deduplicate symbols, preserving order."""
        seen: set[str] = set()
        result: list[str] = []
        for s in v:
            upper = s.strip().upper()
            if upper and upper not in seen:
                seen.add(upper)
                result.append(upper)
        return result


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------


class ResearchRunResult(BaseModel):
    """
    Output result from a research run.

    Contains engine-specific results populated based on the run type.
    For COMPOSITE runs, both backtest_result and monte_carlo_result are populated.

    Attributes:
        backtest_result: Populated for BACKTEST and COMPOSITE runs.
        walk_forward_result: Populated for WALK_FORWARD runs.
        monte_carlo_result: Populated for MONTE_CARLO and COMPOSITE runs.
        summary_metrics: Flattened key metrics for quick display.
        completed_at: UTC timestamp when the engine finished.

    Example:
        result = ResearchRunResult(
            backtest_result=backtest_result,
            summary_metrics={"total_return": 0.15, "sharpe_ratio": 1.2},
            completed_at=datetime.now(timezone.utc),
        )
    """

    model_config = ConfigDict(frozen=True)

    backtest_result: BacktestResult | None = None
    walk_forward_result: WalkForwardResult | None = None
    monte_carlo_result: MonteCarloResult | None = None
    summary_metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="Flattened key metrics for quick display",
    )
    completed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the engine finished",
    )


# ---------------------------------------------------------------------------
# Record contract (aggregate root)
# ---------------------------------------------------------------------------


class ResearchRunRecord(BaseModel):
    """
    Full research run record combining configuration, status, and result.

    This is the aggregate root for the research run domain. The repository
    persists and retrieves instances of this record.

    Attributes:
        id: ULID primary key.
        config: The run configuration that was submitted.
        status: Current lifecycle status.
        result: Engine result; None until COMPLETED.
        error_message: Error description if FAILED.
        created_by: User ID who submitted the run.
        created_at: UTC creation timestamp.
        updated_at: UTC last-update timestamp.
        started_at: UTC timestamp when execution began.
        completed_at: UTC timestamp when execution finished.

    Example:
        record = ResearchRunRecord(
            id="01HRUN00000000000000000001",
            config=config,
            status=ResearchRunStatus.PENDING,
            created_by="01HUSER00000000000000001",
        )
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., min_length=1, description="ULID primary key")
    config: ResearchRunConfig
    status: ResearchRunStatus = ResearchRunStatus.PENDING
    result: ResearchRunResult | None = None
    error_message: str | None = None
    created_by: str = Field(..., min_length=1, description="User ID")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None


# ---------------------------------------------------------------------------
# API-layer DTOs
# ---------------------------------------------------------------------------


class SubmitResearchRunRequest(BaseModel):
    """
    API request body for submitting a new research run.

    Attributes:
        config: The research run configuration.

    Example:
        request = SubmitResearchRunRequest(config=config)
    """

    config: ResearchRunConfig


class ResearchRunListResponse(BaseModel):
    """
    Paginated list of research run records.

    Attributes:
        runs: List of research run records.
        total_count: Total number of matching records.

    Example:
        response = ResearchRunListResponse(runs=[record], total_count=1)
    """

    runs: list[ResearchRunRecord]
    total_count: int = Field(..., ge=0)
