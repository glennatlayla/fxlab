"""
Run results sub-resource response contracts (M2.C3).

Purpose:
    Define the wire-format Pydantic models returned by the
    ``GET /runs/{run_id}/results/{equity-curve,blotter,metrics}``
    endpoints introduced in M2.C3. Each model is frozen + extra='forbid'
    so any drift between the route layer and consumers surfaces as a
    contract failure rather than a silent shape change.

Responsibilities:
    - EquityCurvePoint / EquityCurveResponse: equity-curve sub-resource.
    - TradeBlotterEntry / TradeBlotterPage: paginated blotter sub-resource.
    - RunMetrics: flattened summary metrics for the metrics sub-resource.

Does NOT:
    - Contain business logic, persistence, or HTTP concerns.
    - Mutate or compute results — pure DTOs only.
    - Re-export domain primitives from libs.contracts.backtest beyond the
      minimum needed for the wire shape (Decimal-as-string, etc.).

Dependencies:
    - pydantic: BaseModel, ConfigDict, Field, field_validator.
    - Standard library: datetime, decimal.

Error conditions:
    - ValidationError: when constructed from data that violates the
      schema (Pydantic enforcement).

Example:
    response = EquityCurveResponse(
        run_id="01HRUN00000000000000000001",
        points=[EquityCurvePoint(timestamp=ts, equity=Decimal("105000"))],
    )
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Pagination bounds — kept module-level so tests and callers can import them
# without instantiating any model. Both values are part of the wire contract.
# ---------------------------------------------------------------------------

#: Default trades-per-page when ``page_size`` is omitted from the request.
DEFAULT_BLOTTER_PAGE_SIZE: int = 100

#: Hard ceiling on ``page_size``; requests above this return HTTP 422.
MAX_BLOTTER_PAGE_SIZE: int = 1000


# ---------------------------------------------------------------------------
# Equity curve
# ---------------------------------------------------------------------------


class EquityCurvePoint(BaseModel):
    """
    A single (timestamp, equity) sample on the run's equity curve.

    Attributes:
        timestamp: UTC timestamp of the sample.
        equity: Portfolio equity at this point, expressed as Decimal so
            currency precision is preserved across the wire.

    Example:
        point = EquityCurvePoint(
            timestamp=datetime(2025, 6, 15, 16, 0, tzinfo=timezone.utc),
            equity=Decimal("105000"),
        )
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: datetime
    equity: Decimal = Field(..., ge=0, description="Portfolio equity at this point.")


class EquityCurveResponse(BaseModel):
    """
    Response body for ``GET /runs/{run_id}/results/equity-curve``.

    Attributes:
        run_id: ULID of the run this curve belongs to.
        point_count: Number of samples in ``points`` (mirrors len() so
            consumers can size buffers without iterating the list).
        points: Ordered samples, ascending by timestamp.

    Example:
        body = EquityCurveResponse(
            run_id="01HRUN00000000000000000001",
            point_count=2,
            points=[...],
        )
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(..., min_length=1, description="Run ULID.")
    point_count: int = Field(..., ge=0, description="Number of samples in points.")
    points: list[EquityCurvePoint] = Field(
        default_factory=list,
        description="Equity curve samples ordered ascending by timestamp.",
    )


# ---------------------------------------------------------------------------
# Trade blotter
# ---------------------------------------------------------------------------


class TradeBlotterEntry(BaseModel):
    """
    A single executed trade row in the blotter sub-resource.

    Attributes:
        trade_id: Stable identifier for the trade. M2.C3 uses the trade's
            position in the underlying ``BacktestResult.trades`` list as
            ``trade-{index:06d}`` so pagination is deterministic across
            repeated queries.
        timestamp: UTC execution timestamp.
        symbol: Instrument symbol.
        side: 'buy' or 'sell'.
        quantity: Trade size as Decimal.
        price: Execution price as Decimal.
        commission: Commission paid (default 0).
        slippage: Estimated slippage cost (default 0).

    Example:
        entry = TradeBlotterEntry(
            trade_id="trade-000001",
            timestamp=ts,
            symbol="AAPL",
            side="buy",
            quantity=Decimal("100"),
            price=Decimal("151.50"),
        )
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    trade_id: str = Field(..., min_length=1, description="Stable trade identifier.")
    timestamp: datetime
    symbol: str = Field(..., min_length=1)
    side: str = Field(..., pattern=r"^(buy|sell)$")
    quantity: Decimal = Field(..., gt=0)
    price: Decimal = Field(..., gt=0)
    commission: Decimal = Field(default=Decimal("0"), ge=0)
    slippage: Decimal = Field(default=Decimal("0"), ge=0)


