"""
Unit tests for Portfolio Orchestrator contracts and engine (M13).

Tests cover:
1. Contract validation — orchestrator state, triggers, drift, decisions, results.
2. Drift detection — threshold triggering, no drift, mixed drift.
3. Rebalance decision — should/should not rebalance based on drift vs threshold.
4. Rebalance execution — capital movement calculation, strategy adjustments.
5. Diagnostics — state reporting, drift reporting.
6. Edge cases — single strategy, all strategies at target, drawdown breach.

Follows §5 TDD naming: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from decimal import Decimal

from libs.contracts.portfolio import (
    AllocationMethod,
    PortfolioConfig,
    RebalanceFrequency,
    StrategyAllocationConfig,
    StrategyPerformanceInput,
)
from libs.contracts.portfolio_orchestrator import (
    OrchestratorDiagnostics,
    OrchestratorState,
    RebalanceDecision,
    RebalanceResult,
    RebalanceTrigger,
    StrategyDrift,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_strategy_config(
    strategy_id: str = "s1",
    deployment_id: str = "d1",
    fixed_weight: float = 0.0,
    max_drawdown_limit: float = 0.20,
    enabled: bool = True,
) -> StrategyAllocationConfig:
    return StrategyAllocationConfig(
        strategy_id=strategy_id,
        deployment_id=deployment_id,
        fixed_weight=fixed_weight,
        max_drawdown_limit=max_drawdown_limit,
        enabled=enabled,
    )


def _make_performance(
    strategy_id: str = "s1",
    deployment_id: str = "d1",
    volatility: float = 0.20,
    win_rate: float = 0.55,
    avg_win_loss_ratio: float = 1.5,
    current_equity: Decimal = Decimal("500000"),
    max_drawdown: float = 0.05,
) -> StrategyPerformanceInput:
    return StrategyPerformanceInput(
        strategy_id=strategy_id,
        deployment_id=deployment_id,
        volatility=volatility,
        win_rate=win_rate,
        avg_win_loss_ratio=avg_win_loss_ratio,
        current_equity=current_equity,
        max_drawdown=max_drawdown,
    )


def _make_portfolio_config(
    strategy_configs: list[StrategyAllocationConfig] | None = None,
    allocation_method: AllocationMethod = AllocationMethod.EQUAL_WEIGHT,
    total_capital: Decimal = Decimal("1000000"),
    rebalance_threshold: float = 0.05,
) -> PortfolioConfig:
    if strategy_configs is None:
        strategy_configs = [
            _make_strategy_config("s1", "d1"),
            _make_strategy_config("s2", "d2"),
        ]
    return PortfolioConfig(
        portfolio_id="pf-test",
        name="Test Portfolio",
        total_capital=total_capital,
        allocation_method=allocation_method,
        rebalance_frequency=RebalanceFrequency.ON_THRESHOLD,
        rebalance_threshold=rebalance_threshold,
        strategy_configs=strategy_configs,
    )


def _build_orchestrator():
    from services.worker.execution.portfolio_orchestrator import PortfolioOrchestrator
    from services.worker.research.portfolio_allocation_engine import (
        PortfolioAllocationEngine,
    )

    return PortfolioOrchestrator(allocation_engine=PortfolioAllocationEngine())


# ===========================================================================
# Test: Contract Validation
# ===========================================================================


class TestOrchestratorContracts:
    """Verify orchestrator contract validation."""

    def test_orchestrator_state_enum(self) -> None:
        """All orchestrator states are defined."""
        assert OrchestratorState.IDLE.value == "idle"
        assert OrchestratorState.RUNNING.value == "running"
        assert OrchestratorState.REBALANCING.value == "rebalancing"
        assert OrchestratorState.PAUSED.value == "paused"
        assert OrchestratorState.STOPPED.value == "stopped"

    def test_rebalance_trigger_enum(self) -> None:
        """All rebalance triggers are defined."""
        assert RebalanceTrigger.SCHEDULED.value == "scheduled"
        assert RebalanceTrigger.THRESHOLD_DRIFT.value == "threshold_drift"
        assert RebalanceTrigger.MANUAL.value == "manual"
        assert RebalanceTrigger.DRAWDOWN_BREACH.value == "drawdown_breach"

    def test_strategy_drift_valid(self) -> None:
        """StrategyDrift builds with valid data."""
        drift = StrategyDrift(
            strategy_id="s1",
            target_weight=0.50,
            current_weight=0.55,
            drift=0.05,
            drift_pct=0.10,
        )
        assert drift.drift == 0.05

    def test_rebalance_decision_valid(self) -> None:
        """RebalanceDecision builds with valid data."""
        decision = RebalanceDecision(
            portfolio_id="pf-001",
            should_rebalance=True,
            trigger=RebalanceTrigger.MANUAL,
            max_drift=0.08,
        )
        assert decision.should_rebalance is True
        assert decision.decided_at.tzinfo is not None

    def test_rebalance_result_valid(self) -> None:
        """RebalanceResult builds with valid data."""
        decision = RebalanceDecision(
            portfolio_id="pf-001",
            trigger=RebalanceTrigger.MANUAL,
        )
        result = RebalanceResult(
            portfolio_id="pf-001",
            decision=decision,
            success=True,
            strategies_adjusted=2,
            total_capital_moved=Decimal("50000"),
        )
        assert result.success is True
        assert result.strategies_adjusted == 2

    def test_orchestrator_diagnostics_valid(self) -> None:
        """OrchestratorDiagnostics builds with valid data."""
        diag = OrchestratorDiagnostics(
            portfolio_id="pf-001",
            state=OrchestratorState.RUNNING,
            num_active_strategies=3,
            total_equity=Decimal("1050000"),
        )
        assert diag.state == OrchestratorState.RUNNING


# ===========================================================================
# Test: Drift Detection
# ===========================================================================


class TestDriftDetection:
    """Verify drift detection logic."""

    def test_drift_detected_when_above_threshold(self) -> None:
        """Drift above threshold → should_rebalance is True."""
        config = _make_portfolio_config(rebalance_threshold=0.05)
        # s1 has 600k (60%), s2 has 400k (40%), target is 50/50
        performances = [
            _make_performance("s1", "d1", current_equity=Decimal("600000")),
            _make_performance("s2", "d2", current_equity=Decimal("400000")),
        ]

        orchestrator = _build_orchestrator()
        decision = orchestrator.evaluate_rebalance(
            config,
            performances,
            RebalanceTrigger.THRESHOLD_DRIFT,
        )

        assert decision.should_rebalance is True
        assert decision.max_drift > 0.05

    def test_no_drift_when_at_target(self) -> None:
        """No drift when strategies are at target weights."""
        config = _make_portfolio_config(rebalance_threshold=0.05)
        # Both at 500k = 50% each
        performances = [
            _make_performance("s1", "d1", current_equity=Decimal("500000")),
            _make_performance("s2", "d2", current_equity=Decimal("500000")),
        ]

        orchestrator = _build_orchestrator()
        decision = orchestrator.evaluate_rebalance(
            config,
            performances,
            RebalanceTrigger.THRESHOLD_DRIFT,
        )

        assert decision.should_rebalance is False
        assert decision.max_drift < 0.05

    def test_drift_below_threshold_no_rebalance(self) -> None:
        """Small drift below threshold → should_rebalance is False."""
        config = _make_portfolio_config(rebalance_threshold=0.10)
        # Slight drift: s1=520k, s2=480k → 52% vs 48%, drift=0.02
        performances = [
            _make_performance("s1", "d1", current_equity=Decimal("520000")),
            _make_performance("s2", "d2", current_equity=Decimal("480000")),
        ]

        orchestrator = _build_orchestrator()
        decision = orchestrator.evaluate_rebalance(
            config,
            performances,
            RebalanceTrigger.THRESHOLD_DRIFT,
        )

        assert decision.should_rebalance is False

    def test_manual_trigger_always_rebalances(self) -> None:
        """Manual trigger → should_rebalance is True regardless of drift."""
        config = _make_portfolio_config(rebalance_threshold=0.05)
        performances = [
            _make_performance("s1", "d1", current_equity=Decimal("500000")),
            _make_performance("s2", "d2", current_equity=Decimal("500000")),
        ]

        orchestrator = _build_orchestrator()
        decision = orchestrator.evaluate_rebalance(
            config,
            performances,
            RebalanceTrigger.MANUAL,
        )

        assert decision.should_rebalance is True

    def test_drift_per_strategy_computed(self) -> None:
        """Per-strategy drift values are populated."""
        config = _make_portfolio_config(rebalance_threshold=0.05)
        performances = [
            _make_performance("s1", "d1", current_equity=Decimal("600000")),
            _make_performance("s2", "d2", current_equity=Decimal("400000")),
        ]

        orchestrator = _build_orchestrator()
        decision = orchestrator.evaluate_rebalance(
            config,
            performances,
            RebalanceTrigger.THRESHOLD_DRIFT,
        )

        assert len(decision.drifts) == 2
        drift_s1 = next(d for d in decision.drifts if d.strategy_id == "s1")
        assert drift_s1.current_weight > drift_s1.target_weight


# ===========================================================================
# Test: Rebalance Execution
# ===========================================================================


class TestRebalanceExecution:
    """Verify rebalance execution logic."""

    def test_execute_rebalance_computes_capital_moved(self) -> None:
        """Execute rebalance computes total capital moved."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1", current_equity=Decimal("600000")),
            _make_performance("s2", "d2", current_equity=Decimal("400000")),
        ]

        orchestrator = _build_orchestrator()
        decision = orchestrator.evaluate_rebalance(
            config,
            performances,
            RebalanceTrigger.MANUAL,
        )
        result = orchestrator.execute_rebalance(config, performances, decision)

        assert result.success is True
        assert result.total_capital_moved > Decimal("0")
        assert result.strategies_adjusted > 0

    def test_execute_rebalance_no_change_needed(self) -> None:
        """Execute rebalance when already at target → zero capital moved."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1", current_equity=Decimal("500000")),
            _make_performance("s2", "d2", current_equity=Decimal("500000")),
        ]

        orchestrator = _build_orchestrator()
        decision = orchestrator.evaluate_rebalance(
            config,
            performances,
            RebalanceTrigger.MANUAL,
        )
        result = orchestrator.execute_rebalance(config, performances, decision)

        assert result.success is True
        assert result.total_capital_moved == Decimal("0")

    def test_execute_rebalance_result_has_timestamps(self) -> None:
        """Rebalance result has valid UTC timestamps."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1", current_equity=Decimal("500000")),
            _make_performance("s2", "d2", current_equity=Decimal("500000")),
        ]

        orchestrator = _build_orchestrator()
        decision = orchestrator.evaluate_rebalance(
            config,
            performances,
            RebalanceTrigger.MANUAL,
        )
        result = orchestrator.execute_rebalance(config, performances, decision)

        assert result.started_at.tzinfo is not None
        assert result.completed_at.tzinfo is not None

    def test_execute_rebalance_preserves_portfolio_id(self) -> None:
        """Result contains the correct portfolio_id."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1", current_equity=Decimal("500000")),
            _make_performance("s2", "d2", current_equity=Decimal("500000")),
        ]

        orchestrator = _build_orchestrator()
        decision = orchestrator.evaluate_rebalance(
            config,
            performances,
            RebalanceTrigger.MANUAL,
        )
        result = orchestrator.execute_rebalance(config, performances, decision)

        assert result.portfolio_id == "pf-test"


# ===========================================================================
# Test: Diagnostics
# ===========================================================================


class TestDiagnostics:
    """Verify orchestrator diagnostics."""

    def test_diagnostics_reports_strategy_count(self) -> None:
        """Diagnostics reports correct number of active strategies."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        orchestrator = _build_orchestrator()
        diag = orchestrator.get_diagnostics(config, performances)

        assert diag.num_active_strategies == 2

    def test_diagnostics_reports_total_equity(self) -> None:
        """Diagnostics reports sum of strategy equities."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1", current_equity=Decimal("600000")),
            _make_performance("s2", "d2", current_equity=Decimal("400000")),
        ]

        orchestrator = _build_orchestrator()
        diag = orchestrator.get_diagnostics(config, performances)

        assert diag.total_equity == Decimal("1000000")

    def test_diagnostics_reports_max_drift(self) -> None:
        """Diagnostics reports maximum drift among strategies."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1", current_equity=Decimal("700000")),
            _make_performance("s2", "d2", current_equity=Decimal("300000")),
        ]

        orchestrator = _build_orchestrator()
        diag = orchestrator.get_diagnostics(config, performances)

        # 70% vs 50% target = 20% drift
        assert diag.max_current_drift > 0.15

    def test_diagnostics_reports_allocation_method(self) -> None:
        """Diagnostics reports the configured allocation method."""
        config = _make_portfolio_config(allocation_method=AllocationMethod.RISK_PARITY)
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        orchestrator = _build_orchestrator()
        diag = orchestrator.get_diagnostics(config, performances)

        assert diag.allocation_method == AllocationMethod.RISK_PARITY


