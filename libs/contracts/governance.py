"""
Governance and approval contracts.

Pydantic v2 schemas for:
- Promotion requests and approval decisions.
- Override requests (SOC 2 evidence_link required).
- Draft autosave payloads (session recovery).

Responsibilities:
- Define all API request/response schemas for governance workflows.
- Enforce evidence_link as an absolute HTTP/HTTPS URI with a non-root path
  (SOC 2 Evidence of Review requirement).
- Enforce rationale length minimums per governance policy.

Does NOT:
- Contain business logic.
- Perform I/O or database access.
- Enforce separation-of-duties (that is the service layer's responsibility).

Dependencies:
- pydantic v2
- Python standard library only.

Error conditions:
- Raises pydantic.ValidationError when evidence_link is not a valid HTTP/HTTPS
  URI with a non-root path.
- Raises pydantic.ValidationError when rationale is below minimum length.

Example:
    from libs.contracts.governance import OverrideRequest, DraftAutosavePayload

    req = OverrideRequest(
        object_id="01H...",
        object_type="candidate",
        override_type=OverrideType.GRADE_OVERRIDE,
        original_state={"grade": "C"},
        new_state={"grade": "B"},
        evidence_link="https://jira.example.com/browse/FX-123",
        rationale="Extended backtest shows grade C is too conservative.",
        submitter_id="01H...",
    )
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, HttpUrl, field_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TargetEnvironment(str, Enum):
    """Deployment target environment."""

    PAPER = "paper"
    LIVE = "live"


class PromotionStatus(str, Enum):
    """Promotion request status."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class OverrideType(str, Enum):
    """Governance override type."""

    BLOCKER_WAIVER = "blocker_waiver"
    GRADE_OVERRIDE = "grade_override"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_evidence_link(value: str | None) -> str:
    """
    Validate that evidence_link is an absolute HTTP/HTTPS URI with a non-root path.

    SOC 2 compliance requires every override request to reference an external
    evidence artefact (Jira ticket, Confluence doc, GitHub issue, etc.) by URL.
    A bare domain (https://example.com or https://example.com/) is insufficient —
    the link must point to a specific resource.

    Args:
        value: The raw evidence_link value from the incoming request.

    Returns:
        The validated string URI.

    Raises:
        ValueError: If scheme is not http/https, or path is root/empty.
    """
    if not value:
        raise ValueError("evidence_link is required for override requests")
    raw = str(value)
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"evidence_link must use http or https scheme (got '{parsed.scheme}')")
    # Strip trailing slash; '' or '/' after stripping means root path.
    path = parsed.path.rstrip("/")
    if not path:
        raise ValueError(
            "evidence_link must reference a specific resource path, not just the host. "
            "Use a Jira ticket, Confluence doc, or GitHub issue URL."
        )
    return raw


# ---------------------------------------------------------------------------
# Promotion schemas
# ---------------------------------------------------------------------------


class PromotionRequestCreate(BaseModel):
    """
    Request payload to create a promotion request.

    Args:
        candidate_id: ULID of the candidate to promote.
        target_environment: Paper or Live deployment tier.
        evidence_link: Optional URI linking to supporting evidence.
    """

    candidate_id: str = Field(..., description="ULID of candidate to promote")
    target_environment: TargetEnvironment
    evidence_link: HttpUrl | None = Field(
        None,
        description="Optional evidence link (Jira, Confluence, GitHub)",
    )


class PromotionRequestResponse(BaseModel):
    """
    Response schema for a promotion request.

    Attributes:
        id: ULID assigned by the server.
        candidate_id: Candidate being promoted.
        target_environment: Target deployment tier.
        submitted_by: ULID of the submitting user.
        status: Current workflow status.
        reviewed_by: ULID of reviewer (None until decided).
        reviewed_at: Timestamp of review decision (None until decided).
        decision_rationale: Free-text rationale from reviewer.
        evidence_link: URI provided at submission time.
        created_at: Server timestamp of creation.
        updated_at: Server timestamp of last update.
        override_watermark: Optional watermark metadata for active overrides on the
            promoted candidate. Populated per spec §8.2.
    """

    id: str = Field(..., description="ULID")
    candidate_id: str
    target_environment: TargetEnvironment
    submitted_by: str
    status: PromotionStatus
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    decision_rationale: str | None = None
    evidence_link: str | None = None
    created_at: datetime
    updated_at: datetime
    override_watermark: dict[str, Any] | None = Field(
        None,
        description="Override watermark metadata for active overrides (spec §8.2)",
    )

    model_config = {"from_attributes": True}


