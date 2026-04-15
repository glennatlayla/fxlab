"""
Shadow-mode query API endpoints.

Responsibilities:
- Expose shadow-specific query endpoints for decision timeline, P&L,
  positions, and account state.
- Expose shadow order submission endpoint.
- Validate request payloads using Pydantic contracts.
- Delegate all business logic to the ShadowExecutionService.
- Map domain errors to HTTP status codes.

Does NOT:
- Contain business logic or shadow adapter management.
- Access the database directly.
- Manage shadow adapter lifecycle (service responsibility).

Dependencies:
- ShadowExecutionService (injected per request).
- libs.contracts.execution: OrderRequest, ExecutionMode.
- structlog for structured logging.

Error conditions:
- 404 Not Found: deployment_id does not exist or has no shadow adapter.
- 409 Conflict: deployment not in executable shadow state.
- 422 Unprocessable Entity: validation error.

Example:
    GET /shadow/{deployment_id}/decisions → 200 [{...}, {...}]
    GET /shadow/{deployment_id}/pnl      → 200 {"total_unrealized_pnl": "450.00", ...}
    GET /shadow/{deployment_id}/positions → 200 [{...}]
    GET /shadow/{deployment_id}/account   → 200 {"equity": "1000450.00", ...}
    POST /shadow/{deployment_id}/orders   → 200 {"status": "filled", ...}
"""

from __future__ import annotations

from decimal import Decimal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from libs.contracts.errors import NotFoundError, StateTransitionError, ValidationError
from libs.contracts.execution import (
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)
from libs.contracts.interfaces.shadow_execution_service_interface import (
    ShadowExecutionServiceInterface,
)
from services.api.auth import AuthenticatedUser, require_scope
from services.api.middleware.correlation import correlation_id_var

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ShadowOrderBody(BaseModel):
    """HTTP request body for submitting a shadow order."""

    client_order_id: str = Field(
        ..., min_length=1, max_length=255, description="Unique idempotency key."
    )
    symbol: str = Field(..., min_length=1, max_length=50, description="Instrument ticker.")
    side: str = Field(..., description="Order side: 'buy' or 'sell'.")
    order_type: str = Field(default="market", description="Order type: market, limit, stop.")
    quantity: str = Field(..., description="Order quantity as decimal string.")
    limit_price: str | None = Field(default=None, description="Limit price for limit orders.")
    stop_price: str | None = Field(default=None, description="Stop price for stop orders.")
    strategy_id: str = Field(
        ..., min_length=26, max_length=26, description="ULID of the originating strategy."
    )


class ShadowRegisterBody(BaseModel):
    """HTTP request body for registering a deployment for shadow execution."""

    initial_equity: str = Field(..., description="Starting hypothetical equity as decimal string.")
    market_prices: dict[str, str] | None = Field(
        default=None, description="Initial market prices {symbol: price_string}."
    )


class ShadowMarketPriceBody(BaseModel):
    """HTTP request body for updating a market price."""

    symbol: str = Field(..., min_length=1, max_length=50, description="Instrument ticker.")
    price: str = Field(..., description="Current market price as decimal string.")


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------

# The shadow execution service is a singleton that manages per-deployment
# adapters. In production, it's wired in the application bootstrap.
# For now, we use a module-level instance that routes can inject.
# This will be replaced with proper DI in M4/M5.

_shadow_service: ShadowExecutionServiceInterface | None = None


def set_shadow_service(service: ShadowExecutionServiceInterface) -> None:
    """
    Configure the module-level shadow execution service instance.

    Called during application bootstrap to wire the service.

    Args:
        service: Configured ShadowExecutionServiceInterface implementation.
    """
    global _shadow_service
    _shadow_service = service


