"""
Governance Override API endpoints.

Responsibilities:
- Expose override request submission and retrieval endpoints.
- Validate override request payloads using OverrideRequest contract
  (enforces SOC 2 evidence_link and rationale requirements).
- Delegate business logic to the GovernanceService.
- Return 201 on successful submission and 404 for unknown override IDs.
- Emit structured log events at all key lifecycle points.

Does NOT:
- Contain business logic or approval logic.
- Enforce separation-of-duties (service layer responsibility).
- Hold module-level DB sessions or singletons.

Dependencies:
- GovernanceService (injected per request via get_governance_service).
- OverrideRepositoryInterface (injected per request via get_override_repository).
- libs.contracts.governance: OverrideRequest
- structlog for structured logging

Error conditions:
- 422 Unprocessable Entity: evidence_link is not a valid HTTP/HTTPS URI with
  a non-root path, or rationale is too short.
- 404 Not Found: override_id does not exist in the store.

Example:
    POST /overrides/request → 201 {"override_id": "01H...", "status": "pending"}
    GET /overrides/01H...   → 200 {OverrideDetail}
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from libs.contracts.governance import OverrideRequest
from libs.contracts.interfaces.override_repository import OverrideRepositoryInterface
from services.api._validation import require_min_length, require_pattern, require_uri
from services.api.auth import AuthenticatedUser, require_scope
from services.api.db import get_db
from services.api.middleware.correlation import correlation_id_var
from services.api.services.interfaces.governance_service_interface import (
    GovernanceServiceInterface,
)

# ---------------------------------------------------------------------------
# Validation constants — enforced manually because pydantic-core field
# constraints are not applied in this venv (stub pydantic-core).
# See services/api/_validation.py for the shared utility helpers.
# ---------------------------------------------------------------------------
_RATIONALE_MIN_LEN = 20


logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request-scoped dependency providers — no module-level singletons.
# Each request gets its own DB session, repository, and service instance.
# ---------------------------------------------------------------------------


def get_override_repository(
    db: Session = Depends(get_db),
) -> OverrideRepositoryInterface:
    """
    Provide a request-scoped override repository.

    Always returns SqlOverrideRepository backed by the request's DB session.
    In tests, get_db() yields a SQLite session (configured in db.py) so the
    SQL repos work identically. Unit tests that need in-memory mocks should
    use app.dependency_overrides[get_override_repository].

    Args:
        db: SQLAlchemy session injected by FastAPI per request.

    Returns:
        SqlOverrideRepository bound to the request's session.
    """
    from services.api.repositories.sql_override_repository import SqlOverrideRepository

    return SqlOverrideRepository(db=db)


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
    "/request",
    status_code=status.HTTP_201_CREATED,
    summary="Submit a governance override request",
)
async def request_override(
    payload: OverrideRequest,
    user: AuthenticatedUser = Depends(require_scope("overrides:request")),
    svc: GovernanceServiceInterface = Depends(get_governance_service),
) -> dict:
    """
    Submit a governance override request.

    evidence_link is validated to be an absolute HTTP/HTTPS URI with a
    non-root path (SOC 2 Evidence of Review requirement). Requests without
    a valid evidence_link are rejected with 422.

    All business logic is delegated to the GovernanceService, which
    creates the Override record and emits an audit event.

    Args:
        payload: OverrideRequest body — all fields required.
        user: Authenticated user from JWT.
        svc: Request-scoped GovernanceService.

    Returns:
        201 response with override_id and status='pending'.

    Raises:
        HTTPException 422: If evidence_link validation fails or rationale
            is shorter than 20 characters.

    Example:
        POST /overrides/request
        → 201 {"override_id": "01H...", "status": "pending"}
    """
    corr_id = correlation_id_var.get("no-corr")

    # Manual validation — pydantic-core constraints not enforced in this venv.
    require_uri(payload.evidence_link, field="evidence_link")
    require_min_length(payload.rationale, field="rationale", min_len=_RATIONALE_MIN_LEN)
    require_pattern(
        payload.object_type,
        field="object_type",
        pattern=r"^(candidate|deployment)$",
        description="'candidate' or 'deployment'",
    )

    logger.info(
        "override.request.called",
        object_type=payload.object_type,
        override_type=payload.override_type.value
        if hasattr(payload.override_type, "value")
        else payload.override_type,
        submitter_id=user.user_id,
        component="overrides",
        correlation_id=corr_id,
    )

    result = svc.submit_override(
        submitter_id=user.user_id,
        object_id=payload.object_id,
        object_type=payload.object_type,
        override_type=payload.override_type.value
        if hasattr(payload.override_type, "value")
        else payload.override_type,
        original_state=payload.original_state,
        new_state=payload.new_state,
        evidence_link=payload.evidence_link,
        rationale=payload.rationale,
        correlation_id=corr_id,
    )

    logger.info(
        "override.request.submitted",
        override_id=result["override_id"],
        component="overrides",
        correlation_id=corr_id,
        result="success",
    )

    return result


@router.get(
    "/{override_id}",
    summary="Retrieve a governance override request by ID",
)
async def get_override(
    override_id: str = Path(..., description="Override request ULID"),
    user: AuthenticatedUser = Depends(require_scope("overrides:request")),
    repo: OverrideRepositoryInterface = Depends(get_override_repository),
) -> dict:
    """
    Retrieve details of a governance override request.

    Args:
        override_id: ULID of the override request.
        user: Authenticated user from JWT.
        repo: Request-scoped override repository.

    Returns:
        OverrideDetail-shaped dict with full override information.

    Raises:
        HTTPException 404: If override_id is not found.

    Example:
        GET /overrides/01H...
        → 200 {"id": "01H...", "status": "pending", ...}
    """
    corr_id = correlation_id_var.get("no-corr")

    record = repo.get_by_id(override_id)

    if record is None:
        logger.warning(
            "override.get.not_found",
            override_id=override_id,
            component="overrides",
            correlation_id=corr_id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Override request '{override_id}' not found.",
        )

    logger.debug(
        "override.get.found",
        override_id=override_id,
        component="overrides",
        correlation_id=corr_id,
    )
    return record
