"""
Data quality REST API endpoints (Phase 8 — M2).

Responsibilities:
- Expose data quality scores, anomalies, and trading readiness checks.
- Provide on-demand quality evaluation trigger.
- Provide multi-symbol quality dashboard summary.
- Delegate all business logic to DataQualityServiceInterface.

Does NOT:
- Detect anomalies or compute scores (service layer responsibility).
- Access the database directly (repository layer responsibility).
- Contain alerting logic (notification infrastructure responsibility).

Dependencies:
- DataQualityService (injected): quality scoring and anomaly detection.
- DataQualityRepositoryInterface (injected): data access.
- AuthenticatedUser + scope enforcement from auth module.

Error conditions:
- 404: No quality score found for the requested symbol.
- 422: Invalid request body (Pydantic validation).
- 401/403: Missing or insufficient authentication.

Example (curl):
    curl -H "Authorization: Bearer $TOKEN" \\
        http://localhost:8000/data-quality/score/AAPL
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from libs.contracts.data_quality import (
    AnomalySeverity,
    QualityScore,
)
from libs.contracts.execution import ExecutionMode
from libs.contracts.market_data import CandleInterval
from services.api.auth import AuthenticatedUser, get_current_user, require_scope
from services.api.db import get_db
from services.api.middleware.correlation import correlation_id_var
from services.api.services.data_quality_service import DataQualityService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/data-quality", tags=["data-quality"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class EvaluateRequest(BaseModel):
    """
    Request body for on-demand quality evaluation.

    Attributes:
        symbol: Ticker symbol to evaluate.
        interval: Candle interval (default "1m").
        window_minutes: Evaluation window in minutes (default 60).

    Example:
        {"symbol": "AAPL", "interval": "1m", "window_minutes": 60}
    """

    symbol: str = Field(..., min_length=1, max_length=20, description="Ticker symbol")
    interval: str = Field(default="1m", description="Candle interval")
    window_minutes: int = Field(default=60, gt=0, le=1440, description="Window in minutes")


# ---------------------------------------------------------------------------
# Dependency providers
# ---------------------------------------------------------------------------


def get_data_quality_service(
    db: Session = Depends(get_db),
) -> DataQualityService:
    """
    Provide the DataQualityService with all required repositories.

    Wires the SQL-backed data quality and market data repositories
    into the service for the current request's session scope.

    Args:
        db: SQLAlchemy session injected by FastAPI dependency injection.

    Returns:
        Fully-wired DataQualityService instance.
    """
    from services.api.repositories.sql_data_quality_repository import (
        SqlDataQualityRepository,
    )
    from services.api.repositories.sql_market_data_repository import (
        SqlMarketDataRepository,
    )

    dq_repo = SqlDataQualityRepository(db=db)
    md_repo = SqlMarketDataRepository(db=db)
    return DataQualityService(
        data_quality_repo=dq_repo,
        market_data_repo=md_repo,
    )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_score(score: QualityScore) -> dict[str, Any]:
    """
    Serialize a QualityScore to a JSON-safe dict.

    Converts enums to values and datetimes to ISO strings.

    Args:
        score: Domain QualityScore object.

    Returns:
        Plain dict ready for JSON response.
    """
    return {
        "symbol": score.symbol,
        "interval": score.interval.value,
        "window_start": score.window_start.isoformat(),
        "window_end": score.window_end.isoformat(),
        "completeness": score.completeness,
        "timeliness": score.timeliness,
        "consistency": score.consistency,
        "accuracy": score.accuracy,
        "composite_score": score.composite_score,
        "grade": score.grade.value,
        "anomaly_count": score.anomaly_count,
        "scored_at": score.scored_at.isoformat() if score.scored_at else None,
    }


def _serialize_anomaly(anomaly: Any) -> dict[str, Any]:
    """
    Serialize a DataAnomaly to a JSON-safe dict.

    Args:
        anomaly: Domain DataAnomaly object.

    Returns:
        Plain dict ready for JSON response.
    """
    return {
        "anomaly_id": anomaly.anomaly_id,
        "symbol": anomaly.symbol,
        "interval": anomaly.interval.value,
        "anomaly_type": anomaly.anomaly_type.value,
        "severity": anomaly.severity.value,
        "detected_at": anomaly.detected_at.isoformat(),
        "bar_timestamp": anomaly.bar_timestamp.isoformat() if anomaly.bar_timestamp else None,
        "details": anomaly.details,
        "resolved": anomaly.resolved,
        "resolved_at": anomaly.resolved_at.isoformat() if anomaly.resolved_at else None,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/score/{symbol}")
async def get_latest_score(
    symbol: str,
    user: AuthenticatedUser = Depends(get_current_user),
    service: DataQualityService = Depends(get_data_quality_service),
) -> JSONResponse:
    """
    Get the latest quality score for a symbol.

    Args:
        symbol: Ticker symbol to query.
        user: Authenticated user (injected).
        service: DataQualityService (injected).

    Returns:
        JSON with quality score details.

    Raises:
        HTTPException 404: If no score exists for the symbol.
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "data_quality.get_score",
        symbol=symbol.upper(),
        correlation_id=corr_id,
        component="data_quality_routes",
    )

    score = service.get_latest_score(symbol.upper(), CandleInterval.D1)
    if score is None:
        raise HTTPException(status_code=404, detail=f"No quality score for {symbol.upper()}")

    return JSONResponse(content=_serialize_score(score))


