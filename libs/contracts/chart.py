"""
Chart data contracts (Phase 3 — M7 extension).

Purpose:
    Pydantic schemas for server-side chart data, LTTB metadata, and run chart
    payload envelopes consumed by the Results Explorer (M27) frontend.

Responsibilities:
    - Define wire-transfer shapes for equity, drawdown, and composite chart payloads.
    - Carry LTTB metadata so the UI can display a "data was downsampled" notice.
    - Carry trade truncation flags so the UI knows when the blotter is capped.

Does NOT:
    - Perform downsampling (that lives in libs/utils/lttb.py).
    - Access databases or file systems.
    - Contain business logic.

Dependencies:
    - pydantic.BaseModel / Field.
    - datetime (stdlib).

Error conditions:
    - None: these are pure data containers.

Example:
    resp = EquityChartResponse(
        run_id="01HQRUN...",
        points=[EquityCurvePoint(timestamp=dt, equity=10_000.0)],
        sampling_applied=False,
        raw_equity_point_count=1,
        trades_truncated=False,
        total_trade_count=50,
        generated_at=dt,
    )
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ChartType(str, Enum):
    """Chart type enumeration."""

    EQUITY_CURVE = "equity_curve"
    DRAWDOWN = "drawdown"
    RETURNS_DISTRIBUTION = "returns_distribution"
    ROLLING_SHARPE = "rolling_sharpe"


class SamplingMethod(str, Enum):
    """Data sampling method."""

    LTTB = "lttb"  # Largest Triangle Three Buckets
    UNIFORM = "uniform"
    NONE = "none"


class EquityCurvePoint(BaseModel):
    """
    Single point on an equity curve.

    Represents a timestamp and equity value pair.
    """

    timestamp: datetime = Field(..., description="Point timestamp")
    equity: float = Field(..., description="Equity value at this timestamp")


class ChartData(BaseModel):
    """
    Chart data response.

    Contains downsampled data points and metadata for frontend rendering.
    """

    chart_type: ChartType = Field(..., description="Chart type")
    subject_id: str = Field(..., description="Subject entity ULID (run_id, candidate_id, etc.)")
    points: list[EquityCurvePoint] = Field(
        ..., description="Chart data points (max 2000 for wire transfer)"
    )
    sampling_applied: bool = Field(..., description="Whether data was downsampled before serving")
    sampling_method: SamplingMethod | None = Field(
        default=None, description="Sampling method used (if sampling_applied=true)"
    )
    original_point_count: int = Field(
        ..., description="Original data point count before sampling", ge=0
    )
    generated_at: datetime = Field(..., description="Chart data generation timestamp")


class DrawdownPoint(BaseModel):
    """
    Single point on a drawdown curve.

    Drawdown is expressed as a fraction: 0.0 means no drawdown; -0.5 means
    a 50 % peak-to-trough decline.
    """

    timestamp: datetime = Field(..., description="Point timestamp")
    drawdown: float = Field(..., description="Drawdown fraction (0.0 to -1.0)")


class EquityChartResponse(BaseModel):
    """
    Equity curve chart response for a single run.

    Carries LTTB downsampling metadata so the frontend can display a
    "data was downsampled — showing N of M points" notice when applicable.

    Responsibilities:
    - Hold the (possibly LTTB-reduced) equity curve points.
    - Report whether downsampling was applied and the original point count.
    - Report whether trade data was truncated and the actual trade count.

    Does NOT:
    - Perform downsampling logic (handled by the route/service layer).

    Example:
        resp = EquityChartResponse(
            run_id="01HQRUN...",
            points=[EquityCurvePoint(timestamp=dt, equity=10_000.0)],
            sampling_applied=False,
            raw_equity_point_count=1,
            trades_truncated=False,
            total_trade_count=50,
            generated_at=dt,
        )
    """

    run_id: str = Field(..., description="Run ULID this chart belongs to")
    points: list[EquityCurvePoint] = Field(
        ..., description="Equity curve data points (LTTB-reduced if sampling_applied)"
    )
    sampling_applied: bool = Field(..., description="True when LTTB downsampling was applied")
    sampling_method: SamplingMethod | None = Field(
        default=None, description="Sampling algorithm used (populated when sampling_applied)"
    )
    raw_equity_point_count: int = Field(
        ..., description="Original point count before any downsampling", ge=0
    )
    trades_truncated: bool = Field(
        ..., description="True when trade blotter was capped at MAX_TRADES_WIRE limit"
    )
    total_trade_count: int = Field(
        ..., description="Total trade count in the run (may exceed served count)", ge=0
    )
    generated_at: datetime = Field(..., description="Timestamp when this payload was generated")


class DrawdownChartResponse(BaseModel):
    """
    Drawdown series chart response for a single run.

    Responsibilities:
    - Hold the (possibly LTTB-reduced) drawdown curve points.
    - Report sampling metadata consistent with EquityChartResponse.

    Does NOT:
    - Compute drawdown from equity values (handled upstream).

    Example:
        resp = DrawdownChartResponse(
            run_id="01HQRUN...",
            points=[DrawdownPoint(timestamp=dt, drawdown=0.0)],
            sampling_applied=False,
            raw_point_count=1,
            generated_at=dt,
        )
    """

    run_id: str = Field(..., description="Run ULID this chart belongs to")
    points: list[DrawdownPoint] = Field(..., description="Drawdown curve data points")
    sampling_applied: bool = Field(..., description="True when LTTB downsampling was applied")
    raw_point_count: int = Field(
        ..., description="Original point count before any downsampling", ge=0
    )
    generated_at: datetime = Field(..., description="Timestamp when this payload was generated")


class RunChartsPayload(BaseModel):
    """
    Composite chart payload for a completed run.

    Bundles all chart series for a run into a single response so the
    Results Explorer can make one request instead of several.

    Responsibilities:
    - Aggregate equity and drawdown chart responses for a run.
    - Provide a single generated_at timestamp for cache validation.

    Does NOT:
    - Contain raw trade data (trades are a separate concern).

    Example:
        payload = RunChartsPayload(
            run_id="01HQRUN...",
            equity=equity_resp,
            drawdown=drawdown_resp,
            generated_at=dt,
        )
    """

    run_id: str = Field(..., description="Run ULID")
    equity: EquityChartResponse = Field(..., description="Equity curve chart data")
    drawdown: DrawdownChartResponse = Field(..., description="Drawdown chart data")
    generated_at: datetime = Field(..., description="Payload generation timestamp")
