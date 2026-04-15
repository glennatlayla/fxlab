"""
Paper-mode execution API endpoints.

Responsibilities:
- Expose paper-specific endpoints for order submission, processing,
  cancellation, positions, account, open orders, and reconciliation.
- Validate request payloads using Pydantic contracts.
- Delegate all business logic to the PaperExecutionService.
- Map domain errors to HTTP status codes.

Does NOT:
- Contain business logic or paper adapter management.
- Access the database directly.
- Manage paper adapter lifecycle (service responsibility).

Dependencies:
- PaperExecutionService (injected per request).
- libs.contracts.execution: OrderRequest, ExecutionMode.
- structlog for structured logging.

Error conditions:
- 404 Not Found: deployment_id does not exist or has no paper adapter.
- 409 Conflict: deployment not in executable paper state.
- 422 Unprocessable Entity: validation error.

Example:
    POST /paper/{deployment_id}/register        → 201
    POST /paper/{deployment_id}/orders           → 200 (SUBMITTED)
    POST /paper/{deployment_id}/process          → 200 (fills)
    POST /paper/{deployment_id}/orders/{id}/cancel → 200
    POST /paper/{deployment_id}/market-price     → 200
    GET  /paper/{deployment_id}/positions        → 200
    GET  /paper/{deployment_id}/account          → 200
    GET  /paper/{deployment_id}/open-orders      → 200
    GET  /paper/{deployment_id}/all-orders       → 200 (reconciliation)
    DELETE /paper/{deployment_id}                → 200
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
from libs.contracts.interfaces.paper_execution_service_interface import (
    PaperExecutionServiceInterface,
)
from services.api.auth import AuthenticatedUser, require_scope
from services.api.middleware.correlation import correlation_id_var

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class PaperRegisterBody(BaseModel):
    """HTTP request body for registering a deployment for paper execution."""

    initial_equity: str = Field(..., description="Starting hypothetical equity as decimal string.")
    market_prices: dict[str, str] | None = Field(
        default=None, description="Initial market prices {symbol: price_string}."
    )
    commission_per_order: str = Field(
        default="0", description="Fixed commission per fill as decimal string."
    )


class PaperOrderBody(BaseModel):
    """HTTP request body for submitting a paper order."""

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


class PaperMarketPriceBody(BaseModel):
    """HTTP request body for updating a market price."""

    symbol: str = Field(..., min_length=1, max_length=50, description="Instrument ticker.")
    price: str = Field(..., description="Current market price as decimal string.")


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------

_paper_service: PaperExecutionServiceInterface | None = None


def set_paper_service(service: PaperExecutionServiceInterface) -> None:
    """
    Configure the module-level paper execution service instance.

    Called during application bootstrap to wire the service.

    Args:
        service: Configured PaperExecutionServiceInterface implementation.
    """
    global _paper_service
    _paper_service = service


def get_paper_service() -> PaperExecutionServiceInterface:
    """
    Dependency provider for the paper execution service.

    Returns:
        The configured PaperExecutionServiceInterface.

    Raises:
        RuntimeError: if the service has not been configured.
    """
    if _paper_service is None:
        raise RuntimeError(
            "Paper execution service not configured. "
            "Call set_paper_service() during application bootstrap."
        )
    return _paper_service


# ---------------------------------------------------------------------------
# Helper: serialize OrderResponse to JSON-safe dict
# ---------------------------------------------------------------------------


def _order_response_to_dict(resp) -> dict:
    """
    Convert an OrderResponse to a JSON-serialisable dictionary.

    Args:
        resp: OrderResponse instance.

    Returns:
        Dict with string-encoded decimals and enum values.
    """
    return {
        "client_order_id": resp.client_order_id,
        "broker_order_id": resp.broker_order_id,
        "symbol": resp.symbol,
        "side": resp.side.value,
        "order_type": resp.order_type.value,
        "quantity": str(resp.quantity),
        "filled_quantity": str(resp.filled_quantity),
        "average_fill_price": (
            str(resp.average_fill_price) if resp.average_fill_price is not None else None
        ),
        "status": resp.status.value,
        "execution_mode": resp.execution_mode.value if resp.execution_mode else None,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{deployment_id}/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register deployment for paper execution",
)
async def register_paper_deployment(
    body: PaperRegisterBody,
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: PaperExecutionServiceInterface = Depends(get_paper_service),
) -> JSONResponse:
    """
    Register a deployment for paper execution, creating an isolated adapter.

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
            commission_per_order=Decimal(body.commission_per_order),
        )
        logger.info(
            "paper_deployment_registered_via_api",
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
    summary="Submit paper order",
)
async def submit_paper_order(
    body: PaperOrderBody,
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: PaperExecutionServiceInterface = Depends(get_paper_service),
) -> JSONResponse:
    """
    Submit an order for paper execution.

    Returns 200 with SUBMITTED status. Call POST /process to advance fills.
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
            execution_mode=ExecutionMode.PAPER,
        )
        resp = service.submit_paper_order(
            deployment_id=deployment_id,
            request=request,
            correlation_id=correlation_id_var.get(""),
        )
        return JSONResponse(status_code=200, content=_order_response_to_dict(resp))
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
    "/{deployment_id}/process",
    summary="Process pending paper orders",
)
async def process_pending_orders(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: PaperExecutionServiceInterface = Depends(get_paper_service),
) -> JSONResponse:
    """
    Process pending orders for a deployment (tick-based fill cycle).

    Returns 200 with list of orders that were filled this tick.
    """
    try:
        filled = service.process_pending_orders(deployment_id=deployment_id)
        return JSONResponse(
            status_code=200,
            content={
                "filled_count": len(filled),
                "orders": [_order_response_to_dict(f) for f in filled],
            },
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/{deployment_id}/orders/{broker_order_id}/cancel",
    summary="Cancel paper order",
)
async def cancel_paper_order(
    deployment_id: str = Path(..., description="Deployment ULID"),
    broker_order_id: str = Path(..., description="Broker order ID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: PaperExecutionServiceInterface = Depends(get_paper_service),
) -> JSONResponse:
    """
    Cancel an open paper order.

    Returns 200 with the order's current status.
    """
    try:
        resp = service.cancel_paper_order(
            deployment_id=deployment_id,
            broker_order_id=broker_order_id,
            correlation_id=correlation_id_var.get(""),
        )
        return JSONResponse(status_code=200, content=_order_response_to_dict(resp))
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/{deployment_id}/market-price",
    summary="Update paper market price",
)
async def update_paper_market_price(
    body: PaperMarketPriceBody,
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: PaperExecutionServiceInterface = Depends(get_paper_service),
) -> JSONResponse:
    """
    Update a market price for a deployment's paper adapter.

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
    "/{deployment_id}/positions",
    summary="Get paper positions",
)
async def get_paper_positions(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: PaperExecutionServiceInterface = Depends(get_paper_service),
) -> JSONResponse:
    """
    Get current positions for a paper deployment.

    Returns 200 with list of positions, 404 if not registered.
    """
    try:
        positions = service.get_paper_positions(deployment_id=deployment_id)
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
    summary="Get paper account",
)
async def get_paper_account(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: PaperExecutionServiceInterface = Depends(get_paper_service),
) -> JSONResponse:
    """
    Get account state for a paper deployment.

    Returns 200 with account snapshot, 404 if not registered.
    """
    try:
        acct = service.get_paper_account(deployment_id=deployment_id)
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


