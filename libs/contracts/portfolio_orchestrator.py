"""
Portfolio orchestrator contracts and value objects (Phase 8 M13).

Responsibilities:
- Define orchestrator state enumeration.
- Define rebalance request, decision, and result models.
- Define orchestrator diagnostics for monitoring.
- Define drift detection and cross-strategy risk models.

Does NOT:
- Implement orchestration logic (PortfolioOrchestrator responsibility).
- Execute trades (broker adapter responsibility).
- Persist results (caller / repository responsibility).

Dependencies:
- pydantic: BaseModel, Field.
- Standard library: datetime, decimal, enum.
- libs.contracts.portfolio: AllocationMethod, StrategyAllocation.

Error conditions:
- ValidationError: invalid field values (Pydantic enforcement).

Example:
    request = RebalanceRequest(
        portfolio_id="pf-001",
        trigger=RebalanceTrigger.THRESHOLD_DRIFT,
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

from libs.contracts.portfolio import AllocationMethod, StrategyAllocation


class OrchestratorState(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """
    Lifecycle state of the portfolio orchestrator.

    - IDLE: Orchestrator created but not managing any active deployments.
    - RUNNING: Actively monitoring strategy deployments.
    - REBALANCING: Currently executing a rebalance cycle.
    - PAUSED: Temporarily paused (e.g., during maintenance).
    - STOPPED: Permanently stopped, no longer managing deployments.

    Example:
        state = OrchestratorState.RUNNING
    """

    IDLE = "idle"
    RUNNING = "running"
    REBALANCING = "rebalancing"
    PAUSED = "paused"
    STOPPED = "stopped"


class RebalanceTrigger(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """
    What triggered a rebalance.

    - SCHEDULED: Time-based trigger (daily, weekly, monthly).
    - THRESHOLD_DRIFT: A strategy's weight drifted beyond the threshold.
    - MANUAL: Operator-triggered via API.
    - DRAWDOWN_BREACH: A strategy exceeded its drawdown limit.

    Example:
        trigger = RebalanceTrigger.THRESHOLD_DRIFT
    """

    SCHEDULED = "scheduled"
    THRESHOLD_DRIFT = "threshold_drift"
    MANUAL = "manual"
    DRAWDOWN_BREACH = "drawdown_breach"


class RebalanceRequest(BaseModel):
    """
    Request to initiate a portfolio rebalance.

    Attributes:
        portfolio_id: Portfolio to rebalance.
        trigger: What triggered this rebalance.
        requested_at: When the request was made.
        requested_by: Identifier of the requestor (system or user).

    Example:
        request = RebalanceRequest(
            portfolio_id="pf-001",
            trigger=RebalanceTrigger.MANUAL,
            requested_by="operator-1",
        )
    """

    model_config = {"frozen": True}

    portfolio_id: str = Field(description="Portfolio to rebalance.")
    trigger: RebalanceTrigger = Field(description="What triggered the rebalance.")
    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    requested_by: str = Field(
        default="system",
        description="Requestor identifier.",
    )


class StrategyDrift(BaseModel):
    """
    Drift measurement for a single strategy.

    Attributes:
        strategy_id: Strategy identifier.
        target_weight: Target allocation weight.
        current_weight: Actual current weight.
        drift: Absolute drift from target (current - target).
        drift_pct: Drift as a percentage of target.

    Example:
        drift = StrategyDrift(
            strategy_id="s1",
            target_weight=0.50,
            current_weight=0.55,
            drift=0.05,
            drift_pct=0.10,
        )
    """

    model_config = {"frozen": True}

    strategy_id: str
    target_weight: float = Field(ge=0.0, le=1.0)
    current_weight: float = Field(ge=0.0, le=1.0)
    drift: float = Field(description="Absolute drift (current - target).")
    drift_pct: float = Field(description="Drift as fraction of target.")


class RebalanceDecision(BaseModel):
    """
    Decision about whether and how to rebalance.

    Contains the old and new allocations, plus any adjustment orders
    that would need to be submitted.

    Attributes:
        portfolio_id: Portfolio identifier.
        should_rebalance: Whether rebalancing is warranted.
        trigger: What triggered the evaluation.
        drifts: Per-strategy drift measurements.
        current_allocations: Allocations before rebalance.
        target_allocations: Proposed allocations after rebalance.
        max_drift: Largest absolute drift among all strategies.
        decided_at: When the decision was made.

    Example:
        decision = RebalanceDecision(
            portfolio_id="pf-001",
            should_rebalance=True,
            trigger=RebalanceTrigger.THRESHOLD_DRIFT,
            drifts=[...],
            current_allocations=[...],
            target_allocations=[...],
            max_drift=0.08,
        )
    """

    model_config = {"frozen": True}

    portfolio_id: str
    should_rebalance: bool = Field(default=False)
    trigger: RebalanceTrigger
    drifts: list[StrategyDrift] = Field(default_factory=list)
    current_allocations: list[StrategyAllocation] = Field(default_factory=list)
    target_allocations: list[StrategyAllocation] = Field(default_factory=list)
    max_drift: float = Field(default=0.0, ge=0.0)
    decided_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class RebalanceResult(BaseModel):
    """
    Result of executing a rebalance cycle.

    Attributes:
        portfolio_id: Portfolio identifier.
        decision: The rebalance decision that was executed.
        success: Whether the rebalance completed successfully.
        strategies_adjusted: Number of strategies that had allocations changed.
        total_capital_moved: Total capital moved between strategies.
        error_message: Error details if rebalance failed.
        started_at: When the rebalance started.
        completed_at: When the rebalance completed.

    Example:
        result = RebalanceResult(
            portfolio_id="pf-001",
            decision=decision,
            success=True,
            strategies_adjusted=2,
            total_capital_moved=Decimal("50000"),
        )
    """

    model_config = {"frozen": True}

    portfolio_id: str
    decision: RebalanceDecision
    success: bool = Field(default=True)
    strategies_adjusted: int = Field(default=0, ge=0)
    total_capital_moved: Decimal = Field(default=Decimal("0"), ge=0)
    error_message: str | None = Field(default=None)
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    completed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class OrchestratorDiagnostics(BaseModel):
    """
    Diagnostics snapshot for the portfolio orchestrator.

    Attributes:
        portfolio_id: Portfolio identifier.
        state: Current orchestrator state.
        num_active_strategies: Number of active strategy deployments.
        total_equity: Current total portfolio equity.
        last_rebalance_at: When the last rebalance occurred.
        rebalances_executed: Total number of rebalances executed.
        max_current_drift: Largest drift among strategies right now.
        allocation_method: Currently configured allocation method.
        checked_at: When this diagnostic was captured.

    Example:
        diag = OrchestratorDiagnostics(
            portfolio_id="pf-001",
            state=OrchestratorState.RUNNING,
            num_active_strategies=3,
            total_equity=Decimal("1050000"),
        )
    """

    model_config = {"frozen": True}

    portfolio_id: str
    state: OrchestratorState = Field(default=OrchestratorState.IDLE)
    num_active_strategies: int = Field(default=0, ge=0)
    total_equity: Decimal = Field(default=Decimal("0"), ge=0)
    last_rebalance_at: datetime | None = Field(default=None)
    rebalances_executed: int = Field(default=0, ge=0)
    max_current_drift: float = Field(default=0.0, ge=0.0)
    allocation_method: AllocationMethod = Field(
        default=AllocationMethod.EQUAL_WEIGHT,
    )
    checked_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
