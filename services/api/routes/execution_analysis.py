"""
Execution analysis API endpoints.

Responsibilities:
- Expose drift computation endpoint for a deployment.
- Expose order timeline replay endpoint.
- Expose correlation ID search endpoint.
- Delegate all business logic to ExecutionAnalysisService.
- Map domain errors to HTTP status codes.

Does NOT:
- Contain drift computation logic.
- Access adapters, repositories, or event stores directly.

Dependencies:
- ExecutionAnalysisInterface (injected via module-level DI).
- libs.contracts.drift schemas.
- libs.contracts.execution schemas.

Error conditions:
- 404 Not Found: deployment or order not found.
- 422 Unprocessable Entity: invalid request body or missing parameters.

Example:
    POST /execution-analysis/{deployment_id}/drift   → 200 {drift_report}
    GET  /execution-analysis/timeline/{order_id}     → 200 {timeline}
    GET  /execution-analysis/search?correlation_id=X → 200 [{event}]
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from libs.contracts.drift import (
    DriftReport,
    ReplayTimeline,
)
from libs.contracts.errors import NotFoundError
from libs.contracts.execution import OrderEvent
from libs.contracts.execution_report import OrderHistoryQuery
from libs.contracts.interfaces.execution_analysis_interface import (
    ExecutionAnalysisInterface,
)
from services.api.auth import AuthenticatedUser, require_scope

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Module-level DI
# ---------------------------------------------------------------------------

_service: ExecutionAnalysisInterface | None = None


def set_execution_analysis_service(svc: ExecutionAnalysisInterface) -> None:
    """
    Inject the execution analysis service instance.

    Args:
        svc: ExecutionAnalysisInterface implementation.
    """
    global _service  # noqa: PLW0603
    _service = svc


def get_execution_analysis_service() -> ExecutionAnalysisInterface:
    """
    Retrieve the execution analysis service.

    Returns:
        The injected ExecutionAnalysisInterface.

    Raises:
        RuntimeError: if no service has been injected.
    """
    if _service is None:
        raise RuntimeError("ExecutionAnalysisService not configured")
    return _service


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ComputeDriftBody(BaseModel):
    """Request body for drift computation."""

    window: str = Field(
        ...,
        description="Time window for analysis (e.g., '1h', '24h', '7d').",
        min_length=1,
    )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _report_to_dict(report: DriftReport) -> dict[str, Any]:
    """
    Serialize a DriftReport to a JSON-compatible dict.

    Args:
        report: DriftReport to serialize.

    Returns:
        Dict suitable for JSON response.
    """
    return {
        "report_id": report.report_id,
        "deployment_id": report.deployment_id,
        "window": report.window,
        "metrics": [
            {
                "metric_name": m.metric_name,
                "expected_value": str(m.expected_value),
                "actual_value": str(m.actual_value),
                "drift_pct": str(m.drift_pct),
                "severity": m.severity.value,
                "symbol": m.symbol,
                "order_id": m.order_id,
                "details": m.details,
            }
            for m in report.metrics
        ],
        "max_severity": report.max_severity.value,
        "total_metrics": report.total_metrics,
        "critical_count": report.critical_count,
        "significant_count": report.significant_count,
        "minor_count": report.minor_count,
        "negligible_count": report.negligible_count,
        "created_at": report.created_at.isoformat(),
    }


def _timeline_to_dict(timeline: ReplayTimeline) -> dict[str, Any]:
    """
    Serialize a ReplayTimeline to a JSON-compatible dict.

    Args:
        timeline: ReplayTimeline to serialize.

    Returns:
        Dict suitable for JSON response.
    """
    return {
        "order_id": timeline.order_id,
        "deployment_id": timeline.deployment_id,
        "symbol": timeline.symbol,
        "correlation_id": timeline.correlation_id,
        "events": [
            {
                "event_type": e.event_type,
                "timestamp": e.timestamp.isoformat(),
                "details": e.details,
                "source": e.source,
            }
            for e in timeline.events
        ],
        "created_at": timeline.created_at.isoformat(),
    }


def _event_to_dict(event: OrderEvent) -> dict[str, Any]:
    """
    Serialize an OrderEvent to a JSON-compatible dict.

    Args:
        event: OrderEvent to serialize.

    Returns:
        Dict suitable for JSON response.
    """
    return {
        "event_id": event.event_id,
        "order_id": event.order_id,
        "event_type": event.event_type,
        "timestamp": event.timestamp.isoformat(),
        "details": event.details,
        "correlation_id": event.correlation_id,
    }


def _order_history_page_to_dict(page) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """
    Serialize an OrderHistoryPage to a JSON-compatible dict.

    Args:
        page: OrderHistoryPage to serialize.

    Returns:
        Dict suitable for JSON response.
    """
    return {
        "items": [
            {
                "order_id": item.order_id,
                "client_order_id": item.client_order_id,
                "broker_order_id": item.broker_order_id,
                "deployment_id": item.deployment_id,
                "strategy_id": item.strategy_id,
                "symbol": item.symbol,
                "side": item.side,
                "order_type": item.order_type,
                "quantity": str(item.quantity),
                "filled_quantity": str(item.filled_quantity),
                "average_fill_price": (
                    str(item.average_fill_price) if item.average_fill_price else None
                ),
                "limit_price": str(item.limit_price) if item.limit_price else None,
                "stop_price": str(item.stop_price) if item.stop_price else None,
                "status": item.status,
                "time_in_force": item.time_in_force,
                "execution_mode": item.execution_mode,
                "correlation_id": item.correlation_id,
                "submitted_at": item.submitted_at.isoformat() if item.submitted_at else None,
                "filled_at": item.filled_at.isoformat() if item.filled_at else None,
                "cancelled_at": item.cancelled_at.isoformat() if item.cancelled_at else None,
                "rejected_reason": item.rejected_reason,
                "created_at": item.created_at.isoformat(),
                "fills": [
                    {
                        "fill_id": fill.fill_id,
                        "price": str(fill.price),
                        "quantity": str(fill.quantity),
                        "commission": str(fill.commission),
                        "filled_at": fill.filled_at.isoformat(),
                        "broker_execution_id": fill.broker_execution_id,
                    }
                    for fill in item.fills
                ],
            }
            for item in page.items
        ],
        "total": page.total,
        "page": page.page,
        "page_size": page.page_size,
        "total_pages": page.total_pages,
    }


def _execution_report_to_dict(report) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """
    Serialize an ExecutionReportSummary to a JSON-compatible dict.

    Args:
        report: ExecutionReportSummary to serialize.

    Returns:
        Dict suitable for JSON response.
    """
    return {
        "date_from": report.date_from.isoformat(),
        "date_to": report.date_to.isoformat(),
        "total_orders": report.total_orders,
        "filled_orders": report.filled_orders,
        "cancelled_orders": report.cancelled_orders,
        "rejected_orders": report.rejected_orders,
        "partial_fills": report.partial_fills,
        "fill_rate": str(report.fill_rate),
        "total_volume": str(report.total_volume),
        "total_commission": str(report.total_commission),
        "symbols_traded": report.symbols_traded,
        "avg_slippage_pct": str(report.avg_slippage_pct) if report.avg_slippage_pct else None,
        "latency_p50_ms": report.latency_p50_ms,
        "latency_p95_ms": report.latency_p95_ms,
        "latency_p99_ms": report.latency_p99_ms,
        "by_symbol": [
            {
                "symbol": bd.symbol,
                "total_orders": bd.total_orders,
                "filled_orders": bd.filled_orders,
                "fill_rate": str(bd.fill_rate),
                "total_volume": str(bd.total_volume),
                "avg_fill_price": str(bd.avg_fill_price) if bd.avg_fill_price else None,
                "avg_slippage_pct": str(bd.avg_slippage_pct) if bd.avg_slippage_pct else None,
            }
            for bd in report.by_symbol
        ],
        "by_execution_mode": [
            {
                "execution_mode": md.execution_mode,
                "total_orders": md.total_orders,
                "filled_orders": md.filled_orders,
                "fill_rate": str(md.fill_rate),
                "total_volume": str(md.total_volume),
            }
            for md in report.by_execution_mode
        ],
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{deployment_id}/drift",
    summary="Compute execution drift for a deployment",
    response_model=None,
)
async def compute_drift(
    deployment_id: str,
    body: ComputeDriftBody,
    _user: AuthenticatedUser = Depends(require_scope("deployments:read")),
) -> dict[str, Any]:
    """
    Compute execution drift by comparing actual fills against expected prices.

    Args:
        deployment_id: ULID of the deployment.
        body: Request body with time window.

    Returns:
        DriftReport as JSON dict.

    Raises:
        HTTPException 404: deployment not found.
    """
    svc = get_execution_analysis_service()
    try:
        report = svc.compute_drift(
            deployment_id=deployment_id,
            window=body.window,
        )
    except NotFoundError as exc:
        logger.warning(
            "Deployment not found for drift analysis",
            extra={
                "operation": "compute_drift_not_found",
                "component": "execution_analysis_route",
                "deployment_id": deployment_id,
            },
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    logger.info(
        "Drift analysis completed via API",
        extra={
            "operation": "compute_drift_api",
            "component": "execution_analysis_route",
            "deployment_id": deployment_id,
            "window": body.window,
            "total_metrics": report.total_metrics,
        },
    )
    return _report_to_dict(report)


@router.get(
    "/timeline/{order_id}",
    summary="Get order timeline replay",
    response_model=None,
)
async def get_timeline(
    order_id: str,
    _user: AuthenticatedUser = Depends(require_scope("deployments:read")),
) -> dict[str, Any]:
    """
    Reconstruct the full timeline for an order.

    Args:
        order_id: Client order ID.

    Returns:
        ReplayTimeline as JSON dict.

    Raises:
        HTTPException 404: order not found.
    """
    svc = get_execution_analysis_service()
    try:
        timeline = svc.get_order_timeline(order_id=order_id)
    except NotFoundError as exc:
        logger.warning(
            "Order not found for timeline replay",
            extra={
                "operation": "get_timeline_not_found",
                "component": "execution_analysis_route",
                "order_id": order_id,
            },
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    logger.info(
        "Timeline replay completed via API",
        extra={
            "operation": "get_timeline_api",
            "component": "execution_analysis_route",
            "order_id": order_id,
            "event_count": len(timeline.events),
        },
    )
    return _timeline_to_dict(timeline)


@router.get(
    "/search",
    summary="Search events by correlation ID",
    response_model=None,
)
async def search_by_correlation_id(
    correlation_id: str = Query(
        ...,
        description="Distributed tracing correlation ID.",
        min_length=1,
    ),
    _user: AuthenticatedUser = Depends(require_scope("deployments:read")),
) -> list[dict[str, Any]]:
    """
    Search for all execution events matching a correlation ID.

    Args:
        correlation_id: Distributed tracing ID (required query parameter).

    Returns:
        List of OrderEvent dicts.
    """
    svc = get_execution_analysis_service()
    events = svc.search_by_correlation_id(correlation_id=correlation_id)

    logger.info(
        "Correlation ID search completed via API",
        extra={
            "operation": "search_correlation_api",
            "component": "execution_analysis_route",
            "correlation_id": correlation_id,
            "result_count": len(events),
        },
    )
    return [_event_to_dict(e) for e in events]


# ---------------------------------------------------------------------------
# M8 Order History and Execution Report Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/orders",
    summary="Get paginated order history",
    response_model=None,
)
async def get_order_history(
    deployment_id: str | None = Query(None, description="Filter by deployment ULID"),
    symbol: str | None = Query(None, description="Filter by symbol"),
    side: str | None = Query(None, description="Filter by side (buy/sell)"),
    status: str | None = Query(None, description="Filter by order status"),
    execution_mode: str | None = Query(None, description="Filter by execution mode"),
    date_from: str | None = Query(None, description="Filter by start date (ISO 8601)"),
    date_to: str | None = Query(None, description="Filter by end date (ISO 8601)"),
    sort_by: str = Query("submitted_at", description="Sort by field"),
    sort_dir: str = Query("desc", description="Sort direction (asc/desc)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=500, description="Items per page"),
    _user: AuthenticatedUser = Depends(require_scope("deployments:read")),
) -> dict[str, Any]:
    """
    Retrieve paginated order history with filtering and sorting.

    Supports filtering by deployment, symbol, side, status, execution mode,
    and date range. Results are sorted and paginated according to parameters.

    Args:
        deployment_id: Filter to specific deployment (optional).
        symbol: Filter by symbol (optional).
        side: Filter by side: buy or sell (optional).
        status: Filter by order status (optional).
        execution_mode: Filter by execution mode (optional).
        date_from: Inclusive start date (ISO 8601 string, optional).
        date_to: Inclusive end date (ISO 8601 string, optional).
        sort_by: Column to sort by (default: submitted_at).
        sort_dir: Sort direction asc or desc (default: desc).
        page: Page number (1-indexed, default: 1).
        page_size: Items per page (default: 50, max: 500).

    Returns:
        OrderHistoryPage as JSON dict.

    Raises:
        HTTPException 422: invalid query parameters or date format.
    """
    svc = get_execution_analysis_service()

    # Parse dates if provided
    date_from_dt = None
    date_to_dt = None
    if date_from or date_to:
        try:
            if date_from:
                # Handle multiple ISO 8601 formats:
                # - With Z: 2026-04-12T00:00:00Z
                # - With +HH:MM: 2026-04-12T00:00:00+00:00
                # - Spaces instead of +: 2026-04-12T00:00:00 00:00 (URL decode issue)
                date_str = date_from.replace("Z", "+00:00").replace(" ", "+")
                date_from_dt = datetime.fromisoformat(date_str)
            if date_to:
                date_str = date_to.replace("Z", "+00:00").replace(" ", "+")
                date_to_dt = datetime.fromisoformat(date_str)
        except (ValueError, TypeError) as exc:
            logger.warning(
                "Invalid date format in order history request",
                extra={
                    "operation": "get_order_history_invalid_date",
                    "component": "execution_analysis_route",
                    "date_from": date_from,
                    "date_to": date_to,
                    "error": str(exc),
                },
            )
            raise HTTPException(status_code=422, detail=f"Invalid date format: {exc}") from exc

    # Build query
    query = OrderHistoryQuery(
        deployment_id=deployment_id,
        symbol=symbol,
        side=side,
        status=status,
        execution_mode=execution_mode,
        date_from=date_from_dt,
        date_to=date_to_dt,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
    )

    try:
        page_result = svc.get_order_history(query=query)
    except RuntimeError as exc:
        logger.error(
            "Order repository not configured",
            extra={
                "operation": "get_order_history_not_configured",
                "component": "execution_analysis_route",
            },
        )
        raise HTTPException(status_code=500, detail="Order repository not configured") from exc

    logger.info(
        "Order history retrieved via API",
        extra={
            "operation": "get_order_history_api",
            "component": "execution_analysis_route",
            "total": page_result.total,
            "page": page,
            "page_size": page_size,
            "symbol": symbol,
            "execution_mode": execution_mode,
        },
    )

    return _order_history_page_to_dict(page_result)


@router.get(
    "/report",
    summary="Get execution quality report",
    response_model=None,
)
async def get_execution_report(
    date_from: str = Query(..., description="Report start date (ISO 8601)"),
    date_to: str = Query(..., description="Report end date (ISO 8601)"),
    deployment_id: str | None = Query(None, description="Filter by deployment ULID"),
    _user: AuthenticatedUser = Depends(require_scope("deployments:read")),
) -> dict[str, Any]:
    """
    Get aggregate execution quality metrics over a date range.

    Computes fill rates, volumes, commissions, and breakdowns by symbol
    and execution mode for the specified period.

    Args:
        date_from: Report start date (ISO 8601 string, required).
        date_to: Report end date (ISO 8601 string, required).
        deployment_id: Filter to specific deployment (optional).

    Returns:
        ExecutionReportSummary as JSON dict.

    Raises:
        HTTPException 422: invalid date format or missing required parameters.
    """
    svc = get_execution_analysis_service()

    # Parse dates
    try:
        # Handle multiple ISO 8601 formats:
        # - With Z: 2026-04-12T00:00:00Z
        # - With +HH:MM: 2026-04-12T00:00:00+00:00
        # - Spaces instead of +: 2026-04-12T00:00:00 00:00 (URL decode issue)
        date_from_dt = datetime.fromisoformat(date_from.replace("Z", "+00:00").replace(" ", "+"))
        date_to_dt = datetime.fromisoformat(date_to.replace("Z", "+00:00").replace(" ", "+"))
    except (ValueError, TypeError) as exc:
        logger.warning(
            "Invalid date format in execution report request",
            extra={
                "operation": "get_execution_report_invalid_date",
                "component": "execution_analysis_route",
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        raise HTTPException(status_code=422, detail=f"Invalid date format: {exc}") from exc

    try:
        report = svc.get_execution_report(
            date_from=date_from_dt,
            date_to=date_to_dt,
            deployment_id=deployment_id,
        )
    except RuntimeError as exc:
        logger.error(
            "Order repository not configured",
            extra={
                "operation": "get_execution_report_not_configured",
                "component": "execution_analysis_route",
            },
        )
        raise HTTPException(status_code=500, detail="Order repository not configured") from exc

    logger.info(
        "Execution report retrieved via API",
        extra={
            "operation": "get_execution_report_api",
            "component": "execution_analysis_route",
            "date_from": date_from,
            "date_to": date_to,
            "deployment_id": deployment_id,
            "total_orders": report.total_orders,
            "fill_rate": str(report.fill_rate),
        },
    )

    return _execution_report_to_dict(report)


@router.get(
    "/export",
    summary="Export orders as CSV",
    response_model=None,
)
async def export_orders_csv(
    deployment_id: str | None = Query(None, description="Filter by deployment ULID"),
    symbol: str | None = Query(None, description="Filter by symbol"),
    side: str | None = Query(None, description="Filter by side (buy/sell)"),
    status: str | None = Query(None, description="Filter by order status"),
    execution_mode: str | None = Query(None, description="Filter by execution mode"),
    date_from: str | None = Query(None, description="Filter by start date (ISO 8601)"),
    date_to: str | None = Query(None, description="Filter by end date (ISO 8601)"),
    _user: AuthenticatedUser = Depends(require_scope("deployments:read")),
) -> Response:
    """
    Export filtered orders as CSV file.

    Returns all matching orders (without pagination limit) in CSV format
    suitable for download and external analysis.

    Args:
        deployment_id: Filter to specific deployment (optional).
        symbol: Filter by symbol (optional).
        side: Filter by side: buy or sell (optional).
        status: Filter by order status (optional).
        execution_mode: Filter by execution mode (optional).
        date_from: Inclusive start date (ISO 8601 string, optional).
        date_to: Inclusive end date (ISO 8601 string, optional).

    Returns:
        Response with CSV content and appropriate content-type headers.

    Raises:
        HTTPException 422: invalid date format.
    """
    svc = get_execution_analysis_service()

    # Parse dates if provided
    date_from_dt = None
    date_to_dt = None
    if date_from or date_to:
        try:
            if date_from:
                # Handle multiple ISO 8601 formats:
                # - With Z: 2026-04-12T00:00:00Z
                # - With +HH:MM: 2026-04-12T00:00:00+00:00
                # - Spaces instead of +: 2026-04-12T00:00:00 00:00 (URL decode issue)
                date_from_dt = datetime.fromisoformat(
                    date_from.replace("Z", "+00:00").replace(" ", "+")
                )
            if date_to:
                date_to_dt = datetime.fromisoformat(
                    date_to.replace("Z", "+00:00").replace(" ", "+")
                )
        except (ValueError, TypeError) as exc:
            logger.warning(
                "Invalid date format in export request",
                extra={
                    "operation": "export_orders_csv_invalid_date",
                    "component": "execution_analysis_route",
                    "date_from": date_from,
                    "date_to": date_to,
                },
            )
            raise HTTPException(status_code=422, detail=f"Invalid date format: {exc}") from exc

    # Build query (pagination params are ignored for export)
    query = OrderHistoryQuery(
        deployment_id=deployment_id,
        symbol=symbol,
        side=side,
        status=status,
        execution_mode=execution_mode,
        date_from=date_from_dt,
        date_to=date_to_dt,
        page=1,
        page_size=500,  # High limit to get all matching records
    )

    try:
        csv_content = svc.export_orders_csv(query=query)
    except RuntimeError as exc:
        logger.error(
            "Order repository not configured",
            extra={
                "operation": "export_orders_csv_not_configured",
                "component": "execution_analysis_route",
            },
        )
        raise HTTPException(status_code=500, detail="Order repository not configured") from exc

    logger.info(
        "Orders exported to CSV via API",
        extra={
            "operation": "export_orders_csv_api",
            "component": "execution_analysis_route",
            "symbol": symbol,
            "execution_mode": execution_mode,
        },
    )

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=orders_export.csv"},
    )
