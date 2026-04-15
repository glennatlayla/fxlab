"""
Risk alerting API endpoints (Phase 7 — M11).

Responsibilities:
- Expose risk alert evaluation endpoint.
- Provide alert configuration CRUD endpoints.
- List all configured alerts.
- Delegate all computation to RiskAlertService.
- Enforce scope-based access control (deployments:read, operator:write).

Does NOT:
- Contain alert evaluation logic (service responsibility).
- Dispatch notifications (IncidentManager responsibility).

Dependencies:
- RiskAlertService (injected per request via FastAPI DI).
- services.api.auth: scope-based access control.

Error conditions:
- 400: Invalid configuration parameters.
- 401: Missing or invalid authentication.
- 403: Insufficient scope.
- 404: No positions found for deployment.

Example:
    POST /risk/alerts/evaluate/{deployment_id}
    GET  /risk/alerts/config/{deployment_id}
    PUT  /risk/alerts/config
    GET  /risk/alerts/configs
"""

from __future__ import annotations

from decimal import Decimal

import structlog
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from libs.contracts.errors import NotFoundError
from services.api.auth import AuthenticatedUser, require_scope
from services.api.services.risk_alert_service import RiskAlertService

router = APIRouter(prefix="/risk/alerts", tags=["risk-alerts"])

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Dependency provider
# ---------------------------------------------------------------------------


def get_risk_alert_service() -> RiskAlertService:
    """
    Provide the RiskAlertService with real dependencies.

    Wires the SQL repositories, risk analytics service, and
    optionally the IncidentManager for alert dispatch.

    Returns:
        Configured RiskAlertService instance.
    """
    from services.api.db import SessionLocal
    from services.api.repositories.sql_market_data_repository import (
        SqlMarketDataRepository,
    )
    from services.api.repositories.sql_position_repository import (
        SqlPositionRepository,
    )
    from services.api.repositories.sql_risk_alert_config_repository import (
        SqlRiskAlertConfigRepository,
    )
    from services.api.services.risk_analytics_service import RiskAnalyticsService

    db = SessionLocal()
    position_repo = SqlPositionRepository(db)
    market_data_repo = SqlMarketDataRepository(db)
    config_repo = SqlRiskAlertConfigRepository(db)
    analytics = RiskAnalyticsService(
        position_repo=position_repo,
        market_data_repo=market_data_repo,
    )

    return RiskAlertService(
        risk_analytics=analytics,
        config_repo=config_repo,
        incident_manager=None,  # Wired when IncidentManager is available
    )


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class UpdateConfigRequest(BaseModel):
    """Request body for PUT /risk/alerts/config."""

    deployment_id: str = Field(..., min_length=1)
    var_threshold_pct: Decimal = Field(default=Decimal("5.0"), gt=0.0, le=100.0)
    concentration_threshold_pct: Decimal = Field(default=Decimal("30.0"), gt=0.0, le=100.0)
    correlation_threshold: Decimal = Field(default=Decimal("0.90"), gt=-1.0, le=1.0)
    lookback_days: int = Field(default=252, ge=30, le=1260)
    enabled: bool = Field(default=True)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/evaluate/{deployment_id}",
    summary="Evaluate risk alerts for a deployment",
    status_code=status.HTTP_200_OK,
)
def evaluate_alerts(
    deployment_id: str,
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: RiskAlertService = Depends(get_risk_alert_service),
) -> JSONResponse:
    """
    Evaluate all risk alert rules for a deployment.

    Computes current VaR, concentration, and correlation metrics,
    compares against configured thresholds, and dispatches incidents
    for any breaches.

    Args:
        deployment_id: Target deployment.
        user: Authenticated user with deployments:read scope.
        service: RiskAlertService (injected).

    Returns:
        JSONResponse with RiskAlertEvaluation.
    """
    try:
        result = service.evaluate_alerts(deployment_id)
    except NotFoundError as e:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(e)},
        )

    return JSONResponse(content=result.model_dump(mode="json"))


@router.get(
    "/config/{deployment_id}",
    summary="Get alert configuration for a deployment",
    status_code=status.HTTP_200_OK,
)
def get_config(
    deployment_id: str,
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: RiskAlertService = Depends(get_risk_alert_service),
) -> JSONResponse:
    """
    Get the alert configuration for a deployment.

    Returns the persisted config or defaults if not configured.

    Args:
        deployment_id: Target deployment.
        user: Authenticated user with deployments:read scope.
        service: RiskAlertService (injected).

    Returns:
        JSONResponse with RiskAlertConfig.
    """
    config = service.get_config(deployment_id)
    return JSONResponse(content=config.model_dump(mode="json"))


@router.put(
    "/config",
    summary="Create or update alert configuration",
    status_code=status.HTTP_200_OK,
)
def update_config(
    request: UpdateConfigRequest,
    user: AuthenticatedUser = Depends(require_scope("operator:write")),
    service: RiskAlertService = Depends(get_risk_alert_service),
) -> JSONResponse:
    """
    Create or update the alert configuration for a deployment.

    Requires operator:write scope since this modifies system behavior.

    Args:
        request: Alert configuration parameters.
        user: Authenticated user with operator:write scope.
        service: RiskAlertService (injected).

    Returns:
        JSONResponse with saved RiskAlertConfig.
    """
    from libs.contracts.risk_alert import RiskAlertConfig

    config = RiskAlertConfig(
        deployment_id=request.deployment_id,
        var_threshold_pct=request.var_threshold_pct,
        concentration_threshold_pct=request.concentration_threshold_pct,
        correlation_threshold=request.correlation_threshold,
        lookback_days=request.lookback_days,
        enabled=request.enabled,
    )
    saved = service.update_config(config)
    return JSONResponse(content=saved.model_dump(mode="json"))


@router.get(
    "/configs",
    summary="List all alert configurations",
    status_code=status.HTTP_200_OK,
)
def list_configs(
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: RiskAlertService = Depends(get_risk_alert_service),
) -> JSONResponse:
    """
    List all configured risk alert configurations.

    Args:
        user: Authenticated user with deployments:read scope.
        service: RiskAlertService (injected).

    Returns:
        JSONResponse with list of configs and count.
    """
    configs = service.list_configs()
    return JSONResponse(
        content={
            "configs": [c.model_dump(mode="json") for c in configs],
            "count": len(configs),
        }
    )
