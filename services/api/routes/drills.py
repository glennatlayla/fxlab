"""
Drill execution API endpoints.

Responsibilities:
- Expose drill execution endpoint per deployment.
- Expose live eligibility check endpoint.
- Expose drill history retrieval endpoint.
- Delegate all business logic to DrillService.
- Map domain errors to HTTP status codes.

Does NOT:
- Contain drill execution logic.
- Access adapters or repositories directly.

Dependencies:
- DrillServiceInterface (injected via module-level DI).
- libs.contracts.drill schemas.

Error conditions:
- 404 Not Found: deployment not found.
- 422 Unprocessable Entity: invalid drill type or request body.

Example:
    POST /drills/{deployment_id}/execute       → 200 {drill_result}
    GET  /drills/{deployment_id}/eligibility   → 200 {eligible, missing}
    GET  /drills/{deployment_id}/history       → 200 [{drill_result}]
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from libs.contracts.drill import DrillResult
from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.drill_service_interface import (
    DrillServiceInterface,
)
from services.api.auth import AuthenticatedUser, require_scope

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Module-level DI
# ---------------------------------------------------------------------------

_service: DrillServiceInterface | None = None


def set_drill_service(svc: DrillServiceInterface) -> None:
    """
    Inject the drill service instance.

    Args:
        svc: DrillServiceInterface implementation.
    """
    global _service  # noqa: PLW0603
    _service = svc


def get_drill_service() -> DrillServiceInterface:
    """
    Retrieve the drill service.

    Returns:
        The injected DrillServiceInterface.

    Raises:
        RuntimeError: if no service has been injected.
    """
    if _service is None:
        raise RuntimeError("DrillService not configured")
    return _service


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ExecuteDrillBody(BaseModel):
    """Request body for drill execution."""

    drill_type: str = Field(
        ...,
        description="Type of drill (kill_switch, rollback, reconnect, failover).",
        min_length=1,
    )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _result_to_dict(result: DrillResult) -> dict[str, Any]:
    """
    Serialize a DrillResult to a JSON-compatible dict.

    Args:
        result: DrillResult to serialize.

    Returns:
        Dict suitable for JSON response.
    """
    return {
        "result_id": result.result_id,
        "deployment_id": result.deployment_id,
        "drill_type": result.drill_type.value,
        "passed": result.passed,
        "mtth_ms": result.mtth_ms,
        "timeline": result.timeline,
        "discrepancies": result.discrepancies,
        "details": result.details,
        "executed_at": result.executed_at.isoformat(),
        "duration_ms": result.duration_ms,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{deployment_id}/execute",
    summary="Execute a production readiness drill",
    response_model=None,
)
async def execute_drill(
    deployment_id: str,
    body: ExecuteDrillBody,
    _user: AuthenticatedUser = Depends(require_scope("deployments:read")),
) -> dict[str, Any]:
    """
    Execute a production readiness drill against a deployment.

    Args:
        deployment_id: ULID of the deployment.
        body: Request body with drill type.

    Returns:
        DrillResult as JSON dict.

    Raises:
        HTTPException 404: deployment not found.
        HTTPException 422: invalid drill type.
    """
    svc = get_drill_service()
    try:
        result = svc.execute_drill(
            drill_type=body.drill_type,
            deployment_id=deployment_id,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info(
        "Drill executed via API",
        extra={
            "operation": "execute_drill_api",
            "component": "drill_route",
            "deployment_id": deployment_id,
            "drill_type": body.drill_type,
            "passed": result.passed,
        },
    )
    return _result_to_dict(result)


@router.get(
    "/{deployment_id}/eligibility",
    summary="Check live deployment eligibility",
    response_model=None,
)
async def check_eligibility(
    deployment_id: str,
    _user: AuthenticatedUser = Depends(require_scope("deployments:read")),
) -> dict[str, Any]:
    """
    Check whether a deployment has passed all required drills for live.

    Args:
        deployment_id: ULID of the deployment.

    Returns:
        Dict with eligible bool and missing_requirements list.

    Raises:
        HTTPException 404: deployment not found.
    """
    svc = get_drill_service()
    try:
        eligible, missing = svc.check_live_eligibility(
            deployment_id=deployment_id,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "deployment_id": deployment_id,
        "eligible": eligible,
        "missing_requirements": [
            {
                "drill_type": r.drill_type.value,
                "description": r.description,
                "required": r.required,
            }
            for r in missing
        ],
    }


@router.get(
    "/{deployment_id}/history",
    summary="Get drill execution history",
    response_model=None,
)
async def get_history(
    deployment_id: str,
    _user: AuthenticatedUser = Depends(require_scope("deployments:read")),
) -> list[dict[str, Any]]:
    """
    Retrieve all drill results for a deployment.

    Args:
        deployment_id: ULID of the deployment.

    Returns:
        List of DrillResult dicts.
    """
    svc = get_drill_service()
    results = svc.get_drill_history(deployment_id=deployment_id)
    return [_result_to_dict(r) for r in results]
