"""
Reconciliation API endpoints.

Responsibilities:
- Expose reconciliation run trigger endpoint.
- Expose reconciliation report retrieval endpoints.
- Delegate all business logic to the ReconciliationService.
- Map domain errors to HTTP status codes.

Does NOT:
- Contain reconciliation logic.
- Access the database or broker adapters directly.

Dependencies:
- ReconciliationServiceInterface (injected via module-level DI).
- libs.contracts.reconciliation: ReconciliationTrigger.
- structlog for structured logging.

Error conditions:
- 404 Not Found: deployment or report not found.
- 422 Unprocessable Entity: invalid trigger or missing query params.

Example:
    POST /reconciliation/{deployment_id}/run  → 200 {report}
    GET  /reconciliation/reports/{report_id}  → 200 {report}
    GET  /reconciliation/reports?deployment_id=... → 200 [{report}]
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.reconciliation_service_interface import (
    ReconciliationServiceInterface,
)
from libs.contracts.reconciliation import (
    ReconciliationReport,
    ReconciliationTrigger,
)
from services.api.auth import require_scope

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Module-level DI for the reconciliation service
# ---------------------------------------------------------------------------

_reconciliation_service: ReconciliationServiceInterface | None = None


def set_reconciliation_service(service: ReconciliationServiceInterface) -> None:
    """
    Inject the reconciliation service implementation.

    Called during application bootstrap or test setup.

    Args:
        service: ReconciliationServiceInterface implementation.
    """
    global _reconciliation_service
    _reconciliation_service = service


def get_reconciliation_service() -> ReconciliationServiceInterface:
    """
    Retrieve the injected reconciliation service.

    Returns:
        The configured ReconciliationServiceInterface.

    Raises:
        RuntimeError: if no service has been injected.
    """
    if _reconciliation_service is None:
        raise RuntimeError(
            "ReconciliationService not configured. "
            "Call set_reconciliation_service() during app bootstrap."
        )
    return _reconciliation_service


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ReconciliationRunBody(BaseModel):
    """Request body for triggering a reconciliation run."""

    trigger: ReconciliationTrigger = Field(
        ..., description="What triggered this reconciliation run."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _report_to_dict(report: ReconciliationReport) -> dict:
    """
    Convert a ReconciliationReport to a JSON-serializable dict.

    Args:
        report: The reconciliation report to convert.

    Returns:
        Dict suitable for JSON response.
    """
    return {
        "report_id": report.report_id,
        "deployment_id": report.deployment_id,
        "trigger": report.trigger.value,
        "discrepancies": [
            {
                "discrepancy_type": d.discrepancy_type.value,
                "entity_type": d.entity_type,
                "entity_id": d.entity_id,
                "symbol": d.symbol,
                "field": d.field,
                "internal_value": d.internal_value,
                "broker_value": d.broker_value,
                "auto_resolved": d.auto_resolved,
                "resolution": d.resolution,
            }
            for d in report.discrepancies
        ],
        "resolved_count": report.resolved_count,
        "unresolved_count": report.unresolved_count,
        "status": report.status,
        "orders_checked": report.orders_checked,
        "positions_checked": report.positions_checked,
        "created_at": report.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{deployment_id}/run",
    dependencies=[Depends(require_scope("deployments:read"))],
)
def run_reconciliation(
    deployment_id: str,
    body: ReconciliationRunBody,
) -> dict:
    """
    Trigger a reconciliation run for a deployment.

    Compares internal state against broker state and returns a report
    of all discrepancies found.

    Args:
        deployment_id: ULID of the deployment.
        body: Request body containing the trigger type.

    Returns:
        ReconciliationReport as JSON dict.

    Raises:
        HTTPException 404: deployment not found or no adapter registered.
    """
    service = get_reconciliation_service()
    try:
        report = service.run_reconciliation(
            deployment_id=deployment_id,
            trigger=body.trigger,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    logger.info(
        "Reconciliation run completed via API",
        extra={
            "operation": "reconciliation_run_api",
            "component": "reconciliation_routes",
            "deployment_id": deployment_id,
            "report_id": report.report_id,
            "status": report.status,
        },
    )
    return _report_to_dict(report)


@router.get(
    "/reports/{report_id}",
    dependencies=[Depends(require_scope("deployments:read"))],
)
def get_report(report_id: str) -> dict:
    """
    Get a specific reconciliation report by ID.

    Args:
        report_id: ULID of the reconciliation report.

    Returns:
        ReconciliationReport as JSON dict.

    Raises:
        HTTPException 404: report not found.
    """
    service = get_reconciliation_service()
    try:
        report = service.get_report(report_id=report_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _report_to_dict(report)


@router.get(
    "/reports",
    dependencies=[Depends(require_scope("deployments:read"))],
)
def list_reports(
    deployment_id: str = Query(..., description="ULID of the deployment."),
    limit: int = Query(default=20, ge=1, le=100, description="Max reports."),
) -> list[dict]:
    """
    List reconciliation reports for a deployment.

    Args:
        deployment_id: ULID of the deployment (required query param).
        limit: Maximum number of reports to return (1-100, default 20).

    Returns:
        List of ReconciliationReport dicts, most recent first.
    """
    service = get_reconciliation_service()
    reports = service.list_reports(deployment_id=deployment_id, limit=limit)
    return [_report_to_dict(r) for r in reports]