class PromotionApprovalRequest(BaseModel):
    """
    Request payload to approve or reject a promotion request.

    Args:
        decision: Must be 'approved' or 'rejected'.
        rationale: Decision rationale, minimum 10 characters.
    """

    decision: str = Field(..., pattern="^(approved|rejected)$")
    rationale: str = Field(..., min_length=10, description="Decision rationale")


# ---------------------------------------------------------------------------
# Approval reject schema (M13 gap G-05)
# ---------------------------------------------------------------------------


class ApprovalRejectRequest(BaseModel):
    """
    Request payload to reject a pending approval request.

    Distinct from PromotionApprovalRequest: rejection always requires a
    rationale; the decision field is implicit ('rejected').

    Args:
        rationale: Human-readable rejection reason, minimum 10 characters.
                   This becomes the immutable audit record of the decision.

    Example:
        payload = ApprovalRejectRequest(
            rationale="Evidence link is stale; backtest does not cover current regime."
        )
    """

    rationale: str = Field(
        ...,
        min_length=10,
        description="Rejection rationale (audit record — minimum 10 characters)",
    )


# ---------------------------------------------------------------------------
# Override request schemas (M13 gaps G-06 to G-09)
# ---------------------------------------------------------------------------


class OverrideRequest(BaseModel):
    """
    Request payload to submit a governance override request.

    SOC 2 compliance: evidence_link is required and must be an absolute
    HTTP/HTTPS URI pointing to a specific resource (not just a domain root).
    Free-text rationale alone does not satisfy Evidence of Review requirements.

    Args:
        object_id: ULID of the candidate or deployment being overridden.
        object_type: Must be 'candidate' or 'deployment'.
        override_type: Blocker waiver or grade override.
        original_state: Serialised state before the override is applied.
        new_state: Serialised state after the override is applied.
        evidence_link: Absolute HTTP/HTTPS URI to a supporting evidence artefact.
        rationale: Detailed override justification (minimum 20 characters).
        submitter_id: ULID of the user submitting this request.

    Raises:
        ValidationError: If evidence_link is not an absolute HTTP/HTTPS URI
            with a non-root path, or rationale is too short.

    Example:
        req = OverrideRequest(
            object_id="01H...",
            object_type="candidate",
            override_type=OverrideType.GRADE_OVERRIDE,
            original_state={"grade": "C"},
            new_state={"grade": "B"},
            evidence_link="https://jira.example.com/browse/FX-123",
            rationale="Extended backtest over 3-year window justifies grade uplift.",
            submitter_id="01H...",
        )
    """

    object_id: str = Field(..., description="ULID of candidate or deployment")
    object_type: str = Field(..., pattern="^(candidate|deployment)$")
    override_type: OverrideType
    original_state: dict[str, Any] = Field(..., description="State before override")
    new_state: dict[str, Any] = Field(..., description="State after override")
    evidence_link: str = Field(
        ...,
        description=(
            "Required absolute HTTP/HTTPS URI linking to a Jira ticket, "
            "Confluence doc, or GitHub issue. Root-path URIs are rejected."
        ),
    )
    rationale: str = Field(
        ...,
        min_length=20,
        description="Override justification (SOC 2 audit record — minimum 20 characters)",
    )
    submitter_id: str = Field(..., description="ULID of submitting user")

    @field_validator("evidence_link", mode="before")
    @classmethod
    def validate_evidence_link(cls, v: Any) -> str:
        """
        Validate evidence_link is an absolute HTTP/HTTPS URI with a non-root path.

        Args:
            v: Raw value from the incoming request body.

        Returns:
            The validated string URI.

        Raises:
            ValueError: If scheme is not http/https or path is root/empty.
        """
        return _validate_evidence_link(str(v) if v is not None else None)


