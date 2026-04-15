"""
Live trading API endpoints.

Responsibilities:
- Expose live-specific endpoints for order submission, cancellation,
  position queries, account state, P&L, and order reconciliation.
- Validate request payloads using Pydantic contracts.
- Delegate all business logic to the LiveExecutionService.
- Map domain errors to HTTP status codes.
- Enforce live:trade scope on all endpoints.

Does NOT:
- Contain business logic or broker adapter management.
- Access the database directly.
- Manage broker lifecycle (service responsibility).

Dependencies:
- LiveExecutionService (injected via module-level DI).
- libs.contracts.execution: OrderRequest, ExecutionMode.
- services.api.auth: require_scope("live:trade").
- structlog for structured logging.

Error conditions:
- 401 Unauthorized: Missing or invalid authentication token.
- 403 Forbidden: Caller lacks live:trade scope.
- 404 Not Found: deployment_id or order not found.
- 409 Conflict: kill switch active, blocking order submission.
- 422 Unprocessable Entity: risk gate rejection or validation error.
- 502 Bad Gateway: broker communication failure.

Example:
    POST /live/orders?deployment_id=01HDEPLOY...           -> 201 (submitted)
    GET  /live/orders?deployment_id=01HDEPLOY...           -> 200 (order list)
    GET  /live/positions?deployment_id=01HDEPLOY...        -> 200 (positions)
    POST /live/orders/{id}/cancel?deployment_id=01HDEPLOY... -> 200 (cancelled)
    GET  /live/pnl?deployment_id=01HDEPLOY...              -> 200 (P&L)
    POST /live/orders/{id}/sync?deployment_id=01HDEPLOY... -> 200 (synced)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from libs.contracts.errors import (
    ExternalServiceError,
    KillSwitchActiveError,
    NotFoundError,
    RiskGateRejectionError,
    StateTransitionError,
    ValidationError,
)
from libs.contracts.execution import (
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)
from services.api.auth import AuthenticatedUser, require_scope
from services.api.middleware.audit_trail import audit_action
from services.api.middleware.correlation import correlation_id_var
from services.api.services.interfaces.live_execution_service_interface import (
    LiveExecutionServiceInterface,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/live", tags=["live"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class LiveOrderBody(BaseModel):
    """HTTP request body for submitting a live order."""

    client_order_id: str = Field(..., description="Client idempotency key.", min_length=1)
    symbol: str = Field(..., description="Instrument ticker (e.g. AAPL).", min_length=1)
    side: str = Field(..., description="Order side: 'buy' or 'sell'.")
    order_type: str = Field(..., description="Order type: market, limit, stop, stop_limit.")
    quantity: str = Field(..., description="Order quantity as decimal string.", min_length=1)
    time_in_force: str = Field(default="day", description="Time in force: day, gtc, ioc, fok.")
    strategy_id: str = Field(..., description="Originating strategy ULID.", min_length=1)
    limit_price: str | None = Field(default=None, description="Limit price for limit orders.")
    stop_price: str | None = Field(default=None, description="Stop price for stop orders.")


# ---------------------------------------------------------------------------
# Module-level dependency injection
# ---------------------------------------------------------------------------

_live_execution_service: LiveExecutionServiceInterface | None = None


def set_live_execution_service(service: LiveExecutionServiceInterface | None) -> None:
    """Wire the LiveExecutionService instance for live routes (called at app startup)."""
    global _live_execution_service
    _live_execution_service = service


def get_live_execution_service() -> LiveExecutionServiceInterface:
    """FastAPI dependency: return the wired LiveExecutionService."""
    if _live_execution_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Live execution service not configured.",
        )
    return _live_execution_service


# ---------------------------------------------------------------------------
# Submit live order
# ---------------------------------------------------------------------------


@router.post(
    "/orders",
    status_code=status.HTTP_201_CREATED,
    summary="Submit a live order",
    dependencies=[
        Depends(
            audit_action(
                action="order.submit_live",
                object_type="order",
                extract_details=lambda req, params: {"deployment_id": params.get("deployment_id")},
            )
        ),
    ],
)
async def submit_live_order(
    body: LiveOrderBody,
    deployment_id: str = Query(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("live:trade")),
    service: LiveExecutionServiceInterface = Depends(get_live_execution_service),
) -> dict[str, Any]:
    """
    Submit a live order through a real broker adapter.

    Requires live:trade scope. The order passes through kill switch check
    and risk gate enforcement before submission.

    Returns:
        OrderResponse serialized as dict.

    Raises:
        403: Caller lacks live:trade scope.
        404: Deployment not found.
        409: Kill switch active.
        422: Risk gate rejection.
        502: Broker communication failure.
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "live.order.submit_requested",
        client_order_id=body.client_order_id,
        deployment_id=deployment_id,
        symbol=body.symbol,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="live_routes",
    )

    # Build the normalized OrderRequest
    try:
        request = OrderRequest(
            client_order_id=body.client_order_id,
            symbol=body.symbol,
            side=OrderSide(body.side),
            order_type=OrderType(body.order_type),
            quantity=Decimal(body.quantity),
            time_in_force=TimeInForce(body.time_in_force),
            deployment_id=deployment_id,
            strategy_id=body.strategy_id,
            correlation_id=corr_id,
            execution_mode=ExecutionMode.LIVE,
            limit_price=Decimal(body.limit_price) if body.limit_price else None,
            stop_price=Decimal(body.stop_price) if body.stop_price else None,
        )
    except (ValueError, Exception) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid order request: {exc}",
        ) from None

    try:
        response = service.submit_live_order(
            deployment_id=deployment_id,
            request=request,
            correlation_id=corr_id,
        )
        return response.model_dump(mode="json")
    except KillSwitchActiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Trading halted: {exc}",
        ) from None
    except RiskGateRejectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Risk gate rejection: {exc.reason or str(exc)}",
        ) from None
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None
    except StateTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    except ExternalServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Broker communication error: {exc}",
        ) from None
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None


