"""
Approvals API endpoints.

Responsibilities:
- Expose approval action endpoints for governance workflows.
- Validate approval/rejection payloads using typed contracts.
- Delegate all business logic to the GovernanceService.
- Map domain errors to HTTP status codes.
- Emit structured log events for audit traceability.

Does NOT:
- Contain business logic or SoD enforcement (service layer responsibility).
- Access the database directly (service + repository responsibility).
- Hold module-level DB sessions or singletons.

Dependencies:
- GovernanceService (injected per request via get_governance_service).
- libs.contracts.governance: ApprovalRejectRequest.
- structlog for structured logging.

Error conditions:
- 409 Conflict: SoD violation (submitter == reviewer).
- 422 Unprocessable Entity: malformed request body.
- 404 Not Found: approval_id does not exist.

Example:
    POST /approvals/{id}/approve   → 200 {"approval_id": "...", "status": "approved"}
    POST /approvals/{id}/reject    {"rationale": "..."} → 200 {..., "status": "rejected"}
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from libs.contracts.errors import NotFoundError, SeparationOfDutiesError
from libs.contracts.governance import ApprovalRejectRequest
from services.api._validation import (
    require_min_length,
    require_non_empty,
)
from services.api.auth import AuthenticatedUser, require_scope
from services.api.db import get_db
from services.api.middleware.audit_trail import audit_action
from services.api.middleware.correlation import correlation_id_var
from services.api.middleware.rate_limit import rate_limit
from services.api.services.interfaces.governance_service_interface import (
    GovernanceServiceInterface,
)

logger = structlog.get_logger(__name__)

# Minimum rationale length — enforced manually (see services/api/_validation.py).
_RATIONALE_MIN_LEN = 10

router = APIRouter()


# ---------------------------------------------------------------------------
# Request-scoped dependency provider — no module-level singletons.
# ---------------------------------------------------------------------------


def get_governance_service(
    db: Session = Depends(get_db),
) -> GovernanceServiceInterface:
    """
    Provide a request-scoped GovernanceService.

    Constructs the service with SQL-backed repositories and audit writer
    bound to the current request's DB session. Session is closed
    automatically by FastAPI's get_db dependency when the request completes.

    Args:
        db: SQLAlchemy session injected by FastAPI per request.

    Returns:
        GovernanceService wired to request-scoped dependencies.
    """
    from services.api.repositories.sql_approval_repository import SqlApprovalRepository
    from services.api.repositories.sql_override_repository import SqlOverrideRepository
    from services.api.services.audit_writer import SqlAuditWriter
    from services.api.services.governance_service import GovernanceService

    override_repo = SqlOverrideRepository(db=db)
    approval_repo = SqlApprovalRepository(db=db)
    audit_writer = SqlAuditWriter(db=db)

    return GovernanceService(
        override_repo=override_repo,
        approval_repo=approval_repo,
        audit_writer=audit_writer,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{approval_id}/approve",
    dependencies=[
        Depends(
            audit_action(
                action="approval.approve",
                object_type="approval",
                extract_object_id="approval_id",
            )
        ),
    ],
)
async def approve_request(
    approval_id: str = Path(..., description="Approval request ULID"),
    payload: dict[str, Any] | None = None,
    user: AuthenticatedUser = Depends(require_scope("approvals:write")),
    svc: GovernanceServiceInterface = Depends(get_governance_service),
    _rate_limit: None = Depends(
        rate_limit(max_requests=10, window_seconds=60, scope="approval_action")
    ),
) -> dict:
    """
    Approve a pending approval request.

    Enforces separation of duties: the reviewer (authenticated user) must not
    be the same person who submitted the approval request.

    Args:
        approval_id: The ULID of the approval request to approve.
        payload: Optional approval decision payload.
        user: Authenticated user from JWT.
        svc: Request-scoped GovernanceService.

    Returns:
        Dict with approval_id and status='approved'.

    Raises:
        HTTPException 409: If reviewer == submitter (SoD violation).
        HTTPException 404: If approval_id does not exist.

    Example:
        POST /approvals/01HAPPROVAL.../approve
        → {"approval_id": "01HAPPROVAL...", "status": "approved"}
    """
    corr_id = correlation_id_var.get("no-corr")

    logger.info(
        "approval.approve.called",
        approval_id=approval_id,
        reviewer_id=user.user_id,
        component="approvals",
        correlation_id=corr_id,
    )

    try:
        result = svc.approve_request(
            approval_id=approval_id,
            reviewer_id=user.user_id,
            correlation_id=corr_id,
        )
    except SeparationOfDutiesError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reviewer cannot be the same person who submitted this request.",
        )
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval request '{approval_id}' not found.",
        )

    logger.info(
        "approval.approve.completed",
        approval_id=approval_id,
        component="approvals",
        correlation_id=corr_id,
        result="success",
    )
    return result


@router.post(
    "/{approval_id}/reject",
    dependencies=[
        Depends(
            audit_action(
                action="approval.reject",
                object_type="approval",
                extract_object_id="approval_id",
            )
        ),
    ],
)
async def reject_request(
    approval_id: str = Path(..., description="Approval request ULID"),
    payload: ApprovalRejectRequest = None,
    user: AuthenticatedUser = Depends(require_scope("approvals:write")),
    svc: GovernanceServiceInterface = Depends(get_governance_service),
    _rate_limit: None = Depends(
        rate_limit(max_requests=10, window_seconds=60, scope="approval_action")
    ),
) -> dict:
    """
    Reject a pending approval request.

    A rejection rationale is mandatory (minimum 10 characters) because it
    forms the immutable audit record of the governance decision.

    Args:
        approval_id: The ULID of the approval request to reject.
        payload: Rejection payload containing the mandatory rationale.
        user: Authenticated user from JWT.
        svc: Request-scoped GovernanceService.

    Returns:
        Dict with approval_id, status='rejected', and the provided rationale.

    Raises:
        HTTPException 409: If reviewer == submitter (SoD violation).
        HTTPException 404: If approval_id does not exist.
        HTTPException 422: If rationale is missing or fewer than 10 characters.

    Example:
        POST /approvals/01HAPPROVAL.../reject
        {"rationale": "Evidence link is stale; regime not covered by backtest."}
        → {"approval_id": "01HAPPROVAL...", "status": "rejected", "rationale": "..."}
    """
    corr_id = correlation_id_var.get("no-corr")

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Request body is required.",
        )
    require_non_empty(payload.rationale, field="rationale")
    require_min_length(payload.rationale, field="rationale", min_len=_RATIONALE_MIN_LEN)

    logger.info(
        "approval.reject.called",
        approval_id=approval_id,
        reviewer_id=user.user_id,
        rationale_length=len(payload.rationale),
        component="approvals",
        correlation_id=corr_id,
    )

    try:
        result = svc.reject_request(
            approval_id=approval_id,
            reviewer_id=user.user_id,
            rationale=payload.rationale,
            correlation_id=corr_id,
        )
    except SeparationOfDutiesError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reviewer cannot be the same person who submitted this request.",
        )
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval request '{approval_id}' not found.",
        )

    logger.info(
        "approval.reject.completed",
        approval_id=approval_id,
        component="approvals",
        correlation_id=corr_id,
        result="success",
    )
    return result
