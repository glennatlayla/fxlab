"""
Portfolio risk analytics contracts and value objects.

Responsibilities:
- Define VaR (Value-at-Risk) and CVaR result contracts.
- Define correlation matrix and entry contracts.
- Define concentration report and Herfindahl-Hirschman Index contracts.
- Define portfolio risk summary aggregating all risk dimensions.
- Provide frozen Pydantic models for type safety and serialization.

Does NOT:
- Compute risk metrics (service responsibility).
- Persist results (repository/cache responsibility).
- Fetch market data or position data (injected via service dependencies).

Dependencies:
- pydantic: BaseModel, Field.
- Standard library: Decimal, datetime, enum.

Error conditions:
- ValidationError: invalid field values (Pydantic enforcement).

Example:
    var_result = VaRResult(
        var_95=Decimal("-2500.00"),
        var_99=Decimal("-4100.00"),
        cvar_95=Decimal("-3200.00"),
        cvar_99=Decimal("-5000.00"),
        method=VaRMethod.HISTORICAL,
        lookback_days=252,
    )
    summary = PortfolioRiskSummary(
        var=var_result,
        correlation=matrix,
        concentration=report,
        total_exposure=Decimal("100000.00"),
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class VaRMethod(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+; keeping str+Enum for 3.10 compat
    """
    Method used for Value-at-Risk computation.

    Values:
    - HISTORICAL: Non-parametric, based on actual return distribution.
    - PARAMETRIC: Assumes normal distribution, uses mean and std dev.
    """

    HISTORICAL = "historical"
    PARAMETRIC = "parametric"


class VaRResult(BaseModel):
    """
    Value-at-Risk and Conditional VaR computation result.

    VaR represents the maximum expected loss at a given confidence level
    over the lookback period. CVaR (Expected Shortfall) is the expected
    loss given that the loss exceeds VaR — a coherent risk measure that
    captures tail risk better than VaR alone.

    All values are expressed as portfolio dollar amounts (negative = loss).

    Responsibilities:
    - Carry VaR and CVaR at 95% and 99% confidence levels.
    - Record the computation method and parameters for auditability.

    Does NOT:
    - Compute VaR (service responsibility).

    Example:
        result = VaRResult(
            var_95=Decimal("-2500.00"),
            var_99=Decimal("-4100.00"),
            cvar_95=Decimal("-3200.00"),
            cvar_99=Decimal("-5000.00"),
            method=VaRMethod.HISTORICAL,
            lookback_days=252,
        )
    """

    model_config = {"frozen": True}

    var_95: Decimal = Field(
        ...,
        description="95% VaR as portfolio dollar amount (negative = loss).",
    )
    var_99: Decimal = Field(
        ...,
        description="99% VaR as portfolio dollar amount (negative = loss).",
    )
    cvar_95: Decimal = Field(
        ...,
        description="95% CVaR (Expected Shortfall) as portfolio dollar amount.",
    )
    cvar_99: Decimal = Field(
        ...,
        description="99% CVaR (Expected Shortfall) as portfolio dollar amount.",
    )
    method: VaRMethod = Field(
        ...,
        description="Computation method used.",
    )
    lookback_days: int = Field(
        ...,
        ge=1,
        description="Number of trading days used in the computation.",
    )
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the computation was performed.",
    )


class CorrelationEntry(BaseModel):
    """
    Pairwise correlation between two symbols.

    Responsibilities:
    - Store a single element of the correlation matrix.
    - Record the lookback period used in the computation.

    Does NOT:
    - Compute correlation (service responsibility).

    Example:
        entry = CorrelationEntry(
            symbol_a="AAPL",
            symbol_b="MSFT",
            correlation=Decimal("0.85"),
            lookback_days=252,
        )
    """

    model_config = {"frozen": True}

    symbol_a: str = Field(..., min_length=1, description="First symbol in the pair.")
    symbol_b: str = Field(..., min_length=1, description="Second symbol in the pair.")
    correlation: Decimal = Field(
        ...,
        ge=-1.0,
        le=1.0,
        description="Pearson correlation coefficient (-1 to 1).",
    )
    lookback_days: int = Field(
        ...,
        ge=1,
        description="Number of trading days used in the computation.",
    )


class CorrelationMatrix(BaseModel):
    """
    Full correlation matrix for a portfolio's symbols.

    The matrix is symmetric with 1.0 on the diagonal. The ``entries``
    list contains every pairwise correlation (including self-correlations
    for completeness). The ``matrix`` field provides the dense 2D
    representation as a list of rows for numerical consumers.

    Responsibilities:
    - Store the full pairwise correlation structure.
    - Provide both sparse (entries) and dense (matrix) representations.
    - Record computation timestamp for cache invalidation.

    Does NOT:
    - Validate positive semi-definiteness (service responsibility).

    Example:
        matrix = CorrelationMatrix(
            symbols=["AAPL", "MSFT"],
            entries=[
                CorrelationEntry(symbol_a="AAPL", symbol_b="AAPL", correlation=Decimal("1.0"), lookback_days=252),
                CorrelationEntry(symbol_a="AAPL", symbol_b="MSFT", correlation=Decimal("0.85"), lookback_days=252),
                CorrelationEntry(symbol_a="MSFT", symbol_b="AAPL", correlation=Decimal("0.85"), lookback_days=252),
                CorrelationEntry(symbol_a="MSFT", symbol_b="MSFT", correlation=Decimal("1.0"), lookback_days=252),
            ],
            matrix=[["1.0", "0.85"], ["0.85", "1.0"]],
        )
    """

    model_config = {"frozen": True}

    symbols: list[str] = Field(
        ...,
        min_length=1,
        description="Ordered list of symbols forming matrix axes.",
    )
    entries: list[CorrelationEntry] = Field(
        ...,
        description="All pairwise correlation entries.",
    )
    matrix: list[list[str]] = Field(
        ...,
        description="Dense 2D correlation matrix as decimal strings (row-major).",
    )
    lookback_days: int = Field(
        ...,
        ge=1,
        description="Number of trading days used across all pairs.",
    )
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the computation was performed.",
    )


class SymbolConcentration(BaseModel):
    """
    Concentration data for a single symbol in the portfolio.

    Responsibilities:
    - Record market value and percentage weight of one holding.

    Does NOT:
    - Compute concentration metrics (service responsibility).

    Example:
        sc = SymbolConcentration(
            symbol="AAPL",
            market_value=Decimal("25000.00"),
            pct_of_portfolio=Decimal("25.0"),
        )
    """

    model_config = {"frozen": True}

    symbol: str = Field(..., min_length=1, description="Instrument ticker.")
    market_value: Decimal = Field(
        ...,
        description="Absolute market value of the position.",
    )
    pct_of_portfolio: Decimal = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Percentage of total portfolio value (0-100).",
    )


class ConcentrationReport(BaseModel):
    """
    Portfolio concentration analysis result.

    The Herfindahl-Hirschman Index (HHI) measures portfolio concentration:
    - HHI = 10,000 for a single-stock portfolio (maximum concentration).
    - HHI approaches 0 for perfectly diversified equal-weight portfolios.
    - HHI = sum of squared percentage weights.

    Responsibilities:
    - Report per-symbol concentration and portfolio-level HHI.
    - Provide top-N concentration summary for quick assessment.

    Does NOT:
    - Recommend position adjustments (advisory/strategy responsibility).

    Example:
        report = ConcentrationReport(
            per_symbol=[
                SymbolConcentration(symbol="AAPL", market_value=Decimal("50000"), pct_of_portfolio=Decimal("50")),
                SymbolConcentration(symbol="MSFT", market_value=Decimal("50000"), pct_of_portfolio=Decimal("50")),
            ],
            herfindahl_index=Decimal("5000"),
            top_5_pct=Decimal("100.0"),
        )
    """

    model_config = {"frozen": True}

    per_symbol: list[SymbolConcentration] = Field(
        ...,
        description="Per-symbol concentration breakdown, sorted by weight descending.",
    )
    herfindahl_index: Decimal = Field(
        ...,
        ge=0.0,
        le=10000.0,
        description="Herfindahl-Hirschman Index (0-10000).",
    )
    top_5_pct: Decimal = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Sum of the top-5 position weights as percentage.",
    )
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the computation was performed.",
    )


class PortfolioRiskSummary(BaseModel):
    """
    Aggregated portfolio risk summary combining all risk dimensions.

    Provides a single-query snapshot of VaR, correlation structure,
    concentration analysis, and exposure breakdown for a deployment.

    Exposure definitions:
    - total_exposure: sum of absolute market values (long + short).
    - net_exposure: sum of signed market values (long - short).
    - gross_exposure: same as total_exposure (alias for clarity).
    - long_exposure: sum of positive market values.
    - short_exposure: sum of absolute negative market values.

    Responsibilities:
    - Aggregate all risk dimensions into a single response.
    - Provide exposure breakdown by direction.

    Does NOT:
    - Compute any metrics (delegates to sub-computations).

    Example:
        summary = PortfolioRiskSummary(
            var=var_result,
            correlation=matrix,
            concentration=concentration_report,
            total_exposure=Decimal("100000.00"),
            net_exposure=Decimal("80000.00"),
            gross_exposure=Decimal("100000.00"),
            long_exposure=Decimal("90000.00"),
            short_exposure=Decimal("10000.00"),
        )
    """

    model_config = {"frozen": True}

    var: VaRResult = Field(..., description="Value-at-Risk and CVaR results.")
    correlation: CorrelationMatrix = Field(..., description="Correlation matrix.")
    concentration: ConcentrationReport = Field(..., description="Concentration report.")
    total_exposure: Decimal = Field(
        ...,
        description="Sum of absolute market values across all positions.",
    )
    net_exposure: Decimal = Field(
        ...,
        description="Sum of signed market values (long - short).",
    )
    gross_exposure: Decimal = Field(
        ...,
        description="Same as total_exposure (alias for clarity).",
    )
    long_exposure: Decimal = Field(
        ...,
        ge=0.0,
        description="Sum of positive (long) market values.",
    )
    short_exposure: Decimal = Field(
        ...,
        ge=0.0,
        description="Sum of absolute negative (short) market values.",
    )
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the summary was assembled.",
    )
