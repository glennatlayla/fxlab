"""
Portfolio orchestrator interface (port).

Responsibilities:
- Define the abstract contract for portfolio orchestration.
- Specify methods for drift detection, rebalance evaluation, and execution.

Does NOT:
- Implement orchestration logic (PortfolioOrchestrator responsibility).
- Define result contracts (libs.contracts.portfolio_orchestrator).
- Manage API routing.

Dependencies:
- libs.contracts.portfolio: PortfolioConfig, StrategyPerformanceInput.
- libs.contracts.portfolio_orchestrator: RebalanceRequest, RebalanceDecision,
  RebalanceResult, OrchestratorDiagnostics.

Example:
    orchestrator: PortfolioOrchestratorInterface = PortfolioOrchestrator(engine)
    decision = orchestrator.evaluate_rebalance(config, performances)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.portfolio import PortfolioConfig, StrategyPerformanceInput
from libs.contracts.portfolio_orchestrator import (
    OrchestratorDiagnostics,
    RebalanceDecision,
    RebalanceResult,
    RebalanceTrigger,
)


class PortfolioOrchestratorInterface(ABC):
    """
    Port interface for portfolio orchestration.

    Provides drift detection, rebalance decision-making, and rebalance
    execution coordination.

    Responsibilities:
    - Evaluate whether a rebalance is needed (drift detection).
    - Compute rebalance decisions with old/new allocations.
    - Execute rebalance by computing capital adjustments.
    - Report orchestrator diagnostics.

    Does NOT:
    - Submit actual broker orders (caller coordinates with broker adapters).
    - Manage execution loop lifecycle directly.

    Example:
        decision = orchestrator.evaluate_rebalance(config, performances)
        if decision.should_rebalance:
            result = orchestrator.execute_rebalance(config, performances, decision)
    """

    @abstractmethod
    def evaluate_rebalance(
        self,
        config: PortfolioConfig,
        performances: list[StrategyPerformanceInput],
        trigger: RebalanceTrigger,
    ) -> RebalanceDecision:
        """
        Evaluate whether a rebalance is needed.

        Computes current vs target allocations and measures drift.

        Args:
            config: Portfolio configuration.
            performances: Current per-strategy performance data.
            trigger: What triggered this evaluation.

        Returns:
            RebalanceDecision indicating whether rebalancing is warranted.

        Example:
            decision = orchestrator.evaluate_rebalance(config, perfs, trigger)
        """

    @abstractmethod
    def execute_rebalance(
        self,
        config: PortfolioConfig,
        performances: list[StrategyPerformanceInput],
        decision: RebalanceDecision,
    ) -> RebalanceResult:
        """
        Execute a rebalance based on a prior decision.

        Computes capital movements needed to achieve target allocations.

        Args:
            config: Portfolio configuration.
            performances: Current per-strategy performance data.
            decision: Prior rebalance decision to execute.

        Returns:
            RebalanceResult with outcome details.

        Example:
            result = orchestrator.execute_rebalance(config, perfs, decision)
        """

    @abstractmethod
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
