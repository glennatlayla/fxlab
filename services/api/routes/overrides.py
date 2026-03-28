"""
Governance Override API endpoints.

Responsibilities:
- Expose override request submission and retrieval endpoints.
- Validate override request payloads using OverrideRequest contract
  (enforces SOC 2 evidence_link and rationale requirements).
- Return 201 on successful submission and 404 for unknown override IDs.
- Emit structured log events at all key lifecycle points.

Does NOT:
- Contain business logic or approval logic.
- Enforce separation-of-duties (service layer responsibility).
- Select the repository implementation (delegated to _get_repository).

Dependencies:
- libs.contracts.governance: OverrideRequest
- SqlOverrideRepository (when ENVIRONMENT != "test")
- MockOverrideRepository (when ENVIRONMENT == "test" / unset)
- structlog for structured logging

Error conditions:
- 422 Unprocessable Entity: evidence_link is not a valid HTTP/HTTPS URI with
  a non-root path, or rationale is too short.
- 404 Not Found: override_id does not exist in the store.

Example:
    POST /overrides/request
    {
        "object_id": "01H...",
        "object_type": "candidate",
        "override_type": "grade_override",
        "original_state": {"grade": "C"},
        "new_state": {"grade": "B"},
        "evidence_link": "https://jira.example.com/browse/FX-123",
        "rationale": "Extended backtest justifies grade uplift.",
        "submitter_id": "01H..."
    }
    → 201 {"override_id": "01H...", "status": "pending"}

    GET /overrides/01H...
    → 200 {OverrideDetail}
"""

from __future__ import annotations

import os

import structlog
from fastapi import APIRouter, HTTPException, Path, status

from libs.contracts.governance import OverrideRequest
from services.api._validation import require_min_length, require_uri

# ---------------------------------------------------------------------------
# Validation constants — enforced manually because pydantic-core field
# constraints are not applied in this venv (stub pydantic-core).
# See services/api/_validation.py for the shared utility helpers.
# ---------------------------------------------------------------------------
_RATIONALE_MIN_LEN = 20


logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Repository factory — ENVIRONMENT gate.
# ENVIRONMENT="test" (or unset) → MockOverrideRepository (fast, in-memory).
# Any other value              → SqlOverrideRepository (PostgreSQL/SQLite).
# Production containers set ENV ENVIRONMENT=production in the Dockerfile.
# ---------------------------------------------------------------------------

def _get_repository():
    """
    Return the appropriate override repository implementation.

    Returns:
        SqlOverrideRepository when ENVIRONMENT != "test".
        MockOverrideRepository when ENVIRONMENT == "test" (pytest default).
    """
    if os.environ.get("ENVIRONMENT", "test") != "test":
        from services.api.db import get_db
        from services.api.repositories.sql_override_repository import SqlOverrideRepository
        db = next(get_db())
        return SqlOverrideRepository(db=db)
    from libs.contracts.mocks.mock_override_repository import MockOverrideRepository
    return MockOverrideRepository()


# ---------------------------------------------------------------------------
# Module-level singleton repository (one per worker process lifetime).
# This avoids reconstructing the repo on every request while ensuring
# the ENVIRONMENT gate is evaluated at import time (not at startup).
# ---------------------------------------------------------------------------
_repo = None


def _repo_instance():
    """
    Lazily initialise and return the module-level repository singleton.

    Lazy init is required because the ORM models (and therefore the mock/SQL
    imports) must not be evaluated before the application bootstraps the DB.

    Returns:
        The override repository singleton for this worker process.
    """
    global _repo
    if _repo is None:
        _repo = _get_repository()
    return _repo


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/request",
    status_code=status.HTTP_201_CREATED,
    summary="Submit a governance override request",
)
async def request_override(payload: OverrideRequest) -> dict:
    """
    Submit a governance override request.

    evidence_link is validated to be an absolute HTTP/HTTPS URI with a
    non-root path (SOC 2 Evidence of Review requirement). Requests without
    a valid evidence_link are rejected with 422.

    Args:
        payload: OverrideRequest body — all fields required.

    Returns:
        201 response with override_id and status='pending'.

    Raises:
        HTTPException 422: If evidence_link validation fails or rationale
            is shorter than 20 characters.

    Example:
        POST /overrides/request
        → 201 {"override_id": "01H...", "status": "pending"}
    """
    # Manual validation — pydantic-core constraints not enforced in this venv.
    require_uri(payload.evidence_link, field="evidence_link")
    require_min_length(payload.rationale, field="rationale", min_len=_RATIONALE_MIN_LEN)

    repo = _repo_instance()
    result = repo.create(
        object_id=payload.object_id,
        object_type=payload.object_type,
        override_type=payload.override_type,
        original_state=payload.original_state,
        new_state=payload.new_state,
        evidence_link=payload.evidence_link,
        rationale=payload.rationale,
        submitter_id=payload.submitter_id,
    )

    logger.info(
        "override.request.submitted",
        override_id=result["override_id"],
        object_type=payload.object_type,
        override_type=payload.override_type.value
        if hasattr(payload.override_type, "value")
        else payload.override_type,
        submitter_id=payload.submitter_id,
    )

    return result


@router.get(
    "/{override_id}",
    summary="Retrieve a governance override request by ID",
)
async def get_override(
    override_id: str = Path(..., description="Override request ULID"),
) -> dict:
    """
    Retrieve details of a governance override request.

    Args:
        override_id: ULID of the override request.

    Returns:
        OverrideDetail-shaped dict with full override information.

    Raises:
        HTTPException 404: If override_id is not found.

    Example:
        GET /overrides/01H...
        → 200 {"id": "01H...", "status": "pending", ...}
    """
    repo = _repo_instance()
    record = repo.get_by_id(override_id)

    if record is None:
        logger.warning("override.get.not_found", override_id=override_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Override request '{override_id}' not found.",
        )

    logger.debug("override.get.found", override_id=override_id)
    return record