# ===========================================================================
# Test: Edge Cases
# ===========================================================================


class TestEdgeCases:
    """Verify edge case handling."""

    def test_single_strategy_no_drift(self) -> None:
        """Single strategy → zero drift, no rebalance needed."""
        configs = [_make_strategy_config("s1", "d1")]
        config = _make_portfolio_config(strategy_configs=configs)
        performances = [_make_performance("s1", "d1", current_equity=Decimal("1000000"))]

        orchestrator = _build_orchestrator()
        decision = orchestrator.evaluate_rebalance(
            config,
            performances,
            RebalanceTrigger.THRESHOLD_DRIFT,
        )

        assert decision.should_rebalance is False
        assert decision.max_drift < 1e-9

    def test_scheduled_trigger_rebalances_on_any_drift(self) -> None:
        """Scheduled trigger → rebalance regardless of drift magnitude."""
        config = _make_portfolio_config(rebalance_threshold=0.50)
        performances = [
            _make_performance("s1", "d1", current_equity=Decimal("510000")),
            _make_performance("s2", "d2", current_equity=Decimal("490000")),
        ]

        orchestrator = _build_orchestrator()
        decision = orchestrator.evaluate_rebalance(
            config,
            performances,
            RebalanceTrigger.SCHEDULED,
        )

        # Scheduled always rebalances
        assert decision.should_rebalance is True

    def test_three_strategies_max_drift(self) -> None:
        """Three strategies: max drift is from the most deviated one."""
        configs = [
            _make_strategy_config("s1", "d1"),
            _make_strategy_config("s2", "d2"),
            _make_strategy_config("s3", "d3"),
        ]
        config = _make_portfolio_config(strategy_configs=configs, rebalance_threshold=0.05)
        # Target: 33.3% each. s1=50%, s2=30%, s3=20%
        performances = [
            _make_performance("s1", "d1", current_equity=Decimal("500000")),
            _make_performance("s2", "d2", current_equity=Decimal("300000")),
            _make_performance("s3", "d3", current_equity=Decimal("200000")),
        ]

        orchestrator = _build_orchestrator()
        decision = orchestrator.evaluate_rebalance(
            config,
            performances,
            RebalanceTrigger.THRESHOLD_DRIFT,
        )

        assert decision.should_rebalance is True
        # Max drift is from s1 (50% vs 33.3% = 16.7% drift)
        assert decision.max_drift > 0.10

    def test_decision_contains_target_allocations(self) -> None:
        """Decision includes computed target allocations."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1", current_equity=Decimal("600000")),
            _make_performance("s2", "d2", current_equity=Decimal("400000")),
        ]

        orchestrator = _build_orchestrator()
        decision = orchestrator.evaluate_rebalance(
            config,
            performances,
            RebalanceTrigger.MANUAL,
        )

        assert len(decision.target_allocations) == 2
