"""
Portfolio risk analytics API endpoints.

Responsibilities:
- Expose VaR, correlation matrix, concentration, and summary endpoints.
- Delegate all computation to RiskAnalyticsService.
- Serialize Decimal and nested Pydantic models to JSON-safe dicts.
- Enforce scope-based access control (deployments:read).
- Map domain errors to HTTP status codes.

Does NOT:
- Contain risk computation logic (service responsibility).
- Access databases directly (injected via DI).
- Cache results (caller/infrastructure responsibility).

Dependencies:
- RiskAnalyticsService (injected per request via FastAPI DI).
- services.api.auth: scope-based access control.
- libs.contracts.risk_analytics: result contracts.

Error conditions:
- 400: Invalid parameters (e.g., lookback_days < 30).
- 401: Missing or invalid authentication.
- 403: Insufficient scope.
- 404: No positions or insufficient market data.

Example:
    GET /risk/analytics/var/01HDEPLOY...
    GET /risk/analytics/correlation/01HDEPLOY...
    GET /risk/analytics/concentration/01HDEPLOY...
    GET /risk/analytics/summary/01HDEPLOY...
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from libs.contracts.errors import NotFoundError, ValidationError
from libs.contracts.interfaces.risk_analytics_service import (
    RiskAnalyticsServiceInterface,
)
from libs.contracts.risk_analytics import (
    ConcentrationReport,
    CorrelationMatrix,
    PortfolioRiskSummary,
    VaRResult,
)
from services.api.auth import AuthenticatedUser, require_scope
from services.api.db import get_db

router = APIRouter(prefix="/risk/analytics", tags=["risk-analytics"])

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Dependency providers
# ---------------------------------------------------------------------------


def get_risk_analytics_service(db: Session = Depends(get_db)):
    """
    Provide the RiskAnalyticsService wired to real repositories.

    Args:
        db: SQLAlchemy session injected by FastAPI DI.

    Returns:
        RiskAnalyticsService bound to position and market data repos.
    """
    from services.api.repositories.sql_market_data_repository import (
        SqlMarketDataRepository,
    )
    from services.api.repositories.sql_position_repository import (
        SqlPositionRepository,
    )
    from services.api.services.risk_analytics_service import RiskAnalyticsService

    return RiskAnalyticsService(
        position_repo=SqlPositionRepository(db=db),
        market_data_repo=SqlMarketDataRepository(db=db),
    )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_var(result: VaRResult) -> dict:
    """
    Serialize a VaRResult to a JSON-safe dict.

    Args:
        result: VaRResult instance.

    Returns:
        JSON-serializable dict with string Decimals.
    """
    return result.model_dump(mode="json")


def _serialize_correlation(result: CorrelationMatrix) -> dict:
    """
    Serialize a CorrelationMatrix to a JSON-safe dict.

    Args:
        result: CorrelationMatrix instance.

    Returns:
        JSON-serializable dict.
    """
    return result.model_dump(mode="json")


def _serialize_concentration(result: ConcentrationReport) -> dict:
    """
    Serialize a ConcentrationReport to a JSON-safe dict.

    Args:
        result: ConcentrationReport instance.

    Returns:
        JSON-serializable dict.
    """
    return result.model_dump(mode="json")


def _serialize_summary(result: PortfolioRiskSummary) -> dict:
    """
    Serialize a PortfolioRiskSummary to a JSON-safe dict.

    Args:
        result: PortfolioRiskSummary instance.

    Returns:
        JSON-serializable dict.
    """
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/var/{deployment_id}",
    summary="Compute VaR and CVaR for a deployment",
    status_code=status.HTTP_200_OK,
)
def get_var(
    deployment_id: str,
    lookback_days: int = Query(
        default=252, ge=30, le=1000, description="Lookback period in trading days"
    ),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: RiskAnalyticsServiceInterface = Depends(get_risk_analytics_service),
) -> JSONResponse:
    """
    Compute Value-at-Risk and Conditional VaR (Expected Shortfall).

    Returns Historical VaR and CVaR at 95% and 99% confidence levels,
    scaled to portfolio dollar amounts.

    Args:
        deployment_id: ULID of the deployment.
        lookback_days: Trading days for return history (30-1000).
        user: Authenticated user with deployments:read scope.
        service: RiskAnalyticsService (injected).

    Returns:
        JSONResponse with VaR result.
    """
    try:
        result = service.compute_var(
            deployment_id=deployment_id,
            lookback_days=lookback_days,
        )
    except ValidationError as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(e)},
        )
    except NotFoundError as e:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(e)},
        )

    return JSONResponse(content=_serialize_var(result))


@router.get(
    "/correlation/{deployment_id}",
    summary="Compute correlation matrix for portfolio symbols",
    status_code=status.HTTP_200_OK,
)
def get_correlation(
    deployment_id: str,
    lookback_days: int = Query(
        default=252, ge=30, le=1000, description="Lookback period in trading days"
    ),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: RiskAnalyticsServiceInterface = Depends(get_risk_analytics_service),
) -> JSONResponse:
    """
    Compute Pearson correlation matrix from daily returns.

    Returns a symmetric matrix with 1.0 on the diagonal, guaranteed
    positive semi-definite.

    Args:
        deployment_id: ULID of the deployment.
        lookback_days: Trading days for return history (30-1000).
        user: Authenticated user with deployments:read scope.
        service: RiskAnalyticsService (injected).

    Returns:
        JSONResponse with correlation matrix.
    """
    try:
        result = service.compute_correlation_matrix(
            deployment_id=deployment_id,
            lookback_days=lookback_days,
        )
    except NotFoundError as e:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(e)},
        )

    return JSONResponse(content=_serialize_correlation(result))


@router.get(
    "/concentration/{deployment_id}",
    summary="Compute portfolio concentration analysis",
    status_code=status.HTTP_200_OK,
)
def get_concentration(
    deployment_id: str,
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: RiskAnalyticsServiceInterface = Depends(get_risk_analytics_service),
) -> JSONResponse:
    """
    Compute portfolio concentration with Herfindahl-Hirschman Index.

    Returns per-symbol weights, HHI score, and top-5 position
    concentration percentage.

    Args:
        deployment_id: ULID of the deployment.
        user: Authenticated user with deployments:read scope.
        service: RiskAnalyticsService (injected).

    Returns:
        JSONResponse with concentration report.
    """
    try:
        result = service.compute_concentration(
            deployment_id=deployment_id,
        )
    except NotFoundError as e:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(e)},
        )

    return JSONResponse(content=_serialize_concentration(result))


@router.get(
    "/summary/{deployment_id}",
    summary="Get full portfolio risk summary",
    status_code=status.HTTP_200_OK,
)
def get_summary(
    deployment_id: str,
    lookback_days: int = Query(
        default=252, ge=30, le=1000, description="Lookback period in trading days"
    ),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: RiskAnalyticsServiceInterface = Depends(get_risk_analytics_service),
) -> JSONResponse:
    """
    Assemble full portfolio risk summary.

    Combines VaR, correlation matrix, concentration analysis, and
    exposure breakdown in a single response.

    Args:
        deployment_id: ULID of the deployment.
        lookback_days: Trading days for VaR and correlation (30-1000).
        user: Authenticated user with deployments:read scope.
        service: RiskAnalyticsService (injected).

    Returns:
        JSONResponse with portfolio risk summary.
    """
    try:
        result = service.get_portfolio_risk_summary(
            deployment_id=deployment_id,
            lookback_days=lookback_days,
        )
    except ValidationError as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(e)},
        )
    except NotFoundError as e:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(e)},
        )

    return JSONResponse(content=_serialize_summary(result))
