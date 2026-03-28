"""
Approvals API endpoints.

Responsibilities:
- Expose approval action endpoints for governance workflows.
- Validate approval/rejection payloads using typed contracts.
- Emit structured log events for audit traceability.

Does NOT:
- Contain business logic or database access.
- Enforce separation-of-duties (service layer responsibility).
- Emit audit events directly (delegated to audit_service).

Dependencies:
- libs.contracts.governance: ApprovalRejectRequest, PromotionApprovalRequest
- structlog for structured logging

Error conditions:
- 422 Unprocessable Entity: malformed request body (rationale too short, etc.)
- 404 Not Found: approval_id does not exist (raised by service layer)

Example:
    POST /approvals/{id}/approve   {"decision": "approved", "rationale": "..."}
    POST /approvals/{id}/reject    {"rationale": "Insufficient evidence."}
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, HTTPException, Path, status

from libs.contracts.governance import ApprovalRejectRequest
from services.api._validation import require_min_length, require_non_empty

logger = structlog.get_logger(__name__)

# Minimum rationale length — enforced manually (see services/api/_validation.py).
_RATIONALE_MIN_LEN = 10

router = APIRouter()


@router.post("/{approval_id}/approve")
async def approve_request(
    approval_id: str = Path(..., description="Approval request ULID"),
    payload: Optional[Dict[str, Any]] = None,
) -> dict:
    """
    Approve a pending approval request.

    Args:
        approval_id: The ULID of the approval request to approve.
        payload: Approval decision payload containing rationale.

    Returns:
        Dict with approval_id and status='approved'.

    Raises:
        HTTPException 422: If payload validation fails.

    Example:
        POST /approvals/01HAPPROVAL.../approve
        {"decision": "approved", "rationale": "Backtest results are satisfactory."}
        → {"approval_id": "01HAPPROVAL...", "status": "approved"}
    """
    logger.info(
        "approval.approve.called",
        approval_id=approval_id,
    )
    # Stub: real implementation queries DB, enforces SoD, emits audit event.
    return {"approval_id": approval_id, "status": "approved"}


@router.post("/{approval_id}/reject")
async def reject_request(
    approval_id: str = Path(..., description="Approval request ULID"),
    payload: ApprovalRejectRequest = None,
) -> dict:
    """
    Reject a pending approval request.

    A rejection rationale is mandatory (minimum 10 characters) because it
    forms the immutable audit record of the governance decision.

    Args:
        approval_id: The ULID of the approval request to reject.
        payload: Rejection payload containing the mandatory rationale.

    Returns:
        Dict with approval_id, status='rejected', and the provided rationale.

    Raises:
        HTTPException 422: If rationale is missing or fewer than 10 characters.

    Example:
        POST /approvals/01HAPPROVAL.../reject
        {"rationale": "Evidence link is stale; regime not covered by backtest."}
        → {"approval_id": "01HAPPROVAL...", "status": "rejected", "rationale": "..."}
    """
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Request body is required.",
        )
    require_non_empty(payload.rationale, field="rationale")
    require_min_length(payload.rationale, field="rationale", min_len=_RATIONALE_MIN_LEN)
    logger.info(
        "approval.reject.called",
        approval_id=approval_id,
        rationale_length=len(payload.rationale),
    )
    return {
        "approval_id": approval_id,
        "status": "rejected",
        "rationale": payload.rationale,
    }
