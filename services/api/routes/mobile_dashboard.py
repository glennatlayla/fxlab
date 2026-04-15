"""
Mobile dashboard API endpoints.

Responsibilities:
- Expose GET /mobile/dashboard endpoint for aggregated trading metrics.
- Delegate all aggregation logic to MobileDashboardService.
- Handle authentication and error responses.
- Return JSON-serialized MobileDashboardSummary.

Does NOT:
- Contain aggregation logic (service responsibility).
- Access adapters or repositories directly.

Dependencies:
- MobileDashboardService (request-scoped, injected via get_mobile_dashboard_service).
- get_current_user (FastAPI dependency): ensures authentication.
- libs.contracts.mobile_dashboard: MobileDashboardSummary.

Error conditions:
- 401 Unauthorized: missing or invalid authentication.
- 500 Internal Server Error: unhandled service exceptions.

Example:
    GET /mobile/dashboard HTTP/1.1
    Authorization: Bearer <TOKEN>

    Response (200):
    {
        "active_runs": 3,
        "completed_runs_24h": 5,
        "pending_approvals": 2,
        "active_kill_switches": 1,
        "pnl_today_usd": 1250.50,
        "last_alert_severity": "warning",
        "last_alert_message": "Position delta exceeds threshold",
        "generated_at": "2026-04-13T14:30:00+00:00"
    }
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from libs.contracts.interfaces.mobile_dashboard_service_interface import (
    MobileDashboardServiceInterface,
)
from libs.contracts.mobile_dashboard import MobileDashboardSummary
from services.api.auth import AuthenticatedUser, get_current_user
from services.api.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mobile", tags=["mobile"])

# ---------------------------------------------------------------------------
# Request-scoped dependency provider — no module-level singletons.
# ---------------------------------------------------------------------------


def get_mobile_dashboard_service(
    db: Session = Depends(get_db),
) -> MobileDashboardServiceInterface:
    """
    Provide a request-scoped MobileDashboardService.

    Constructs the service with SQL-backed repositories bound to the current
    request's DB session. Session is closed automatically by FastAPI's
    get_db dependency when the request completes.

    Args:
        db: SQLAlchemy session injected by FastAPI per request.

    Returns:
        MobileDashboardService wired to request-scoped dependencies.
    """
    from services.api.repositories.sql_approval_repository import SqlApprovalRepository
    from services.api.repositories.sql_kill_switch_event_repository import (
        SqlKillSwitchEventRepository,
    )
    from services.api.repositories.sql_research_run_repository import (
        SqlResearchRunRepository,
    )
    from services.api.services.mobile_dashboard_service import MobileDashboardService

    research_run_repo = SqlResearchRunRepository(db=db)
    approval_repo = SqlApprovalRepository(db=db)
    kill_switch_repo = SqlKillSwitchEventRepository(db=db)

    return MobileDashboardService(
        research_run_repo=research_run_repo,
        approval_repo=approval_repo,
        kill_switch_event_repo=kill_switch_repo,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/dashboard",
    response_model=MobileDashboardSummary,
)
def get_dashboard(
    user: AuthenticatedUser = Depends(get_current_user),
    service: MobileDashboardServiceInterface = Depends(get_mobile_dashboard_service),
) -> MobileDashboardSummary:
    """
    Retrieve aggregated mobile dashboard summary.

    Queries multiple data sources (research runs, approvals, kill switches,
    alerts) and returns a single aggregated response optimized for mobile UX.

    Args:
        user: Authenticated user (enforced by Depends(get_current_user)).
        service: Request-scoped MobileDashboardService.

    Returns:
        MobileDashboardSummary with all metrics populated.

    Raises:
        HTTPException: on unhandled service exceptions (mapped to 500).

    Example:
        GET /mobile/dashboard HTTP/1.1
        Authorization: Bearer <TOKEN>

        Response (200):
        {
            "active_runs": 3,
            "completed_runs_24h": 5,
            ...
        }
    """
    logger.info(
        "Fetching mobile dashboard summary",
        extra={
            "user_id": user.user_id,
            "operation": "get_mobile_dashboard",
        },
    )

    summary = service.get_summary()

    logger.info(
        "Mobile dashboard summary retrieved",
        extra={
            "user_id": user.user_id,
            "operation": "get_mobile_dashboard",
            "active_runs": summary.active_runs,
            "pending_approvals": summary.pending_approvals,
        },
    )

    return summary