def get_shadow_service() -> ShadowExecutionServiceInterface:
    """
    Dependency provider for the shadow execution service.

    Returns:
        The configured ShadowExecutionServiceInterface.

    Raises:
        RuntimeError: if the service has not been configured.
    """
    if _shadow_service is None:
        raise RuntimeError(
            "Shadow execution service not configured. "
            "Call set_shadow_service() during application bootstrap."
        )
    return _shadow_service


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{deployment_id}/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register deployment for shadow execution",
)
async def register_shadow_deployment(
    body: ShadowRegisterBody,
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: ShadowExecutionServiceInterface = Depends(get_shadow_service),
) -> JSONResponse:
    """
    Register a deployment for shadow execution, creating an isolated adapter.

    Returns 201 on success, 422 on duplicate registration.
    """
    try:
        market_prices: dict[str, Decimal] | None = None
        if body.market_prices:
            market_prices = {symbol: Decimal(price) for symbol, price in body.market_prices.items()}
        service.register_deployment(
            deployment_id=deployment_id,
            initial_equity=Decimal(body.initial_equity),
            market_prices=market_prices,
        )
        logger.info(
            "shadow_deployment_registered_via_api",
            deployment_id=deployment_id,
            user_id=user.user_id,
        )
        return JSONResponse(
            status_code=201,
            content={"deployment_id": deployment_id, "status": "registered"},
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post(
    "/{deployment_id}/orders",
    summary="Submit shadow order",
)
async def submit_shadow_order(
    body: ShadowOrderBody,
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: ShadowExecutionServiceInterface = Depends(get_shadow_service),
) -> JSONResponse:
    """
    Submit an order for shadow execution.

    Returns 200 with the shadow fill result.
    """
    try:
        request = OrderRequest(
            client_order_id=body.client_order_id,
            symbol=body.symbol,
            side=OrderSide(body.side),
            order_type=OrderType(body.order_type),
            quantity=Decimal(body.quantity),
            limit_price=Decimal(body.limit_price) if body.limit_price else None,
            stop_price=Decimal(body.stop_price) if body.stop_price else None,
            time_in_force=TimeInForce.DAY,
            deployment_id=deployment_id,
            strategy_id=body.strategy_id,
            correlation_id=correlation_id_var.get(""),
            execution_mode=ExecutionMode.SHADOW,
        )
        resp = service.execute_shadow_order(
            deployment_id=deployment_id,
            request=request,
            correlation_id=correlation_id_var.get(""),
        )
        return JSONResponse(
            status_code=200,
            content={
                "client_order_id": resp.client_order_id,
                "broker_order_id": resp.broker_order_id,
                "symbol": resp.symbol,
                "side": resp.side.value,
                "quantity": str(resp.quantity),
                "filled_quantity": str(resp.filled_quantity),
                "average_fill_price": str(resp.average_fill_price),
                "status": resp.status.value,
                "execution_mode": resp.execution_mode.value,
            },
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StateTransitionError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(e),
                "current_state": e.current_state,
                "attempted_state": e.attempted_state,
            },
        )
    except (ValueError, ValidationError) as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post(
    "/{deployment_id}/market-price",
    summary="Update shadow market price",
)
async def update_shadow_market_price(
    body: ShadowMarketPriceBody,
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: ShadowExecutionServiceInterface = Depends(get_shadow_service),
) -> JSONResponse:
    """
    Update a market price for a deployment's shadow adapter.

    Returns 200 on success, 404 if deployment not registered.
    """
    try:
        service.update_market_price(
            deployment_id=deployment_id,
            symbol=body.symbol,
            price=Decimal(body.price),
        )
        return JSONResponse(
            status_code=200,
            content={"status": "updated", "symbol": body.symbol, "price": body.price},
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/{deployment_id}/decisions",
    summary="Get shadow decisions",
)
async def get_shadow_decisions(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: ShadowExecutionServiceInterface = Depends(get_shadow_service),
) -> JSONResponse:
    """
    Retrieve the full decision timeline for a shadow deployment.

    Returns 200 with list of decision events, 404 if not registered.
    """
    try:
        decisions = service.get_shadow_decisions(deployment_id=deployment_id)
        return JSONResponse(status_code=200, content=decisions)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/{deployment_id}/pnl",
    summary="Get shadow P&L",
)
async def get_shadow_pnl(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: ShadowExecutionServiceInterface = Depends(get_shadow_service),
) -> JSONResponse:
    """
    Get hypothetical P&L summary for a shadow deployment.

    Returns 200 with P&L data, 404 if not registered.
    """
    try:
        pnl = service.get_shadow_pnl(deployment_id=deployment_id)
        return JSONResponse(status_code=200, content=pnl)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/{deployment_id}/positions",
    summary="Get shadow positions",
)
async def get_shadow_positions(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: ShadowExecutionServiceInterface = Depends(get_shadow_service),
) -> JSONResponse:
    """
    Get current hypothetical positions for a shadow deployment.

    Returns 200 with list of positions, 404 if not registered.
    """
    try:
        positions = service.get_shadow_positions(deployment_id=deployment_id)
        return JSONResponse(
            status_code=200,
            content=[
                {
                    "symbol": p.symbol,
                    "quantity": str(p.quantity),
                    "average_entry_price": str(p.average_entry_price),
                    "market_price": str(p.market_price),
                    "market_value": str(p.market_value),
                    "unrealized_pnl": str(p.unrealized_pnl),
                    "realized_pnl": str(p.realized_pnl),
                    "cost_basis": str(p.cost_basis),
                }
                for p in positions
            ],
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/{deployment_id}/account",
    summary="Get shadow account",
)
async def get_shadow_account(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: ShadowExecutionServiceInterface = Depends(get_shadow_service),
) -> JSONResponse:
    """
    Get hypothetical account state for a shadow deployment.

    Returns 200 with account snapshot, 404 if not registered.
    """
    try:
        acct = service.get_shadow_account(deployment_id=deployment_id)
        return JSONResponse(
            status_code=200,
            content={
                "account_id": acct.account_id,
                "equity": str(acct.equity),
                "cash": str(acct.cash),
                "buying_power": str(acct.buying_power),
                "portfolio_value": str(acct.portfolio_value),
                "daily_pnl": str(acct.daily_pnl),
                "positions_count": acct.positions_count,
            },
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete(
    "/{deployment_id}",
    summary="Deregister shadow deployment",
)
async def deregister_shadow_deployment(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: ShadowExecutionServiceInterface = Depends(get_shadow_service),
) -> JSONResponse:
    """
    Deregister a deployment and clean up its shadow adapter.

    Returns 200 on success, 404 if not registered.
    """
    try:
        service.deregister_deployment(deployment_id=deployment_id)
        return JSONResponse(
            status_code=200,
            content={"deployment_id": deployment_id, "status": "deregistered"},
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
