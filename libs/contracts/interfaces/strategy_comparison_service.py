"""
Strategy comparison service interface (Phase 7 — M13).

Responsibilities:
- Define the abstract contract for comparing strategy performance.
- Serve as the dependency injection target for routes.

Does NOT:
- Implement comparison logic (service responsibility).
- Fetch P&L data (PnlAttributionService responsibility).
- Persist results (caller responsibility).

Dependencies:
- None (pure interface).

Error conditions:
- ValidationError: insufficient data for comparison.
- NotFoundError: deployment not found.

Example:
    service: StrategyComparisonServiceInterface = StrategyComparisonService(...)
    result = service.compare_strategies(request)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.strategy_comparison import (
    StrategyComparisonRequest,
    StrategyComparisonResult,
    StrategyMetrics,
)


class StrategyComparisonServiceInterface(ABC):
    """
    Port interface for strategy performance comparison and ranking.

    Responsibilities:
    - Compare multiple strategies by risk-adjusted metrics.
    - Rank strategies by configurable criteria.
    - Compute expanded metrics for individual strategies.

    Does NOT:
    - Execute trades or manage positions.
    - Persist comparison results.
    """

    @abstractmethod
    def compare_strategies(
        self,
        request: StrategyComparisonRequest,
    ) -> StrategyComparisonResult:
        """
        Compare and rank strategies by the requested criteria.

        Fetches P&L timeseries for each deployment, computes all
        metrics, and returns ranked results.

        Args:
            request: Comparison request with deployment IDs and criteria.

        Returns:
            StrategyComparisonResult with rankings and comparison matrix.

        Raises:
            ValidationError: If fewer than 2 deployments have data.
        """
        ...

    @abstractmethod
    def get_strategy_metrics(
        self,
        deployment_id: str,
    ) -> StrategyMetrics:
        """
        Compute expanded metrics for a single deployment.

        Args:
            deployment_id: Deployment identifier.

        Returns:
            StrategyMetrics with all computed values.

        Raises:
            NotFoundError: If deployment has no P&L data.
        """
        ...
