"""
Chart API routes (Phase 3 — M7: Chart + LTTB + Queue Backend APIs).

Purpose:
    Expose server-side downsampled equity curve, drawdown, and composite chart
    payloads for the Results Explorer frontend (M27).

Responsibilities:
    - GET /runs/{run_id}/charts         → RunChartsPayload (composite)
    - GET /runs/{run_id}/charts/equity  → EquityChartResponse (LTTB applied)
    - GET /runs/{run_id}/charts/drawdown → DrawdownChartResponse
    - Apply LTTB when raw equity point count exceeds EQUITY_LTTB_THRESHOLD (2 000).
    - Set trades_truncated when trade count exceeds TRADES_TRUNCATE_THRESHOLD (5 000).
    - Translate NotFoundError from the repository to HTTP 404.

Does NOT:
    - Cache chart data (SQL cache wiring deferred — see ISS-016).
    - Perform backtesting, equity computation, or trade aggregation.
    - Apply business logic beyond LTTB thresholds.

Dependencies:
    - ChartRepositoryInterface (injected via Depends): provides raw data points.
    - libs.utils.lttb: lttb_downsample algorithm.
    - libs.contracts.chart: response schemas.
    - libs.contracts.errors: NotFoundError.

Error conditions:
    - NotFoundError from repository → HTTP 404 with detail message.

Example:
    GET /runs/01HQRUN.../charts/equity
    → {
        "run_id": "01HQRUN...",
        "points": [...],            # ≤ 2 000 points when sampling_applied
        "sampling_applied": true,
        "sampling_method": "lttb",
        "raw_equity_point_count": 50000,
        "trades_truncated": false,
        "total_trade_count": 230,
        "generated_at": "2026-03-27T..."
      }
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from libs.contracts.chart import (
    DrawdownChartResponse,
    DrawdownPoint,
    EquityChartResponse,
    EquityCurvePoint,
    RunChartsPayload,
    SamplingMethod,
)
from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.chart_repository import ChartRepositoryInterface
from libs.utils.lttb import lttb_downsample

logger = structlog.get_logger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Phase 3 M24 thresholds (Phase 3 Workplan Milestone 24 / spec §10 results)
# ---------------------------------------------------------------------------

EQUITY_LTTB_THRESHOLD: int = 2_000    # max wire points for equity curve
TRADES_TRUNCATE_THRESHOLD: int = 5_000  # max trades before truncation flag


# ---------------------------------------------------------------------------
# Dependency provider
# ---------------------------------------------------------------------------


def get_chart_repository() -> ChartRepositoryInterface:
    """
    Provide a ChartRepositoryInterface implementation.

    Returns:
        MockChartRepository bootstrap stub until SQL wiring is complete.

    Note:
        TODO: ISS-016 — Wire SqlChartRepository via lifespan DI container.
              This stub exists so startup does not fail before DI is wired.
    """
    from libs.contracts.mocks.mock_chart_repository import MockChartRepository  # pragma: no cover

    return MockChartRepository()  # pragma: no cover


# ---------------------------------------------------------------------------
# Serialization helpers (LL-008: explicit model_dump + JSONResponse)
# ---------------------------------------------------------------------------


def _serialize_equity_point(pt: EquityCurvePoint) -> dict[str, Any]:
    """
    Serialize one EquityCurvePoint to a JSON-safe dict.

    Args:
        pt: EquityCurvePoint with timestamp and equity fields.

    Returns:
        Dict with timestamp as ISO string and equity as float.

    Example:
        d = _serialize_equity_point(EquityCurvePoint(timestamp=dt, equity=10_000.0))
        assert isinstance(d["timestamp"], str)
    """
    return {
        "timestamp": (
            pt.timestamp.isoformat()
            if hasattr(pt.timestamp, "isoformat")
            else str(pt.timestamp)
        ),
        "equity": pt.equity,
    }


def _serialize_drawdown_point(pt: DrawdownPoint) -> dict[str, Any]:
    """
    Serialize one DrawdownPoint to a JSON-safe dict.

    Args:
        pt: DrawdownPoint with timestamp and drawdown fields.

    Returns:
        Dict with timestamp as ISO string and drawdown as float.

    Example:
        d = _serialize_drawdown_point(DrawdownPoint(timestamp=dt, drawdown=-0.1))
        assert d["drawdown"] == -0.1
    """
    return {
        "timestamp": (
            pt.timestamp.isoformat()
            if hasattr(pt.timestamp, "isoformat")
            else str(pt.timestamp)
        ),
        "drawdown": pt.drawdown,
    }


def _serialize_equity_response(resp: EquityChartResponse) -> dict[str, Any]:
    """
    Serialize EquityChartResponse to a JSON-safe dict.

    Handles nested EquityCurvePoint serialization and all datetime fields.

    Args:
        resp: EquityChartResponse instance.

    Returns:
        Dict with all fields serialized to JSON-safe types.

    Example:
        d = _serialize_equity_response(resp)
        assert isinstance(d["generated_at"], str)
    """
    raw = resp.model_dump()
    raw["points"] = [_serialize_equity_point(p) for p in resp.points]
    if hasattr(raw.get("generated_at"), "isoformat"):
        raw["generated_at"] = raw["generated_at"].isoformat()
    # sampling_method is a str-enum — already a string after model_dump()
    return raw


def _serialize_drawdown_response(resp: DrawdownChartResponse) -> dict[str, Any]:
    """
    Serialize DrawdownChartResponse to a JSON-safe dict.

    Args:
        resp: DrawdownChartResponse instance.

    Returns:
        Dict with all fields serialized to JSON-safe types.

    Example:
        d = _serialize_drawdown_response(resp)
        assert isinstance(d["generated_at"], str)
    """
    raw = resp.model_dump()
    raw["points"] = [_serialize_drawdown_point(p) for p in resp.points]
    if hasattr(raw.get("generated_at"), "isoformat"):
        raw["generated_at"] = raw["generated_at"].isoformat()
    return raw


def _serialize_charts_payload(payload: RunChartsPayload) -> dict[str, Any]:
    """
    Serialize RunChartsPayload (composite) to a JSON-safe dict.

    Args:
        payload: RunChartsPayload containing equity and drawdown sub-responses.

    Returns:
        Dict with all nested fields serialized.

    Example:
        d = _serialize_charts_payload(payload)
        assert "equity" in d and "drawdown" in d
    """
    return {
        "run_id": payload.run_id,
        "equity": _serialize_equity_response(payload.equity),
        "drawdown": _serialize_drawdown_response(payload.drawdown),
        "generated_at": (
            payload.generated_at.isoformat()
            if hasattr(payload.generated_at, "isoformat")
            else str(payload.generated_at)
        ),
    }


# ---------------------------------------------------------------------------
# Business logic helpers
# ---------------------------------------------------------------------------


def _build_equity_response(
    run_id: str,
    raw_equity: list[EquityCurvePoint],
    trade_count: int,
    correlation_id: str,
) -> EquityChartResponse:
    """
    Apply LTTB to raw equity points and build EquityChartResponse.

    LTTB fires when len(raw_equity) > EQUITY_LTTB_THRESHOLD.
    Trade truncation flag fires when trade_count > TRADES_TRUNCATE_THRESHOLD.

    Args:
        run_id:         Run ULID.
        raw_equity:     Full, un-downsampled equity curve from repository.
        trade_count:    Total trade count from repository.
        correlation_id: Tracing ID for structured logging.

    Returns:
        EquityChartResponse with sampling metadata populated.

    Example:
        resp = _build_equity_response("01HQRUN...", pts, 50, "c")
        assert not resp.sampling_applied  # 50 points < 2 000 threshold
    """
    raw_count = len(raw_equity)
    apply_lttb = raw_count > EQUITY_LTTB_THRESHOLD

    if apply_lttb:
        # Convert to numeric (x, y) pairs; LTTB operates on floats only.
        numeric_pts = [(pt.timestamp.timestamp(), pt.equity) for pt in raw_equity]
        downsampled = lttb_downsample(numeric_pts, threshold=EQUITY_LTTB_THRESHOLD)
        # Rebuild EquityCurvePoint objects by matching sampled x values back to
        # original objects (avoids floating-point datetime reconstruction).
        ts_map: dict[float, EquityCurvePoint] = {
            pt.timestamp.timestamp(): pt for pt in raw_equity
        }
        points: list[EquityCurvePoint] = []
        for x, y in downsampled:
            matched = ts_map.get(x)
            if matched is not None:
                points.append(matched)
            else:
                # Floating-point miss: reconstruct from sampled coordinates.
                # This is a defensive fallback; LTTB on a sorted series should
                # always return exact timestamps from the input.
                points.append(  # pragma: no cover
                    EquityCurvePoint(
                        timestamp=datetime.fromtimestamp(x, tz=timezone.utc),
                        equity=y,
                    )
                )
        sampling_method: SamplingMethod | None = SamplingMethod.LTTB
        logger.debug(
            "charts.equity.lttb_applied",
            run_id=run_id,
            raw_count=raw_count,
            sampled_count=len(points),
            correlation_id=correlation_id,
        )
    else:
        points = raw_equity
        sampling_method = None

    # LL-007: pydantic-core cross-arch stub fails on Optional[SamplingMethod]
    # validation when the field is non-None.  model_construct() bypasses
    # pydantic-core entirely so the route works in the cross-arch sandbox.
    return EquityChartResponse.model_construct(
        run_id=run_id,
        points=points,
        sampling_applied=apply_lttb,
        sampling_method=sampling_method,
        raw_equity_point_count=raw_count,
        trades_truncated=trade_count > TRADES_TRUNCATE_THRESHOLD,
        total_trade_count=trade_count,
        generated_at=datetime.now(timezone.utc),
    )


def _build_drawdown_response(
    run_id: str,
    raw_drawdown: list[DrawdownPoint],
) -> DrawdownChartResponse:
    """
    Apply LTTB to raw drawdown points and build DrawdownChartResponse.

    Args:
        run_id:       Run ULID.
        raw_drawdown: Full, un-downsampled drawdown series from repository.

    Returns:
        DrawdownChartResponse with sampling metadata populated.

    Example:
        resp = _build_drawdown_response("01HQRUN...", pts)
        assert resp.raw_point_count == len(pts)
    """
    raw_count = len(raw_drawdown)
    apply_lttb = raw_count > EQUITY_LTTB_THRESHOLD

    if apply_lttb:
        numeric_pts = [(pt.timestamp.timestamp(), pt.drawdown) for pt in raw_drawdown]
        downsampled = lttb_downsample(numeric_pts, threshold=EQUITY_LTTB_THRESHOLD)
        ts_map: dict[float, DrawdownPoint] = {
            pt.timestamp.timestamp(): pt for pt in raw_drawdown
        }
        points_dd: list[DrawdownPoint] = []
        for x, y in downsampled:
            matched = ts_map.get(x)
            if matched is not None:
                points_dd.append(matched)
            else:
                points_dd.append(  # pragma: no cover
                    DrawdownPoint(
                        timestamp=datetime.fromtimestamp(x, tz=timezone.utc),
                        drawdown=y,
                    )
                )
    else:
        points_dd = raw_drawdown

    return DrawdownChartResponse(
        run_id=run_id,
        points=points_dd,
        sampling_applied=apply_lttb,
        raw_point_count=raw_count,
        generated_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/charts")
def get_run_charts(
    run_id: str,
    x_correlation_id: str = "no-corr",
    repo: ChartRepositoryInterface = Depends(get_chart_repository),
) -> JSONResponse:
    """
    Return composite chart payload (equity + drawdown) for a run.

    Args:
        run_id:           Run ULID path parameter.
        x_correlation_id: Request correlation ID.
        repo:             Injected chart repository.

    Returns:
        JSONResponse containing RunChartsPayload with equity and drawdown sub-payloads.

    Raises:
        HTTPException(404): If no chart data exists for run_id.

    Example:
        GET /runs/01HQRUN.../charts
        → {"run_id": "...", "equity": {...}, "drawdown": {...}, "generated_at": "..."}
    """
    corr = x_correlation_id or "no-corr"
    logger.info("charts.composite.request", run_id=run_id, correlation_id=corr)
    try:
        raw_equity = repo.find_equity_by_run_id(run_id, corr)
        raw_drawdown = repo.find_drawdown_by_run_id(run_id, corr)
        trade_count = repo.find_trade_count_by_run_id(run_id, corr)
    except NotFoundError as exc:
        logger.warning(
            "charts.composite.not_found",
            run_id=run_id,
            detail=str(exc),
            correlation_id=corr,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    equity_resp = _build_equity_response(run_id, raw_equity, trade_count, corr)
    drawdown_resp = _build_drawdown_response(run_id, raw_drawdown)
    payload = RunChartsPayload(
        run_id=run_id,
        equity=equity_resp,
        drawdown=drawdown_resp,
        generated_at=datetime.now(timezone.utc),
    )
    logger.info(
        "charts.composite.response",
        run_id=run_id,
        equity_points=len(equity_resp.points),
        drawdown_points=len(drawdown_resp.points),
        correlation_id=corr,
    )
    return JSONResponse(content=_serialize_charts_payload(payload))


@router.get("/runs/{run_id}/charts/equity")
def get_run_equity_chart(
    run_id: str,
    x_correlation_id: str = "no-corr",
    repo: ChartRepositoryInterface = Depends(get_chart_repository),
) -> JSONResponse:
    """
    Return LTTB-downsampled equity curve for a run.

    LTTB fires when the raw equity series exceeds EQUITY_LTTB_THRESHOLD (2 000)
    points.  The trades_truncated flag is set when total_trade_count exceeds
    TRADES_TRUNCATE_THRESHOLD (5 000).

    Args:
        run_id:           Run ULID path parameter.
        x_correlation_id: Tracing correlation ID.
        repo:             Injected chart repository.

    Returns:
        JSONResponse containing EquityChartResponse.

    Raises:
        HTTPException(404): If no equity data exists for run_id.

    Example:
        GET /runs/01HQRUN.../charts/equity
        → {"run_id": "...", "points": [...], "sampling_applied": true, ...}
    """
    corr = x_correlation_id or "no-corr"
    logger.info("charts.equity.request", run_id=run_id, correlation_id=corr)
    try:
        raw_equity = repo.find_equity_by_run_id(run_id, corr)
        trade_count = repo.find_trade_count_by_run_id(run_id, corr)
    except NotFoundError as exc:
        logger.warning(
            "charts.equity.not_found",
            run_id=run_id,
            detail=str(exc),
            correlation_id=corr,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    resp = _build_equity_response(run_id, raw_equity, trade_count, corr)
    logger.info(
        "charts.equity.response",
        run_id=run_id,
        sampling_applied=resp.sampling_applied,
        points_served=len(resp.points),
        raw_count=resp.raw_equity_point_count,
        correlation_id=corr,
    )
    return JSONResponse(content=_serialize_equity_response(resp))


@router.get("/runs/{run_id}/charts/drawdown")
def get_run_drawdown_chart(
    run_id: str,
    x_correlation_id: str = "no-corr",
    repo: ChartRepositoryInterface = Depends(get_chart_repository),
) -> JSONResponse:
    """
    Return LTTB-downsampled drawdown series for a run.

    Args:
        run_id:           Run ULID path parameter.
        x_correlation_id: Tracing correlation ID.
        repo:             Injected chart repository.

    Returns:
        JSONResponse containing DrawdownChartResponse.

    Raises:
        HTTPException(404): If no drawdown data exists for run_id.

    Example:
        GET /runs/01HQRUN.../charts/drawdown
        → {"run_id": "...", "points": [...], "sampling_applied": false, ...}
    """
    corr = x_correlation_id or "no-corr"
    logger.info("charts.drawdown.request", run_id=run_id, correlation_id=corr)
    try:
        raw_drawdown = repo.find_drawdown_by_run_id(run_id, corr)
    except NotFoundError as exc:
        logger.warning(
            "charts.drawdown.not_found",
            run_id=run_id,
            detail=str(exc),
            correlation_id=corr,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    resp = _build_drawdown_response(run_id, raw_drawdown)
    logger.info(
        "charts.drawdown.response",
        run_id=run_id,
        points_served=len(resp.points),
        correlation_id=corr,
    )
    return JSONResponse(content=_serialize_drawdown_response(resp))
