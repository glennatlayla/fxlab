"""
Position sizing API endpoints.

Responsibilities:
- Expose position sizing computation endpoint.
- List available sizing methods.
- Delegate all computation to PositionSizingService.
- Enforce scope-based access control (deployments:read).

Does NOT:
- Contain sizing logic (service responsibility).
- Execute trades.

Dependencies:
- PositionSizingService (injected per request via FastAPI DI).
- services.api.auth: scope-based access control.

Error conditions:
- 400: Invalid parameters or missing required fields for method.
- 401: Missing or invalid authentication.
- 403: Insufficient scope.

Example:
    POST /risk/position-size
    GET /risk/position-size/methods
"""

from __future__ import annotations

from decimal import Decimal

import structlog
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from libs.contracts.errors import ValidationError
from libs.contracts.position_sizing import SizingMethod, SizingRequest
from services.api.auth import AuthenticatedUser, require_scope
from services.api.services.position_sizing_service import PositionSizingService

router = APIRouter(prefix="/risk/position-size", tags=["position-sizing"])

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Dependency provider
# ---------------------------------------------------------------------------


def get_position_sizing_service() -> PositionSizingService:
    """
    Provide the PositionSizingService.

    The sizing service is stateless — no database dependencies needed.

    Returns:
        PositionSizingService instance.
    """
    return PositionSizingService()


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------


class ComputeSizeRequest(BaseModel):
    """Request body for POST /risk/position-size."""

    symbol: str = Field(..., min_length=1, max_length=10)
    side: str = Field(..., pattern=r"^(buy|sell)$")
    method: str = Field(..., description="Sizing method name.")
    risk_per_trade_pct: Decimal = Field(default=Decimal("2.0"), gt=0.0, le=100.0)
    account_equity: Decimal = Field(..., gt=0.0)
    current_price: Decimal = Field(default=Decimal("0"), ge=0.0)
    max_position_size: Decimal | None = Field(default=None)
    atr_value: Decimal | None = Field(default=None)
    atr_multiplier: Decimal = Field(default=Decimal("2.0"), gt=0.0)
    win_rate: Decimal | None = Field(default=None)
    avg_win_loss_ratio: Decimal | None = Field(default=None)
    total_positions: int = Field(default=1, ge=1)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    summary="Compute recommended position size",
    status_code=status.HTTP_200_OK,
)
def compute_position_size(
    request: ComputeSizeRequest,
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: PositionSizingService = Depends(get_position_sizing_service),
) -> JSONResponse:
    """
    Compute recommended position size without executing a trade.

    Args:
        request: Sizing parameters.
        user: Authenticated user with deployments:read scope.
        service: PositionSizingService (injected).

    Returns:
        JSONResponse with sizing result.
    """
    try:
        method = SizingMethod(request.method)
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "detail": f"Unknown method: {request.method}. "
                f"Valid: {[m.value for m in SizingMethod]}"
            },
        )

    sizing_request = SizingRequest(
        symbol=request.symbol,
        side=request.side,
        method=method,
        risk_per_trade_pct=request.risk_per_trade_pct,
        account_equity=request.account_equity,
        current_price=request.current_price,
        max_position_size=request.max_position_size,
        atr_value=request.atr_value,
        atr_multiplier=request.atr_multiplier,
        win_rate=request.win_rate,
        avg_win_loss_ratio=request.avg_win_loss_ratio,
        total_positions=request.total_positions,
    )

    try:
        result = service.compute_size(sizing_request)
    except ValidationError as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(e)},
        )

    return JSONResponse(content=result.model_dump(mode="json"))


@router.get(
    "/methods",
    summary="List available sizing methods",
    status_code=status.HTTP_200_OK,
)
def list_methods(
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: PositionSizingService = Depends(get_position_sizing_service),
) -> JSONResponse:
    """
    List all available position sizing methods.

    Args:
        user: Authenticated user with deployments:read scope.
        service: PositionSizingService (injected).

    Returns:
        JSONResponse with available methods.
    """
    methods = service.get_available_methods()
    return JSONResponse(
        content={
            "methods": [{"name": m.value, "description": m.name} for m in methods],
            "count": len(methods),
        }
    )
