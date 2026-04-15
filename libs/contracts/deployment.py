"""
Deployment state machine Pydantic schemas for Phase 4 execution layer.

Responsibilities:
- Define the DeploymentState enum with all valid deployment lifecycle states.
- Define valid state transitions via DEPLOYMENT_TRANSITIONS mapping.
- Provide Pydantic schemas for deployment create, health, and transition payloads.
- Declare emergency posture types (flatten_all, cancel_open, hold, custom).

Does NOT:
- Enforce state transitions (service layer responsibility).
- Persist deployment records (repository layer responsibility).
- Know about HTTP, queues, or infrastructure.

Dependencies:
- libs.contracts.execution: ExecutionMode enum.
- Pydantic v2 for schema validation.

Error conditions:
- Pydantic ValidationError for malformed payloads.

Example:
    from libs.contracts.deployment import (
        DeploymentState,
        DeploymentCreateRequest,
        EmergencyPosture,
        is_valid_transition,
    )
    req = DeploymentCreateRequest(
        strategy_id="01HSTRAT...",
        execution_mode="paper",
        emergency_posture="flatten_all",
    )
    assert is_valid_transition(DeploymentState.approved, DeploymentState.activating)
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DeploymentState(str, Enum):
    """
    Deployment lifecycle state machine states.

    State machine flow:
        created → pending_approval → approved → activating → active
        active ↔ frozen
        active → deactivating → deactivated
        any error state → failed
        active/frozen → rolled_back
    """

    created = "created"
    pending_approval = "pending_approval"
    approved = "approved"
    activating = "activating"
    active = "active"
    frozen = "frozen"
    deactivating = "deactivating"
    deactivated = "deactivated"
    rolled_back = "rolled_back"
    failed = "failed"


class EmergencyPostureType(str, Enum):
    """
    Declared emergency posture for a deployment.

    Determines what happens when a kill switch fires:
    - flatten_all: Close all open positions immediately.
    - cancel_open: Cancel all pending orders, keep existing positions.
    - hold: Do nothing; human must intervene.
    - custom: Strategy-specific logic (requires custom_posture_config).
    """

    flatten_all = "flatten_all"
    cancel_open = "cancel_open"
    hold = "hold"
    custom = "custom"


# ---------------------------------------------------------------------------
# State transition map — the authoritative definition of valid transitions
# ---------------------------------------------------------------------------

# Keys: source state. Values: set of allowed target states.
DEPLOYMENT_TRANSITIONS: dict[DeploymentState, frozenset[DeploymentState]] = {
    DeploymentState.created: frozenset({DeploymentState.pending_approval, DeploymentState.failed}),
    DeploymentState.pending_approval: frozenset({DeploymentState.approved, DeploymentState.failed}),
    DeploymentState.approved: frozenset({DeploymentState.activating, DeploymentState.failed}),
    DeploymentState.activating: frozenset({DeploymentState.active, DeploymentState.failed}),
    DeploymentState.active: frozenset(
        {
            DeploymentState.frozen,
            DeploymentState.deactivating,
            DeploymentState.rolled_back,
            DeploymentState.failed,
        }
    ),
    DeploymentState.frozen: frozenset(
        {
            DeploymentState.active,  # unfreeze
            DeploymentState.deactivating,
            DeploymentState.rolled_back,
            DeploymentState.failed,
        }
    ),
    DeploymentState.deactivating: frozenset({DeploymentState.deactivated, DeploymentState.failed}),
    # Terminal states — no outbound transitions
    DeploymentState.deactivated: frozenset(),
    DeploymentState.rolled_back: frozenset(),
    DeploymentState.failed: frozenset(),
}


def is_valid_transition(from_state: DeploymentState, to_state: DeploymentState) -> bool:
    """
    Check whether a state transition is valid per the deployment state machine.

    Args:
        from_state: Current deployment state.
        to_state: Proposed target state.

    Returns:
        True if the transition is allowed, False otherwise.

    Example:
        >>> is_valid_transition(DeploymentState.approved, DeploymentState.activating)
        True
        >>> is_valid_transition(DeploymentState.deactivated, DeploymentState.active)
        False
    """
    allowed = DEPLOYMENT_TRANSITIONS.get(from_state, frozenset())
    return to_state in allowed


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class RiskLimits(BaseModel):
    """
    Risk limits applied to a deployment.

    Responsibilities:
    - Declare maximum position size, daily loss, and order rate limits.
    - Provide sane defaults for paper-mode deployments.

    Example:
        limits = RiskLimits(max_position_size="10000", max_daily_loss="5000")
    """

    model_config = {"frozen": True}

    max_position_size: str = Field(
        default="0",
        description="Maximum position size in base currency (string for precision).",
    )
    max_daily_loss: str = Field(
        default="0",
        description="Maximum daily loss threshold before kill switch triggers (string for precision).",
    )
    max_order_rate_per_minute: int = Field(
        default=60,
        description="Maximum orders per minute before rate-limiting.",
        ge=1,
        le=10000,
    )
    max_notional_per_order: str = Field(
        default="0",
        description="Maximum notional value per single order (string for precision).",
    )


class DeploymentCreateRequest(BaseModel):
    """
    Request payload for creating a new deployment.

    Responsibilities:
    - Validate strategy_id, execution_mode, emergency_posture, and risk_limits.
    - Ensure emergency posture is declared at creation time (spec rule 6).

    Does NOT:
    - Enforce approval gates or readiness checks (service layer).

    Example:
        req = DeploymentCreateRequest(
            strategy_id="01HSTRAT...",
            execution_mode="paper",
            emergency_posture="flatten_all",
        )
    """

    model_config = {"frozen": True}

    strategy_id: str = Field(
        ...,
        min_length=26,
        max_length=26,
        description="ULID of the strategy to deploy.",
    )
    execution_mode: str = Field(
        ...,
        description="Execution mode: 'shadow', 'paper', or 'live'.",
    )
    emergency_posture: str = Field(
        ...,
        description="Emergency posture: 'flatten_all', 'cancel_open', 'hold', or 'custom'.",
    )
    risk_limits: RiskLimits = Field(
        default_factory=RiskLimits,
        description="Risk limits for this deployment.",
    )
    custom_posture_config: dict[str, Any] | None = Field(
        default=None,
        description="Custom posture configuration (required when emergency_posture='custom').",
    )

    @model_validator(mode="after")
    def _validate_execution_mode_and_posture(self) -> DeploymentCreateRequest:
        """Validate execution_mode enum and custom posture config requirement."""
        valid_modes = {"shadow", "paper", "live"}
        if self.execution_mode not in valid_modes:
            raise ValueError(
                f"execution_mode must be one of {valid_modes}, got '{self.execution_mode}'"
            )
        valid_postures = {"flatten_all", "cancel_open", "hold", "custom"}
        if self.emergency_posture not in valid_postures:
            raise ValueError(
                f"emergency_posture must be one of {valid_postures}, got '{self.emergency_posture}'"
            )
        if self.emergency_posture == "custom" and not self.custom_posture_config:
            raise ValueError("custom_posture_config is required when emergency_posture='custom'")
        return self


class DeploymentTransitionRecord(BaseModel):
    """
    Immutable record of a deployment state transition for audit purposes.

    Responsibilities:
    - Capture from_state, to_state, actor, reason, and timestamp.

    Example:
        record = DeploymentTransitionRecord(
            from_state="approved",
            to_state="activating",
            actor="user:01HUSER...",
            reason="Manual activation",
            timestamp="2026-04-11T10:00:00Z",
        )
    """

    model_config = {"frozen": True}

    from_state: str
    to_state: str
    actor: str = Field(description="Identity string (e.g. 'user:<ulid>' or 'system').")
    reason: str = Field(description="Human-readable reason for the transition.")
    timestamp: str = Field(description="ISO-8601 timestamp of the transition.")


class DeploymentHealthResponse(BaseModel):
    """
    Live health summary for an active deployment.

    Responsibilities:
    - Aggregate real-time deployment health metrics.
    - Include position summary, P&L, order counts, and adapter status.

    Example:
        health = DeploymentHealthResponse(
            deployment_id="01HDEPLOY...",
            state="active",
            execution_mode="paper",
            ...
        )
    """

    model_config = {"frozen": True}

    deployment_id: str
    state: str
    execution_mode: str
    emergency_posture: str
    open_order_count: int = 0
    position_count: int = 0
    total_unrealized_pnl: str = "0"
    total_realized_pnl: str = "0"
    adapter_connected: bool = False
    last_heartbeat_at: str | None = None
    risk_limits: RiskLimits = Field(default_factory=RiskLimits)


class DeploymentResponse(BaseModel):
    """
    API response for a deployment record.

    Responsibilities:
    - Serialise deployment data for API consumers.

    Example:
        resp = DeploymentResponse(
            id="01HDEPLOY...",
            strategy_id="01HSTRAT...",
            state="active",
            ...
        )
    """

    model_config = {"frozen": True}

    id: str
    strategy_id: str
    state: str
    execution_mode: str
    emergency_posture: str
    risk_limits: RiskLimits = Field(default_factory=RiskLimits)
    custom_posture_config: dict[str, Any] | None = None
    deployed_by: str
    created_at: str
    updated_at: str