@router.get(
    "/{deployment_id}/open-orders",
    summary="Get open paper orders",
)
async def get_open_orders(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: PaperExecutionServiceInterface = Depends(get_paper_service),
) -> JSONResponse:
    """
    Get all open/pending orders for a paper deployment.

    Returns 200 with list of open orders, 404 if not registered.
    """
    try:
        orders = service.get_open_orders(deployment_id=deployment_id)
        return JSONResponse(
            status_code=200,
            content=[_order_response_to_dict(o) for o in orders],
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/{deployment_id}/all-orders",
    summary="Get all paper order states (reconciliation)",
)
async def get_all_order_states(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: PaperExecutionServiceInterface = Depends(get_paper_service),
) -> JSONResponse:
    """
    Get all order states for reconciliation recovery.

    Returns 200 with list of all orders (all statuses), 404 if not registered.
    """
    try:
        orders = service.get_all_order_states(deployment_id=deployment_id)
        return JSONResponse(
            status_code=200,
            content=[_order_response_to_dict(o) for o in orders],
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete(
    "/{deployment_id}",
    summary="Deregister paper deployment",
)
async def deregister_paper_deployment(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: PaperExecutionServiceInterface = Depends(get_paper_service),
) -> JSONResponse:
    """
    Deregister a deployment and clean up its paper adapter.

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