class TradeBlotterPage(BaseModel):
    """
    Response body for ``GET /runs/{run_id}/results/blotter``.

    Pagination contract:
        - ``page`` is 1-based.
        - ``page_size`` defaults to ``DEFAULT_BLOTTER_PAGE_SIZE`` (100)
          and is capped at ``MAX_BLOTTER_PAGE_SIZE`` (1000); above the
          cap the route returns HTTP 422.
        - Trades are sorted ascending by ``timestamp``, ``trade_id`` for
          tie-break, so identical queries return identical pages.
        - Pages beyond the last populated page return an empty
          ``trades`` list with ``total_count`` and ``total_pages``
          unchanged.

    Attributes:
        run_id: ULID of the run.
        page: 1-based page index requested.
        page_size: Maximum trades per page for this request.
        total_count: Total number of trades for the run.
        total_pages: Ceiling of total_count / page_size (0 if no trades).
        trades: The trades on this page (may be empty for out-of-range
            pages).

    Example:
        page = TradeBlotterPage(
            run_id="01HRUN00000000000000000001",
            page=1,
            page_size=100,
            total_count=1000,
            total_pages=10,
            trades=[...],
        )
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(..., min_length=1, description="Run ULID.")
    page: int = Field(..., ge=1, description="1-based page index.")
    page_size: int = Field(..., ge=1, le=MAX_BLOTTER_PAGE_SIZE)
    total_count: int = Field(..., ge=0, description="Total trades for this run.")
    total_pages: int = Field(..., ge=0, description="Total pages at this page_size.")
    trades: list[TradeBlotterEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class RunMetrics(BaseModel):
    """
    Response body for ``GET /runs/{run_id}/results/metrics``.

    Surfaces the headline performance metrics from the run's
    :class:`ResearchRunResult`. ``summary_metrics`` is passed through
    verbatim from the engine result to avoid losing engine-specific
    keys; the explicit fields below mirror the most common
    backtest-engine outputs so frontends can target them by name.

    Attributes:
        run_id: ULID of the run.
        completed_at: When the engine finished (None if not completed).
        total_return_pct: Total return percentage (None if not derived).
        annualized_return_pct: Annualized return percentage.
        max_drawdown_pct: Maximum drawdown percentage (negative or zero).
        sharpe_ratio: Annualized Sharpe ratio.
        total_trades: Number of trades executed.
        win_rate: Fraction of winning trades, 0.0-1.0.
        profit_factor: Gross profit divided by gross loss.
        final_equity: Ending portfolio equity.
        bars_processed: Number of bars evaluated by the engine.
        summary_metrics: Engine-specific flattened metrics map.

    Example:
        metrics = RunMetrics(
            run_id="01HRUN00000000000000000001",
            completed_at=ts,
            total_return_pct=Decimal("15.50"),
            sharpe_ratio=Decimal("1.45"),
            total_trades=42,
            summary_metrics={"custom": 1},
        )
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(..., min_length=1, description="Run ULID.")
    completed_at: datetime | None = None
    total_return_pct: Decimal | None = None
    annualized_return_pct: Decimal | None = None
    max_drawdown_pct: Decimal | None = None
    sharpe_ratio: Decimal | None = None
    total_trades: int = Field(default=0, ge=0)
    win_rate: Decimal | None = None
    profit_factor: Decimal | None = None
    final_equity: Decimal | None = None
    bars_processed: int = Field(default=0, ge=0)
    summary_metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="Engine-specific flattened metrics map.",
    )