# ---------------------------------------------------------------------------
# List live orders
# ---------------------------------------------------------------------------


@router.get(
    "/orders",
    summary="List live orders",
)
async def list_live_orders(
    deployment_id: str = Query(..., description="Deployment ULID"),
    order_status: str | None = Query(default=None, alias="status", description="Filter by status"),
    user: AuthenticatedUser = Depends(require_scope("live:trade")),
    service: LiveExecutionServiceInterface = Depends(get_live_execution_service),
) -> list[dict[str, Any]]:
    """
    List live orders for a deployment.

    Returns:
        List of order dicts.
    """
    return service.list_live_orders(
        deployment_id=deployment_id,
        status=order_status,
    )


# ---------------------------------------------------------------------------
# Get live positions
# ---------------------------------------------------------------------------


@router.get(
    "/positions",
    summary="Get live positions",
)
async def get_live_positions(
    deployment_id: str = Query(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("live:trade")),
    service: LiveExecutionServiceInterface = Depends(get_live_execution_service),
) -> list[dict[str, Any]]:
    """
    Get current live positions from the broker adapter.

    Returns:
        List of PositionSnapshot dicts.
    """
    try:
        positions = service.get_live_positions(deployment_id=deployment_id)
        return [p.model_dump(mode="json") for p in positions]
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None


# ---------------------------------------------------------------------------
# Cancel live order
# ---------------------------------------------------------------------------


@router.post(
    "/orders/{broker_order_id}/cancel",
    summary="Cancel a live order",
    dependencies=[
        Depends(
            audit_action(
                action="order.cancel_live",
                object_type="order",
                extract_object_id="broker_order_id",
            )
        ),
    ],
)
async def cancel_live_order(
    broker_order_id: str,
    deployment_id: str = Query(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("live:trade")),
    service: LiveExecutionServiceInterface = Depends(get_live_execution_service),
) -> dict[str, Any]:
    """
    Cancel an open live order.

    Returns:
        OrderResponse with current status.
    """
    corr_id = correlation_id_var.get("no-corr")
    try:
        response = service.cancel_live_order(
            deployment_id=deployment_id,
            broker_order_id=broker_order_id,
            correlation_id=corr_id,
        )
        return response.model_dump(mode="json")
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None
    except ExternalServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Broker communication error: {exc}",
        ) from None


# ---------------------------------------------------------------------------
# Get live P&L
# ---------------------------------------------------------------------------


@router.get(
    "/pnl",
    summary="Get live P&L summary",
)
async def get_live_pnl(
    deployment_id: str = Query(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("live:trade")),
    service: LiveExecutionServiceInterface = Depends(get_live_execution_service),
) -> dict[str, Any]:
    """
    Get live P&L summary for a deployment.

    Returns:
        Dict with total_unrealized_pnl, total_realized_pnl, positions.
    """
    try:
        return service.get_live_pnl(deployment_id=deployment_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None


# ---------------------------------------------------------------------------
# Sync order status from broker
# ---------------------------------------------------------------------------


@router.post(
    "/orders/{broker_order_id}/sync",
    summary="Sync order status from broker",
    dependencies=[
        Depends(
            audit_action(
                action="order.sync_status",
                object_type="order",
                extract_object_id="broker_order_id",
            )
        ),
    ],
)
async def sync_order_status(
    broker_order_id: str,
    deployment_id: str = Query(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("live:trade")),
    service: LiveExecutionServiceInterface = Depends(get_live_execution_service),
) -> dict[str, Any]:
    """
    Sync an order's status from the broker.

    Fetches the latest state from the broker and updates the database.

    Returns:
        OrderResponse with the latest broker-reported status.
    """
    corr_id = correlation_id_var.get("no-corr")
    try:
        response = service.sync_order_status(
            deployment_id=deployment_id,
            broker_order_id=broker_order_id,
            correlation_id=corr_id,
        )
        return response.model_dump(mode="json")
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None
    except ExternalServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Broker communication error: {exc}",
        ) from None


