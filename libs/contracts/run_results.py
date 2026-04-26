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
# Trade-blotter CSV export row (round-trip / closed position view)
# ---------------------------------------------------------------------------

#: Streaming chunk size for the CSV blotter export. Picked at 1000 to keep
#: memory bounded for large blotters while still amortising per-yield Python
#: overhead. The route layer streams each chunk via ``StreamingResponse``.
RUN_BLOTTER_EXPORT_CHUNK_SIZE: int = 1000


#: Canonical CSV column order. The export route surfaces this as the first
#: yielded row (header) and consumers (operator spreadsheets) rely on the
#: order as much as the names. Keep in sync with :class:`TradeBlotterRow`.
RUN_BLOTTER_CSV_COLUMNS: tuple[str, ...] = (
    "trade_id",
    "symbol",
    "side",
    "entry_time",
    "exit_time",
    "units",
    "entry_price",
    "exit_price",
    "fees",
    "realized_pnl",
    "holding_period_seconds",
)


class TradeBlotterRow(BaseModel):
    """
    A single closed (round-trip) position row in the CSV export.

    Differs from :class:`TradeBlotterEntry` (single execution leg) by
    pairing an opening leg with its closing leg into one row that
    spreadsheet users can analyse directly. The row carries both
    timestamps, both prices, the aggregate fees (commission + slippage
    across both legs), and the realised PnL for the round-trip.

    Open positions at the end of the run (no matching closing leg)
    surface with ``exit_time``, ``exit_price``, ``realized_pnl``, and
    ``holding_period_seconds`` set to ``None`` so consumers can tell
    "still open" apart from "closed at zero PnL".

    Attributes:
        trade_id: Stable identifier for the round-trip
            (``trade-{open_index:06d}`` keyed off the opening leg).
        symbol: Instrument symbol (must match across both legs).
        side: Side of the OPENING leg ('buy' for long round-trip,
            'sell' for short round-trip).
        entry_time: UTC timestamp when the position was opened.
        exit_time: UTC timestamp when the position was closed; ``None``
            if the position was still open at run end.
        units: Position size as Decimal (matches the opening leg's
            quantity).
        entry_price: Execution price of the opening leg.
        exit_price: Execution price of the closing leg; ``None`` for
            still-open positions.
        fees: Sum of commission + slippage across both legs (or just
            the opening leg for still-open positions).
        realized_pnl: Realised P&L of the round-trip; ``None`` for
            still-open positions. For 'buy' opens:
            ``(exit_price - entry_price) * units - fees``. For 'sell'
            opens: ``(entry_price - exit_price) * units - fees``.
        holding_period_seconds: ``(exit_time - entry_time).total_seconds()``
            for closed round-trips; ``None`` for still-open positions.

    Example:
        row = TradeBlotterRow(
            trade_id="trade-000000",
            symbol="EURUSD",
            side="buy",
            entry_time=datetime(2025, 1, 1, 9, 30, tzinfo=timezone.utc),
            exit_time=datetime(2025, 1, 1, 10, 30, tzinfo=timezone.utc),
            units=Decimal("100"),
            entry_price=Decimal("1.1000"),
            exit_price=Decimal("1.1050"),
            fees=Decimal("1.20"),
            realized_pnl=Decimal("0.30"),
            holding_period_seconds=3600,
        )
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    trade_id: str = Field(..., min_length=1, description="Round-trip identifier.")
    symbol: str = Field(..., min_length=1)
    side: str = Field(..., pattern=r"^(buy|sell)$")
    entry_time: datetime
    exit_time: datetime | None = None
    units: Decimal = Field(..., gt=0)
    entry_price: Decimal = Field(..., gt=0)
    exit_price: Decimal | None = None
    fees: Decimal = Field(default=Decimal("0"), ge=0)
    realized_pnl: Decimal | None = None
    holding_period_seconds: int | None = Field(default=None, ge=0)


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


# ---------------------------------------------------------------------------
# Strategy run history (recent-runs section on the StrategyDetail page)
# ---------------------------------------------------------------------------

#: Default page size when ``page_size`` is omitted from the
#: ``GET /strategies/{strategy_id}/runs`` request. Mirrors the M2.D5 strategy
#: list endpoint default — 20 rows is the largest page the recent-runs
#: section ever needs in the UI grid.
DEFAULT_STRATEGY_RUNS_PAGE_SIZE: int = 20

#: Hard ceiling on ``page_size`` for the recent-runs endpoint. Above this the
#: route returns HTTP 422 (FastAPI's ``le`` validator). 200 matches the cap
#: used by the strategy list endpoint, keeping the wire-contract envelope
#: consistent across the strategies router.
MAX_STRATEGY_RUNS_PAGE_SIZE: int = 200


class RunSummaryMetrics(BaseModel):
    """
    Compact summary metrics surfaced on the recent-runs row.

    Attributes:
        total_return_pct: Total return percentage from the run's headline
            metrics. ``None`` when the run did not produce a backtest
            result (e.g. a FAILED run with no result body, or a walk-
            forward run that has not surfaced this field).
        sharpe_ratio: Annualised Sharpe ratio, when available.
        win_rate: Fraction of winning trades (0.0-1.0), when available.
        trade_count: Number of trades executed during the run; defaults
            to 0 when the run has no result body so the table can render
            a numeric cell rather than an empty placeholder.

    Example:
        metrics = RunSummaryMetrics(
            total_return_pct=Decimal("12.50"),
            sharpe_ratio=Decimal("1.45"),
            win_rate=Decimal("0.55"),
            trade_count=42,
        )
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_return_pct: Decimal | None = None
    sharpe_ratio: Decimal | None = None
    win_rate: Decimal | None = None
    trade_count: int = Field(default=0, ge=0)


