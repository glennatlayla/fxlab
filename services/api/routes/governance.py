"""
Governance list endpoint.

Responsibilities:
- Expose a list endpoint for governance items (overrides + approvals).
- Emit structured log events with correlation IDs.
- Return 501 until M29 (Governance Workflows Frontend) wires the endpoint
  to real override and approval repositories.

Does NOT:
- Contain business logic.
- Access the database directly.

Dependencies:
- structlog for structured logging.
- FastAPI for routing and HTTP exceptions.
- services.api.auth for authentication and scope enforcement.
- services.api.middleware.correlation for correlation_id_var.

Example:
    GET /governance/  → 501 {"detail": "Governance list not yet implemented. Planned for M29."}
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from services.api.auth import AuthenticatedUser, require_any_scope
from services.api.middleware.correlation import correlation_id_var

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/")
async def list_governance_items(
    user: AuthenticatedUser = Depends(require_any_scope("approvals:write", "overrides:request")),
) -> JSONResponse:
    """
    List governance items (overrides + approvals).

    This endpoint is not yet wired to real repositories. It returns 501
    Not Implemented so that callers know the absence of data is intentional,
    not a bug. Full listing will be implemented in M29 (Governance Workflows
    Frontend) when the UI requires paginated governance item queries.

    Args:
        user: Authenticated user with approvals:write or overrides:request scope.

    Returns:
        JSONResponse with 501 status and detail explaining the deferral.

    Raises:
        HTTPException 401: If the user is not authenticated.
        HTTPException 403: If the user lacks the required scope.

    Example:
        GET /governance/
        → 501 {"detail": "Governance item listing not yet implemented. Planned for M29 (Governance Workflows Frontend)."}
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "governance.list.called",
        component="governance",
        correlation_id=corr_id,
        user_id=user.user_id,
        result="not_implemented",
    )
    return JSONResponse(
        status_code=501,
        content={
            "detail": (
                "Governance item listing not yet implemented. "
                "Planned for M29 (Governance Workflows Frontend)."
            ),
        },
    )