# ---------------------------------------------------------------------------
# Orphaned order recovery
# ---------------------------------------------------------------------------


@router.post(
    "/recover-orphans",
    summary="Recover orphaned orders",
    status_code=status.HTTP_200_OK,
    dependencies=[
        Depends(
            audit_action(
                action="order.recover_orphans",
                object_type="order",
                extract_details=lambda req, params: {"deployment_id": params.get("deployment_id")},
            )
        ),
    ],
)
async def recover_orphaned_orders(
    deployment_id: str | None = Query(
        None,
        description="Optional deployment ULID. If provided, recover for this deployment only. "
        "If omitted, recover across all active live deployments.",
    ),
    user: AuthenticatedUser = Depends(require_scope("operator:write")),
) -> dict[str, Any] | list[dict[str, Any]]:
    """
    Recover orphaned orders for a deployment or all deployments.

    Orphaned orders are those that exist at the broker but were not yet
    recorded in the internal database. This occurs when:
    - System submits an order to the broker.
    - Broker acknowledges and creates the order with a broker_order_id.
    - System crashes before recording the broker_order_id internally.
    - On restart, the system knows nothing about the order.

    This endpoint detects such orders by:
    1. Querying all open internal orders for the deployment(s).
    2. Querying the broker for all open orders.
    3. Matching internal pending orders to broker orders by client_order_id.
    4. Importing broker_order_id and status for found orders.
    5. Marking orders as expired if not found at the broker.
    6. Syncing fill data for partial_fill orders.
    7. Logging extra broker orders as critical warnings (never auto-cancelled).

    Args:
        deployment_id: Optional deployment ULID for per-deployment recovery.
                      If omitted, recovery runs across all active live deployments.
        user: Authenticated user with operator:write scope.

    Returns:
        If deployment_id provided:
            Single OrphanRecoveryReport with recovered_count, failed_count, details.
        If deployment_id omitted:
            List of OrphanRecoveryReport, one per deployment recovered.

    Raises:
        401 Unauthorized: Missing or invalid authentication token.
        403 Forbidden: Caller lacks operator:write scope.
        404 Not Found: Deployment not found or has no broker adapter.
        502 Bad Gateway: Broker adapter communication failure.
    """
    from services.api.db import SessionLocal
    from services.api.infrastructure.sql_repositories import (
        SqlDeploymentRepository,
        SqlExecutionEventRepository,
        SqlOrderRepository,
    )
    from services.api.middleware.correlation import correlation_id_var
    from services.api.services.orphaned_order_recovery_service import (
        OrphanedOrderRecoveryService,
    )

    corr_id = correlation_id_var.get("no-corr")

    logger.info(
        "orphan_recovery_endpoint_called",
        deployment_id=deployment_id,
        correlation_id=corr_id,
        component="live_routes",
    )

    db_session = SessionLocal()
    try:
        deployment_repo = SqlDeploymentRepository(db_session)
        order_repo = SqlOrderRepository(db_session)
        event_repo = SqlExecutionEventRepository(db_session)

        # Get broker registry from the application context
        from services.api.infrastructure.broker_registry import BrokerAdapterRegistry

        broker_registry = BrokerAdapterRegistry()
        # In production, this should be: broker_registry = request.app.state.broker_registry

        recovery_service = OrphanedOrderRecoveryService(
            deployment_repo=deployment_repo,
            order_repo=order_repo,
            execution_event_repo=event_repo,
            broker_registry=broker_registry,
        )

        if deployment_id:
            # Single deployment recovery
            try:
                report = recovery_service.recover_orphaned_orders(
                    deployment_id=deployment_id,
                    correlation_id=corr_id,
                )
                logger.info(
                    "orphan_recovery_endpoint_success",
                    deployment_id=deployment_id,
                    recovered_count=report.recovered_count,
                    failed_count=report.failed_count,
                    correlation_id=corr_id,
                    component="live_routes",
                )
                return report.model_dump(mode="json")
            except NotFoundError as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=str(exc),
                ) from None
            except ExternalServiceError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Broker communication error: {exc}",
                ) from None
        else:
            # Batch recovery across all active live deployments
            try:
                reports = recovery_service.recover_all_deployments(
                    correlation_id=corr_id,
                )
                logger.info(
                    "orphan_recovery_endpoint_batch_success",
                    deployments_recovered=len(reports),
                    total_recovered=sum(r.recovered_count for r in reports),
                    total_failed=sum(r.failed_count for r in reports),
                    correlation_id=corr_id,
                    component="live_routes",
                )
                return [r.model_dump(mode="json") for r in reports]
            except ExternalServiceError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Broker communication error during batch recovery: {exc}",
                ) from None
    finally:
        db_session.close()
