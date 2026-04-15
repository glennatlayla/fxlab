"""
Portfolio allocation engine — capital allocation across strategies (M12).

Responsibilities:
- Compute target allocations using configurable methods:
  equal weight, risk parity, inverse volatility, Kelly optimal, fixed.
- Enforce portfolio-level constraints (leverage cap, drawdown limits).
- Return immutable AllocationResult with per-strategy allocations.

Does NOT:
- Execute trades or rebalancing orders (orchestrator responsibility).
- Persist results (caller responsibility).
- Manage execution loops.

Dependencies:
- structlog: Structured logging.
- libs.contracts.portfolio: PortfolioConfig, AllocationResult, etc.
- libs.contracts.interfaces.portfolio_allocation_engine: PortfolioAllocationEngineInterface.

Error conditions:
- ValueError: if no enabled strategies in portfolio config.

Example:
    engine = PortfolioAllocationEngine()
    config = PortfolioConfig(
        portfolio_id="pf-001",
        name="Test",
        total_capital=Decimal("1000000"),
        allocation_method=AllocationMethod.EQUAL_WEIGHT,
        strategy_configs=[...],
    )
    result = engine.compute_allocations(config, performances)
"""

from __future__ import annotations

from decimal import Decimal

import structlog

from libs.contracts.interfaces.portfolio_allocation_engine import (
    PortfolioAllocationEngineInterface,
)
from libs.contracts.portfolio import (
    AllocationMethod,
    AllocationResult,
    PortfolioConfig,
    StrategyAllocation,
    StrategyAllocationConfig,
    StrategyPerformanceInput,
)

logger = structlog.get_logger(__name__)


