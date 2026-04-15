"""
Risk gate API endpoints.

Responsibilities:
- Expose risk event query endpoints.
- Expose risk limits query endpoints.
- Delegate all business logic to the RiskGateService.
- Map domain errors to HTTP status codes.

Does NOT:
- Contain business logic or risk checking.
- Access the database directly.

Dependencies:
- RiskGateInterface (injected per request).
- libs.contracts.risk: RiskEvent, PreTradeRiskLimits.
- structlog for structured logging.

Error conditions:
- 404 Not Found: deployment has no risk limits configured.

Example:
    GET /risk-events?deployment_id=01HDEPLOY... → 200 [{...}]
    GET /deployments/{id}/risk-limits           → 200 {...}
"""

from __future__ import annotations

from decimal import Decimal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.risk_gate_interface import RiskGateInterface
from libs.contracts.risk import PreTradeRiskLimits
from services.api.auth import AuthenticatedUser, require_scope
from services.api.middleware.rate_limit import rate_limit

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class SetRiskLimitsBody(BaseModel):
    """HTTP request body for setting risk limits."""

    max_position_size: str = Field(default="0", description="Max position size per symbol.")
    max_daily_loss: str = Field(default="0", description="Max daily loss threshold.")
    max_order_value: str = Field(default="0", description="Max notional value per order.")
    max_concentration_pct: str = Field(default="0", description="Max concentration % in symbol.")
    max_open_orders: int = Field(default=0, description="Max open orders.", ge=0)


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------

_risk_gate: RiskGateInterface | None = None


def set_risk_gate_service(service: RiskGateInterface) -> None:
    """
    Configure the module-level risk gate service instance.

    Args:
        service: Configured RiskGateInterface implementation.
    """
    global _risk_gate
    _risk_gate = service


def get_risk_gate_service() -> RiskGateInterface:
    """
    Dependency provider for the risk gate service.

    Returns:
        The configured RiskGateInterface.

    Raises:
        RuntimeError: if the service has not been configured.
    """
    if _risk_gate is None:
        raise RuntimeError(
            "Risk gate service not configured. "
            "Call set_risk_gate_service() during application bootstrap."
        )
    return _risk_gate


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/risk-events",
    summary="Get risk events",
)
async def get_risk_events(
    deployment_id: str = Query(..., description="Deployment ULID"),
    severity: str | None = Query(default=None, description="Filter by severity"),
    limit: int = Query(default=100, description="Max events to return", ge=1, le=1000),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: RiskGateInterface = Depends(get_risk_gate_service),
) -> JSONResponse:
    """
    Get risk events for a deployment.

    Returns 200 with list of risk events, most recent first.
    """
    events = service.get_risk_events(
        deployment_id=deployment_id,
        severity=severity,
        limit=limit,
    )
    return JSONResponse(
        status_code=200,
        content=[
            {
                "event_id": e.event_id,
                "deployment_id": e.deployment_id,
                "check_name": e.check_name,
                "severity": e.severity.value,
                "passed": e.passed,
                "reason": e.reason,
                "current_value": e.current_value,
                "limit_value": e.limit_value,
                "order_client_id": e.order_client_id,
                "symbol": e.symbol,
                "correlation_id": e.correlation_id,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
    )


@router.get(
    "/deployments/{deployment_id}/risk-limits",
    summary="Get risk limits for deployment",
)
async def get_risk_limits(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: RiskGateInterface = Depends(get_risk_gate_service),
) -> JSONResponse:
    """
    Get current risk limits for a deployment.

    Returns 200 with risk limits, 404 if not configured.
    """
    try:
        limits = service.get_risk_limits(deployment_id=deployment_id)
        return JSONResponse(
            status_code=200,
            content={
                "deployment_id": deployment_id,
                "max_position_size": str(limits.max_position_size),
                "max_daily_loss": str(limits.max_daily_loss),
                "max_order_value": str(limits.max_order_value),
                "max_concentration_pct": str(limits.max_concentration_pct),
                "max_open_orders": limits.max_open_orders,
            },
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put(
    "/deployments/{deployment_id}/risk-limits",
    summary="Set risk limits for deployment",
)
async def set_risk_limits(
    body: SetRiskLimitsBody,
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: RiskGateInterface = Depends(get_risk_gate_service),
    _rate_limit: None = Depends(
        rate_limit(max_requests=10, window_seconds=3600, scope="risk_setting")
    ),
) -> JSONResponse:
    """
    Set risk limits for a deployment.

    Returns 200 on success.
    """
    limits = PreTradeRiskLimits(
        max_position_size=Decimal(body.max_position_size),
        max_daily_loss=Decimal(body.max_daily_loss),
        max_order_value=Decimal(body.max_order_value),
        max_concentration_pct=Decimal(body.max_concentration_pct),
        max_open_orders=body.max_open_orders,
    )
    service.set_risk_limits(deployment_id=deployment_id, limits=limits)
    return JSONResponse(
        status_code=200,
        content={"deployment_id": deployment_id, "status": "limits_set"},
    )


@router.delete(
    "/deployments/{deployment_id}/risk-limits",
    summary="Clear risk limits for deployment",
)
async def clear_risk_limits(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: RiskGateInterface = Depends(get_risk_gate_service),
) -> JSONResponse:
    """
    Clear risk limits for a deployment.

    Returns 200 on success, 404 if not configured.
    """
    try:
        service.clear_risk_limits(deployment_id=deployment_id)
        return JSONResponse(
            status_code=200,
            content={"deployment_id": deployment_id, "status": "limits_cleared"},
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