class OverrideDetail(BaseModel):
    """
    Response schema for a governance override request.

    Attributes:
        id: ULID assigned by the server.
        object_id: Target candidate or deployment ULID.
        object_type: 'candidate' or 'deployment'.
        override_type: Type of override applied.
        original_state: Captured pre-override state.
        new_state: Captured post-override state.
        evidence_link: Evidence URI from the original request.
        rationale: Justification text from the original request.
        submitter_id: ULID of the submitting user.
        status: Current workflow status ('pending', 'approved', 'rejected').
        reviewed_by: ULID of reviewer (None until decided).
        reviewed_at: Review decision timestamp (None until decided).
        created_at: Server creation timestamp.
        updated_at: Server last-update timestamp.
        override_watermark: Optional watermark metadata indicating an active override
            on the target entity. Populated in responses per spec §8.2.
    """

    id: str = Field(..., description="ULID")
    object_id: str
    object_type: str
    override_type: OverrideType
    original_state: dict[str, Any]
    new_state: dict[str, Any]
    evidence_link: str
    rationale: str
    submitter_id: str
    status: str
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    override_watermark: dict[str, Any] | None = Field(
        None,
        description="Override watermark metadata for active overrides (spec §8.2)",
    )

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Legacy override schemas (kept for backward compatibility)
# ---------------------------------------------------------------------------


class GovernanceOverrideCreate(BaseModel):
    """
    Legacy override create schema (pre-M23 revision).

    Responsibilities:
    - Matches the original Phase 3 override contract.
    - Kept for backward compatibility with existing route stubs.
    - New code should prefer OverrideRequest, which adds submitter_id
      and stricter evidence_link path validation.
    """

    object_id: str = Field(..., description="ULID of candidate or deployment")
    object_type: str = Field(..., pattern="^(candidate|deployment)$")
    override_type: OverrideType
    original_state: dict[str, Any] = Field(..., description="State before override")
    new_state: dict[str, Any] = Field(..., description="State after override")
    evidence_link: HttpUrl = Field(..., description="Required evidence URI")
    rationale: str = Field(..., min_length=20, description="Override rationale")


class GovernanceOverrideResponse(BaseModel):
    """
    Legacy override response schema — kept for backward compatibility.

    New code should prefer OverrideDetail.
    """

    id: str = Field(..., description="ULID")
    object_id: str
    object_type: str
    override_type: OverrideType
    original_state: dict[str, Any]
    new_state: dict[str, Any]
    evidence_link: str
    rationale: str
    created_by: str
    approved_by: str | None = None
    approved_at: datetime | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Draft autosave schemas (M13 gap G-10 — spec Section 7.5)
# ---------------------------------------------------------------------------


class DraftAutosavePayload(BaseModel):
    """
    Request payload for POST /strategies/draft/autosave.

    The frontend calls this endpoint every 30 seconds and on every field blur.
    The draft_payload may be incomplete (partial validation only —
    full StrategyDraftInput validation is not applied here).

    Args:
        user_id: ULID of the user whose draft is being saved.
        draft_payload: Partial StrategyDraftInput dict (may be incomplete).
        form_step: The wizard step the user was on when autosave was triggered.
        client_ts: Client-side ISO timestamp at the moment of autosave.
        session_id: Browser session identifier for recovery disambiguation.

    Example:
        payload = DraftAutosavePayload(
            user_id="01H...",
            draft_payload={"name": "MyStrategy", "lookback": 30},
            form_step="parameters",
            client_ts=datetime(2026, 3, 28, 11, 0, 0),
            session_id="sess-abc123",
        )
    """

    user_id: str = Field(..., description="ULID of the user owning this draft")
    draft_payload: dict[str, Any] = Field(
        ...,
        description="Partial StrategyDraftInput — may be incomplete",
    )
    form_step: str = Field(..., description="Wizard step at time of autosave")
    client_ts: datetime = Field(..., description="Client-side timestamp")
    session_id: str = Field(..., description="Browser session identifier")


class DraftAutosaveResponse(BaseModel):
    """
    Response schema for POST /strategies/draft/autosave.

    Attributes:
        autosave_id: Server-assigned ULID for this autosave record.
        saved_at: Server-side timestamp confirming persistence.

    Example:
        resp = DraftAutosaveResponse(
            autosave_id="01H...",
            saved_at=datetime(2026, 3, 28, 11, 0, 1),
        )
    """

    autosave_id: str = Field(..., description="ULID of the saved autosave record")
    saved_at: datetime = Field(..., description="Server-side persistence timestamp")
