"""
Portfolio allocation engine interface (port).

Responsibilities:
- Define the abstract contract for portfolio allocation engines.
- Specify the compute_allocations method signature.

Does NOT:
- Implement allocation logic (engine layer responsibility).
- Define result contracts (libs.contracts.portfolio).
- Manage execution loops or rebalancing.

Dependencies:
- libs.contracts.portfolio: PortfolioConfig, AllocationResult, StrategyPerformanceInput

Example:
    engine: PortfolioAllocationEngineInterface = PortfolioAllocationEngine()
    result = engine.compute_allocations(config, performances)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.portfolio import (
    AllocationResult,
    PortfolioConfig,
    StrategyPerformanceInput,
)


class PortfolioAllocationEngineInterface(ABC):
    """
    Port interface for portfolio allocation engines.

    Takes a PortfolioConfig and per-strategy performance data,
    computes target allocations using the configured method.

    Responsibilities:
    - Accept a PortfolioConfig and list of StrategyPerformanceInput.
    - Return AllocationResult with computed weights and capital allocations.
    - Enforce portfolio-level constraints (leverage, drawdown caps).

    Does NOT:
    - Execute trades or rebalancing orders.
    - Persist results.
    - Manage execution loops.

    Example:
        result = engine.compute_allocations(config, performances)
    """

    @abstractmethod
    def compute_allocations(
        self,
        config: PortfolioConfig,
        performances: list[StrategyPerformanceInput],
    ) -> AllocationResult:
        """
        Compute portfolio allocations for the given configuration and performance data.

        Args:
            config: Portfolio configuration with method, strategies, and constraints.
            performances: Per-strategy performance metrics (volatility, win rate, etc.).

        Returns:
            AllocationResult with target weights and capital allocations.

        Raises:
            ValueError: If no enabled strategies or performance data is inconsistent.

        Example:
            result = engine.compute_allocations(config, performances)
        """
