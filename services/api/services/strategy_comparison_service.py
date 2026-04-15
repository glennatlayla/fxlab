"""
Strategy comparison and ranking service (Phase 7 — M13).

Responsibilities:
- Fetch P&L summaries for each deployment via PnlAttributionService.
- Compute advanced risk-adjusted metrics (Sortino, Calmar, risk-adjusted return).
- Rank strategies by configurable criteria.
- Produce a comparison matrix with all strategies × all metrics.

Does NOT:
- Execute trades (deployment responsibility).
- Persist comparison results (caller responsibility).
- Fetch market data (indicator/market data service responsibility).

Dependencies:
- PnlAttributionServiceInterface (injected): P&L data source.

Error conditions:
- ValidationError: fewer than 2 deployments have P&L data.

Example:
    service = StrategyComparisonService(pnl_service=pnl_service)
    result = service.compare_strategies(request)
"""

from __future__ import annotations

import logging
import math
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from libs.contracts.interfaces.strategy_comparison_service import (
    StrategyComparisonServiceInterface,
)
from libs.contracts.strategy_comparison import (
    StrategyComparisonRequest,
    StrategyComparisonResult,
    StrategyMetrics,
    StrategyRank,
    StrategyRankingCriteria,
)
from services.api.services.interfaces.pnl_attribution_service_interface import (
    PnlAttributionServiceInterface,
)

logger = logging.getLogger(__name__)

# Annualization factor for daily data (trading days per year)
_TRADING_DAYS_PER_YEAR = 252

# Cap for Calmar ratio when drawdown approaches zero
_CALMAR_RATIO_CAP = Decimal("100")


