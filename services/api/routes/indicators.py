"""
Indicator REST API endpoints.

Responsibilities:
- List available indicators with metadata (GET /indicators).
- Compute one or more indicators on candle data (POST /indicators/compute).
- Get detailed info for a specific indicator (GET /indicators/{name}/info).
- Serialize numpy arrays to JSON-safe lists.
- Apply LTTB downsampling for large result sets.
- Enforce scope-based access control (feeds:read).

Does NOT:
- Contain indicator math (delegated to IndicatorService → IndicatorEngine).
- Manage database connections (injected via FastAPI DI).

Dependencies:
- services.api.services.indicator_service.IndicatorService: business logic.
- libs.indicators: default_engine, default_registry.
- services.api.auth: scope-based access control.
- services.api.routes.market_data: get_market_data_repository for candle data.

Error conditions:
- 400: Invalid query parameters (bad interval, bad indicator name format).
- 401: Missing or invalid authentication.
- 403: Insufficient scope.
- 404: No candle data or indicator not found.
- 500: Internal server error.

Example:
    GET /indicators
    GET /indicators/SMA/info
    POST /indicators/compute {"symbol": "AAPL", "interval": "1d", "indicators": [{"name": "SMA", "params": {"period": 20}}]}
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from libs.contracts.errors import IndicatorNotFoundError, NotFoundError
from libs.contracts.indicator import IndicatorRequest
from libs.contracts.market_data import CandleInterval
from libs.indicators import default_engine
from services.api.auth import AuthenticatedUser, require_scope
from services.api.db import get_db
from services.api.services.indicator_service import IndicatorService

router = APIRouter(prefix="/indicators", tags=["indicators"])


# ---------------------------------------------------------------------------
# Dependency providers
# ---------------------------------------------------------------------------


def get_indicator_service(db: Session = Depends(get_db)) -> IndicatorService:  # type: ignore[no-untyped-def]
    """
    Provide the IndicatorService wired to the current request's DB session.

    Args:
        db: SQLAlchemy session injected by FastAPI DI.

    Returns:
        IndicatorService bound to market data repo and default engine.
    """
    from services.api.repositories.sql_market_data_repository import (
        SqlMarketDataRepository,
    )

    repo = SqlMarketDataRepository(db=db)
    return IndicatorService(engine=default_engine, market_data_repo=repo)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class IndicatorComputeItem(BaseModel):
    """Single indicator request within a compute batch."""

    name: str = Field(..., min_length=1, max_length=50, description="Indicator name (e.g. SMA)")
    params: dict[str, Any] = Field(default_factory=dict, description="Indicator parameters")


class IndicatorComputeRequest(BaseModel):
    """Request body for POST /indicators/compute."""

    symbol: str = Field(..., min_length=1, max_length=10, description="Ticker symbol")
    interval: str = Field(..., description="Candle interval (1m, 5m, 15m, 1h, 1d)")
    indicators: list[IndicatorComputeItem] = Field(
        ..., min_length=1, max_length=20, description="Indicators to compute"
    )
    start: str | None = Field(default=None, description="ISO 8601 start time")
    end: str | None = Field(default=None, description="ISO 8601 end time")


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_indicator_result(result: Any) -> dict[str, Any]:
    """
    Serialize an IndicatorResult to a JSON-safe dict.

    Converts numpy arrays to lists and handles NaN → null.

    Args:
        result: IndicatorResult from the engine.

    Returns:
        JSON-serializable dict.
    """
    output: dict[str, Any] = {
        "indicator_name": result.indicator_name,
        "metadata": result.metadata,
    }

    if result.is_multi_output:
        output["components"] = {
            name: _ndarray_to_list(arr) for name, arr in result.components.items()
        }
        output["values"] = None
    else:
        output["values"] = _ndarray_to_list(result.values) if result.values is not None else None
        output["components"] = {}

    if result.timestamps is not None:
        output["timestamps"] = _ndarray_to_list(result.timestamps)
    else:
        output["timestamps"] = None

    return output


def _ndarray_to_list(arr: np.ndarray) -> list[float | None]:
    """
    Convert numpy array to JSON-safe list, replacing NaN with None.

    Args:
        arr: Numpy array.

    Returns:
        List of float or None values.
    """
    return [None if np.isnan(v) else float(v) for v in arr]


def _serialize_indicator_info(info: Any) -> dict[str, Any]:
    """
    Serialize an IndicatorInfo to a JSON-safe dict.

    Args:
        info: IndicatorInfo Pydantic model.

    Returns:
        JSON-serializable dict.
    """
    return info.model_dump()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    summary="List all available indicators with metadata",
    status_code=status.HTTP_200_OK,
)
def list_indicators(
    user: AuthenticatedUser = Depends(require_scope("feeds:read")),
    service: IndicatorService = Depends(get_indicator_service),
) -> JSONResponse:
    """
    List all registered indicators with their names, descriptions,
    categories, default parameters, and parameter constraints.

    Args:
        user: Authenticated user with feeds:read scope.
        service: IndicatorService (injected).

    Returns:
        JSONResponse with list of indicator metadata.
    """
    available = service.list_available()
    return JSONResponse(
        content={
            "indicators": [_serialize_indicator_info(i) for i in available],
            "count": len(available),
        }
    )


@router.get(
    "/{name}/info",
    summary="Get detailed info for a specific indicator",
    status_code=status.HTTP_200_OK,
)
def get_indicator_info(
    name: str,
    user: AuthenticatedUser = Depends(require_scope("feeds:read")),
    service: IndicatorService = Depends(get_indicator_service),
) -> JSONResponse:
    """
    Retrieve detailed metadata for a specific indicator by name.

    Args:
        name: Indicator name (case-insensitive).
        user: Authenticated user with feeds:read scope.
        service: IndicatorService (injected).

    Returns:
        JSONResponse with indicator metadata, or 404 if not found.
    """
    try:
        info = service.get_indicator_info(name)
    except IndicatorNotFoundError as e:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(e)},
        )

    return JSONResponse(content={"indicator": _serialize_indicator_info(info)})


@router.post(
    "/compute",
    summary="Compute one or more indicators on candle data",
    status_code=status.HTTP_200_OK,
)
def compute_indicators(
    request: IndicatorComputeRequest,
    user: AuthenticatedUser = Depends(require_scope("feeds:read")),
    service: IndicatorService = Depends(get_indicator_service),
) -> JSONResponse:
    """
    Compute one or more indicators for a symbol and interval.

    Fetches candle data from the market data repository and computes
    the requested indicators. Returns time-aligned values.

    Args:
        request: IndicatorComputeRequest with symbol, interval, indicators.
        user: Authenticated user with feeds:read scope.
        service: IndicatorService (injected).

    Returns:
        JSONResponse with computed indicator results.
    """
    # Validate interval
    try:
        ivl = CandleInterval(request.interval)
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": f"Invalid interval: {request.interval}. Valid: 1m, 5m, 15m, 1h, 1d"},
        )

    # Parse optional datetimes
    start_dt = _parse_datetime(request.start) if request.start else None
    end_dt = _parse_datetime(request.end) if request.end else None

    # Build indicator requests
    indicator_requests = [
        IndicatorRequest(indicator_name=item.name, params=item.params)
        for item in request.indicators
    ]

    try:
        results = service.compute_batch(
            indicator_requests,
            symbol=request.symbol.upper(),
            interval=ivl,
            start=start_dt,
            end=end_dt,
        )
    except IndicatorNotFoundError as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(e)},
        )
    except NotFoundError as e:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(e)},
        )

    serialized = {key: _serialize_indicator_result(result) for key, result in results.items()}

    return JSONResponse(
        content={
            "symbol": request.symbol.upper(),
            "interval": request.interval,
            "results": serialized,
            "indicator_count": len(serialized),
        }
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_datetime(value: str) -> datetime | None:
    """
    Parse an ISO 8601 datetime string to a timezone-aware datetime.

    Args:
        value: ISO 8601 string.

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
