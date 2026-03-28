"""
Research run and candidate contracts.

Pydantic v2 schemas for research and optimization runs.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
    config: Dict[str, Any]
    result_uri: Optional[str]
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BlockerDetail(BaseModel):
    """
    Single blocker with owner and next step.
    
    Blocker copy must be actionable for non-technical users.
    """
    code: str = Field(..., description="Blocker code (e.g., AMBIGUITY_DETECTED)")
    message: str = Field(..., description="Human-readable blocker message")
    blocker_owner: str = Field(..., description="Owner email or team responsible")
    next_step: str = Field(..., description="Recommended action to resolve blocker")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RunCandidateResponse(BaseModel):
    """
    Response schema for optimization trial candidate.
    
    Phase 2 contract. Phase 3 consumes readiness state and blocker data.
    """
    id: str = Field(..., description="ULID")
    run_id: str
    trial_id: str
    parameters: Dict[str, Any]
    metrics: Dict[str, Any]
    readiness_grade: Optional[str] = Field(
        None,
        description="A+ | A | B | C | D | F | None",
    )
    blockers: List[BlockerDetail]
    artifact_uri: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ReadinessReportResponse(BaseModel):
    """
    Readiness report for a candidate.
    
    Backend-authoritative. UI never computes this locally.
    """
    candidate_id: str
    grade: Optional[str]
    score: float = Field(..., ge=0.0, le=100.0)
    blockers: List[BlockerDetail]
    evidence: Dict[str, Any] = Field(
        default_factory=dict,
        description="Supporting evidence for scoring",
    )
    generated_at: datetime


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
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Experiment parameters",
    )
    description: Optional[str] = Field(None, description="Human-readable notes")
    created_by: Optional[str] = Field(None, description="ULID of the requesting user")
    created_at: datetime = Field(default_factory=datetime.utcnow)
