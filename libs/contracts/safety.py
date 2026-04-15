"""
Safety control schemas and value objects for kill switches and emergency posture.

Responsibilities:
- Define kill switch scope, status, and activation request contracts.
- Define halt trigger types and halt event records.
- Define emergency posture decision records.
- Provide frozen Pydantic models for type safety and serialization.

Does NOT:
- Implement kill switch logic (service responsibility).
- Execute emergency postures (service responsibility).
- Persist events (repository responsibility).

Dependencies:
- pydantic: BaseModel, Field.
- Standard library: datetime, enum.
- libs.contracts.deployment: EmergencyPostureType.

Example:
    event = KillSwitchActivateRequest(
        scope=KillSwitchScope.STRATEGY,
        target_id="01HSTRAT...",
        reason="Daily loss limit breached",
        activated_by="system:risk_gate",
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from libs.contracts.deployment import EmergencyPostureType


class KillSwitchScope(str, Enum):  # noqa: UP042
    """Scope of a kill switch activation."""

    GLOBAL = "global"
    STRATEGY = "strategy"
    SYMBOL = "symbol"


class HaltTrigger(str, Enum):  # noqa: UP042
    """What triggered a halt event."""

    KILL_SWITCH = "kill_switch"
    DAILY_LOSS = "daily_loss"
    REGIME = "regime"
    DATA_STATE = "data_state"
    MANUAL = "manual"


class KillSwitchStatus(BaseModel):
    """
    Current state of a kill switch at a specific scope+target.

    Example:
        status = KillSwitchStatus(
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            is_active=True,
            activated_at=datetime(2026, 4, 11, 10, 0, 0),
            activated_by="system:risk_gate",
            reason="Emergency halt triggered",
        )
    """

    model_config = {"frozen": True}

    scope: KillSwitchScope = Field(..., description="Kill switch scope.")
    target_id: str = Field(..., description="Target identifier (strategy_id, symbol, or 'global').")
    is_active: bool = Field(..., description="Whether the kill switch is currently active.")
    activated_at: datetime | None = Field(
        default=None, description="When the kill switch was activated."
    )
    deactivated_at: datetime | None = Field(
        default=None, description="When the kill switch was deactivated."
    )
    activated_by: str | None = Field(default=None, description="Who activated the kill switch.")
    reason: str | None = Field(default=None, description="Activation reason.")


class KillSwitchActivateRequest(BaseModel):
    """
    Request to activate a kill switch.

    Example:
        req = KillSwitchActivateRequest(
            scope=KillSwitchScope.STRATEGY,
            target_id="01HSTRAT...",
            reason="Daily loss limit breached",
            activated_by="system:risk_gate",
        )
    """

    model_config = {"frozen": True}

    scope: KillSwitchScope = Field(..., description="Kill switch scope.")
    target_id: str = Field(..., description="Target identifier (strategy_id, symbol, or 'global').")
    reason: str = Field(..., min_length=1, description="Activation reason.")
    activated_by: str = Field(..., min_length=1, description="Identity of activator.")


class HaltEvent(BaseModel):
    """
    Recorded halt event with trigger, scope, and MTTH measurement.

    The halt event captures the complete lifecycle from activation through
    confirmation that all affected orders have been cancelled.

    Example:
        event = HaltEvent(
            event_id="01HHALT...",
            scope=KillSwitchScope.GLOBAL,
            target_id="global",
            trigger=HaltTrigger.DAILY_LOSS,
            reason="Daily loss limit of $5000 breached",
            activated_by="system:risk_gate",
            activated_at=datetime(2026, 4, 11, 10, 0, 0),
            confirmed_at=datetime(2026, 4, 11, 10, 0, 0, 250000),
            mtth_ms=250,
            orders_cancelled=5,
        )
    """

    model_config = {"frozen": True}

    event_id: str = Field(..., description="ULID of the halt event.")
    scope: KillSwitchScope = Field(..., description="Kill switch scope.")
    target_id: str = Field(..., description="Target identifier.")
    trigger: HaltTrigger = Field(..., description="What triggered this halt.")
    reason: str = Field(..., description="Human-readable reason.")
    activated_by: str = Field(..., description="Identity of activator.")
    activated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the halt was triggered.",
    )
    confirmed_at: datetime | None = Field(
        default=None,
        description="When all affected orders were confirmed cancelled.",
    )
    mtth_ms: int | None = Field(
        default=None,
        description="Mean Time To Halt in milliseconds.",
    )
    orders_cancelled: int = Field(default=0, description="Number of orders cancelled.")
    positions_flattened: int = Field(default=0, description="Number of positions flattened.")


class EmergencyPostureDecision(BaseModel):
    """
    Record of an emergency posture execution for a deployment.

    Captures what posture was executed, how many orders/positions
    were affected, and the timing.

    Example:
        decision = EmergencyPostureDecision(
            decision_id="01HEPDEC...",
            deployment_id="01HDEPLOY...",
            posture=EmergencyPostureType.FLATTEN_ALL,
            trigger=HaltTrigger.KILL_SWITCH,
            orders_cancelled=3,
            positions_flattened=2,
            executed_at=datetime(2026, 4, 11, 10, 0, 0),
            duration_ms=150,
        )
    """

    model_config = {"frozen": True}

    decision_id: str = Field(..., description="ULID of the decision.")
    deployment_id: str = Field(..., description="ULID of the deployment.")
    posture: EmergencyPostureType = Field(
        ..., description="The emergency posture that was executed."
    )
    trigger: HaltTrigger = Field(..., description="What triggered the posture.")
    reason: str = Field(default="", description="Human-readable reason.")
    orders_cancelled: int = Field(default=0, description="Number of orders cancelled.")
    positions_flattened: int = Field(default=0, description="Number of positions flattened.")
    executed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the posture was executed.",
    )
    duration_ms: int = Field(default=0, ge=0, description="Execution duration in milliseconds.")
    verification: EmergencyPostureVerification | None = Field(
        default=None,
        description="Post-execution verification result, if verification was performed.",
    )


class EmergencyPostureVerification(BaseModel):
    """
    Result of post-execution verification of emergency posture.

    After executing an emergency posture (flatten_all or cancel_open), the
    system polls broker positions to verify that the actions took effect.
    This schema captures whether all positions were actually closed, what
    residual exposure remains, and how long verification took.

    Responsibilities:
    - Record positions that were confirmed closed.
    - Record positions that failed to close with their current quantities.
    - Calculate aggregate residual exposure in USD.

    Does NOT:
    - Execute the verification (service responsibility).
    - Decide on escalation actions.

    Example:
        verification = EmergencyPostureVerification(
            verified=False,
            positions_closed=3,
            positions_failed=[
                {"symbol": "TSLA", "quantity": "50", "market_value": "8750.00"}
            ],
            residual_exposure_usd=Decimal("8750.00"),
            timeout_s=30,
            verification_duration_ms=30150,
        )
    """

    model_config = {"frozen": True}

    verified: bool = Field(
        ...,
        description="True if all positions are flat after verification.",
    )
    positions_closed: int = Field(
        default=0,
        description="Number of positions confirmed closed during verification.",
    )
    positions_failed: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Positions that remain open after verification timeout. "
            "Each dict contains: symbol, quantity, market_value."
        ),
    )
    residual_exposure_usd: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Sum of abs(market_value) for positions that failed to close.",
    )
    timeout_s: int = Field(
        default=30,
        ge=1,
        description="Verification timeout that was used (seconds).",
    )
    verification_duration_ms: int = Field(
        default=0,
        ge=0,
        description="Time spent in the verification loop (milliseconds).",
    )
