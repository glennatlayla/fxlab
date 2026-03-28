"""
Strategy Routes.

Responsibilities:
- Strategy list/get/versions endpoints.
- Draft autosave endpoints (POST, GET /latest, DELETE /{id}).

Draft autosave allows non-technical operators to recover from session loss.
The frontend calls POST /strategies/draft/autosave every 30 seconds and on
field blur. GET /strategies/draft/autosave/latest is called on login to
offer recovery of incomplete drafts.

Does NOT:
- Contain business logic or scoring logic.
- Access the database directly (routed through repository layer).
- Enforce RBAC (that is the service layer's responsibility).

Dependencies:
- libs.contracts.governance: DraftAutosavePayload, DraftAutosaveResponse
- SqlDraftAutosaveRepository (when ENVIRONMENT != "test")
- MockDraftAutosaveRepository (when ENVIRONMENT == "test" / unset)
- structlog for structured logging

Error conditions:
- 422 Unprocessable Entity: missing required fields in autosave payload.
- 404 Not Found: autosave_id does not exist.
- 204 No Content: no autosave found for user_id (GET /latest).

Example:
    POST /strategies/draft/autosave
    {"user_id": "01H...", "draft_payload": {...}, "form_step": "parameters", ...}
    → 200 {"autosave_id": "01H...", "saved_at": "..."}

    GET /strategies/draft/autosave/latest?user_id=01H...
    → 200 {autosave payload} or 204 if none

    DELETE /strategies/draft/autosave/01H...
    → 204 No Content
"""

from __future__ import annotations

import os
from typing import Any, Optional

import structlog
from fastapi import APIRouter, HTTPException, Path, Query, status
from fastapi.responses import Response

from libs.contracts.governance import DraftAutosavePayload

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Repository factory — ENVIRONMENT gate.
# ENVIRONMENT="test" (or unset) → MockDraftAutosaveRepository (fast, in-memory).
# Any other value              → SqlDraftAutosaveRepository (PostgreSQL/SQLite).
# Production containers set ENV ENVIRONMENT=production in the Dockerfile.
# ---------------------------------------------------------------------------

def _get_repository():
    """
    Return the appropriate autosave repository implementation.

    Returns:
        SqlDraftAutosaveRepository when ENVIRONMENT != "test".
        MockDraftAutosaveRepository when ENVIRONMENT == "test" (pytest default).
    """
    if os.environ.get("ENVIRONMENT", "test") != "test":
        from services.api.db import get_db
        from services.api.repositories.sql_draft_autosave_repository import (
            SqlDraftAutosaveRepository,
        )
        db = next(get_db())
        return SqlDraftAutosaveRepository(db=db)
    from libs.contracts.mocks.mock_draft_autosave_repository import (
        MockDraftAutosaveRepository,
    )
    return MockDraftAutosaveRepository()


# Module-level singleton — lazily initialised.
_repo = None


def _repo_instance():
    """
    Lazily initialise and return the module-level repository singleton.

    Returns:
        The draft autosave repository singleton for this worker process.
    """
    global _repo
    if _repo is None:
        _repo = _get_repository()
    return _repo


# ---------------------------------------------------------------------------
# Strategy list endpoint (pre-existing stub)
# ---------------------------------------------------------------------------


@router.get("/", summary="List strategies")
async def list_strategies() -> dict:
    """
    List strategies.

    Returns:
        Paginated list of strategy summaries (stub returns empty list).
    """
    logger.info("strategies.list.called")
    return {"success": True, "data": []}


# ---------------------------------------------------------------------------
# Draft autosave endpoints (M13 gap G-10 — spec Section 7.5 / 8.8)
# ---------------------------------------------------------------------------


@router.post(
    "/draft/autosave",
    summary="Save a draft strategy autosave",
)
async def post_draft_autosave(payload: DraftAutosavePayload) -> dict:
    """
    Persist a draft strategy autosave for the given user.

    The frontend calls this endpoint every 30 seconds and on every field blur.
    The draft_payload may be incomplete — partial validation only, not full
    StrategyDraftInput validation.

    Autosaves older than 30 days are purged from the server (enforced by a
    background cleanup job, not here).

    Args:
        payload: DraftAutosavePayload containing user_id, draft_payload,
                 form_step, client_ts, and session_id.

    Returns:
        Dict with autosave_id and saved_at timestamp (ISO-8601).

    Raises:
        HTTPException 422: If required fields are missing.

    Example:
        POST /strategies/draft/autosave
        {"user_id": "01H...", "draft_payload": {"name": "S1"}, ...}
        → 200 {"autosave_id": "01H...", "saved_at": "2026-03-28T11:00:01Z"}
    """
    repo = _repo_instance()
    result = repo.create(
        user_id=payload.user_id,
        draft_payload=payload.draft_payload,
        form_step=payload.form_step,
        session_id=payload.session_id,
        client_ts=payload.client_ts,
    )

    logger.info(
        "draft.autosave.saved",
        autosave_id=result["autosave_id"],
        user_id=payload.user_id,
        form_step=payload.form_step,
    )

    return result


@router.get(
    "/draft/autosave/latest",
    summary="Retrieve the latest draft autosave for a user",
)
async def get_latest_draft_autosave(
    user_id: Optional[str] = Query(
        None,
        description="ULID of the user whose latest autosave to fetch",
    ),
) -> Any:
    """
    Return the most recent autosave for the given user, or 204 if none exists.

    Called on login to offer the DraftRecoveryBanner. Autosaves older than
    30 days are excluded (enforced by SQL query in production; mock returns
    whatever is in memory).

    Args:
        user_id: Query parameter — ULID of the user.

    Returns:
        200 with the most recent autosave record if found.
        204 No Content if no autosave exists for the user.

    Raises:
        HTTPException 422: If user_id query param is missing.

    Example:
        GET /strategies/draft/autosave/latest?user_id=01H...
        → 200 {"autosave_id": "01H...", "draft_payload": {...}, ...}
    """
    # Manual validation — pydantic Query(...) 422 enforcement is broken in this env.
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="user_id query parameter is required",
        )

    repo = _repo_instance()
    latest = repo.get_latest(user_id=user_id)

    if latest is None:
        logger.debug("draft.autosave.latest.none", user_id=user_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    logger.debug(
        "draft.autosave.latest.found",
        user_id=user_id,
        autosave_id=latest["autosave_id"],
    )
    return latest


@router.delete(
    "/draft/autosave/{autosave_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Discard a draft autosave",
)
async def delete_draft_autosave(
    autosave_id: str = Path(..., description="Autosave ULID to discard"),
) -> None:
    """
    Explicitly discard a draft autosave record.

    Called when the user selects 'Start Fresh' from the DraftRecoveryBanner.

    Args:
        autosave_id: ULID of the autosave record to delete.

    Returns:
        204 No Content on success.

    Raises:
        HTTPException 404: If autosave_id is not found.

    Example:
        DELETE /strategies/draft/autosave/01H...
        → 204 No Content
    """
    repo = _repo_instance()
    deleted = repo.delete(autosave_id=autosave_id)

    if not deleted:
        logger.warning("draft.autosave.delete.not_found", autosave_id=autosave_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Autosave '{autosave_id}' not found.",
        )

    logger.info("draft.autosave.deleted", autosave_id=autosave_id)
    # FastAPI returns 204 with no body when the function returns None
    # and status_code=204 is set on the decorator.