@router.get("/score/{symbol}/history")
async def get_score_history(
    symbol: str,
    hours: int = Query(default=24, gt=0, le=720, description="Lookback hours"),
    limit: int = Query(default=100, gt=0, le=1000, description="Max results"),
    user: AuthenticatedUser = Depends(get_current_user),
    service: DataQualityService = Depends(get_data_quality_service),
) -> JSONResponse:
    """
    Get historical quality scores for a symbol.

    Args:
        symbol: Ticker symbol to query.
        hours: How many hours to look back (default 24).
        limit: Maximum number of scores to return (default 100).
        user: Authenticated user (injected).
        service: DataQualityService (injected).

    Returns:
        JSON with list of historical scores.
    """
    corr_id = correlation_id_var.get("no-corr")
    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)

    scores = service.get_score_history(
        symbol.upper(),
        CandleInterval.D1,
        since=since,
        limit=limit,
    )

    logger.info(
        "data_quality.get_score_history",
        symbol=symbol.upper(),
        hours=hours,
        result_count=len(scores),
        correlation_id=corr_id,
        component="data_quality_routes",
    )

    return JSONResponse(
        content={
            "symbol": symbol.upper(),
            "scores": [_serialize_score(s) for s in scores],
        }
    )


@router.get("/anomalies/{symbol}")
async def get_anomalies(
    symbol: str,
    hours: int = Query(default=24, gt=0, le=720, description="Lookback hours"),
    severity: str | None = Query(default=None, description="Severity filter"),
    limit: int = Query(default=100, gt=0, le=1000, description="Max results"),
    user: AuthenticatedUser = Depends(get_current_user),
    service: DataQualityService = Depends(get_data_quality_service),
) -> JSONResponse:
    """
    Get anomalies for a symbol.

    Args:
        symbol: Ticker symbol to query.
        hours: How many hours to look back (default 24).
        severity: Optional severity filter ("info", "warning", "critical").
        limit: Maximum number of anomalies to return (default 100).
        user: Authenticated user (injected).
        service: DataQualityService (injected).

    Returns:
        JSON with list of anomalies.
    """
    corr_id = correlation_id_var.get("no-corr")
    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)

    severity_enum = None
    if severity is not None:
        try:
            severity_enum = AnomalySeverity(severity.lower())
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid severity: {severity}. Must be info, warning, or critical.",
            ) from None

    anomalies = service.find_anomalies(
        symbol.upper(),
        CandleInterval.M1,
        since=since,
        severity=severity_enum,
        limit=limit,
    )

    logger.info(
        "data_quality.get_anomalies",
        symbol=symbol.upper(),
        severity=severity,
        result_count=len(anomalies),
        correlation_id=corr_id,
        component="data_quality_routes",
    )

    return JSONResponse(
        content={
            "symbol": symbol.upper(),
            "anomalies": [_serialize_anomaly(a) for a in anomalies],
        }
    )


