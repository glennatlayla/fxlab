"""
Deployment lifecycle API endpoints.

Responsibilities:
- Expose deployment creation, state transition, and query endpoints.
- Validate request payloads using Pydantic contracts.
- Delegate all business logic to the DeploymentService.
- Map domain errors to HTTP status codes.
- Emit structured log events for audit traceability.

Does NOT:
- Contain business logic or state machine enforcement (service layer).
- Access the database directly (service + repository responsibility).
- Hold module-level DB sessions or singletons.

Dependencies:
- DeploymentService (injected per request via get_deployment_service).
- libs.contracts.deployment: DeploymentCreateRequest, DeploymentHealthResponse.
- structlog for structured logging.

Error conditions:
- 404 Not Found: deployment_id does not exist.
- 409 Conflict: invalid state transition.
- 422 Unprocessable Entity: validation error (e.g. missing emergency posture).
- 400 Bad Request: malformed request body.

Example:
    POST /deployments/paper   → 201 {"id": "...", "state": "created"}
    POST /deployments/{id}/submit-for-approval  → 200 {"state": "pending_approval"}
    POST /deployments/{id}/approve  → 200 {"state": "approved"}
    POST /deployments/{id}/activate → 200 {"state": "active"}
    POST /deployments/{id}/freeze   → 200 {"state": "frozen"}
    POST /deployments/{id}/unfreeze → 200 {"state": "active"}
    POST /deployments/{id}/deactivate → 200 {"state": "deactivated"}
    POST /deployments/{id}/rollback → 200 {"state": "rolled_back"}
    GET  /deployments/{id}          → 200 {deployment record}
    GET  /deployments/{id}/health   → 200 {health summary}
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from libs.contracts.deployment import DeploymentCreateRequest, RiskLimits
from libs.contracts.errors import NotFoundError, StateTransitionError, ValidationError
from libs.contracts.interfaces.deployment_service_interface import (
    DeploymentServiceInterface,
)
from services.api.auth import AuthenticatedUser, require_scope
from services.api.db import get_db
from services.api.middleware.correlation import correlation_id_var
from services.api.repositories.sql_deployment_repository import SqlDeploymentRepository
from services.api.services.deployment_service import DeploymentService

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request schemas (route-level — not in contracts because they're HTTP-only)
# ---------------------------------------------------------------------------


class DeploymentCreateBody(BaseModel):
    """HTTP request body for creating a deployment."""

    strategy_id: str = Field(
        ..., min_length=26, max_length=26, description="ULID of the strategy to deploy."
    )
    emergency_posture: str = Field(
        ..., description="Emergency posture: flatten_all, cancel_open, hold, or custom."
    )
    risk_limits: dict[str, Any] | None = Field(
        default=None, description="Optional risk limits configuration."
    )
    custom_posture_config: dict[str, Any] | None = Field(
        default=None, description="Custom posture config (required when posture='custom')."
    )


class FreezeBody(BaseModel):
    """HTTP request body for freezing a deployment."""

    reason: str = Field(..., min_length=1, description="Human-readable freeze reason.")


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------


def get_deployment_service(
    db: Session = Depends(get_db),
) -> DeploymentServiceInterface:
    """
    Request-scoped dependency provider for DeploymentService.

    Wires the SQL repository with the current DB session and returns
    a fully initialised DeploymentService. No module-level singletons.

    Args:
        db: SQLAlchemy session from get_db().

    Returns:
        DeploymentServiceInterface backed by SQL repository.
    """
    repo = SqlDeploymentRepository(db=db)
    return DeploymentService(repo=repo)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/paper",
    status_code=status.HTTP_201_CREATED,
    summary="Create a paper deployment",
)
async def create_paper_deployment(
    body: DeploymentCreateBody,
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: DeploymentServiceInterface = Depends(get_deployment_service),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Create a new paper-mode deployment.

    Returns 201 with the deployment record in 'created' state.

    Raises:
        422: validation failure (bad strategy_id, missing posture, etc.).
    """
    try:
        # Convert dict to RiskLimits object if provided
        risk_limits = RiskLimits(**body.risk_limits) if body.risk_limits else RiskLimits()
        request = DeploymentCreateRequest(
            strategy_id=body.strategy_id,
            execution_mode="paper",
            emergency_posture=body.emergency_posture,
            risk_limits=risk_limits,
            custom_posture_config=body.custom_posture_config,
        )
        result = service.create_deployment(
            request=request,
            deployed_by=user.user_id,
            correlation_id=correlation_id_var.get(""),
        )
        db.commit()
        logger.info(
            "deployment_create_paper",
            deployment_id=result["id"],
            strategy_id=body.strategy_id,
            user_id=user.user_id,
        )
        return JSONResponse(status_code=201, content=result)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post(
    "/live-limited",
    status_code=status.HTTP_201_CREATED,
    summary="Create a live-limited deployment",
)
async def create_live_deployment(
    body: DeploymentCreateBody,
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: DeploymentServiceInterface = Depends(get_deployment_service),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Create a new live-limited deployment.

    Returns 201 with the deployment record in 'created' state.
    """
    try:
        # Convert dict to RiskLimits object if provided
        risk_limits = RiskLimits(**body.risk_limits) if body.risk_limits else RiskLimits()
        request = DeploymentCreateRequest(
            strategy_id=body.strategy_id,
            execution_mode="live",
            emergency_posture=body.emergency_posture,
            risk_limits=risk_limits,
            custom_posture_config=body.custom_posture_config,
        )
        result = service.create_deployment(
            request=request,
            deployed_by=user.user_id,
            correlation_id=correlation_id_var.get(""),
        )
        db.commit()
        logger.info(
            "deployment_create_live",
            deployment_id=result["id"],
            strategy_id=body.strategy_id,
            user_id=user.user_id,
        )
        return JSONResponse(status_code=201, content=result)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post(
    "/{deployment_id}/submit-for-approval",
    summary="Submit deployment for approval",
)
async def submit_for_approval(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: DeploymentServiceInterface = Depends(get_deployment_service),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Transition deployment from 'created' to 'pending_approval'.

    Returns 200 on success, 404 on not found, 409 on invalid state.
    """
    try:
        result = service.submit_for_approval(
            deployment_id=deployment_id,
            actor=f"user:{user.user_id}",
            correlation_id=correlation_id_var.get(""),
        )
        db.commit()
        return JSONResponse(status_code=200, content=result)
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


@router.post(
    "/{deployment_id}/approve",
    summary="Approve deployment",
)
async def approve_deployment(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:approve")),
    service: DeploymentServiceInterface = Depends(get_deployment_service),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Transition deployment from 'pending_approval' to 'approved'.

    Returns 200 on success, 404 on not found, 409 on invalid state.
    """
    try:
        result = service.approve_deployment(
            deployment_id=deployment_id,
            actor=f"user:{user.user_id}",
            correlation_id=correlation_id_var.get(""),
        )
        db.commit()
        return JSONResponse(status_code=200, content=result)
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


@router.post(
    "/{deployment_id}/activate",
    summary="Activate deployment",
)
async def activate_deployment(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: DeploymentServiceInterface = Depends(get_deployment_service),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Transition deployment from 'approved' to 'active' (via 'activating').

    Pre-activation gates are enforced by the service layer:
    - Emergency posture must be declared.
    - Deployment must be in 'approved' state.

    Returns 200 on success, 404 on not found, 409 on invalid state,
    422 on gate failure.
    """
    try:
        result = service.activate_deployment(
            deployment_id=deployment_id,
            actor=f"user:{user.user_id}",
            correlation_id=correlation_id_var.get(""),
        )
        db.commit()
        return JSONResponse(status_code=200, content=result)
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
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post(
    "/{deployment_id}/freeze",
    summary="Freeze deployment",
)
async def freeze_deployment(
    body: FreezeBody,
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: DeploymentServiceInterface = Depends(get_deployment_service),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Freeze an active deployment — rejects all new order submissions.

    Returns 200 on success, 404 on not found, 409 on invalid state.
    """
    try:
        result = service.freeze_deployment(
            deployment_id=deployment_id,
            reason=body.reason,
            actor=f"user:{user.user_id}",
            correlation_id=correlation_id_var.get(""),
        )
        db.commit()
        return JSONResponse(status_code=200, content=result)
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


@router.post(
    "/{deployment_id}/unfreeze",
    summary="Unfreeze deployment",
)
async def unfreeze_deployment(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: DeploymentServiceInterface = Depends(get_deployment_service),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Unfreeze a frozen deployment — resumes order processing.

    Returns 200 on success, 404 on not found, 409 on invalid state.
    """
    try:
        result = service.unfreeze_deployment(
            deployment_id=deployment_id,
            actor=f"user:{user.user_id}",
            correlation_id=correlation_id_var.get(""),
        )
        db.commit()
        return JSONResponse(status_code=200, content=result)
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


@router.post(
    "/{deployment_id}/deactivate",
    summary="Deactivate deployment",
)
async def deactivate_deployment(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: DeploymentServiceInterface = Depends(get_deployment_service),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Gracefully deactivate a deployment.

    Returns 200 on success, 404 on not found, 409 on invalid state.
    """
    try:
        result = service.deactivate_deployment(
            deployment_id=deployment_id,
            actor=f"user:{user.user_id}",
            correlation_id=correlation_id_var.get(""),
        )
        db.commit()
        return JSONResponse(status_code=200, content=result)
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


@router.post(
    "/{deployment_id}/rollback",
    summary="Rollback deployment",
)
async def rollback_deployment(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:write")),
    service: DeploymentServiceInterface = Depends(get_deployment_service),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Emergency rollback from active/frozen to rolled_back.

    Returns 200 on success, 404 on not found, 409 on invalid state.
    """
    try:
        result = service.rollback_deployment(
            deployment_id=deployment_id,
            actor=f"user:{user.user_id}",
            correlation_id=correlation_id_var.get(""),
        )
        db.commit()
        return JSONResponse(status_code=200, content=result)
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


@router.get(
    "/{deployment_id}",
    summary="Get deployment",
)
async def get_deployment(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: DeploymentServiceInterface = Depends(get_deployment_service),
) -> JSONResponse:
    """
    Retrieve a deployment by ID.

    Returns 200 with deployment record, 404 on not found.
    """
    try:
        result = service.get_deployment(deployment_id=deployment_id)
        return JSONResponse(status_code=200, content=result)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/{deployment_id}/health",
    summary="Get deployment health",
)
async def get_deployment_health(
    deployment_id: str = Path(..., description="Deployment ULID"),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: DeploymentServiceInterface = Depends(get_deployment_service),
) -> JSONResponse:
    """
    Get real-time health summary for a deployment.

    Returns 200 with health metrics, 404 on not found.
    """
    try:
        health = service.get_deployment_health(deployment_id=deployment_id)
        return JSONResponse(status_code=200, content=health.model_dump())
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