class StrategyComparisonService(StrategyComparisonServiceInterface):
    """
    Production implementation of strategy performance comparison.

    Fetches P&L summary data for each deployment, computes additional
    risk-adjusted metrics (Sortino ratio, Calmar ratio, risk-adjusted
    return), ranks by the requested criteria, and returns a comparison
    matrix.

    Responsibilities:
    - Compute Sortino ratio from daily P&L downside deviation.
    - Compute Calmar ratio (annualized return / |max drawdown|).
    - Compute risk-adjusted return (Sharpe × sqrt(252)).
    - Rank strategies with deterministic tiebreaker (deployment_id).

    Does NOT:
    - Execute trades or manage positions.
    - Persist results.

    Dependencies:
    - PnlAttributionServiceInterface (injected).

    Example:
        service = StrategyComparisonService(pnl_service=pnl_service)
        result = service.compare_strategies(request)
    """

    def __init__(
        self,
        *,
        pnl_service: PnlAttributionServiceInterface,
    ) -> None:
        """
        Initialize the strategy comparison service.

        Args:
            pnl_service: P&L attribution service for fetching metrics.
        """
        self._pnl_service = pnl_service

    def compare_strategies(
        self,
        request: StrategyComparisonRequest,
    ) -> StrategyComparisonResult:
        """
        Compare and rank strategies by the requested criteria.

        Fetches P&L summary for each deployment, computes advanced
        metrics, ranks by criteria, and returns the comparison result.

        Args:
            request: Comparison request with deployment IDs and criteria.

        Returns:
            StrategyComparisonResult with rankings and comparison matrix.

        Raises:
            ValidationError: If fewer than 2 deployments have P&L data.
        """
        logger.info(
            "Strategy comparison started",
            extra={
                "operation": "compare_strategies",
                "component": "StrategyComparisonService",
                "deployment_count": len(request.deployment_ids),
                "criteria": request.ranking_criteria.value,
            },
        )

        all_metrics: list[StrategyMetrics] = []

        for dep_id in request.deployment_ids:
            try:
                metrics = self._compute_metrics(dep_id, request.date_from, request.date_to)
                all_metrics.append(metrics)
            except Exception:
                logger.warning(
                    "Strategy comparison: failed to compute metrics",
                    extra={
                        "operation": "compare_strategies",
                        "component": "StrategyComparisonService",
                        "deployment_id": dep_id,
                    },
                    exc_info=True,
                )

        if len(all_metrics) < 2:
            from libs.contracts.errors import ValidationError

            raise ValidationError(
                f"At least 2 deployments must have P&L data for comparison, got {len(all_metrics)}"
            )

        # Rank by the requested criteria
        rankings = self._rank_strategies(all_metrics, request.ranking_criteria)

        logger.info(
            "Strategy comparison completed",
            extra={
                "operation": "compare_strategies",
                "component": "StrategyComparisonService",
                "strategies_compared": len(all_metrics),
                "criteria": request.ranking_criteria.value,
            },
        )

        return StrategyComparisonResult(
            rankings=rankings,
            ranking_criteria=request.ranking_criteria,
            comparison_matrix=all_metrics,
        )

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
        return self._compute_metrics(deployment_id, None, None)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_metrics(
        self,
        deployment_id: str,
        date_from: date | None,
        date_to: date | None,
    ) -> StrategyMetrics:
        """
        Compute full metrics for a single deployment.

        Fetches P&L summary from the PnlAttributionService and then
        computes additional advanced metrics (Sortino, Calmar,
        risk-adjusted return).

        Args:
            deployment_id: Deployment identifier.
            date_from: Optional period start.
            date_to: Optional period end.

        Returns:
            StrategyMetrics with all fields populated.
        """
        summary = self._pnl_service.get_pnl_summary(deployment_id=deployment_id)

        # Extract base metrics from P&L summary
        net_pnl = self._to_decimal(summary.get("net_pnl", 0))
        total_trades = int(summary.get("total_trades", 0))
        winning_trades = int(summary.get("winning_trades", 0))
        win_rate = self._to_decimal(summary.get("win_rate", 0))
        sharpe_ratio = self._to_decimal(summary.get("sharpe_ratio", 0))
        max_drawdown_pct = self._to_decimal(summary.get("max_drawdown_pct", 0))
        profit_factor = self._to_decimal(summary.get("profit_factor", 0))
        strategy_name = str(summary.get("strategy_name", ""))
        total_commission = self._to_decimal(summary.get("total_commission", 0))

        # Fetch timeseries for Sortino/Calmar computation
        daily_returns: list[Decimal] = []
        if date_from and date_to:
            try:
                timeseries = self._pnl_service.get_pnl_timeseries(
                    deployment_id=deployment_id,
                    date_from=date_from,
                    date_to=date_to,
                    granularity="daily",
                )
                daily_returns = [
                    self._to_decimal(point.get("daily_pnl", 0)) for point in timeseries
                ]
            except Exception:
                logger.debug(
                    "Could not fetch timeseries for advanced metrics",
                    extra={
                        "operation": "_compute_metrics",
                        "component": "StrategyComparisonService",
                        "deployment_id": deployment_id,
                    },
                )

        # Compute advanced metrics
        sortino = self._compute_sortino_ratio(daily_returns)
        annualized_return = self._compute_annualized_return(daily_returns)
        calmar = self._compute_calmar_ratio(annualized_return, max_drawdown_pct)
        risk_adj_return = self._compute_risk_adjusted_return(sharpe_ratio)

        # Ensure max_drawdown is negative or zero
        if max_drawdown_pct > Decimal("0"):
            max_drawdown_pct = Decimal("0")

        return StrategyMetrics(
            deployment_id=deployment_id,
            strategy_name=strategy_name,
            net_pnl=net_pnl,
            total_trades=total_trades,
            winning_trades=winning_trades,
            win_rate=self._clamp(win_rate, Decimal("0"), Decimal("1")),
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            max_drawdown_pct=min(max_drawdown_pct, Decimal("0")),
            profit_factor=max(profit_factor, Decimal("0")),
            risk_adjusted_return=risk_adj_return,
            annualized_return_pct=annualized_return,
            total_commission=max(total_commission, Decimal("0")),
        )

    def _rank_strategies(
        self,
        metrics_list: list[StrategyMetrics],
        criteria: StrategyRankingCriteria,
    ) -> list[StrategyRank]:
        """
        Rank strategies by the specified criteria.

        Higher values rank better for all criteria except MAX_DRAWDOWN,
        where less negative (closer to zero) is better.

        Uses deployment_id as deterministic tiebreaker for stable ranking.

        Args:
            metrics_list: List of computed metrics for each strategy.
            criteria: Ranking criteria to sort by.

        Returns:
            Sorted list of StrategyRank objects, rank starting at 1.
        """

        # Extract the sort key based on criteria
        def sort_key(m: StrategyMetrics) -> tuple[Decimal, str]:
            value = self._get_criteria_value(m, criteria)
            # For all criteria: higher value = better rank.
            # MAX_DRAWDOWN values are negative (e.g. -5% > -15%), so
            # the natural ordering (higher = better) already works:
            # -5 > -15, so -5% ranks first. No negation needed.
            return (value, m.deployment_id)

        sorted_metrics = sorted(metrics_list, key=sort_key, reverse=True)

        return [StrategyRank(rank=i + 1, metrics=m) for i, m in enumerate(sorted_metrics)]

    @staticmethod
    def _get_criteria_value(
        metrics: StrategyMetrics,
        criteria: StrategyRankingCriteria,
    ) -> Decimal:
        """
        Extract the metric value for the given ranking criteria.

        Args:
            metrics: Strategy metrics.
            criteria: Which metric to extract.

        Returns:
            Decimal value for the requested metric.
        """
        mapping: dict[StrategyRankingCriteria, Decimal] = {
            StrategyRankingCriteria.SHARPE_RATIO: metrics.sharpe_ratio,
            StrategyRankingCriteria.SORTINO_RATIO: metrics.sortino_ratio,
            StrategyRankingCriteria.CALMAR_RATIO: metrics.calmar_ratio,
            StrategyRankingCriteria.MAX_DRAWDOWN: metrics.max_drawdown_pct,
            StrategyRankingCriteria.WIN_RATE: metrics.win_rate,
            StrategyRankingCriteria.PROFIT_FACTOR: metrics.profit_factor,
            StrategyRankingCriteria.NET_PNL: metrics.net_pnl,
            StrategyRankingCriteria.RISK_ADJUSTED_RETURN: metrics.risk_adjusted_return,
        }
        return mapping.get(criteria, Decimal("0"))

    @staticmethod
    def _compute_sortino_ratio(daily_returns: list[Decimal]) -> Decimal:
        """
        Compute annualized Sortino ratio from daily P&L returns.

        Sortino ratio penalises only downside volatility (negative returns),
        unlike Sharpe which penalises all volatility equally.

        Formula: (mean_daily_return / downside_deviation) × sqrt(252)

        Args:
            daily_returns: List of daily P&L values.

        Returns:
            Annualized Sortino ratio as Decimal.
        """
        if len(daily_returns) < 2:
            return Decimal("0")

        mean_return = sum(daily_returns) / len(daily_returns)

        # Downside deviation: std dev of returns below zero
        negative_returns = [r for r in daily_returns if r < Decimal("0")]
        if not negative_returns:
            # No negative returns — Sortino is effectively infinity, cap it
            return _CALMAR_RATIO_CAP

        squared_neg = [float(r) ** 2 for r in negative_returns]
        # Use count of ALL returns in denominator (semi-deviation convention)
        downside_variance = sum(squared_neg) / len(daily_returns)
        downside_dev = math.sqrt(downside_variance)

        if downside_dev == 0:
            return _CALMAR_RATIO_CAP

        daily_sortino = float(mean_return) / downside_dev
        annualized = daily_sortino * math.sqrt(_TRADING_DAYS_PER_YEAR)

        try:
            return Decimal(str(annualized)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, OverflowError):
            return Decimal("0")

    @staticmethod
    def _compute_annualized_return(daily_returns: list[Decimal]) -> Decimal:
        """
        Compute annualized return percentage from daily P&L.

        Uses the geometric mean of daily returns assuming equal-weight
        daily compounding over 252 trading days.

        For simplicity with P&L values (not percentage returns), this
        computes total return / (N / 252) as a linear annualization.

        Args:
            daily_returns: List of daily P&L values.

        Returns:
            Annualized return as a percentage.
        """
        if not daily_returns:
            return Decimal("0")

        total_return = sum(daily_returns)
        trading_days = len(daily_returns)

        if trading_days == 0:
            return Decimal("0")

        # Annualize: total_return × (252 / trading_days)
        annualized = float(total_return) * (_TRADING_DAYS_PER_YEAR / trading_days)

        try:
            return Decimal(str(annualized)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, OverflowError):
            return Decimal("0")

    @staticmethod
    def _compute_calmar_ratio(
        annualized_return: Decimal,
        max_drawdown_pct: Decimal,
    ) -> Decimal:
        """
        Compute Calmar ratio: annualized return / |max drawdown|.

        Caps at _CALMAR_RATIO_CAP when drawdown approaches zero.

        Args:
            annualized_return: Annualized return value.
            max_drawdown_pct: Maximum drawdown as percentage (negative).

        Returns:
            Calmar ratio as Decimal.
        """
        abs_drawdown = abs(max_drawdown_pct)
        if abs_drawdown == Decimal("0"):
            if annualized_return > Decimal("0"):
                return _CALMAR_RATIO_CAP
            return Decimal("0")

        ratio = annualized_return / abs_drawdown

        try:
            result = ratio.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, OverflowError):
            return Decimal("0")

        # Cap at the maximum
        if result > _CALMAR_RATIO_CAP:
            return _CALMAR_RATIO_CAP
        if result < -_CALMAR_RATIO_CAP:
            return -_CALMAR_RATIO_CAP

        return result

    @staticmethod
    def _compute_risk_adjusted_return(sharpe_ratio: Decimal) -> Decimal:
        """
        Compute risk-adjusted return: Sharpe × sqrt(252).

        Args:
            sharpe_ratio: Annualized Sharpe ratio.

        Returns:
            Risk-adjusted return as Decimal.
        """
        sqrt_252 = Decimal(str(math.sqrt(_TRADING_DAYS_PER_YEAR)))
        try:
            return (sharpe_ratio * sqrt_252).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, OverflowError):
            return Decimal("0")

    @staticmethod
    def _to_decimal(value: Any) -> Decimal:
        """
        Safely convert a value to Decimal.

        Args:
            value: Any numeric value (int, float, str, Decimal).

        Returns:
            Decimal representation, or Decimal("0") on failure.
        """
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError, TypeError):
            return Decimal("0")

    @staticmethod
    def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
        """
        Clamp a Decimal value to [low, high].

        Args:
            value: Value to clamp.
            low: Minimum.
            high: Maximum.

        Returns:
            Clamped value.
        """
        return max(low, min(high, value))
