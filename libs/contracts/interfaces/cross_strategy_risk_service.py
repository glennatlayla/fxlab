"""
Cross-strategy risk service interface (port).

Responsibilities:
- Define the abstract contract for cross-strategy risk aggregation.
- Specify methods for VaR, marginal VaR, correlations, drawdown sync,
  and optimization suggestions.

Does NOT:
- Implement risk calculations (service layer responsibility).
- Define result contracts (libs.contracts.cross_strategy_risk).

Dependencies:
- libs.contracts.cross_strategy_risk: all result types.
- libs.contracts.portfolio: PortfolioConfig, StrategyPerformanceInput.

Example:
    service: CrossStrategyRiskServiceInterface = CrossStrategyRiskService()
    var = service.compute_portfolio_var(config, performances)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.cross_strategy_risk import (
    CorrelationMatrix,
    DrawdownSyncEvent,
    MarginalVaRResult,
    OptimizationSuggestion,
    PortfolioVaR,
)
from libs.contracts.portfolio import PortfolioConfig, StrategyPerformanceInput


class CrossStrategyRiskServiceInterface(ABC):
    """
    Port interface for cross-strategy risk aggregation.

    Provides portfolio-level risk metrics, correlation tracking,
    drawdown synchronization detection, and allocation optimization.

    Responsibilities:
    - Compute portfolio-level VaR from strategy return data.
    - Decompose VaR into per-strategy marginal contributions.
    - Compute strategy return correlation matrix.
    - Detect synchronized drawdown events.
    - Suggest optimised capital allocations.

    Does NOT:
    - Execute trades or rebalancing.
    - Persist results.

    Example:
        var = service.compute_portfolio_var(config, performances)
        corr = service.compute_correlation_matrix(config, performances)
    """

    @abstractmethod
    def compute_portfolio_var(
        self,
        config: PortfolioConfig,
        performances: list[StrategyPerformanceInput],
    ) -> PortfolioVaR:
        """
        Compute portfolio-level Value at Risk.

        Args:
            config: Portfolio configuration.
            performances: Per-strategy performance data with returns.

        Returns:
            PortfolioVaR with 95% and 99% VaR.

        Example:
            var = service.compute_portfolio_var(config, performances)
        """

    @abstractmethod
    def compute_marginal_var(
        self,
        config: PortfolioConfig,
        performances: list[StrategyPerformanceInput],
    ) -> MarginalVaRResult:
        """
        Compute per-strategy marginal VaR contribution.

        Args:
            config: Portfolio configuration.
            performances: Per-strategy performance data with returns.

        Returns:
            MarginalVaRResult with per-strategy VaR decomposition.

        Example:
            mvar = service.compute_marginal_var(config, performances)
        """

    @abstractmethod
    def compute_correlation_matrix(
        self,
        config: PortfolioConfig,
        performances: list[StrategyPerformanceInput],
    ) -> CorrelationMatrix:
        """
        Compute pairwise correlation matrix of strategy returns.

        Args:
            config: Portfolio configuration.
            performances: Per-strategy performance data with returns.

        Returns:
            CorrelationMatrix with pairwise correlations and high-correlation alerts.

        Example:
            corr = service.compute_correlation_matrix(config, performances)
        """

    @abstractmethod
    def detect_drawdown_sync(
        self,
        config: PortfolioConfig,
        performances: list[StrategyPerformanceInput],
        drawdown_threshold: float = 0.05,
    ) -> list[DrawdownSyncEvent]:
        """
        Detect synchronized drawdown events across strategies.

        Args:
            config: Portfolio configuration.
            performances: Per-strategy performance data.
            drawdown_threshold: Minimum drawdown to count as in-drawdown.

        Returns:
            List of DrawdownSyncEvent for each detected synchronization.

        Example:
            events = service.detect_drawdown_sync(config, performances)
        """

    @abstractmethod
    def suggest_optimization(
        self,
        config: PortfolioConfig,
        performances: list[StrategyPerformanceInput],
    ) -> OptimizationSuggestion:
        """
        Suggest optimised allocation weights using mean-variance optimization.

        Args:
            config: Portfolio configuration.
            performances: Per-strategy performance data with returns.

        Returns:
            OptimizationSuggestion with suggested weights and expected metrics.

        Example:
            suggestion = service.suggest_optimization(config, performances)
        """