@router.post("/evaluate")
async def evaluate_quality(
    request: EvaluateRequest,
    user: AuthenticatedUser = Depends(require_scope("operator:write")),
    service: DataQualityService = Depends(get_data_quality_service),
) -> JSONResponse:
    """
    Trigger on-demand quality evaluation for a symbol.

    Requires operator:write scope.

    Args:
        request: Evaluation request with symbol, interval, window.
        user: Authenticated user with operator:write scope (injected).
        service: DataQualityService (injected).

    Returns:
        JSON with the computed quality score.
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "data_quality.evaluate_triggered",
        symbol=request.symbol.upper(),
        interval=request.interval,
        window_minutes=request.window_minutes,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="data_quality_routes",
    )

    try:
        interval = CandleInterval(request.interval)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid interval: {request.interval}",
        ) from None

    score = service.evaluate_quality(
        symbol=request.symbol.upper(),
        interval=interval,
        window_minutes=request.window_minutes,
    )

    logger.info(
        "data_quality.evaluate_complete",
        symbol=request.symbol.upper(),
        composite_score=score.composite_score,
        grade=score.grade.value,
        correlation_id=corr_id,
        component="data_quality_routes",
    )

    return JSONResponse(content=_serialize_score(score))


@router.get("/readiness")
async def check_readiness(
    symbols: str = Query(..., description="Comma-separated symbol list"),
    mode: str = Query(default="live", description="Execution mode"),
    user: AuthenticatedUser = Depends(get_current_user),
    service: DataQualityService = Depends(get_data_quality_service),
) -> JSONResponse:
    """
    Check trading readiness for one or more symbols.

    Args:
        symbols: Comma-separated list of ticker symbols.
        mode: Execution mode ("live", "paper", "shadow").
        user: Authenticated user (injected).
        service: DataQualityService (injected).

    Returns:
        JSON with readiness result including per-symbol details.
    """
    corr_id = correlation_id_var.get("no-corr")
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]

    try:
        exec_mode = ExecutionMode(mode.lower())
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid execution mode: {mode}. Must be live, paper, or shadow.",
        ) from None

    result = service.check_trading_readiness(symbol_list, exec_mode)

    logger.info(
        "data_quality.readiness_checked",
        symbols=symbol_list,
        mode=mode,
        all_ready=result.all_ready,
        correlation_id=corr_id,
        component="data_quality_routes",
    )

    return JSONResponse(
        content={
            "execution_mode": result.execution_mode.value,
            "all_ready": result.all_ready,
            "symbols": [
                {
                    "symbol": sr.symbol,
                    "ready": sr.ready,
                    "score": _serialize_score(sr.quality_score) if sr.quality_score else None,
                    "blocking_reasons": sr.blocking_reasons,
                }
                for sr in result.symbols
            ],
            "evaluated_at": result.evaluated_at.isoformat() if result.evaluated_at else None,
        }
    )


@router.get("/summary")
async def get_summary(
    symbols: str = Query(..., description="Comma-separated symbol list"),
    user: AuthenticatedUser = Depends(get_current_user),
    service: DataQualityService = Depends(get_data_quality_service),
) -> JSONResponse:
    """
    Get quality summary for multiple symbols.

    Provides a dashboard-style overview of the latest quality score
    for each requested symbol.

    Args:
        symbols: Comma-separated list of ticker symbols.
        user: Authenticated user (injected).
        service: DataQualityService (injected).

    Returns:
        JSON with per-symbol quality summary.
    """
    corr_id = correlation_id_var.get("no-corr")
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]

    summaries = []
    for sym in symbol_list:
        score = service.get_latest_score(sym, CandleInterval.D1)
        summaries.append(
            {
                "symbol": sym,
                "score": _serialize_score(score) if score else None,
            }
        )

    logger.info(
        "data_quality.summary",
        symbol_count=len(symbol_list),
        correlation_id=corr_id,
        component="data_quality_routes",
    )

    return JSONResponse(
        content={
            "symbols": summaries,
        }
    )
