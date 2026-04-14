"""
Research run and candidate contracts.

Pydantic v2 schemas for research and optimization runs.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunType(str, Enum):
    """Research run type."""

    RESEARCH = "research"
    OPTIMIZATION = "optimization"


class RunStatus(str, Enum):
    """Research run status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchRunResponse(BaseModel):
    """
    Response schema for research or optimization run.

    Phase 2 contract. Phase 3 consumes but does not mutate.
    """

    id: str = Field(..., description="ULID")
    strategy_build_id: str
    run_type: RunType
    status: RunStatus
    config: dict[str, Any]
    result_uri: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BlockerDetail(BaseModel):
    """
    Single blocker with owner and next step.

    Blocker copy must be actionable for non-technical users.
    """

    code: str = Field(..., description="Blocker code (e.g., AMBIGUITY_DETECTED)")
    message: str = Field(..., description="Human-readable blocker message")
    blocker_owner: str = Field(..., description="Owner email or team responsible")
    next_step: str = Field(..., description="Recommended action to resolve blocker")
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunCandidateResponse(BaseModel):
    """
    Response schema for optimization trial candidate.

    Phase 2 contract. Phase 3 consumes readiness state and blocker data.
    Includes override_watermark per spec §8.2 for governance visibility.
    """

    id: str = Field(..., description="ULID")
    run_id: str
    trial_id: str
    parameters: dict[str, Any]
    metrics: dict[str, Any]
    readiness_grade: str | None = Field(
        None,
        description="A+ | A | B | C | D | F | None",
    )
    blockers: list[BlockerDetail]
    artifact_uri: str | None
    created_at: datetime
    updated_at: datetime
    override_watermark: dict[str, Any] | None = Field(
        None,
        description="Override watermark metadata for active overrides (spec §8.2)",
    )

    model_config = ConfigDict(from_attributes=True)


class ReadinessReportResponse(BaseModel):
    """
    Readiness report for a candidate.

    Backend-authoritative. UI never computes this locally.
    Includes override_watermark per spec §8.2 for governance visibility.
    """

    candidate_id: str
    grade: str | None
    score: float = Field(..., ge=0.0, le=100.0)
    blockers: list[BlockerDetail]
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Supporting evidence for scoring",
    )
    generated_at: datetime
    override_watermark: dict[str, Any] | None = Field(
        None,
        description="Override watermark metadata for active overrides (spec §8.2)",
    )


# ---------------------------------------------------------------------------
# M2 additions
# ---------------------------------------------------------------------------
from pydantic import BaseModel, Field  # noqa: F811 — already imported above but safe


class ExperimentPlan(BaseModel):
    """
    Specification for a research experiment run.

    Used as an input contract by research worker interfaces.
    """

    id: str = Field(..., description="ULID of the experiment plan")
    strategy_id: str = Field(..., description="ULID of the target strategy")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Experiment parameters",
    )
    description: str | None = Field(None, description="Human-readable notes")
    created_by: str | None = Field(None, description="ULID of the requesting user")
    created_at: datetime = Field(default_factory=datetime.utcnow)
