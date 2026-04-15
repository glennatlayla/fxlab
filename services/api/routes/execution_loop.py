"""
Execution loop REST API routes (M8).

Responsibilities:
- Expose execution loop management through REST endpoints.
- Start, stop, pause, resume loops via ExecutionLoopManager.
- Retrieve diagnostics for individual and all loops.
- List active loops with their current state.
- Enforce authentication and scope requirements.

Does NOT:
- Implement loop logic (StrategyExecutionEngine does that).
- Manage the loop registry (ExecutionLoopManager does that).
- Define contracts (libs.contracts.execution_loop).

Dependencies:
- services.api.infrastructure.execution_loop_manager: ExecutionLoopManager
- libs.contracts.execution_loop: ExecutionLoopConfig, LoopDiagnostics
- services.api.auth: get_current_user, require_scope

Endpoints:
    POST   /execution/loops                        — Start a new execution loop
    DELETE /execution/loops/{deployment_id}         — Stop an execution loop
    PUT    /execution/loops/{deployment_id}/pause   — Pause
    PUT    /execution/loops/{deployment_id}/resume  — Resume
    GET    /execution/loops/{deployment_id}/diagnostics — Loop diagnostics
    GET    /execution/loops                         — List all active loops
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from libs.contracts.execution import ExecutionMode
from libs.contracts.execution_loop import (
    ExecutionLoopConfig,
    InvalidStateTransitionError,
)
from libs.contracts.market_data import CandleInterval
from services.api.auth import get_current_user, require_scope

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/execution/loops", tags=["execution-loops"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class StartLoopRequest(BaseModel):
    """Request body for starting a new execution loop."""

    deployment_id: str = Field(..., min_length=1, max_length=128)
    strategy_id: str = Field(..., min_length=1, max_length=128)
    signal_strategy_id: str = Field(..., min_length=1, max_length=128)
    symbols: list[str] = Field(..., min_length=1)
    interval: CandleInterval
    execution_mode: ExecutionMode
    max_positions_per_symbol: int = Field(default=1, ge=1, le=100)
    cooldown_after_trade_s: int = Field(default=60, ge=0)
    max_consecutive_errors: int = Field(default=5, ge=1, le=100)
    health_check_interval_s: int = Field(default=30, ge=5)


class LoopStatusResponse(BaseModel):
    """Response model for loop status."""

    deployment_id: str
    state: str
    bars_processed: int = 0
    signals_generated: int = 0
    signals_approved: int = 0
    signals_rejected: int = 0
    orders_submitted: int = 0
    orders_filled: int = 0
    errors: int = 0
    uptime_seconds: float = 0.0
    consecutive_errors: int = 0


class LoopListResponse(BaseModel):
    """Response model for listing all active loops."""

    loops: list[LoopStatusResponse]
    total: int


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str
    deployment_id: str


# ---------------------------------------------------------------------------
# Helper: get manager from app state
# ---------------------------------------------------------------------------


def _get_manager(request: Request) -> Any:
    """
    Retrieve ExecutionLoopManager from app state.

    Raises:
        HTTPException 503 if manager is not initialised.
    """
    manager = getattr(request.app.state, "execution_loop_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=503,
            detail="Execution loop manager not initialised",
        )
    return manager


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=MessageResponse,
    status_code=201,
    dependencies=[Depends(get_current_user), Depends(require_scope("operator:write"))],
)
async def start_loop(
    body: StartLoopRequest,
    request: Request,
) -> MessageResponse:
    """
    Start a new execution loop for a deployment.

    Requires operator:write scope.

    Args:
        body: Loop configuration.
        request: FastAPI request (for accessing app state).

    Returns:
        MessageResponse confirming the loop was started.

    Raises:
        409: If a loop already exists for the deployment.
        503: If the loop manager is not initialised.
    """
    manager = _get_manager(request)

    config = ExecutionLoopConfig(
        deployment_id=body.deployment_id,
        strategy_id=body.strategy_id,
        signal_strategy_id=body.signal_strategy_id,
        symbols=body.symbols,
        interval=body.interval,
        execution_mode=body.execution_mode,
        max_positions_per_symbol=body.max_positions_per_symbol,
        cooldown_after_trade_s=body.cooldown_after_trade_s,
        max_consecutive_errors=body.max_consecutive_errors,
        health_check_interval_s=body.health_check_interval_s,
    )

    # Create and start the engine.
    # The factory function on the manager creates the engine with proper DI.
    factory = getattr(request.app.state, "execution_engine_factory", None)
    if factory is None:
        raise HTTPException(
            status_code=503,
            detail="Execution engine factory not configured",
        )

    try:
        engine = factory(config)
        engine.start(config)
        manager.register(config.deployment_id, engine)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    logger.info(
        "Execution loop started via API",
        deployment_id=config.deployment_id,
        execution_mode=config.execution_mode.value,
    )

    return MessageResponse(
        message=f"Loop started for deployment {config.deployment_id}",
        deployment_id=config.deployment_id,
    )


@router.delete(
    "/{deployment_id}",
    response_model=MessageResponse,
    dependencies=[Depends(get_current_user), Depends(require_scope("operator:write"))],
)
async def stop_loop(
    deployment_id: str,
    request: Request,
) -> MessageResponse:
    """
    Stop an execution loop.

    Args:
        deployment_id: The deployment to stop.
        request: FastAPI request.

    Returns:
        MessageResponse confirming the loop was stopped.

    Raises:
        404: If no loop exists for the deployment.
        409: If the loop cannot be stopped (invalid state).
    """
    manager = _get_manager(request)

    try:
        loop = manager.get(deployment_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        loop.stop()
        manager.unregister(deployment_id)
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    logger.info("Execution loop stopped via API", deployment_id=deployment_id)

    return MessageResponse(
        message=f"Loop stopped for deployment {deployment_id}",
        deployment_id=deployment_id,
    )


@router.put(
    "/{deployment_id}/pause",
    response_model=MessageResponse,
    dependencies=[Depends(get_current_user), Depends(require_scope("operator:write"))],
)
async def pause_loop(
    deployment_id: str,
    request: Request,
) -> MessageResponse:
    """
    Pause an execution loop.

    Args:
        deployment_id: The deployment to pause.
        request: FastAPI request.

    Returns:
        MessageResponse confirming the loop was paused.

    Raises:
        404: If no loop exists for the deployment.
        409: If the loop cannot be paused (invalid state).
    """
    manager = _get_manager(request)

    try:
        loop = manager.get(deployment_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        loop.pause()
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    logger.info("Execution loop paused via API", deployment_id=deployment_id)

    return MessageResponse(
        message=f"Loop paused for deployment {deployment_id}",
        deployment_id=deployment_id,
    )


@router.put(
    "/{deployment_id}/resume",
    response_model=MessageResponse,
    dependencies=[Depends(get_current_user), Depends(require_scope("operator:write"))],
)
async def resume_loop(
    deployment_id: str,
    request: Request,
) -> MessageResponse:
    """
    Resume a paused execution loop.

    Args:
        deployment_id: The deployment to resume.
        request: FastAPI request.

    Returns:
        MessageResponse confirming the loop was resumed.

    Raises:
        404: If no loop exists for the deployment.
        409: If the loop cannot be resumed (invalid state).
    """
    manager = _get_manager(request)

    try:
        loop = manager.get(deployment_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        loop.resume()
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    logger.info("Execution loop resumed via API", deployment_id=deployment_id)

    return MessageResponse(
        message=f"Loop resumed for deployment {deployment_id}",
        deployment_id=deployment_id,
    )


@router.get(
    "/{deployment_id}/diagnostics",
    response_model=LoopStatusResponse,
    dependencies=[Depends(get_current_user)],
)
async def get_diagnostics(
    deployment_id: str,
    request: Request,
) -> LoopStatusResponse:
    """
    Get diagnostics for a specific execution loop.

    Args:
        deployment_id: The deployment to query.
        request: FastAPI request.

    Returns:
        LoopStatusResponse with current metrics.

    Raises:
        404: If no loop exists for the deployment.
    """
    manager = _get_manager(request)

    try:
        diag = manager.get_diagnostics(deployment_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return LoopStatusResponse(
        deployment_id=diag.deployment_id,
        state=diag.state.value,
        bars_processed=diag.bars_processed,
        signals_generated=diag.signals_generated,
        signals_approved=diag.signals_approved,
        signals_rejected=diag.signals_rejected,
        orders_submitted=diag.orders_submitted,
        orders_filled=diag.orders_filled,
        errors=diag.errors,
        uptime_seconds=diag.uptime_seconds,
        consecutive_errors=diag.consecutive_errors,
    )


@router.get(
    "",
    response_model=LoopListResponse,
    dependencies=[Depends(get_current_user)],
)
async def list_loops(
    request: Request,
) -> LoopListResponse:
    """
    List all active execution loops with their diagnostics.

    Args:
        request: FastAPI request.

    Returns:
        LoopListResponse with all active loops.
    """
    manager = _get_manager(request)
    all_diag = manager.list_diagnostics()

    loops = [
        LoopStatusResponse(
            deployment_id=d.deployment_id,
            state=d.state.value,
            bars_processed=d.bars_processed,
            signals_generated=d.signals_generated,
            signals_approved=d.signals_approved,
            signals_rejected=d.signals_rejected,
            orders_submitted=d.orders_submitted,
            orders_filled=d.orders_filled,
            errors=d.errors,
            uptime_seconds=d.uptime_seconds,
            consecutive_errors=d.consecutive_errors,
        )
        for d in all_diag
    ]

    return LoopListResponse(loops=loops, total=len(loops))