class PortfolioAllocationEngine(PortfolioAllocationEngineInterface):
    """
    Portfolio allocation engine for multi-strategy capital distribution.

    Computes target allocations using one of five methods, then applies
    portfolio-level constraints (leverage cap, per-strategy drawdown limits).

    Responsibilities:
    - Filter to enabled strategies only.
    - Compute raw weights using configured allocation method.
    - Apply drawdown limit constraints (zero out breaching strategies).
    - Apply leverage cap (scale down if total weight exceeds cap).
    - Redistribute weight from excluded strategies to remaining ones.
    - Compute capital allocations from final weights.

    Does NOT:
    - Execute trades or manage execution loops.
    - Persist results.

    Thread safety:
    - Thread-safe: each compute_allocations() call uses only local state.

    Example:
        engine = PortfolioAllocationEngine()
        result = engine.compute_allocations(config, performances)
    """

    def compute_allocations(
        self,
        config: PortfolioConfig,
        performances: list[StrategyPerformanceInput],
    ) -> AllocationResult:
        """
        Compute portfolio allocations for the given configuration.

        Args:
            config: Portfolio configuration with method, strategies, constraints.
            performances: Per-strategy performance metrics.

        Returns:
            AllocationResult with target weights and capital allocations.

        Raises:
            ValueError: If no enabled strategies in portfolio.

        Example:
            result = engine.compute_allocations(config, performances)
        """
        logger.info(
            "Portfolio allocation started",
            portfolio_id=config.portfolio_id,
            method=config.allocation_method.value,
            num_strategies=len(config.strategy_configs),
        )

        # Build performance lookup keyed by strategy_id
        perf_map: dict[str, StrategyPerformanceInput] = {p.strategy_id: p for p in performances}

        # Filter to enabled strategies
        enabled_configs = [sc for sc in config.strategy_configs if sc.enabled]
        if not enabled_configs:
            raise ValueError("No enabled strategies in portfolio configuration")

        # Compute raw weights using the configured method
        raw_weights = self._compute_raw_weights(
            config.allocation_method,
            enabled_configs,
            perf_map,
        )

        # Apply drawdown limit constraint: zero out strategies exceeding their limit
        constrained = False
        constraint_notes: list[str] = []
        for sc in enabled_configs:
            perf = perf_map.get(sc.strategy_id)
            if perf and perf.max_drawdown > sc.max_drawdown_limit:
                raw_weights[sc.strategy_id] = 0.0
                constrained = True
                constraint_notes.append(
                    f"{sc.strategy_id}: drawdown {perf.max_drawdown:.2%} "
                    f"exceeds limit {sc.max_drawdown_limit:.2%}, zeroed",
                )

        # Redistribute: normalise non-zero weights to sum to 1.0
        # Skip normalisation for FIXED method — user-specified weights are used as-is,
        # and the leverage cap constraint handles any over-allocation.
        if config.allocation_method != AllocationMethod.FIXED:
            raw_weights = self._normalise_weights(raw_weights)

        # Apply leverage cap
        total_raw = sum(raw_weights.values())
        if total_raw > config.max_total_leverage + 1e-12:
            scale = config.max_total_leverage / total_raw
            raw_weights = {k: v * scale for k, v in raw_weights.items()}
            constrained = True
            constraint_notes.append(
                f"Total weight {total_raw:.4f} exceeded leverage cap "
                f"{config.max_total_leverage}, scaled down",
            )

        # Build allocations for ALL strategies (enabled get weights, disabled get 0)
        allocations: list[StrategyAllocation] = []
        total_weight = 0.0
        for sc in config.strategy_configs:
            weight = raw_weights.get(sc.strategy_id, 0.0)
            capital = Decimal(str(round(float(config.total_capital) * weight, 2)))
            perf = perf_map.get(sc.strategy_id)
            current_weight = (
                float(perf.current_equity) / float(config.total_capital)
                if perf and float(config.total_capital) > 0
                else 0.0
            )

            allocations.append(
                StrategyAllocation(
                    strategy_id=sc.strategy_id,
                    deployment_id=sc.deployment_id,
                    target_weight=weight,
                    current_weight=min(current_weight, 1.0),
                    capital_allocated=capital,
                    max_drawdown_limit=sc.max_drawdown_limit,
                )
            )
            total_weight += weight

        logger.info(
            "Portfolio allocation completed",
            portfolio_id=config.portfolio_id,
            total_weight=round(total_weight, 6),
            constrained=constrained,
            num_allocations=len(allocations),
        )

        return AllocationResult(
            config=config,
            allocations=allocations,
            total_weight=round(total_weight, 10),
            leverage_utilised=round(total_weight, 10),
            constrained=constrained,
            constraint_notes=constraint_notes,
        )

    # ------------------------------------------------------------------
    # Internal: Compute raw weights by method
    # ------------------------------------------------------------------

    def _compute_raw_weights(
        self,
        method: AllocationMethod,
        enabled_configs: list[StrategyAllocationConfig],
        perf_map: dict[str, StrategyPerformanceInput],
    ) -> dict[str, float]:
        """
        Compute raw (pre-constraint) weights using the configured method.

        Args:
            method: Allocation method to use.
            enabled_configs: Enabled strategy configurations.
            perf_map: Performance data keyed by strategy_id.

        Returns:
            Dict of strategy_id → raw weight.
        """
        if method == AllocationMethod.EQUAL_WEIGHT:
            return self._equal_weight(enabled_configs)
        if method in (AllocationMethod.RISK_PARITY, AllocationMethod.INVERSE_VOLATILITY):
            return self._inverse_volatility_weight(enabled_configs, perf_map)
        if method == AllocationMethod.KELLY_OPTIMAL:
            return self._kelly_weight(enabled_configs, perf_map)
        if method == AllocationMethod.FIXED:
            return self._fixed_weight(enabled_configs)

        # Unreachable due to enum exhaustiveness, but satisfy type checker
        return self._equal_weight(enabled_configs)

    # ------------------------------------------------------------------
    # Equal Weight
    # ------------------------------------------------------------------

    @staticmethod
    def _equal_weight(
        enabled_configs: list[StrategyAllocationConfig],
    ) -> dict[str, float]:
        """
        Equal weight: divide equally among enabled strategies.

        Args:
            enabled_configs: Enabled strategy configurations.

        Returns:
            Dict of strategy_id → 1/N weight.
        """
        n = len(enabled_configs)
        weight = 1.0 / n if n > 0 else 0.0
        return {sc.strategy_id: weight for sc in enabled_configs}

    # ------------------------------------------------------------------
    # Inverse Volatility / Risk Parity
    # ------------------------------------------------------------------

    @staticmethod
    def _inverse_volatility_weight(
        enabled_configs: list[StrategyAllocationConfig],
        perf_map: dict[str, StrategyPerformanceInput],
    ) -> dict[str, float]:
        """
        Inverse volatility weighting (used for both RISK_PARITY and INVERSE_VOLATILITY).

        Weight for each strategy is proportional to 1/volatility. Zero-volatility
        strategies receive a large but finite inverse (1/min_vol_floor) to avoid
        division by zero.

        Args:
            enabled_configs: Enabled strategy configurations.
            perf_map: Performance data keyed by strategy_id.

        Returns:
            Dict of strategy_id → normalised inverse-vol weight.
        """
        # Floor for zero volatility to avoid division by zero
        min_vol_floor = 1e-8

        inv_vols: dict[str, float] = {}
        for sc in enabled_configs:
            perf = perf_map.get(sc.strategy_id)
            vol = perf.volatility if perf else 0.0
            inv_vols[sc.strategy_id] = 1.0 / max(vol, min_vol_floor)

        total_inv = sum(inv_vols.values())
        if total_inv == 0:
            # Fallback to equal weight
            n = len(enabled_configs)
            return {sc.strategy_id: 1.0 / n for sc in enabled_configs}

        return {sid: iv / total_inv for sid, iv in inv_vols.items()}

    # ------------------------------------------------------------------
    # Kelly Optimal
    # ------------------------------------------------------------------

    def _kelly_weight(
        self,
        enabled_configs: list[StrategyAllocationConfig],
        perf_map: dict[str, StrategyPerformanceInput],
    ) -> dict[str, float]:
        """
        Kelly criterion-based allocation.

        Kelly fraction = win_rate - (1 - win_rate) / avg_win_loss_ratio.
        Negative fractions are clamped to 0. If all fractions are 0,
        falls back to equal weight.

        Uses half-Kelly for practical safety (multiply raw Kelly by 0.5).

        Args:
            enabled_configs: Enabled strategy configurations.
            perf_map: Performance data keyed by strategy_id.

        Returns:
            Dict of strategy_id → normalised Kelly weight.
        """
        kelly_fractions: dict[str, float] = {}
        for sc in enabled_configs:
            perf = perf_map.get(sc.strategy_id)
            if perf and perf.avg_win_loss_ratio > 0:
                # Kelly formula: f* = p - q/b where p=win_rate, q=1-p, b=avg_win/avg_loss
                kelly = perf.win_rate - (1.0 - perf.win_rate) / perf.avg_win_loss_ratio
                # Half-Kelly for safety
                kelly = max(kelly * 0.5, 0.0)
            else:
                kelly = 0.0
            kelly_fractions[sc.strategy_id] = kelly

        total_kelly = sum(kelly_fractions.values())

        # If all Kelly fractions are zero/negative, fall back to equal weight
        if total_kelly <= 0:
            return self._equal_weight(enabled_configs)

        # Normalise to sum to 1.0
        return {sid: kf / total_kelly for sid, kf in kelly_fractions.items()}

    # ------------------------------------------------------------------
    # Fixed Weight
    # ------------------------------------------------------------------

    @staticmethod
    def _fixed_weight(
        enabled_configs: list[StrategyAllocationConfig],
    ) -> dict[str, float]:
        """
        Fixed weight: use the user-specified fixed_weight from each config.

        Weights are used as-is (not normalised), but may be scaled down
        by the leverage cap constraint.

        Args:
            enabled_configs: Enabled strategy configurations.

        Returns:
            Dict of strategy_id → fixed weight.
        """
        return {sc.strategy_id: sc.fixed_weight for sc in enabled_configs}

    # ------------------------------------------------------------------
    # Utility: Normalise weights
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_weights(weights: dict[str, float]) -> dict[str, float]:
        """
        Normalise non-zero weights to sum to 1.0.

        Zero-weight entries remain at 0. Only positive weights are scaled.

        Args:
            weights: Dict of strategy_id → weight.

        Returns:
            Normalised dict of strategy_id → weight.
        """
        positive_total = sum(w for w in weights.values() if w > 0)
        if positive_total <= 0:
            return weights

        return {sid: (w / positive_total if w > 0 else 0.0) for sid, w in weights.items()}
