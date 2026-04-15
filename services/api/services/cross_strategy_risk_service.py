"""
Cross-strategy risk aggregation service (Phase 8 M14).

Responsibilities:
- Compute portfolio-level VaR from weighted strategy returns.
- Decompose VaR into per-strategy marginal contributions.
- Compute pairwise strategy return correlation matrix.
- Detect synchronized drawdown events across strategies.
- Suggest optimised capital allocations via mean-variance optimization.

Does NOT:
- Execute trades or rebalancing (orchestrator responsibility).
- Persist results (caller / repository responsibility).
- Manage execution loops.

Dependencies:
- numpy: Array operations for portfolio math.
- structlog: Structured logging.
- libs.contracts.cross_strategy_risk: result types.
- libs.contracts.portfolio: PortfolioConfig, StrategyPerformanceInput.
- libs.contracts.interfaces.cross_strategy_risk_service: interface.

Error conditions:
- ValueError: if no performance data or returns are empty.

Example:
    service = CrossStrategyRiskService()
    var = service.compute_portfolio_var(config, performances)
    corr = service.compute_correlation_matrix(config, performances)
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import structlog

from libs.contracts.cross_strategy_risk import (
    CorrelationMatrix,
    DrawdownSyncEvent,
    MarginalVaR,
    MarginalVaRResult,
    OptimizationSuggestion,
    PortfolioVaR,
    VaRMethod,
)
from libs.contracts.interfaces.cross_strategy_risk_service import (
    CrossStrategyRiskServiceInterface,
)
from libs.contracts.portfolio import PortfolioConfig, StrategyPerformanceInput

logger = structlog.get_logger(__name__)


class CrossStrategyRiskService(CrossStrategyRiskServiceInterface):
    """
    Cross-strategy risk aggregation and capital optimization service.

    Computes portfolio-level risk metrics by aggregating per-strategy
    returns with consideration for correlations and diversification.

    Responsibilities:
    - Historical VaR from weighted portfolio return distribution.
    - Marginal VaR via component VaR decomposition.
    - Correlation matrix from return series.
    - Drawdown synchronization from per-strategy drawdown data.
    - Mean-variance optimization for allocation suggestions.

    Does NOT:
    - Execute trades or rebalancing.
    - Persist results.

    Thread safety:
    - Thread-safe: all methods are stateless and use only local variables.

    Example:
        service = CrossStrategyRiskService()
        var = service.compute_portfolio_var(config, performances)
    """

    def compute_portfolio_var(
        self,
        config: PortfolioConfig,
        performances: list[StrategyPerformanceInput],
    ) -> PortfolioVaR:
        """
        Compute portfolio-level VaR using historical simulation.

        Weights strategy returns by their equity allocation, computes
        portfolio return series, then takes percentile-based VaR.

        Args:
            config: Portfolio configuration.
            performances: Per-strategy performance data with returns.

        Returns:
            PortfolioVaR with 95% and 99% VaR.

        Example:
            var = service.compute_portfolio_var(config, performances)
        """
        logger.info(
            "Computing portfolio VaR",
            portfolio_id=config.portfolio_id,
            num_strategies=len(performances),
        )

        total_equity = sum(float(p.current_equity) for p in performances)
        if total_equity <= 0:
            total_equity = 1.0

        # Build portfolio return series from weighted strategy returns
        portfolio_returns = self._compute_weighted_returns(performances, total_equity)

        if len(portfolio_returns) == 0:
            return PortfolioVaR(
                portfolio_id=config.portfolio_id,
                var_95=Decimal("0"),
                var_99=Decimal("0"),
                total_equity=Decimal(str(round(total_equity, 2))),
                lookback_days=0,
            )

        # Historical VaR: percentiles of loss distribution
        # VaR is positive, representing maximum expected loss
        var_95_pct = float(np.percentile(portfolio_returns, 5))
        var_99_pct = float(np.percentile(portfolio_returns, 1))

        # Convert to absolute loss amount (negative returns = losses)
        var_95 = abs(min(var_95_pct, 0.0)) * total_equity
        var_99 = abs(min(var_99_pct, 0.0)) * total_equity

        logger.info(
            "Portfolio VaR computed",
            portfolio_id=config.portfolio_id,
            var_95=round(var_95, 2),
            var_99=round(var_99, 2),
        )

        return PortfolioVaR(
            portfolio_id=config.portfolio_id,
            method=VaRMethod.HISTORICAL,
            var_95=Decimal(str(round(var_95, 2))),
            var_99=Decimal(str(round(var_99, 2))),
            total_equity=Decimal(str(round(total_equity, 2))),
            lookback_days=len(portfolio_returns),
        )

    def compute_marginal_var(
        self,
        config: PortfolioConfig,
        performances: list[StrategyPerformanceInput],
    ) -> MarginalVaRResult:
        """
        Compute per-strategy marginal VaR contribution.

        Uses component VaR: the strategy's weight × covariance contribution.

        Args:
            config: Portfolio configuration.
            performances: Per-strategy performance data with returns.

        Returns:
            MarginalVaRResult with per-strategy VaR decomposition.

        Example:
            mvar = service.compute_marginal_var(config, performances)
        """
        logger.info(
            "Computing marginal VaR",
            portfolio_id=config.portfolio_id,
        )

        portfolio_var = self.compute_portfolio_var(config, performances)
        total_equity = float(portfolio_var.total_equity)

        # Compute weights
        weights = []
        for p in performances:
            weights.append(float(p.current_equity) / total_equity if total_equity > 0 else 0.0)

        # Build return matrix
        min_len = self._min_return_length(performances)
        if min_len == 0 or len(performances) == 0:
            return MarginalVaRResult(
                portfolio_id=config.portfolio_id,
                portfolio_var=portfolio_var,
                marginal_vars=[],
            )

        return_matrix = np.array([p.returns[:min_len] for p in performances])

        # Covariance matrix
        cov_matrix = np.cov(return_matrix)
        if cov_matrix.ndim == 0:
            # Single strategy
            cov_matrix = np.array([[float(cov_matrix)]])

        weights_arr = np.array(weights)
        portfolio_vol = np.sqrt(weights_arr @ cov_matrix @ weights_arr)

        # Marginal VaR = weight_i * (Cov[i, :] @ weights) / portfolio_vol
        marginal_vars: list[MarginalVaR] = []
        for i, perf in enumerate(performances):
            if portfolio_vol > 0:
                component_var = weights_arr[i] * (cov_matrix[i] @ weights_arr) / portfolio_vol
                pct_contribution = component_var / portfolio_vol if portfolio_vol > 0 else 0.0
            else:
                component_var = 0.0
                pct_contribution = 1.0 / len(performances) if performances else 0.0

            # Scale to absolute VaR amounts
            mvar_95 = abs(pct_contribution) * float(portfolio_var.var_95)
            mvar_99 = abs(pct_contribution) * float(portfolio_var.var_99)

            marginal_vars.append(
                MarginalVaR(
                    strategy_id=perf.strategy_id,
                    marginal_var_95=Decimal(str(round(mvar_95, 2))),
                    marginal_var_99=Decimal(str(round(mvar_99, 2))),
                    pct_contribution=round(abs(pct_contribution), 6),
                )
            )

        return MarginalVaRResult(
            portfolio_id=config.portfolio_id,
            portfolio_var=portfolio_var,
            marginal_vars=marginal_vars,
        )

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
            CorrelationMatrix with pairwise correlations and alerts.

        Example:
            corr = service.compute_correlation_matrix(config, performances)
        """
        logger.info(
            "Computing correlation matrix",
            portfolio_id=config.portfolio_id,
        )

        strategy_ids = [p.strategy_id for p in performances]
        n = len(performances)
        min_len = self._min_return_length(performances)

        if min_len == 0 or n == 0:
            return CorrelationMatrix(
                portfolio_id=config.portfolio_id,
                strategy_ids=strategy_ids,
                matrix=[[1.0] * n for _ in range(n)],
                lookback_days=0,
            )

        # Build return matrix and compute correlation
        return_matrix = np.array([p.returns[:min_len] for p in performances])

        if n == 1:
            corr_matrix = [[1.0]]
        else:
            np_corr = np.corrcoef(return_matrix)
            corr_matrix = [[round(float(np_corr[i][j]), 10) for j in range(n)] for i in range(n)]

        # Detect high correlation pairs
        threshold = config.max_correlation_between_strategies
        high_pairs: list[tuple[str, str, float]] = []
        for i in range(n):
            for j in range(i + 1, n):
                corr_val = corr_matrix[i][j]
                if abs(corr_val) > threshold:
                    high_pairs.append((strategy_ids[i], strategy_ids[j], round(corr_val, 6)))

        return CorrelationMatrix(
            portfolio_id=config.portfolio_id,
            strategy_ids=strategy_ids,
            matrix=corr_matrix,
            lookback_days=min_len,
            high_correlation_pairs=high_pairs,
        )

    def detect_drawdown_sync(
        self,
        config: PortfolioConfig,
        performances: list[StrategyPerformanceInput],
        drawdown_threshold: float = 0.05,
    ) -> list[DrawdownSyncEvent]:
        """
        Detect synchronized drawdown events across strategies.

        A sync event is detected when 2+ strategies simultaneously
        exceed the drawdown threshold.

        Args:
            config: Portfolio configuration.
            performances: Per-strategy performance data.
            drawdown_threshold: Minimum drawdown to count as in-drawdown.

        Returns:
            List of DrawdownSyncEvent (0 or 1 element).

        Example:
            events = service.detect_drawdown_sync(config, perfs)
        """
        # Find strategies currently in drawdown
        in_drawdown = [p for p in performances if p.max_drawdown >= drawdown_threshold]

        # Need at least 2 strategies in drawdown for synchronization
        if len(in_drawdown) < 2:
            return []

        drawdowns = [p.max_drawdown for p in in_drawdown]
        avg_dd = sum(drawdowns) / len(drawdowns)
        max_dd = max(drawdowns)

        # Compute correlation during drawdown period (from available returns)
        correlation = 0.0
        if len(in_drawdown) >= 2:
            min_len = self._min_return_length(in_drawdown)
            if min_len > 1:
                return_matrix = np.array([p.returns[:min_len] for p in in_drawdown])
                np_corr = np.corrcoef(return_matrix)
                # Average off-diagonal correlation
                n = len(in_drawdown)
                off_diag = [float(np_corr[i][j]) for i in range(n) for j in range(i + 1, n)]
                correlation = sum(off_diag) / len(off_diag) if off_diag else 0.0

        event = DrawdownSyncEvent(
            portfolio_id=config.portfolio_id,
            strategy_ids=[p.strategy_id for p in in_drawdown],
            avg_drawdown=round(avg_dd, 10),
            max_drawdown=round(max_dd, 10),
            correlation_during_event=round(correlation, 6),
        )

        return [event]

    def suggest_optimization(
        self,
        config: PortfolioConfig,
        performances: list[StrategyPerformanceInput],
    ) -> OptimizationSuggestion:
        """
        Suggest optimised allocation weights using mean-variance optimization.

        Implements Markowitz mean-variance optimization to find the
        maximum Sharpe ratio portfolio on the efficient frontier.

        Args:
            config: Portfolio configuration.
            performances: Per-strategy performance data with returns.

        Returns:
            OptimizationSuggestion with suggested weights and metrics.

        Example:
            suggestion = service.suggest_optimization(config, performances)
        """
        logger.info(
            "Computing optimization suggestion",
            portfolio_id=config.portfolio_id,
        )

        n = len(performances)
        total_equity = sum(float(p.current_equity) for p in performances)
        current_weights = {
            p.strategy_id: float(p.current_equity) / total_equity if total_equity > 0 else 0.0
            for p in performances
        }

        min_len = self._min_return_length(performances)
        if min_len < 2 or n == 0:
            # Not enough data — return equal weights
            equal_w = 1.0 / n if n > 0 else 0.0
            return OptimizationSuggestion(
                portfolio_id=config.portfolio_id,
                suggested_weights={p.strategy_id: equal_w for p in performances},
                current_weights=current_weights,
            )

        # Mean returns and covariance
        return_matrix = np.array([p.returns[:min_len] for p in performances])
        mean_returns = np.mean(return_matrix, axis=1)
        cov_matrix = np.cov(return_matrix)
        if cov_matrix.ndim == 0:
            cov_matrix = np.array([[float(cov_matrix)]])

        # Annualise (assume daily returns)
        annual_mean = mean_returns * 252
        annual_cov = cov_matrix * 252

        # Find maximum Sharpe ratio portfolio via analytical solution
        # For the unconstrained case: w* ∝ Σ⁻¹ @ μ
        try:
            inv_cov = np.linalg.inv(annual_cov)
            raw_weights = inv_cov @ annual_mean

            # Ensure non-negative (long-only constraint)
            raw_weights = np.maximum(raw_weights, 0.0)

            # Normalise to sum to 1.0
            total_w = np.sum(raw_weights)
            opt_weights = raw_weights / total_w if total_w > 0 else np.ones(n) / n
        except np.linalg.LinAlgError:
            # Singular covariance — fall back to equal weight
            opt_weights = np.ones(n) / n

        # Compute expected metrics at optimal weights
        exp_return = float(opt_weights @ annual_mean)
        exp_vol = float(np.sqrt(opt_weights @ annual_cov @ opt_weights))
        sharpe = exp_return / exp_vol if exp_vol > 0 else 0.0

        suggested = {performances[i].strategy_id: round(float(opt_weights[i]), 6) for i in range(n)}

        return OptimizationSuggestion(
            portfolio_id=config.portfolio_id,
            suggested_weights=suggested,
            expected_return=round(exp_return, 6),
            expected_volatility=round(exp_vol, 6),
            sharpe_ratio=round(sharpe, 6),
            current_weights=current_weights,
            method="mean_variance",
        )

    # ------------------------------------------------------------------
    # Internal: Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_weighted_returns(
        performances: list[StrategyPerformanceInput],
        total_equity: float,
    ) -> np.ndarray:
        """
        Compute portfolio return series from equity-weighted strategy returns.

        Args:
            performances: Per-strategy performance data.
            total_equity: Total portfolio equity.

        Returns:
            1D numpy array of portfolio returns.
        """
        if not performances:
            return np.array([])

        # Find minimum return series length
        min_len = min(len(p.returns) for p in performances) if performances else 0
        if min_len == 0:
            return np.array([])

        # Weight by equity fraction
        portfolio_returns = np.zeros(min_len)
        for p in performances:
            weight = float(p.current_equity) / total_equity if total_equity > 0 else 0.0
            portfolio_returns += weight * np.array(p.returns[:min_len])

        return portfolio_returns

    @staticmethod
    def _min_return_length(performances: list[StrategyPerformanceInput]) -> int:
        """
        Get minimum return series length across all strategies.

        Args:
            performances: Per-strategy performance data.

        Returns:
            Minimum number of return observations.
        """
        if not performances:
            return 0
        return min(len(p.returns) for p in performances)
