"""
Drill execution and production readiness schemas.

Responsibilities:
- Define drill type classification for production readiness verification.
- Define drill result with pass/fail, MTTH, timeline, and discrepancies.
- Define drill requirement for live deployment eligibility gating.

Does NOT:
- Implement drill execution logic (service responsibility).
- Persist drill results (repository/caller responsibility).

Dependencies:
- pydantic: BaseModel, Field.
- Standard library: datetime, decimal, enum.

Example:
    result = DrillResult(
        result_id="01HDRILL001",
        deployment_id="01HDEPLOY001",
        drill_type=DrillType.KILL_SWITCH,
        passed=True,
        mtth_ms=150,
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DrillType(str, Enum):
    """Types of production readiness drills."""

    KILL_SWITCH = "kill_switch"
    ROLLBACK = "rollback"
    RECONNECT = "reconnect"
    FAILOVER = "failover"


class DrillResult(BaseModel):
    """
    Result of a production readiness drill execution.

    Records the outcome of a drill run including pass/fail status,
    mean time to halt (MTTH), execution timeline, and any
    discrepancies found during the drill.

    Example:
        result = DrillResult(
            result_id="01HDRILL001",
            deployment_id="01HDEPLOY001",
            drill_type=DrillType.KILL_SWITCH,
            passed=True,
            mtth_ms=150,
            timeline=["kill_switch_activated", "orders_cancelled", "confirmed"],
        )
    """

    model_config = {"frozen": True}

    result_id: str = Field(..., description="ULID of the drill result.")
    deployment_id: str = Field(..., description="ULID of the deployment tested.")
    drill_type: DrillType = Field(..., description="Type of drill executed.")
    passed: bool = Field(..., description="Whether the drill passed all checks.")
    mtth_ms: int | None = Field(
        default=None,
        description="Mean time to halt in milliseconds (for kill switch drills).",
    )
    timeline: list[str] = Field(
        default_factory=list,
        description="Ordered list of events during drill execution.",
    )
    discrepancies: list[str] = Field(
        default_factory=list,
        description="List of discrepancies found during the drill.",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional drill-specific context.",
    )
    executed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the drill was executed.",
    )
    duration_ms: int = Field(
        default=0,
        description="Total drill execution time in milliseconds.",
    )


class DrillRequirement(BaseModel):
    """
    Prerequisite drill requirement for live deployment eligibility.

    Each requirement specifies a drill type that must have a passing
    result before a deployment can be promoted to live execution.

    Example:
        req = DrillRequirement(
            drill_type=DrillType.KILL_SWITCH,
            description="Kill switch activation and MTTH measurement",
            required=True,
        )
    """

    model_config = {"frozen": True}

    drill_type: DrillType = Field(..., description="Required drill type.")
    description: str = Field(
        default="", description="Human-readable description of the requirement."
    )
    required: bool = Field(
        default=True, description="Whether this drill is mandatory for live eligibility."
    )


# Standard set of requirements for live deployment eligibility
LIVE_ELIGIBILITY_REQUIREMENTS: list[DrillRequirement] = [
    DrillRequirement(
        drill_type=DrillType.KILL_SWITCH,
        description="Kill switch activation, order cancellation, and MTTH measurement.",
        required=True,
    ),
    DrillRequirement(
        drill_type=DrillType.ROLLBACK,
        description="Deployment rollback from active to previous known-good state.",
        required=True,
    ),
    DrillRequirement(
        drill_type=DrillType.RECONNECT,
        description="Broker adapter reconnection after simulated disconnect.",
        required=True,
    ),
    DrillRequirement(
        drill_type=DrillType.FAILOVER,
        description="Broker failover with position reconciliation after recovery.",
        required=True,
    ),
]
