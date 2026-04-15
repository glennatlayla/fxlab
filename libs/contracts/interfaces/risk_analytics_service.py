"""
Portfolio risk analytics service interface (port).

Responsibilities:
- Define the abstract contract for portfolio-level risk computations.
- Specify VaR, correlation, concentration, and summary operations.
- Serve as the dependency injection target for controllers and tests.

Does NOT:
- Implement any computation logic (service implementation responsibility).
- Fetch data (repository interfaces are injected into the implementation).
- Persist results (caller or cache layer responsibility).

Dependencies:
- None (pure interface).

Error conditions:
- NotFoundError: deployment has no positions or insufficient market data.
- ValidationError: invalid parameters (e.g., negative lookback_days).

Example:
    service: RiskAnalyticsServiceInterface = RiskAnalyticsService(
        position_repo=position_repo,
        market_data_repo=market_data_repo,
    )
    var = service.compute_var(deployment_id="01HDEPLOY...", lookback_days=252)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.risk_analytics import (
    ConcentrationReport,
    CorrelationMatrix,
    PortfolioRiskSummary,
    VaRResult,
)


class RiskAnalyticsServiceInterface(ABC):
    """
    Port interface for portfolio risk analytics computations.

    Responsibilities:
    - Compute Value-at-Risk (Historical and Parametric) with CVaR.
    - Compute Pearson correlation matrices across portfolio symbols.
    - Compute concentration analysis (HHI, per-symbol weights).
    - Assemble full portfolio risk summary.

    Does NOT:
    - Access databases directly (injected via repository interfaces).
    - Make trading decisions based on risk metrics.
    - Cache results (caller responsibility).

    All methods operate on a specific deployment_id, computing risk
    metrics for that deployment's current positions and historical
    market data.
    """

    @abstractmethod
    def compute_var(
        self,
        *,
        deployment_id: str,
        lookback_days: int = 252,
    ) -> VaRResult:
        """
        Compute Value-at-Risk and Conditional VaR for a deployment.

        Uses both Historical and Parametric methods. The returned result
        uses the Historical method by default (more robust for non-normal
        distributions typical in financial returns).

        Historical VaR: sort daily portfolio P&L returns, pick percentile.
        Parametric VaR: assume normal distribution, compute mean ± z × std.
        CVaR: mean of returns beyond the VaR threshold (Expected Shortfall).

        Args:
            deployment_id: ULID of the deployment to analyse.
            lookback_days: Number of trading days for return history.
                Must be >= 30 for statistical significance.

        Returns:
            VaRResult with 95% and 99% VaR and CVaR values.

        Raises:
            NotFoundError: If the deployment has no positions.
            NotFoundError: If insufficient market data for the lookback period.
            ValidationError: If lookback_days < 30.
        """
        ...

    @abstractmethod
    def compute_correlation_matrix(
        self,
        *,
        deployment_id: str,
        lookback_days: int = 252,
    ) -> CorrelationMatrix:
        """
        Compute Pearson correlation matrix for portfolio symbols.

        Computes pairwise correlations from daily returns over the
        lookback period. The resulting matrix is symmetric with 1.0
        on the diagonal and is guaranteed positive semi-definite.

        Args:
            deployment_id: ULID of the deployment to analyse.
            lookback_days: Number of trading days for return history.

        Returns:
            CorrelationMatrix with entries, dense matrix, and metadata.

        Raises:
            NotFoundError: If the deployment has no positions.
            NotFoundError: If insufficient market data for the lookback period.
        """
        ...

    @abstractmethod
    def compute_concentration(
        self,
        *,
        deployment_id: str,
    ) -> ConcentrationReport:
        """
        Compute portfolio concentration analysis.

        Calculates per-symbol weights and Herfindahl-Hirschman Index (HHI).
        HHI = sum of squared percentage weights. A single-stock portfolio
        has HHI = 10,000; a perfectly diversified N-stock equal-weight
        portfolio has HHI = 10,000/N.

        Args:
            deployment_id: ULID of the deployment to analyse.

        Returns:
            ConcentrationReport with per-symbol weights, HHI, and top-5 %.

        Raises:
            NotFoundError: If the deployment has no positions.
        """
        ...

    @abstractmethod
    def get_portfolio_risk_summary(
        self,
        *,
        deployment_id: str,
        lookback_days: int = 252,
    ) -> PortfolioRiskSummary:
        """
        Assemble a full portfolio risk summary.

        Computes VaR, correlation matrix, concentration, and exposure
        breakdown in a single call. This is the primary endpoint for
        dashboard rendering.

        Args:
            deployment_id: ULID of the deployment to analyse.
            lookback_days: Number of trading days for VaR and correlation.

        Returns:
            PortfolioRiskSummary with all risk dimensions.

        Raises:
            NotFoundError: If the deployment has no positions or data.
        """
        ...
