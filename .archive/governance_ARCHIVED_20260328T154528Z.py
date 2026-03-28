"""
Governance and approval contracts.

Pydantic v2 schemas for promotion requests and overrides.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, HttpUrl


class TargetEnvironment(str, Enum):
    """Deployment target environment."""
    PAPER = "paper"
    LIVE = "live"


class PromotionStatus(str, Enum):
    """Promotion request status."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PromotionRequestCreate(BaseModel):
    """
    Request payload to create a promotion request.
    """
    candidate_id: str = Field(..., description="ULID of candidate to promote")
    target_environment: TargetEnvironment
    evidence_link: Optional[HttpUrl] = Field(
        None,
        description="Optional evidence link (Jira, Confluence, GitHub)",
    )


class PromotionRequestResponse(BaseModel):
    """
    Response schema for promotion request.
    """
    id: str = Field(..., description="ULID")
    candidate_id: str
    target_environment: TargetEnvironment
    submitted_by: str
    status: PromotionStatus
    reviewed_by: Optional[str]
    reviewed_at: Optional[datetime]
    decision_rationale: Optional[str]
    evidence_link: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PromotionApprovalRequest(BaseModel):
    """
    Request payload to approve or reject a promotion request.
    """
    decision: str = Field(..., pattern="^(approved|rejected)$")
    rationale: str = Field(..., min_length=10, description="Decision rationale")


class OverrideType(str, Enum):
    """Governance override type."""
    BLOCKER_WAIVER = "blocker_waiver"
    GRADE_OVERRIDE = "grade_override"


class GovernanceOverrideCreate(BaseModel):
    """
    Request payload to create a governance override.
    
    Evidence link is required for SOC 2 compliance.
    """
    object_id: str = Field(..., description="ULID of candidate or deployment")
    object_type: str = Field(..., pattern="^(candidate|deployment)$")
    override_type: OverrideType
    original_state: Dict[str, Any] = Field(..., description="State before override")
    new_state: Dict[str, Any] = Field(..., description="State after override")
    evidence_link: HttpUrl = Field(..., description="Required evidence URI")
    rationale: str = Field(..., min_length=20, description="Override rationale")


class GovernanceOverrideResponse(BaseModel):
    """
    Response schema for governance override.
    """
    id: str = Field(..., description="ULID")
    object_id: str
    object_type: str
    override_type: OverrideType
    original_state: Dict[str, Any]
    new_state: Dict[str, Any]
    evidence_link: str
    rationale: str
    created_by: str
    approved_by: Optional[str]
    approved_at: Optional[datetime]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
