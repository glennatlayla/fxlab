"""
Portfolio orchestrator — multi-strategy coordination and rebalancing (M13).

Responsibilities:
- Evaluate whether a portfolio needs rebalancing based on drift detection.
- Compute rebalance decisions comparing current vs target allocations.
- Execute rebalance by calculating capital movements needed.
- Report orchestrator diagnostics (drift, equity, strategy count).

Does NOT:
- Submit broker orders directly (caller coordinates with broker adapters).
- Manage execution loop lifecycle (StrategyExecutionEngine responsibility).
- Persist results (caller / repository responsibility).
- Stream or poll market data.

Dependencies:
- PortfolioAllocationEngineInterface (injected): computes target allocations.
- structlog: Structured logging.
- libs.contracts.portfolio: config and allocation types.
- libs.contracts.portfolio_orchestrator: orchestrator-specific types.

Error conditions:
- ValueError: propagated from allocation engine if no enabled strategies.

Example:
    engine = PortfolioAllocationEngine()
    orchestrator = PortfolioOrchestrator(allocation_engine=engine)
    decision = orchestrator.evaluate_rebalance(config, performances, trigger)
    if decision.should_rebalance:
        result = orchestrator.execute_rebalance(config, performances, decision)
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from decimal import Decimal

import structlog

from libs.contracts.interfaces.portfolio_allocation_engine import (
    PortfolioAllocationEngineInterface,
)
from libs.contracts.interfaces.portfolio_orchestrator import (
    PortfolioOrchestratorInterface,
)
from libs.contracts.portfolio import (
    PortfolioConfig,
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

logger = structlog.get_logger(__name__)


class PortfolioOrchestrator(PortfolioOrchestratorInterface):
    """
    Portfolio orchestrator for multi-strategy coordination.

    Coordinates drift detection, rebalance decisions, and capital
    movement calculations across a set of strategy deployments.

    Responsibilities:
    - Compute current allocations from performance data.
    - Compare current vs target allocations to measure drift.
    - Decide whether rebalancing is warranted based on trigger type and threshold.
    - Calculate capital movements needed to achieve target allocations.
    - Report diagnostics for monitoring.

    Does NOT:
    - Submit broker orders.
    - Manage execution loop lifecycle.
    - Persist results.

    Thread safety:
    - Thread-safe: mutable state (_rebalances_executed, _last_rebalance_at)
      protected by _lock.

    Example:
        orchestrator = PortfolioOrchestrator(allocation_engine=engine)
        decision = orchestrator.evaluate_rebalance(config, perfs, trigger)
    """

    def __init__(
        self,
        allocation_engine: PortfolioAllocationEngineInterface,
    ) -> None:
        """
        Initialise the portfolio orchestrator.

        Args:
            allocation_engine: Engine for computing target allocations.
        """
        self._allocation_engine = allocation_engine
        self._lock = threading.Lock()
        self._rebalances_executed: int = 0
        self._last_rebalance_at: datetime | None = None

    def evaluate_rebalance(
        self,
        config: PortfolioConfig,
        performances: list[StrategyPerformanceInput],
        trigger: RebalanceTrigger,
    ) -> RebalanceDecision:
        """
        Evaluate whether a rebalance is needed.

        Computes target allocations, measures drift of each strategy,
        and decides based on trigger type and threshold.

        Args:
            config: Portfolio configuration.
            performances: Current per-strategy performance data.
            trigger: What triggered this evaluation.

        Returns:
            RebalanceDecision with drift measurements and recommendation.

        Example:
            decision = orchestrator.evaluate_rebalance(config, perfs, trigger)
        """
        logger.info(
            "Evaluating rebalance",
            portfolio_id=config.portfolio_id,
            trigger=trigger.value,
            num_strategies=len(config.strategy_configs),
        )

        # Compute target allocations
        allocation_result = self._allocation_engine.compute_allocations(
            config,
            performances,
        )

        # Build performance lookup
        perf_map = {p.strategy_id: p for p in performances}

        # Compute total current equity in Decimal — money math must never
        # round-trip through float64 (silent precision loss on fractional
        # cents, non-USD quote precision, and odd-lot share prices).
        total_equity: Decimal = Decimal("0")
        for p in performances:
            total_equity += p.current_equity

        # Compute per-strategy drift. Weights are dimensionless ratios,
        # constrained to [0,1] by the StrategyDrift contract; we compute
        # them as Decimal ratios and only convert to float at the output
        # boundary. max_drift is accumulated as Decimal to avoid introducing
        # float error into the should_rebalance decision.
        drifts: list[StrategyDrift] = []
        max_drift_d: Decimal = Decimal("0")

        for alloc in allocation_result.allocations:
            perf = perf_map.get(alloc.strategy_id)
            if perf and total_equity > 0:
                current_weight_d = perf.current_equity / total_equity
            else:
                current_weight_d = Decimal("0")
            target_weight_d = Decimal(str(alloc.target_weight))
            drift_d = current_weight_d - target_weight_d
            drift_abs_d = abs(drift_d)
            drift_pct_d = drift_abs_d / target_weight_d if target_weight_d > 0 else Decimal("0")

            drifts.append(
                StrategyDrift(
                    strategy_id=alloc.strategy_id,
                    target_weight=round(float(target_weight_d), 10),
                    current_weight=round(float(current_weight_d), 10),
                    drift=round(float(drift_d), 10),
                    drift_pct=round(float(drift_pct_d), 10),
                )
            )
            if drift_abs_d > max_drift_d:
                max_drift_d = drift_abs_d

        # Convert to float only for the threshold comparison; the threshold
        # itself is a float contract field.
        max_drift_f = float(max_drift_d)

        # Decide whether to rebalance
        should_rebalance = self._should_rebalance(
            trigger,
            max_drift_f,
            config.rebalance_threshold,
        )

        # Build current allocations from performance data (Decimal equity in)
        current_allocations = self._build_current_allocations(
            config,
            perf_map,
            total_equity,
        )

        logger.info(
            "Rebalance evaluation complete",
            portfolio_id=config.portfolio_id,
            max_drift=round(max_drift_f, 6),
            should_rebalance=should_rebalance,
        )

        return RebalanceDecision(
            portfolio_id=config.portfolio_id,
            should_rebalance=should_rebalance,
            trigger=trigger,
            drifts=drifts,
            current_allocations=current_allocations,
            target_allocations=allocation_result.allocations,
            max_drift=round(max_drift_f, 10),
        )

    def execute_rebalance(
        self,
        config: PortfolioConfig,
        performances: list[StrategyPerformanceInput],
        decision: RebalanceDecision,
    ) -> RebalanceResult:
        """
        Execute a rebalance based on a prior decision.

        Computes the capital that would need to move between strategies
        to achieve the target allocations.

        Args:
            config: Portfolio configuration.
            performances: Current per-strategy performance data.
            decision: Prior rebalance decision to execute.

        Returns:
            RebalanceResult with capital movement details.

        Example:
            result = orchestrator.execute_rebalance(config, perfs, decision)
        """
        started_at = datetime.now(timezone.utc)

        logger.info(
            "Executing rebalance",
            portfolio_id=config.portfolio_id,
            trigger=decision.trigger.value,
        )

        # Build performance lookup
        perf_map = {p.strategy_id: p for p in performances}

        # Compute capital movements in pure Decimal arithmetic. Casting
        # current_equity or capital_allocated to float here would silently
        # drop precision — dollars or fractional units can drift by up to
        # half an ULP per conversion, and summing many such deltas
        # accumulates visible error on large portfolios. Keep Decimal.
        min_adjustment = Decimal("0.01")  # $0.01 — below this, treat as no-op
        total_capital_moved = Decimal("0")
        strategies_adjusted = 0

        for target_alloc in decision.target_allocations:
            perf = perf_map.get(target_alloc.strategy_id)
            current_capital: Decimal = perf.current_equity if perf else Decimal("0")
            target_capital: Decimal = target_alloc.capital_allocated
            delta: Decimal = abs(target_capital - current_capital)

            if delta > min_adjustment:
                total_capital_moved += delta
                strategies_adjusted += 1

        completed_at = datetime.now(timezone.utc)

        # Track rebalance count (thread-safe)
        with self._lock:
            self._rebalances_executed += 1
            self._last_rebalance_at = completed_at

        logger.info(
            "Rebalance executed",
            portfolio_id=config.portfolio_id,
            strategies_adjusted=strategies_adjusted,
            total_capital_moved=str(total_capital_moved),
        )

        return RebalanceResult(
            portfolio_id=config.portfolio_id,
            decision=decision,
            success=True,
            strategies_adjusted=strategies_adjusted,
            total_capital_moved=total_capital_moved,
            started_at=started_at,
            completed_at=completed_at,
        )

    def get_diagnostics(
        self,
        config: PortfolioConfig,
        performances: list[StrategyPerformanceInput],
    ) -> OrchestratorDiagnostics:
        """
        Get current orchestrator diagnostics.

        Args:
            config: Portfolio configuration.
            performances: Current per-strategy performance data.

        Returns:
            OrchestratorDiagnostics snapshot.

        Example:
            diag = orchestrator.get_diagnostics(config, performances)
        """
        # Count enabled strategies
        enabled_count = sum(1 for sc in config.strategy_configs if sc.enabled)

        # Total equity from performance data
        total_equity = Decimal("0")
        for p in performances:
            total_equity += p.current_equity

        # Compute max drift by evaluating allocations — Decimal throughout
        # to match the precision guarantees of evaluate_rebalance(). We
        # convert to float only at the output boundary where the
        # OrchestratorDiagnostics contract demands float.
        allocation_result = self._allocation_engine.compute_allocations(
            config,
            performances,
        )
        perf_map = {p.strategy_id: p for p in performances}

        max_drift_d: Decimal = Decimal("0")
        for alloc in allocation_result.allocations:
            perf = perf_map.get(alloc.strategy_id)
            if perf and total_equity > 0:
                current_weight_d = perf.current_equity / total_equity
            else:
                current_weight_d = Decimal("0")
            target_weight_d = Decimal(str(alloc.target_weight))
            drift_abs_d = abs(current_weight_d - target_weight_d)
            if drift_abs_d > max_drift_d:
                max_drift_d = drift_abs_d
        max_drift = float(max_drift_d)

        with self._lock:
            rebalances = self._rebalances_executed
            last_rebalance = self._last_rebalance_at

        return OrchestratorDiagnostics(
            portfolio_id=config.portfolio_id,
            state=OrchestratorState.RUNNING,
            num_active_strategies=enabled_count,
            total_equity=total_equity,
            last_rebalance_at=last_rebalance,
            rebalances_executed=rebalances,
            max_current_drift=round(max_drift, 10),
            allocation_method=config.allocation_method,
        )

    # ------------------------------------------------------------------
    # Internal: Rebalance decision logic
    # ------------------------------------------------------------------

    @staticmethod
    def _should_rebalance(
        trigger: RebalanceTrigger,
        max_drift: float,
        threshold: float,
    ) -> bool:
        """
        Decide whether to rebalance based on trigger type and drift.

        Manual and scheduled triggers always rebalance.
        Threshold drift and drawdown breach triggers check drift vs threshold.

        Args:
            trigger: What triggered the evaluation.
            max_drift: Largest absolute drift among strategies.
            threshold: Configured rebalance threshold.

        Returns:
            True if rebalancing should proceed.
        """
        # Manual and scheduled always rebalance
        if trigger in (RebalanceTrigger.MANUAL, RebalanceTrigger.SCHEDULED):
            return True

        # Threshold-based: rebalance if max drift exceeds threshold
        return max_drift > threshold

    # ------------------------------------------------------------------
    # Internal: Build current allocations from performance
    # ------------------------------------------------------------------

    @staticmethod
    def _build_current_allocations(
        config: PortfolioConfig,
        perf_map: dict[str, StrategyPerformanceInput],
        total_equity: Decimal,
    ) -> list:
        """
        Build current StrategyAllocation list from performance data.

        Monetary values (capital_allocated) are preserved as the exact
        Decimal supplied by the caller — no float round-trip, no rounding
        to cents. The StrategyAllocation contract stores capital_allocated
        as Decimal precisely so downstream risk and reconciliation math
        can be exact.

        Weight fields on the contract are typed as float and must be in
        [0, 1]; we compute the ratio as Decimal and convert to float only
        at this single boundary.

        Args:
            config: Portfolio configuration.
            perf_map: Performance data keyed by strategy_id.
            total_equity: Total portfolio equity (Decimal).

        Returns:
            List of StrategyAllocation with current weights and exact capital.
        """
        from libs.contracts.portfolio import StrategyAllocation

        allocations = []
        for sc in config.strategy_configs:
            perf = perf_map.get(sc.strategy_id)
            if perf and total_equity > 0:
                current_weight_d = perf.current_equity / total_equity
                current_weight = float(current_weight_d)
            else:
                current_weight = 0.0
            # Preserve equity exactly — real-money math should not round
            # silently to cents here. The repository / broker adapter
            # layer is responsible for venue-appropriate rounding.
            capital: Decimal = perf.current_equity if perf else Decimal("0")

            allocations.append(
                StrategyAllocation(
                    strategy_id=sc.strategy_id,
                    deployment_id=sc.deployment_id,
                    target_weight=current_weight,
                    current_weight=current_weight,
                    capital_allocated=capital,
                    max_drawdown_limit=sc.max_drawdown_limit,
                )
            )
        return allocations
