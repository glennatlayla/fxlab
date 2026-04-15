"""
Market data REST API endpoints.

Responsibilities:
- Expose OHLCV candlestick data via paginated GET endpoints.
- Provide latest candle endpoint for live dashboard.
- List detected data gaps for operational monitoring.
- Trigger gap backfill tasks for operators.
- Apply LTTB downsampling when result sets exceed wire thresholds.
- Enforce scope-based access control (feeds:read, operator:write).

Does NOT:
- Contain business logic or indicator calculations.
- Manage database connections (injected via FastAPI DI).
- Compute indicators (that's the indicator engine's job).

Dependencies:
- SqlMarketDataRepository: Candle persistence and gap detection.
- libs.utils.lttb: LTTB downsampling for large result sets.
- services.api.auth: Scope-based access control.
- FastAPI: Route definitions and dependency injection.

Error conditions:
- 400: Invalid query parameters (bad interval, bad date format).
- 401: Missing or invalid authentication token.
- 403: Insufficient scope for the requested operation.
- 404: No data found for the given parameters.
- 500: Internal server error (database failure).

Example:
    GET /market-data/candles?symbol=AAPL&interval=1d&start=2025-01-01&limit=500
    GET /market-data/candles/latest?symbol=AAPL&interval=1d
    GET /market-data/gaps?symbol=AAPL&interval=1d
    POST /market-data/backfill {"symbol": "AAPL", "interval": "1d"}
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from libs.contracts.market_data import CandleInterval
from libs.utils.lttb import lttb_downsample
from services.api.auth import AuthenticatedUser, require_scope
from services.api.db import get_db

router = APIRouter(prefix="/market-data", tags=["market-data"])

#: Maximum number of candle points to return on the wire before LTTB
#: downsampling kicks in. Matches the chart rendering budget.
_LTTB_THRESHOLD = 2000


# ---------------------------------------------------------------------------
# Dependency providers
# ---------------------------------------------------------------------------


def get_market_data_repository(db: Session = Depends(get_db)):  # type: ignore[no-untyped-def]
    """
    Provide the active MarketDataRepositoryInterface implementation.

    Args:
        db: SQLAlchemy session injected by FastAPI DI.

    Returns:
        SqlMarketDataRepository bound to the current request's session.
    """
    from services.api.repositories.sql_market_data_repository import (
        SqlMarketDataRepository,
    )

    return SqlMarketDataRepository(db=db)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class BackfillRequest(BaseModel):
    """Request body for triggering a gap backfill task."""

    symbol: str = Field(..., min_length=1, max_length=10, description="Ticker symbol")
    interval: str = Field(default="1d", description="Candle interval (e.g. 1d, 1h, 5m)")
    start: str | None = Field(default=None, description="ISO 8601 start of scan range")
    end: str | None = Field(default=None, description="ISO 8601 end of scan range")


# ---------------------------------------------------------------------------
# Serialization helpers (LL-008: explicit model_dump + JSONResponse)
# ---------------------------------------------------------------------------


def _serialize_candle(candle: Any) -> dict[str, Any]:
    """
    Serialize a Candle Pydantic model to a JSON-safe dict.

    Converts Decimal prices to string and datetime to ISO format.

    Args:
        candle: Candle Pydantic model instance.

    Returns:
        JSON-serializable dict.
    """
    raw = candle.model_dump()
    # Convert Decimal fields to string for JSON
    for field in ("open", "high", "low", "close", "vwap"):
        if field in raw and raw[field] is not None:
            raw[field] = str(raw[field])
    # Convert datetime to ISO
    if "timestamp" in raw and hasattr(raw["timestamp"], "isoformat"):
        raw["timestamp"] = raw["timestamp"].isoformat()
    # Convert enum to value
    if "interval" in raw and hasattr(raw["interval"], "value"):
        raw["interval"] = raw["interval"].value
    return raw


def _serialize_gap(gap: Any) -> dict[str, Any]:
    """
    Serialize a DataGap Pydantic model to a JSON-safe dict.

    Args:
        gap: DataGap Pydantic model instance.

    Returns:
        JSON-serializable dict.
    """
    raw = gap.model_dump()
    for dt_field in ("gap_start", "gap_end", "detected_at"):
        if dt_field in raw and hasattr(raw[dt_field], "isoformat"):
            raw[dt_field] = raw[dt_field].isoformat()
    if "interval" in raw and hasattr(raw["interval"], "value"):
        raw["interval"] = raw["interval"].value
    return raw


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/candles",
    summary="Query OHLCV candles with pagination and LTTB downsampling",
    status_code=status.HTTP_200_OK,
)
def get_candles(
    symbol: str = Query(..., min_length=1, max_length=10, description="Ticker symbol"),
    interval: str = Query(..., description="Candle interval (1m, 5m, 15m, 1h, 1d)"),
    start: str | None = Query(default=None, description="ISO 8601 start of time range"),
    end: str | None = Query(default=None, description="ISO 8601 end of time range"),
    limit: int = Query(default=1000, ge=1, le=10000, description="Max candles per page"),
    cursor: str | None = Query(default=None, description="Pagination cursor from previous page"),
    downsample: bool = Query(default=True, description="Apply LTTB downsampling if over threshold"),
    user: AuthenticatedUser = Depends(require_scope("feeds:read")),
    repo=Depends(get_market_data_repository),  # type: ignore[assignment]
) -> JSONResponse:
    """
    Query OHLCV candle data with time range filtering and cursor pagination.

    Returns a paginated result set. When the total number of candles exceeds
    the LTTB threshold (2000 points), the close prices are downsampled to
    preserve visual fidelity while reducing payload size.

    Args:
        symbol: Ticker symbol (e.g. AAPL).
        interval: Candle interval string.
        start: Start of time range (inclusive).
        end: End of time range (inclusive).
        limit: Maximum candles per page.
        cursor: Opaque cursor from previous page.
        downsample: Whether to apply LTTB downsampling.
        user: Authenticated user with feeds:read scope.
        repo: MarketDataRepository (injected).

    Returns:
        JSONResponse with candles, total_count, has_more, next_cursor.
    """
    from libs.contracts.market_data import MarketDataQuery

    # Validate interval
    try:
        ivl = CandleInterval(interval)
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": f"Invalid interval: {interval}. Valid: 1m, 5m, 15m, 1h, 1d"},
        )

    # Parse optional datetimes
    start_dt = _parse_datetime(start) if start else None
    end_dt = _parse_datetime(end) if end else None

    if start_dt is None and end_dt is None and start is not None:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": f"Invalid start datetime: {start}"},
        )

    query = MarketDataQuery(
        symbol=symbol.upper(),
        interval=ivl,
        start=start_dt,
        end=end_dt,
        limit=limit,
        cursor=cursor,
    )

    page = repo.query_candles(query)

    candles_serialized = [_serialize_candle(c) for c in page.candles]

    # Apply LTTB downsampling if we have too many points and downsampling is enabled
    lttb_applied = False
    if downsample and len(candles_serialized) > _LTTB_THRESHOLD:
        candles_serialized = _apply_lttb(candles_serialized, _LTTB_THRESHOLD)
        lttb_applied = True

    return JSONResponse(
        content={
            "candles": candles_serialized,
            "total_count": page.total_count,
            "has_more": page.has_more,
            "next_cursor": page.next_cursor,
            "lttb_applied": lttb_applied,
        }
    )


@router.get(
    "/candles/latest",
    summary="Get the most recent candle for a symbol and interval",
    status_code=status.HTTP_200_OK,
)
def get_latest_candle(
    symbol: str = Query(..., min_length=1, max_length=10, description="Ticker symbol"),
    interval: str = Query(..., description="Candle interval"),
    user: AuthenticatedUser = Depends(require_scope("feeds:read")),
    repo=Depends(get_market_data_repository),  # type: ignore[assignment]
) -> JSONResponse:
    """
    Retrieve the most recent candle for a symbol and interval.

    Used by the live dashboard for current price display.

    Args:
        symbol: Ticker symbol.
        interval: Candle interval string.
        user: Authenticated user with feeds:read scope.
        repo: MarketDataRepository (injected).

    Returns:
        JSONResponse with the latest candle, or 404 if no data.
    """
    try:
        ivl = CandleInterval(interval)
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": f"Invalid interval: {interval}"},
        )

    candle = repo.get_latest_candle(symbol.upper(), ivl)
    if candle is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": f"No candle data for {symbol.upper()} at {interval}"},
        )

    return JSONResponse(content={"candle": _serialize_candle(candle)})


@router.get(
    "/gaps",
    summary="List detected data gaps for a symbol and interval",
    status_code=status.HTTP_200_OK,
)
def get_gaps(
    symbol: str = Query(..., min_length=1, max_length=10, description="Ticker symbol"),
    interval: str = Query(..., description="Candle interval"),
    start: str | None = Query(default=None, description="ISO 8601 start of scan range"),
    end: str | None = Query(default=None, description="ISO 8601 end of scan range"),
    user: AuthenticatedUser = Depends(require_scope("feeds:read")),
    repo=Depends(get_market_data_repository),  # type: ignore[assignment]
) -> JSONResponse:
    """
    List detected data gaps for a symbol and interval range.

    Used by operators to monitor data quality and identify missing
    candle data that may need backfill.

    Args:
        symbol: Ticker symbol.
        interval: Candle interval string.
        start: Start of scan range.
        end: End of scan range.
        user: Authenticated user with feeds:read scope.
        repo: MarketDataRepository (injected).

    Returns:
        JSONResponse with list of detected gaps.
    """
    try:
        ivl = CandleInterval(interval)
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": f"Invalid interval: {interval}"},
        )

    # Default to last 30 days if no range specified
    now = datetime.now(timezone.utc)
    start_dt = _parse_datetime(start) if start else now.replace(day=1)
    end_dt = _parse_datetime(end) if end else now

    gaps = repo.detect_gaps(symbol.upper(), ivl, start_dt, end_dt)

    return JSONResponse(
        content={
            "gaps": [_serialize_gap(g) for g in gaps],
            "count": len(gaps),
            "symbol": symbol.upper(),
            "interval": interval,
        }
    )


@router.post(
    "/backfill",
    summary="Trigger gap backfill task (operator scope required)",
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_backfill(
    request: BackfillRequest,
    user: AuthenticatedUser = Depends(require_scope("operator:write")),
) -> JSONResponse:
    """
    Trigger an asynchronous gap backfill task for a specific symbol.

    Dispatches the backfill task and returns immediately with a task
    reference. The actual backfill runs asynchronously.

    Args:
        request: BackfillRequest with symbol, interval, and optional range.
        user: Authenticated user with operator:write scope.

    Returns:
        JSONResponse with status and task reference (202 Accepted).
    """
    from services.worker.tasks.market_data_tasks import backfill_gaps

    # Validate interval
    try:
        CandleInterval(request.interval)
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": f"Invalid interval: {request.interval}"},
        )

    # Execute synchronously for now (Celery dispatch can be added later
    # when worker infrastructure is deployed). This keeps the endpoint
    # functional without requiring a Celery broker.
    result = backfill_gaps(
        symbol=request.symbol.upper(),
        interval=request.interval,
        start=request.start,
        end=request.end,
    )

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "status": "accepted",
            "message": f"Backfill task submitted for {request.symbol.upper()}",
            "result": result,
        },
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_datetime(value: str) -> datetime | None:
    """
    Parse an ISO 8601 datetime string to a timezone-aware datetime.

    Args:
        value: ISO 8601 string (e.g. "2025-01-01T00:00:00Z").

    Returns:
        Timezone-aware datetime, or None if parsing fails.
    """
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _apply_lttb(candles: list[dict[str, Any]], threshold: int) -> list[dict[str, Any]]:
    """
    Apply LTTB downsampling to serialized candle dicts.

    Converts timestamp + close price to (x, y) float pairs for LTTB,
    then filters the original candle list to keep only the selected points.

    Args:
        candles: List of serialized candle dicts with 'timestamp' and 'close'.
        threshold: Target number of points after downsampling.

    Returns:
        Downsampled list of candle dicts.
    """
    if len(candles) <= threshold:
        return candles

    # Build (x, y) points: x = timestamp epoch, y = close price
    points: list[tuple[float, float]] = []
    for c in candles:
        ts_str = c.get("timestamp", "")
        close_str = c.get("close", "0")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            x = ts.timestamp()
        except (ValueError, AttributeError):
            x = 0.0
        try:
            y = float(close_str)
        except (ValueError, TypeError):
            y = 0.0
        points.append((x, y))

    # Run LTTB
    reduced = lttb_downsample(points, threshold)

    # Build set of selected x values for O(n) filtering
    selected_x = {p[0] for p in reduced}

    # Filter original candles to keep selected points
    result = []
    for i, c in enumerate(candles):
        if points[i][0] in selected_x:
            result.append(c)

    return result