class RunSummaryItem(BaseModel):
    """
    One row in the recent-runs section of the StrategyDetail page.

    Pinned to the columns the frontend table renders: status pill,
    timestamps, headline metrics, plus the run id used as the navigation
    target for the "View results" action button.

    Attributes:
        id: ULID of the run; used for the
            ``/runs/{id}/results`` navigation link.
        status: Current lifecycle status (``pending`` | ``queued`` |
            ``running`` | ``completed`` | ``failed`` | ``cancelled``).
            Drives the status-badge variant in the UI.
        started_at: UTC timestamp when execution began. ``None`` for
            runs that never left the QUEUED state.
        completed_at: UTC timestamp when execution finished (terminal
            status). ``None`` for non-terminal runs.
        summary_metrics: Compact summary surfaced inline on the row.

    Example:
        item = RunSummaryItem(
            id="01HRUN00000000000000000001",
            status="completed",
            started_at=ts0,
            completed_at=ts1,
            summary_metrics=RunSummaryMetrics(
                total_return_pct=Decimal("12.50"),
                sharpe_ratio=Decimal("1.45"),
                win_rate=Decimal("0.55"),
                trade_count=42,
            ),
        )
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., min_length=1, description="Run ULID.")
    status: str = Field(
        ...,
        pattern=r"^(pending|queued|running|completed|failed|cancelled)$",
        description="Current lifecycle status.",
    )
    started_at: datetime | None = None
    completed_at: datetime | None = None
    summary_metrics: RunSummaryMetrics = Field(
        default_factory=RunSummaryMetrics,
        description="Compact summary metrics for the recent-runs table.",
    )


class StrategyRunsPage(BaseModel):
    """
    Response body for ``GET /strategies/{strategy_id}/runs``.

    Pagination contract mirrors :class:`StrategyListPage` and the trade
    blotter:
        - ``page`` is 1-based.
        - ``page_size`` defaults to
          :data:`DEFAULT_STRATEGY_RUNS_PAGE_SIZE` (20) and is capped at
          :data:`MAX_STRATEGY_RUNS_PAGE_SIZE` (200); above the cap the
          route returns HTTP 422 (FastAPI's ``le`` validator).
        - Runs are ordered by ``created_at`` descending so the most
          recent submission appears first.
        - Pages beyond the last populated page return an empty ``runs``
          list with ``total_count`` and ``total_pages`` unchanged so the
          UI can disable the "Next" button without re-querying.

    Attributes:
        runs: The runs on this page (may be empty).
        page: 1-based page index requested.
        page_size: Maximum runs per page for this request.
        total_count: Total runs matching the strategy filter.
        total_pages: Ceiling of ``total_count / page_size`` (0 if no rows).

    Example:
        page = StrategyRunsPage(
            runs=[item],
            page=1,
            page_size=20,
            total_count=37,
            total_pages=2,
        )
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    runs: list[RunSummaryItem] = Field(default_factory=list)
    page: int = Field(..., ge=1, description="1-based page index.")
    page_size: int = Field(
        ...,
        ge=1,
        le=MAX_STRATEGY_RUNS_PAGE_SIZE,
        description="Runs per page.",
    )
    total_count: int = Field(..., ge=0, description="Total matching runs.")
    total_pages: int = Field(..., ge=0, description="Total pages at this page_size.")


# ---------------------------------------------------------------------------
# Cancel result (POST /runs/{run_id}/cancel)
# ---------------------------------------------------------------------------


class RunCancelResult(BaseModel):
    """
    Response body for ``POST /runs/{run_id}/cancel``.

    Communicates the outcome of an operator-driven cancellation request
    in a way the frontend toast / Recent-runs refresh can consume without
    re-reading the full :class:`ResearchRunRecord`. The shape is small on
    purpose: the route layer also re-issues the recent-runs query so the
    full record refresh is already covered.

    Attributes:
        run_id: ULID of the run the cancel was requested for.
        previous_status: Status the row carried just before the cancel
            attempt. ``"running"`` and ``"queued"``/``"pending"`` are
            actionable; the terminal statuses (``"completed"``,
            ``"failed"``, ``"cancelled"``) are reported with
            ``cancelled=False`` and an explanatory ``reason``.
        current_status: Status the row carries after the cancel attempt.
            For an actionable cancel this is always ``"cancelled"``; for
            a no-op (terminal state) this equals ``previous_status``.
        cancelled: ``True`` when the row was actually transitioned to
            CANCELLED. ``False`` when the run was already in a terminal
            state and the request was a no-op.
        reason: Free-form explanatory string. ``"user_requested"`` for
            actionable cancels; ``"terminal_state"`` for the no-op
            branch; ``"task_already_finished"`` when the executor pool
            reported no in-flight task because the worker finished
            between the lookup and the cancel.

    Example:
        result = RunCancelResult(
            run_id="01HRUN00000000000000000001",
            previous_status="running",
            current_status="cancelled",
            cancelled=True,
            reason="user_requested",
        )
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(..., min_length=1, description="Run ULID.")
    previous_status: str = Field(
        ...,
        pattern=r"^(pending|queued|running|completed|failed|cancelled)$",
        description="Status before the cancel attempt.",
    )
    current_status: str = Field(
        ...,
        pattern=r"^(pending|queued|running|completed|failed|cancelled)$",
        description="Status after the cancel attempt.",
    )
    cancelled: bool = Field(
        ...,
        description="True when the row was actually transitioned to CANCELLED.",
    )
    reason: str = Field(
        ...,
        min_length=1,
        description="Explanatory string for the outcome.",
    )
