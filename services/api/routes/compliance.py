"""
Compliance report API endpoints.

Responsibilities:
- Expose execution compliance report endpoint for a deployment.
- Expose best execution analysis endpoint.
- Expose venue routing statistics endpoint.
- Expose monthly summary endpoint.
- Expose CSV export endpoint.
- Delegate all business logic to ComplianceReportService.
- Map domain errors to HTTP status codes.

Does NOT:
- Contain compliance analysis logic.
- Access adapters, repositories, or services directly.

Dependencies:
- ComplianceReportServiceInterface (injected via module-level DI).
- libs.contracts.compliance_report schemas.

Error conditions:
- 404 Not Found: deployment or resource not found.
- 422 Unprocessable Entity: invalid request parameters (date range, month format).
- 401 Unauthorized: missing or invalid authentication.
- 403 Forbidden: insufficient scope (compliance:read required).

Example:
    GET  /compliance/execution-report?date_from=...&date_to=... → 200 {report}
    GET  /compliance/best-execution?date_from=...&date_to=... → 200 {report}
    GET  /compliance/venue-routing?date_from=...&date_to=... → 200 {report}
    GET  /compliance/monthly-summary?month=YYYY-MM → 200 {summary}
    GET  /compliance/execution-report/csv?date_from=...&date_to=... → 200 text/csv
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from libs.contracts.errors import NotFoundError
from services.api.auth import AuthenticatedUser, require_scope
from services.api.services.interfaces.compliance_report_service_interface import (
    ComplianceReportServiceInterface,
)

logger = structlog.get_logger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Module-level DI
# ---------------------------------------------------------------------------

_service: ComplianceReportServiceInterface | None = None


def set_compliance_report_service(svc: ComplianceReportServiceInterface) -> None:
    """
    Inject the compliance report service instance.

    Args:
        svc: ComplianceReportServiceInterface implementation.
    """
    global _service  # noqa: PLW0603
    _service = svc


def get_compliance_report_service() -> ComplianceReportServiceInterface:
    """
    Retrieve the compliance report service.

    Returns:
        The injected ComplianceReportServiceInterface.

    Raises:
        RuntimeError: if no service has been injected.
    """
    if _service is None:
        raise RuntimeError("ComplianceReportService not configured")
    return _service


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _compliance_order_to_dict(record: Any) -> dict[str, Any]:
    """
    Serialize a ComplianceOrderRecord to a JSON-compatible dict.

    Args:
        record: ComplianceOrderRecord to serialize.

    Returns:
        Dict suitable for JSON response.
    """
    return {
        "order_id": record.order_id,
        "client_order_id": record.client_order_id,
        "broker_order_id": record.broker_order_id,
        "symbol": record.symbol,
        "side": record.side,
        "order_type": record.order_type,
        "quantity": str(record.quantity),
        "filled_quantity": str(record.filled_quantity),
        "average_fill_price": str(record.average_fill_price) if record.average_fill_price else None,
        "limit_price": str(record.limit_price) if record.limit_price else None,
        "status": record.status,
        "execution_mode": record.execution_mode,
        "venue": record.venue,
        "submitted_at": record.submitted_at.isoformat() if record.submitted_at else None,
        "filled_at": record.filled_at.isoformat() if record.filled_at else None,
        "cancelled_at": record.cancelled_at.isoformat() if record.cancelled_at else None,
        "commission": str(record.commission),
        "correlation_id": record.correlation_id,
    }


def _execution_report_to_dict(report: Any) -> dict[str, Any]:
    """
    Serialize an ExecutionComplianceReport to a JSON-compatible dict.

    Args:
        report: ExecutionComplianceReport to serialize.

    Returns:
        Dict suitable for JSON response.
    """
    return {
        "report_id": report.report_id,
        "date_from": report.date_from.isoformat(),
        "date_to": report.date_to.isoformat(),
        "generated_at": report.generated_at.isoformat(),
        "total_orders": report.total_orders,
        "total_filled": report.total_filled,
        "total_cancelled": report.total_cancelled,
        "total_rejected": report.total_rejected,
        "total_volume": str(report.total_volume),
        "total_commission": str(report.total_commission),
        "orders": [_compliance_order_to_dict(o) for o in report.orders],
    }


def _best_execution_to_dict(report: Any) -> dict[str, Any]:
    """
    Serialize a BestExecutionReport to a JSON-compatible dict.

    Args:
        report: BestExecutionReport to serialize.

    Returns:
        Dict suitable for JSON response.
    """
    return {
        "report_id": report.report_id,
        "date_from": report.date_from.isoformat(),
        "date_to": report.date_to.isoformat(),
        "generated_at": report.generated_at.isoformat(),
        "total_analyzed": report.total_analyzed,
        "avg_price_improvement_bps": (
            str(report.avg_price_improvement_bps)
            if report.avg_price_improvement_bps is not None
            else None
        ),
        "avg_slippage_bps": (
            str(report.avg_slippage_bps) if report.avg_slippage_bps is not None else None
        ),
        "avg_fill_latency_ms": report.avg_fill_latency_ms,
        "pct_with_price_improvement": (
            str(report.pct_with_price_improvement)
            if report.pct_with_price_improvement is not None
            else None
        ),
        "records": [
            {
                "order_id": r.order_id,
                "symbol": r.symbol,
                "side": r.side,
                "fill_price": str(r.fill_price),
                "nbbo_bid": str(r.nbbo_bid) if r.nbbo_bid else None,
                "nbbo_ask": str(r.nbbo_ask) if r.nbbo_ask else None,
                "nbbo_midpoint": str(r.nbbo_midpoint) if r.nbbo_midpoint else None,
                "price_improvement": (
                    str(r.price_improvement) if r.price_improvement is not None else None
                ),
                "slippage_bps": str(r.slippage_bps) if r.slippage_bps is not None else None,
                "fill_latency_ms": r.fill_latency_ms,
                "venue": r.venue,
                "filled_at": r.filled_at.isoformat() if r.filled_at else None,
            }
            for r in report.records
        ],
    }


def _venue_routing_to_dict(report: Any) -> dict[str, Any]:
    """
    Serialize a VenueRoutingReport to a JSON-compatible dict.

    Args:
        report: VenueRoutingReport to serialize.

    Returns:
        Dict suitable for JSON response.
    """
    return {
        "report_id": report.report_id,
        "date_from": report.date_from.isoformat(),
        "date_to": report.date_to.isoformat(),
        "generated_at": report.generated_at.isoformat(),
        "venues": [
            {
                "venue": v.venue,
                "total_orders": v.total_orders,
                "filled_orders": v.filled_orders,
                "fill_rate": str(v.fill_rate),
                "total_volume": str(v.total_volume),
                "avg_fill_latency_ms": v.avg_fill_latency_ms,
            }
            for v in report.venues
        ],
    }


def _monthly_summary_to_dict(summary: Any) -> dict[str, Any]:
    """
    Serialize a MonthlySummary to a JSON-compatible dict.

    Args:
        summary: MonthlySummary to serialize.

    Returns:
        Dict suitable for JSON response.
    """
    return {
        "report_id": summary.report_id,
        "month": summary.month,
        "generated_at": summary.generated_at.isoformat(),
        "total_orders": summary.total_orders,
        "total_filled": summary.total_filled,
        "total_cancelled": summary.total_cancelled,
        "total_rejected": summary.total_rejected,
        "total_volume": str(summary.total_volume),
        "total_commission": str(summary.total_commission),
        "fill_rate": str(summary.fill_rate),
        "error_rate": str(summary.error_rate),
        "unique_symbols": summary.unique_symbols,
        "unique_venues": summary.unique_venues,
        "avg_fill_latency_ms": summary.avg_fill_latency_ms,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/execution-report",
    summary="Generate execution compliance report",
    response_model=None,
)
async def get_execution_report(
    date_from: str = Query(
        ...,
        description="Report start date (ISO 8601 format)",
    ),
    date_to: str = Query(
        ...,
        description="Report end date (ISO 8601 format)",
    ),
    deployment_id: str | None = Query(
        None,
        description="Optional filter by deployment ULID",
    ),
    _user: AuthenticatedUser = Depends(require_scope("compliance:read")),
) -> dict[str, Any]:
    """
    Generate execution compliance report for regulatory review.

    Produces a detailed execution report suitable for regulatory review
    (SEC Rule 606, FINRA, MiFID II, etc.). Includes per-order records
    with timestamps, fills, commissions, and execution details.

    Args:
        date_from: Report start date (ISO 8601 string, required).
        date_to: Report end date (ISO 8601 string, required).
        deployment_id: Optional filter to specific deployment (optional).

    Returns:
        ExecutionComplianceReport as JSON dict with order records and totals.

    Raises:
        HTTPException 422: invalid date format or missing required parameters.
        HTTPException 401: missing or invalid authentication.
        HTTPException 403: insufficient scope (compliance:read required).
    """
    svc = get_compliance_report_service()

    # Parse dates
    try:
        date_from_dt = datetime.fromisoformat(date_from.replace("Z", "+00:00").replace(" ", "+"))
        date_to_dt = datetime.fromisoformat(date_to.replace("Z", "+00:00").replace(" ", "+"))
    except (ValueError, TypeError) as exc:
        logger.warning(
            "compliance.invalid_date_format",
            component="compliance_route",
            operation="get_execution_report",
            date_from=date_from,
            date_to=date_to,
        )
        raise HTTPException(status_code=422, detail=f"Invalid date format: {exc}") from exc

    try:
        report = svc.get_execution_report(
            date_from=date_from_dt,
            date_to=date_to_dt,
            deployment_id=deployment_id,
        )
    except ValueError as exc:
        logger.warning(
            "compliance.execution_report_validation_error",
            component="compliance_route",
            operation="get_execution_report",
            error=str(exc),
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NotFoundError as exc:
        logger.warning(
            "compliance.deployment_not_found",
            component="compliance_route",
            operation="get_execution_report",
            deployment_id=deployment_id,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    logger.info(
        "compliance.execution_report_generated",
        component="compliance_route",
        operation="get_execution_report",
        report_id=report.report_id,
        total_orders=report.total_orders,
        deployment_id=deployment_id,
    )

    return _execution_report_to_dict(report)


@router.get(
    "/best-execution",
    summary="Generate best execution analysis report",
    response_model=None,
)
async def get_best_execution(
    date_from: str = Query(
        ...,
        description="Report start date (ISO 8601 format)",
    ),
    date_to: str = Query(
        ...,
        description="Report end date (ISO 8601 format)",
    ),
    deployment_id: str | None = Query(
        None,
        description="Optional filter by deployment ULID",
    ),
    _user: AuthenticatedUser = Depends(require_scope("compliance:read")),
) -> dict[str, Any]:
    """
    Generate best execution analysis report for filled orders.

    Compares actual fill prices against National Best Bid/Offer (NBBO)
    and limit prices to quantify execution quality and price improvement.
    Supports MiFID II and SEC Rule 606(c) best execution reporting.

    Args:
        date_from: Report start date (ISO 8601 string, required).
        date_to: Report end date (ISO 8601 string, required).
        deployment_id: Optional filter to specific deployment (optional).

    Returns:
        BestExecutionReport as JSON dict with price and latency analysis.

    Raises:
        HTTPException 422: invalid date format or missing required parameters.
        HTTPException 401: missing or invalid authentication.
        HTTPException 403: insufficient scope (compliance:read required).
    """
    svc = get_compliance_report_service()

    # Parse dates
    try:
        date_from_dt = datetime.fromisoformat(date_from.replace("Z", "+00:00").replace(" ", "+"))
        date_to_dt = datetime.fromisoformat(date_to.replace("Z", "+00:00").replace(" ", "+"))
    except (ValueError, TypeError) as exc:
        logger.warning(
            "compliance.invalid_date_format",
            component="compliance_route",
            operation="get_best_execution",
            date_from=date_from,
            date_to=date_to,
        )
        raise HTTPException(status_code=422, detail=f"Invalid date format: {exc}") from exc

    try:
        report = svc.get_best_execution(
            date_from=date_from_dt,
            date_to=date_to_dt,
            deployment_id=deployment_id,
        )
    except ValueError as exc:
        logger.warning(
            "compliance.best_execution_validation_error",
            component="compliance_route",
            operation="get_best_execution",
            error=str(exc),
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NotFoundError as exc:
        logger.warning(
            "compliance.deployment_not_found",
            component="compliance_route",
            operation="get_best_execution",
            deployment_id=deployment_id,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    logger.info(
        "compliance.best_execution_generated",
        component="compliance_route",
        operation="get_best_execution",
        report_id=report.report_id,
        total_analyzed=report.total_analyzed,
        deployment_id=deployment_id,
    )

    return _best_execution_to_dict(report)


@router.get(
    "/venue-routing",
    summary="Generate venue routing report",
    response_model=None,
)
async def get_venue_routing(
    date_from: str = Query(
        ...,
        description="Report start date (ISO 8601 format)",
    ),
    date_to: str = Query(
        ...,
        description="Report end date (ISO 8601 format)",
    ),
    deployment_id: str | None = Query(
        None,
        description="Optional filter by deployment ULID",
    ),
    _user: AuthenticatedUser = Depends(require_scope("compliance:read")),
) -> dict[str, Any]:
    """
    Generate venue routing report with per-venue execution statistics.

    Summarizes order routing and fill performance by execution venue
    (exchange, market center, etc.). Supports venue selection transparency
    and regulatory venue routing disclosure requirements.

    Args:
        date_from: Report start date (ISO 8601 string, required).
        date_to: Report end date (ISO 8601 string, required).
        deployment_id: Optional filter to specific deployment (optional).

    Returns:
        VenueRoutingReport as JSON dict with per-venue statistics.

    Raises:
        HTTPException 422: invalid date format or missing required parameters.
        HTTPException 401: missing or invalid authentication.
        HTTPException 403: insufficient scope (compliance:read required).
    """
    svc = get_compliance_report_service()

    # Parse dates
    try:
        date_from_dt = datetime.fromisoformat(date_from.replace("Z", "+00:00").replace(" ", "+"))
        date_to_dt = datetime.fromisoformat(date_to.replace("Z", "+00:00").replace(" ", "+"))
    except (ValueError, TypeError) as exc:
        logger.warning(
            "compliance.invalid_date_format",
            component="compliance_route",
            operation="get_venue_routing",
            date_from=date_from,
            date_to=date_to,
        )
        raise HTTPException(status_code=422, detail=f"Invalid date format: {exc}") from exc

    try:
        report = svc.get_venue_routing(
            date_from=date_from_dt,
            date_to=date_to_dt,
            deployment_id=deployment_id,
        )
    except ValueError as exc:
        logger.warning(
            "compliance.venue_routing_validation_error",
            component="compliance_route",
            operation="get_venue_routing",
            error=str(exc),
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NotFoundError as exc:
        logger.warning(
            "compliance.deployment_not_found",
            component="compliance_route",
            operation="get_venue_routing",
            deployment_id=deployment_id,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    logger.info(
        "compliance.venue_routing_generated",
        component="compliance_route",
        operation="get_venue_routing",
        report_id=report.report_id,
        venue_count=len(report.venues),
        deployment_id=deployment_id,
    )

    return _venue_routing_to_dict(report)


@router.get(
    "/monthly-summary",
    summary="Generate monthly compliance summary",
    response_model=None,
)
async def get_monthly_summary(
    month: str = Query(
        ...,
        description='Reporting month in "YYYY-MM" format',
        min_length=7,
        max_length=7,
    ),
    deployment_id: str | None = Query(
        None,
        description="Optional filter by deployment ULID",
    ),
    _user: AuthenticatedUser = Depends(require_scope("compliance:read")),
) -> dict[str, Any]:
    """
    Generate monthly aggregate compliance summary.

    High-level executive summary of trading activity for a single
    calendar month. Used for trend analysis, management reporting,
    and regulatory month-end disclosures.

    Args:
        month: Reporting month in "YYYY-MM" format (required).
        deployment_id: Optional filter to specific deployment (optional).

    Returns:
        MonthlySummary as JSON dict with aggregate metrics.

    Raises:
        HTTPException 422: invalid month format or missing required parameters.
        HTTPException 401: missing or invalid authentication.
        HTTPException 403: insufficient scope (compliance:read required).
    """
    svc = get_compliance_report_service()

    try:
        report = svc.get_monthly_summary(
            month=month,
            deployment_id=deployment_id,
        )
    except ValueError as exc:
        logger.warning(
            "compliance.monthly_summary_validation_error",
            component="compliance_route",
            operation="get_monthly_summary",
            month=month,
            error=str(exc),
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NotFoundError as exc:
        logger.warning(
            "compliance.deployment_not_found",
            component="compliance_route",
            operation="get_monthly_summary",
            deployment_id=deployment_id,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    logger.info(
        "compliance.monthly_summary_generated",
        component="compliance_route",
        operation="get_monthly_summary",
        report_id=report.report_id,
        month=month,
        total_orders=report.total_orders,
        deployment_id=deployment_id,
    )

    return _monthly_summary_to_dict(report)


@router.get(
    "/execution-report/csv",
    summary="Export execution report as CSV",
    response_model=None,
)
async def export_execution_report_csv(
    date_from: str = Query(
        ...,
        description="Report start date (ISO 8601 format)",
    ),
    date_to: str = Query(
        ...,
        description="Report end date (ISO 8601 format)",
    ),
    deployment_id: str | None = Query(
        None,
        description="Optional filter by deployment ULID",
    ),
    _user: AuthenticatedUser = Depends(require_scope("compliance:read")),
) -> Response:
    """
    Export execution compliance report as CSV file.

    Converts an execution compliance report into comma-separated values
    format suitable for download, archival, external analysis, or
    regulatory submission.

    Args:
        date_from: Report start date (ISO 8601 string, required).
        date_to: Report end date (ISO 8601 string, required).
        deployment_id: Optional filter to specific deployment (optional).

    Returns:
        Response with CSV content and appropriate content-type headers.

    Raises:
        HTTPException 422: invalid date format or missing required parameters.
        HTTPException 401: missing or invalid authentication.
        HTTPException 403: insufficient scope (compliance:read required).
    """
    svc = get_compliance_report_service()

    # Parse dates
    try:
        date_from_dt = datetime.fromisoformat(date_from.replace("Z", "+00:00").replace(" ", "+"))
        date_to_dt = datetime.fromisoformat(date_to.replace("Z", "+00:00").replace(" ", "+"))
    except (ValueError, TypeError) as exc:
        logger.warning(
            "compliance.invalid_date_format",
            component="compliance_route",
            operation="export_execution_report_csv",
            date_from=date_from,
            date_to=date_to,
        )
        raise HTTPException(status_code=422, detail=f"Invalid date format: {exc}") from exc

    try:
        # First get the execution report
        report = svc.get_execution_report(
            date_from=date_from_dt,
            date_to=date_to_dt,
            deployment_id=deployment_id,
        )
        # Then export it to CSV
        csv_content = svc.export_csv(report=report)
    except ValueError as exc:
        logger.warning(
            "compliance.export_validation_error",
            component="compliance_route",
            operation="export_execution_report_csv",
            error=str(exc),
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NotFoundError as exc:
        logger.warning(
            "compliance.deployment_not_found",
            component="compliance_route",
            operation="export_execution_report_csv",
            deployment_id=deployment_id,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    logger.info(
        "compliance.execution_report_exported_csv",
        component="compliance_route",
        operation="export_execution_report_csv",
        csv_bytes=len(csv_content.encode("utf-8")),
        deployment_id=deployment_id,
    )

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=execution_report.csv"},
    )


__all__ = ["router", "set_compliance_report_service", "get_compliance_report_service"]
