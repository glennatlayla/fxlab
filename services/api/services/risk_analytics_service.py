"""
Portfolio risk analytics service implementation.

Responsibilities:
- Compute Historical VaR and CVaR (Expected Shortfall) at 95%/99%.
- Compute Pearson correlation matrices from daily returns.
- Compute portfolio concentration (HHI, per-symbol weights).
- Assemble full portfolio risk summary with exposure breakdown.
- All numerical computation uses numpy for vectorized performance.

Does NOT:
- Persist results (caller or cache layer responsibility).
- Make trading decisions based on risk metrics.
- Fetch data directly from databases (injected via repository interfaces).

Dependencies:
- PositionRepositoryInterface (injected): current position holdings.
- MarketDataRepositoryInterface (injected): historical OHLCV candles.
- numpy: vectorized numerical computation.

Error conditions:
- NotFoundError: deployment has no positions or insufficient market data.
- ValidationError: invalid parameters (e.g., lookback_days < 30 for VaR).

Example:
    service = RiskAnalyticsService(
        position_repo=position_repo,
        market_data_repo=market_data_repo,
    )
    var = service.compute_var(deployment_id="01HDEPLOY...", lookback_days=252)
    summary = service.get_portfolio_risk_summary(deployment_id="01HDEPLOY...")
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import numpy as np

from libs.contracts.errors import NotFoundError, ValidationError
from libs.contracts.interfaces.risk_analytics_service import (
    RiskAnalyticsServiceInterface,
)
from libs.contracts.market_data import CandleInterval, MarketDataQuery
from libs.contracts.risk_analytics import (
    ConcentrationReport,
    CorrelationEntry,
    CorrelationMatrix,
    PortfolioRiskSummary,
    SymbolConcentration,
    VaRMethod,
    VaRResult,
)

logger = logging.getLogger(__name__)

# Minimum lookback for statistical significance in VaR computation
_MIN_VAR_LOOKBACK = 30

# Maximum candles to fetch per symbol for risk analytics
_MAX_CANDLE_FETCH = 10_000


class RiskAnalyticsService(RiskAnalyticsServiceInterface):
    """
    Production implementation of portfolio risk analytics.

    Computes VaR, correlation matrices, concentration analysis, and
    portfolio risk summaries using real position and market data.

    Responsibilities:
    - Historical VaR: sort daily P&L returns, pick percentile.
    - CVaR (Expected Shortfall): mean of returns beyond VaR threshold.
    - Pearson correlation from daily close-to-close returns.
    - Herfindahl-Hirschman Index for concentration analysis.
    - Exposure breakdown: long, short, net, gross.

    Does NOT:
    - Cache results (caller responsibility).
    - Access databases directly (injected via interfaces).
    - Make trading decisions.

    Dependencies:
    - position_repo: PositionRepositoryInterface for current holdings.
    - market_data_repo: MarketDataRepositoryInterface for historical prices.

    Example:
        service = RiskAnalyticsService(
            position_repo=sql_position_repo,
            market_data_repo=sql_market_data_repo,
        )
        var = service.compute_var(deployment_id="01HDEPLOY...", lookback_days=252)
    """

    def __init__(
        self,
        position_repo: Any,
        market_data_repo: Any,
    ) -> None:
        """
        Initialize RiskAnalyticsService.

        Args:
            position_repo: Repository for position data (PositionRepositoryInterface).
            market_data_repo: Repository for market data (MarketDataRepositoryInterface).
        """
        self._position_repo = position_repo
        self._market_data_repo = market_data_repo

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_var(
        self,
        *,
        deployment_id: str,
        lookback_days: int = 252,
    ) -> VaRResult:
        """
        Compute Value-at-Risk and CVaR for a deployment's portfolio.

        Historical VaR: sorts daily portfolio P&L, picks the 5th and 1st
        percentile. CVaR: mean of returns beyond VaR threshold.

        For multi-asset portfolios, daily portfolio return is the
        value-weighted sum of individual asset returns.

        Args:
            deployment_id: ULID of the deployment.
            lookback_days: Number of trading days (must be >= 30).

        Returns:
            VaRResult with 95% and 99% VaR and CVaR.

        Raises:
            ValidationError: If lookback_days < 30.
            NotFoundError: If no positions or insufficient market data.
        """
        if lookback_days < _MIN_VAR_LOOKBACK:
            raise ValidationError(
                f"lookback_days must be >= {_MIN_VAR_LOOKBACK}, got {lookback_days}"
            )

        positions = self._get_positions(deployment_id)
        portfolio_returns = self._compute_portfolio_returns(positions, lookback_days)

        logger.info(
            "Computing VaR",
            extra={
                "operation": "compute_var",
                "component": "RiskAnalyticsService",
                "deployment_id": deployment_id,
                "lookback_days": lookback_days,
                "n_positions": len(positions),
                "n_returns": len(portfolio_returns),
            },
        )

        # Historical VaR at 95% and 99%
        var_95 = float(np.percentile(portfolio_returns, 5))
        var_99 = float(np.percentile(portfolio_returns, 1))

        # CVaR (Expected Shortfall): mean of returns beyond VaR
        cvar_95 = float(np.mean(portfolio_returns[portfolio_returns <= var_95]))
        cvar_99 = float(np.mean(portfolio_returns[portfolio_returns <= var_99]))

        # Scale by total portfolio value for dollar-denominated VaR
        total_value = self._compute_total_abs_value(positions)

        return VaRResult(
            var_95=_to_decimal(var_95 * total_value),
            var_99=_to_decimal(var_99 * total_value),
            cvar_95=_to_decimal(cvar_95 * total_value),
            cvar_99=_to_decimal(cvar_99 * total_value),
            method=VaRMethod.HISTORICAL,
            lookback_days=lookback_days,
        )

    def compute_correlation_matrix(
        self,
        *,
        deployment_id: str,
        lookback_days: int = 252,
    ) -> CorrelationMatrix:
        """
        Compute Pearson correlation matrix from daily returns.

        Args:
            deployment_id: ULID of the deployment.
            lookback_days: Number of trading days for return history.

        Returns:
            CorrelationMatrix with entries, dense matrix, and metadata.

        Raises:
            NotFoundError: If no positions or insufficient market data.
        """
        positions = self._get_positions(deployment_id)
        symbols = sorted({p["symbol"] for p in positions})

        logger.info(
            "Computing correlation matrix",
            extra={
                "operation": "compute_correlation_matrix",
                "component": "RiskAnalyticsService",
                "deployment_id": deployment_id,
                "lookback_days": lookback_days,
                "n_symbols": len(symbols),
            },
        )

        # Fetch returns for each symbol
        returns_map: dict[str, np.ndarray] = {}
        for sym in symbols:
            returns_map[sym] = self._get_daily_returns(sym, lookback_days)

        # Align return series to minimum length
        min_len = min(len(r) for r in returns_map.values())
        aligned = {sym: r[-min_len:] for sym, r in returns_map.items()}

        n = len(symbols)
        # Build returns matrix: rows = symbols, columns = days
        returns_matrix = np.array([aligned[sym] for sym in symbols])

        # Compute correlation matrix (ternary avoided for readability with numpy)
        corr_matrix = np.array([[1.0]]) if n == 1 else np.corrcoef(returns_matrix)

        # Build entries and dense matrix representation
        entries: list[CorrelationEntry] = []
        matrix_strings: list[list[str]] = []

        for i in range(n):
            row: list[str] = []
            for j in range(n):
                corr_val = float(corr_matrix[i, j])
                # Clamp to [-1, 1] for numerical safety
                corr_val = max(-1.0, min(1.0, corr_val))
                corr_dec = _to_corr_decimal(corr_val)
                row.append(str(corr_dec))
                entries.append(
                    CorrelationEntry(
                        symbol_a=symbols[i],
                        symbol_b=symbols[j],
                        correlation=corr_dec,
                        lookback_days=lookback_days,
                    )
                )
            matrix_strings.append(row)

        return CorrelationMatrix(
            symbols=symbols,
            entries=entries,
            matrix=matrix_strings,
            lookback_days=lookback_days,
        )

    def compute_concentration(
        self,
        *,
        deployment_id: str,
    ) -> ConcentrationReport:
        """
        Compute portfolio concentration analysis with HHI.

        Uses absolute market values for concentration calculation,
        so short positions contribute their absolute value to the total.

        Args:
            deployment_id: ULID of the deployment.

        Returns:
            ConcentrationReport with per-symbol weights, HHI, and top-5 %.

        Raises:
            NotFoundError: If no positions.
        """
        positions = self._get_positions(deployment_id)

        logger.info(
            "Computing concentration",
            extra={
                "operation": "compute_concentration",
                "component": "RiskAnalyticsService",
                "deployment_id": deployment_id,
                "n_positions": len(positions),
            },
        )

        # Calculate absolute market value for each position
        symbol_values: list[tuple[str, Decimal]] = []
        for pos in positions:
            abs_value = abs(Decimal(str(pos["market_value"])))
            symbol_values.append((pos["symbol"], abs_value))

        total_value = sum(v for _, v in symbol_values)
        if total_value == 0:
            raise NotFoundError("Portfolio has zero total market value")

        # Calculate percentage weights
        per_symbol: list[SymbolConcentration] = []
        hhi_sum = Decimal("0")

        for sym, val in symbol_values:
            pct = (val / total_value * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            per_symbol.append(
                SymbolConcentration(
                    symbol=sym,
                    market_value=val,
                    pct_of_portfolio=pct,
                )
            )
            hhi_sum += pct * pct

        # Sort by weight descending
        per_symbol.sort(key=lambda sc: sc.pct_of_portfolio, reverse=True)

        # HHI rounded to integer
        hhi = hhi_sum.quantize(Decimal("1"), rounding=ROUND_HALF_UP)

        # Top 5 percentage
        top_5 = sum((sc.pct_of_portfolio for sc in per_symbol[:5]), Decimal("0")).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )

        return ConcentrationReport(
            per_symbol=per_symbol,
            herfindahl_index=hhi,
            top_5_pct=top_5,
        )

    def get_portfolio_risk_summary(
        self,
        *,
        deployment_id: str,
        lookback_days: int = 252,
    ) -> PortfolioRiskSummary:
        """
        Assemble full portfolio risk summary.

        Computes VaR, correlation, concentration, and exposure
        breakdown in a single call.

        Args:
            deployment_id: ULID of the deployment.
            lookback_days: Number of trading days for VaR and correlation.

        Returns:
            PortfolioRiskSummary with all risk dimensions.

        Raises:
            NotFoundError: If no positions or insufficient data.
        """
        positions = self._get_positions(deployment_id)

        logger.info(
            "Computing portfolio risk summary",
            extra={
                "operation": "get_portfolio_risk_summary",
                "component": "RiskAnalyticsService",
                "deployment_id": deployment_id,
                "lookback_days": lookback_days,
                "n_positions": len(positions),
            },
        )

        # Compute exposure breakdown
        long_exposure = Decimal("0")
        short_exposure = Decimal("0")

        for pos in positions:
            mv = Decimal(str(pos["market_value"]))
            if mv >= 0:
                long_exposure += mv
            else:
                short_exposure += abs(mv)

        gross_exposure = long_exposure + short_exposure
        net_exposure = long_exposure - short_exposure

        # Compute all risk dimensions
        var_result = self.compute_var(deployment_id=deployment_id, lookback_days=lookback_days)
        correlation = self.compute_correlation_matrix(
            deployment_id=deployment_id, lookback_days=lookback_days
        )
        concentration = self.compute_concentration(deployment_id=deployment_id)

        return PortfolioRiskSummary(
            var=var_result,
            correlation=correlation,
            concentration=concentration,
            total_exposure=gross_exposure,
            net_exposure=net_exposure,
            gross_exposure=gross_exposure,
            long_exposure=long_exposure,
            short_exposure=short_exposure,
        )

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

    def _get_daily_returns(
        self,
        symbol: str,
        lookback_days: int,
    ) -> np.ndarray:
        """
        Fetch daily close prices and compute log returns.

        Fetches lookback_days + 1 candles (need N+1 prices for N returns).

        Args:
            symbol: Ticker symbol.
            lookback_days: Number of returns needed.

        Returns:
            Numpy array of daily log returns.

        Raises:
            NotFoundError: If insufficient candle data.
        """
        query = MarketDataQuery(
            symbol=symbol,
            interval=CandleInterval.D1,
            limit=min(lookback_days + 10, _MAX_CANDLE_FETCH),
        )
        page = self._market_data_repo.query_candles(query)
        candles = page.candles

        if len(candles) < lookback_days + 1:
            raise NotFoundError(
                f"Insufficient market data for {symbol}: "
                f"need {lookback_days + 1} candles, got {len(candles)}"
            )

        # Extract close prices as float64
        closes = np.array([float(c.close) for c in candles], dtype=np.float64)

        # Use the most recent lookback_days+1 prices
        closes = closes[-(lookback_days + 1) :]

        # Compute log returns: ln(P_t / P_{t-1})
        returns = np.diff(np.log(closes))

        return returns

    def _compute_portfolio_returns(
        self,
        positions: list[dict[str, Any]],
        lookback_days: int,
    ) -> np.ndarray:
        """
        Compute value-weighted portfolio daily returns.

        Each asset's daily return is weighted by its share of total
        absolute portfolio value. The portfolio return on day t is the
        weighted sum of individual asset returns.

        Args:
            positions: Non-empty list of position dicts.
            lookback_days: Number of trading days.

        Returns:
            Numpy array of portfolio daily returns.

        Raises:
            NotFoundError: If insufficient market data for any symbol.
        """
        total_value = self._compute_total_abs_value(positions)
        if total_value == 0:
            raise NotFoundError("Portfolio has zero total market value")

        # Gather per-symbol returns and weights
        symbols_returns: list[tuple[float, np.ndarray]] = []

        for pos in positions:
            symbol = pos["symbol"]
            mv = float(Decimal(str(pos["market_value"])))
            weight = mv / total_value  # Can be negative for short positions

            returns = self._get_daily_returns(symbol, lookback_days)
            symbols_returns.append((weight, returns))

        # Align to minimum return length
        min_len = min(len(r) for _, r in symbols_returns)
        portfolio_returns = np.zeros(min_len, dtype=np.float64)

        for weight, returns in symbols_returns:
            portfolio_returns += weight * returns[-min_len:]

        return portfolio_returns

    @staticmethod
    def _compute_total_abs_value(positions: list[dict[str, Any]]) -> float:
        """
        Compute total absolute portfolio value.

        Args:
            positions: List of position dicts.

        Returns:
            Sum of absolute market values as float.
        """
        return sum(abs(float(Decimal(str(p["market_value"])))) for p in positions)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _to_decimal(value: float) -> Decimal:
    """
    Convert a float to a Decimal rounded to 2 decimal places.

    Args:
        value: Float value.

    Returns:
        Decimal rounded to 2 decimal places.
    """
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _to_corr_decimal(value: float) -> Decimal:
    """
    Convert a correlation float to a Decimal suitable for CorrelationEntry.

    Rounds to 6 decimal places for precision in correlation values.
    Special-cases exact 1.0 and -1.0 to avoid rounding artefacts.

    Args:
        value: Correlation coefficient as float.

    Returns:
        Decimal rounded appropriately.
    """
    if abs(value - 1.0) < 1e-10:
        return Decimal("1.0")
    if abs(value + 1.0) < 1e-10:
        return Decimal("-1.0")
    return Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
