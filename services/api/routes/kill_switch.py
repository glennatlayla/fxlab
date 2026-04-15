"""
Kill switch API endpoints.

Responsibilities:
- Expose kill switch activation/deactivation endpoints per scope.
- Expose status query endpoint.
- Expose emergency posture execution endpoint.
- Delegate all business logic to KillSwitchService.
- Map domain errors to HTTP status codes.

Does NOT:
- Contain kill switch logic.
- Access adapters or repositories directly.

Dependencies:
- KillSwitchServiceInterface (injected via module-level DI).
- libs.contracts.safety schemas.

Error conditions:
- 404 Not Found: no active kill switch for deactivation, deployment not found.
- 409 Conflict: kill switch already active.
- 422 Unprocessable Entity: invalid request body.

Example:
    POST /kill-switch/global            → 200 {halt_event}
    POST /kill-switch/strategy/{id}     → 200 {halt_event}
    POST /kill-switch/symbol/{symbol}   → 200 {halt_event}
    DELETE /kill-switch/{scope}/{target} → 200 {halt_event}
    GET /kill-switch/status             → 200 [{status}]
    POST /kill-switch/emergency-posture/{deployment_id} → 200 {decision}
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from libs.contracts.errors import NotFoundError, StateTransitionError
from libs.contracts.interfaces.kill_switch_service_interface import (
    KillSwitchServiceInterface,
)
from libs.contracts.safety import (
    EmergencyPostureDecision,
    HaltEvent,
    HaltTrigger,
    KillSwitchScope,
    KillSwitchStatus,
)
from services.api.auth import require_scope
from services.api.middleware.audit_trail import audit_action
from services.api.middleware.rate_limit import rate_limit

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Module-level DI
# ---------------------------------------------------------------------------

_kill_switch_service: KillSwitchServiceInterface | None = None


def set_kill_switch_service(service: KillSwitchServiceInterface) -> None:
    """
    Inject the kill switch service implementation.

    Args:
        service: KillSwitchServiceInterface implementation.
    """
    global _kill_switch_service
    _kill_switch_service = service


def get_kill_switch_service() -> KillSwitchServiceInterface:
    """
    Retrieve the injected kill switch service.

    Returns:
        The configured KillSwitchServiceInterface.

    Raises:
        RuntimeError: if no service has been injected.
    """
    if _kill_switch_service is None:
        raise RuntimeError(
            "KillSwitchService not configured. Call set_kill_switch_service() during app bootstrap."
        )
    return _kill_switch_service


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ActivateKillSwitchBody(BaseModel):
    """Request body for kill switch activation."""

    reason: str = Field(..., min_length=1, description="Activation reason.")
    activated_by: str = Field(..., min_length=1, description="Identity of activator.")
    trigger: HaltTrigger = Field(
        default=HaltTrigger.KILL_SWITCH,
        description="What triggered this activation.",
    )


class EmergencyPostureBody(BaseModel):
    """Request body for emergency posture execution."""

    trigger: HaltTrigger = Field(..., description="What triggered the posture execution.")
    reason: str = Field(..., min_length=1, description="Human-readable reason.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _halt_event_to_dict(event: HaltEvent) -> dict:
    """Convert a HaltEvent to a JSON-serializable dict."""
    return {
        "event_id": event.event_id,
        "scope": event.scope.value,
        "target_id": event.target_id,
        "trigger": event.trigger.value,
        "reason": event.reason,
        "activated_by": event.activated_by,
        "activated_at": event.activated_at.isoformat(),
        "confirmed_at": (event.confirmed_at.isoformat() if event.confirmed_at else None),
        "mtth_ms": event.mtth_ms,
        "orders_cancelled": event.orders_cancelled,
        "positions_flattened": event.positions_flattened,
    }


def _status_to_dict(status: KillSwitchStatus) -> dict:
    """Convert a KillSwitchStatus to a JSON-serializable dict."""
    return {
        "scope": status.scope.value,
        "target_id": status.target_id,
        "is_active": status.is_active,
        "activated_at": (status.activated_at.isoformat() if status.activated_at else None),
        "deactivated_at": (status.deactivated_at.isoformat() if status.deactivated_at else None),
        "activated_by": status.activated_by,
        "reason": status.reason,
    }


def _decision_to_dict(decision: EmergencyPostureDecision) -> dict:
    """Convert an EmergencyPostureDecision to a JSON-serializable dict."""
    return {
        "decision_id": decision.decision_id,
        "deployment_id": decision.deployment_id,
        "posture": decision.posture.value,
        "trigger": decision.trigger.value,
        "reason": decision.reason,
        "orders_cancelled": decision.orders_cancelled,
        "positions_flattened": decision.positions_flattened,
        "executed_at": decision.executed_at.isoformat(),
        "duration_ms": decision.duration_ms,
    }


# ---------------------------------------------------------------------------
# Activation endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/global",
    dependencies=[
        Depends(require_scope("deployments:write")),
        Depends(rate_limit(max_requests=3, window_seconds=60, scope="kill_switch")),
        Depends(
            audit_action(
                action="kill_switch.activate_global",
                object_type="kill_switch",
                extract_object_id=lambda req, params: "global",
            )
        ),
    ],
)
def activate_global(body: ActivateKillSwitchBody) -> dict:
    """
    Activate the global kill switch.

    Cancels all open orders across all deployments.
    """
    service = get_kill_switch_service()
    try:
        event = service.activate_kill_switch(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            reason=body.reason,
            activated_by=body.activated_by,
            trigger=body.trigger,
        )
    except StateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _halt_event_to_dict(event)


@router.post(
    "/strategy/{strategy_id}",
    dependencies=[
        Depends(require_scope("deployments:write")),
        Depends(rate_limit(max_requests=3, window_seconds=60, scope="kill_switch")),
        Depends(
            audit_action(
                action="kill_switch.activate_strategy",
                object_type="kill_switch",
                extract_object_id="strategy_id",
            )
        ),
    ],
)
def activate_strategy(strategy_id: str, body: ActivateKillSwitchBody) -> dict:
    """Activate a strategy-scoped kill switch."""
    service = get_kill_switch_service()
    try:
        event = service.activate_kill_switch(
            scope=KillSwitchScope.STRATEGY,
            target_id=strategy_id,
            reason=body.reason,
            activated_by=body.activated_by,
            trigger=body.trigger,
        )
    except StateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _halt_event_to_dict(event)


@router.post(
    "/symbol/{symbol}",
    dependencies=[
        Depends(require_scope("deployments:write")),
        Depends(rate_limit(max_requests=3, window_seconds=60, scope="kill_switch")),
        Depends(
            audit_action(
                action="kill_switch.activate_symbol",
                object_type="kill_switch",
                extract_object_id="symbol",
            )
        ),
    ],
)
def activate_symbol(symbol: str, body: ActivateKillSwitchBody) -> dict:
    """Activate a symbol-scoped kill switch."""
    service = get_kill_switch_service()
    try:
        event = service.activate_kill_switch(
            scope=KillSwitchScope.SYMBOL,
            target_id=symbol,
            reason=body.reason,
            activated_by=body.activated_by,
            trigger=body.trigger,
        )
    except StateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _halt_event_to_dict(event)


# ---------------------------------------------------------------------------
# Deactivation endpoint
# ---------------------------------------------------------------------------


@router.delete(
    "/{scope}/{target_id}",
    dependencies=[
        Depends(require_scope("deployments:write")),
        Depends(
            audit_action(
                action="kill_switch.deactivate",
                object_type="kill_switch",
                extract_object_id="target_id",
            )
        ),
    ],
)
def deactivate_kill_switch(scope: str, target_id: str) -> dict:
    """
    Deactivate a kill switch at the given scope and target.

    Args:
        scope: One of 'global', 'strategy', 'symbol'.
        target_id: Target identifier.
    """
    service = get_kill_switch_service()
    try:
        ks_scope = KillSwitchScope(scope)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid scope: {scope}. Must be global, strategy, or symbol.",
        ) from exc
    try:
        event = service.deactivate_kill_switch(
            scope=ks_scope,
            target_id=target_id,
            deactivated_by="api",
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _halt_event_to_dict(event)


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/status",
    dependencies=[Depends(require_scope("deployments:read"))],
)
def get_status() -> list[dict]:
    """Get all active kill switch statuses."""
    service = get_kill_switch_service()
    statuses = service.get_status()
    return [_status_to_dict(s) for s in statuses]


# ---------------------------------------------------------------------------
# Emergency posture endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/emergency-posture/{deployment_id}",
    dependencies=[
        Depends(require_scope("deployments:write")),
        Depends(
            audit_action(
                action="kill_switch.execute_emergency_posture",
                object_type="kill_switch",
                extract_object_id="deployment_id",
            )
        ),
    ],
)
def execute_emergency_posture(
    deployment_id: str,
    body: EmergencyPostureBody,
) -> dict:
    """
    Execute the declared emergency posture for a deployment.

    Args:
        deployment_id: ULID of the deployment.
        body: Request body with trigger and reason.
    """
    service = get_kill_switch_service()
    try:
        decision = service.execute_emergency_posture(
            deployment_id=deployment_id,
            trigger=body.trigger,
            reason=body.reason,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _decision_to_dict(decision)
