"""
Stress testing and scenario analysis service implementation.

Responsibilities:
- Execute custom and predefined stress scenarios against portfolio positions.
- Compute per-symbol and portfolio-level P&L impact from percentage shocks.
- Estimate margin impact from stressed portfolio values.
- Determine whether stressed P&L would trigger deployment halt.
- Provide list of predefined historical scenarios.

Does NOT:
- Trigger actual risk actions (advisory/informational only).
- Persist stress test results (caller or cache layer responsibility).
- Fetch data directly from databases (injected via repository interfaces).

Dependencies:
- PositionRepositoryInterface (injected): current position holdings.
- RiskGateInterface (injected): risk limits for halt detection.

Error conditions:
- NotFoundError: deployment has no positions.
- ValidationError: invalid scenario parameters.

Example:
    service = StressTestService(
        position_repo=position_repo,
        risk_gate=risk_gate_service,
    )
    result = service.run_predefined(
        deployment_id="01HDEPLOY...",
        scenario_name=ScenarioLibrary.FLASH_CRASH_2010,
    )
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.stress_test_service import (
    StressTestServiceInterface,
)
from libs.contracts.stress_test import (
    PREDEFINED_SCENARIOS,
    ScenarioLibrary,
    StressScenario,
    StressTestResult,
    SymbolStressImpact,
)

logger = logging.getLogger(__name__)

# Margin impact approximation factor: stressed P&L × this factor
_MARGIN_IMPACT_FACTOR = Decimal("0.5")


class StressTestService(StressTestServiceInterface):
    """
    Production implementation of stress testing and scenario analysis.

    Applies percentage shocks to current positions and computes
    portfolio-level and per-symbol P&L impact. Checks against
    configured risk limits to determine halt triggers.

    Responsibilities:
    - Apply symbol-specific or wildcard shocks to positions.
    - Compute stressed market values and P&L deltas.
    - Estimate margin impact (50% of P&L for equities).
    - Compare stressed P&L against daily loss limits.

    Does NOT:
    - Access databases directly (injected via interfaces).
    - Execute actual trades or risk actions.
    - Cache results.

    Dependencies:
    - position_repo: PositionRepositoryInterface for position data.
    - risk_gate: RiskGateInterface for risk limit lookup (optional).

    Example:
        service = StressTestService(
            position_repo=sql_position_repo,
            risk_gate=risk_gate_service,
        )
        result = service.run_scenario(
            deployment_id="01HDEPLOY...",
            scenario=custom_scenario,
        )
    """

    def __init__(
        self,
        position_repo: Any,
        risk_gate: Any | None = None,
    ) -> None:
        """
        Initialize StressTestService.

        Args:
            position_repo: Repository for position data (PositionRepositoryInterface).
            risk_gate: Risk gate service for limit lookups (RiskGateInterface, optional).
        """
        self._position_repo = position_repo
        self._risk_gate = risk_gate

    def run_scenario(
        self,
        *,
        deployment_id: str,
        scenario: StressScenario,
    ) -> StressTestResult:
        """
        Run a stress scenario against a deployment's portfolio.

        For each position, applies the relevant shock percentage:
        - If the position's symbol appears in shocks, use that specific shock.
        - If "*" (wildcard) appears in shocks, apply it to all positions
          that don't have a symbol-specific shock.
        - If neither matches, the position is unaffected (0% shock).

        Args:
            deployment_id: ULID of the deployment.
            scenario: Stress scenario with shock parameters.

        Returns:
            StressTestResult with full impact analysis.

        Raises:
            NotFoundError: If the deployment has no positions.
        """
        positions = self._get_positions(deployment_id)

        logger.info(
            "Running stress scenario",
            extra={
                "operation": "run_scenario",
                "component": "StressTestService",
                "deployment_id": deployment_id,
                "scenario_name": scenario.name,
                "n_positions": len(positions),
                "n_shocks": len(scenario.shocks),
            },
        )

        wildcard_shock = scenario.shocks.get("*")
        per_symbol_impacts: list[SymbolStressImpact] = []
        total_pnl_impact = Decimal("0")

        for pos in positions:
            symbol = pos["symbol"]
            current_value = Decimal(str(pos["market_value"]))

            # Determine applicable shock
            if symbol in scenario.shocks:
                shock_pct = scenario.shocks[symbol]
            elif wildcard_shock is not None:
                shock_pct = wildcard_shock
            else:
                shock_pct = Decimal("0")

            # Apply shock: stressed_value = current_value * (1 + shock_pct/100)
            shock_factor = Decimal("1") + shock_pct / Decimal("100")
            stressed_value = (current_value * shock_factor).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            pnl_impact = (stressed_value - current_value).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            per_symbol_impacts.append(
                SymbolStressImpact(
                    symbol=symbol,
                    current_value=current_value,
                    shock_pct=shock_pct,
                    stressed_value=stressed_value,
                    pnl_impact=pnl_impact,
                )
            )
            total_pnl_impact += pnl_impact

        # Sort by absolute impact descending
        per_symbol_impacts.sort(key=lambda si: abs(si.pnl_impact), reverse=True)

        # Margin impact approximation
        margin_impact = (total_pnl_impact * _MARGIN_IMPACT_FACTOR).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # Check halt trigger
        would_trigger_halt, daily_loss_limit = self._check_halt_trigger(
            deployment_id, total_pnl_impact
        )

        return StressTestResult(
            scenario_name=scenario.name,
            portfolio_pnl_impact=total_pnl_impact,
            per_symbol_impact=per_symbol_impacts,
            margin_impact=margin_impact,
            would_trigger_halt=would_trigger_halt,
            daily_loss_limit=daily_loss_limit,
        )

    def run_predefined(
        self,
        *,
        deployment_id: str,
        scenario_name: ScenarioLibrary,
    ) -> StressTestResult:
        """
        Run a predefined scenario from the historical library.

        Args:
            deployment_id: ULID of the deployment.
            scenario_name: Predefined scenario identifier.

        Returns:
            StressTestResult with impact analysis.

        Raises:
            NotFoundError: If the deployment has no positions.
            NotFoundError: If the scenario name is not in the library.
        """
        scenario = PREDEFINED_SCENARIOS.get(scenario_name)
        if scenario is None:
            raise NotFoundError(f"Predefined scenario '{scenario_name}' not found in library")

        return self.run_scenario(
            deployment_id=deployment_id,
            scenario=scenario,
        )

    def list_predefined_scenarios(self) -> list[StressScenario]:
        """
        List all available predefined stress scenarios.

        Returns:
            Sorted list of predefined StressScenario configurations.
        """
        return sorted(PREDEFINED_SCENARIOS.values(), key=lambda s: s.name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_positions(self, deployment_id: str) -> list[dict[str, Any]]:
        """
        Fetch positions for a deployment, raising NotFoundError if empty.

        Args:
            deployment_id: Deployment ULID.

        Returns:
            Non-empty list of position dicts.

        Raises:
            NotFoundError: If the deployment has no positions.
        """
        positions = self._position_repo.list_by_deployment(deployment_id=deployment_id)
        if not positions:
            raise NotFoundError(f"No positions found for deployment {deployment_id}")
        return positions

    def _check_halt_trigger(
        self,
        deployment_id: str,
        pnl_impact: Decimal,
    ) -> tuple[bool, Decimal | None]:
        """
        Check if stressed P&L would trigger a deployment halt.

        Compares the absolute value of P&L impact against the configured
        daily loss limit. If no risk gate is configured or no limits are
        set, returns (False, None).

        Args:
            deployment_id: Deployment ULID.
            pnl_impact: Total portfolio P&L impact from stress test.

        Returns:
            Tuple of (would_trigger_halt, daily_loss_limit).
        """
        if self._risk_gate is None:
            return False, None

        try:
            limits = self._risk_gate.get_risk_limits(deployment_id=deployment_id)
        except NotFoundError:
            return False, None

        daily_loss_limit = limits.max_daily_loss
        if daily_loss_limit is None or daily_loss_limit == Decimal("0"):
            return False, None

        # Compare absolute loss against limit
        would_halt = abs(pnl_impact) >= daily_loss_limit
        return would_halt, daily_loss_limit
