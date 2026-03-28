"""
Parity dashboard API endpoints (Phase 3 — M8/M10: Parity Dashboard + Parity Service).

Purpose:
    Expose read-only HTTP endpoints for the parity dashboard UI, surfacing
    cross-feed discrepancies between official and shadow data sources.

Responsibilities:
    - GET /parity/events               — filtered list of parity events.
    - GET /parity/events/{id}          — single parity event detail; 404 on miss.
    - GET /parity/summary              — per-instrument parity severity summary.
    - Provide get_parity_repository() DI factory for dependency injection.
    - Serialize all ParityEvent and ParityInstrumentSummary fields via JSONResponse.

Does NOT:
    - Compute parity deltas or classify severity (upstream service/domain layer).
    - Persist parity events.
    - Connect to any database directly (delegates to ParityRepositoryInterface).

Dependencies:
    - ParityRepositoryInterface (injected via Depends).
    - libs.contracts.parity: ParityEvent, ParityInstrumentSummary.
    - libs.contracts.errors: NotFoundError.

Error conditions:
    - GET /parity/events/{id} raises HTTP 404 when ParityEvent not found.

Known lessons:
    LL-007: worst_severity is str="" (not Optional[str]) to avoid pydantic-core stub.
    LL-008: All handlers use JSONResponse + dict; no response_model=.
    LL-010: Explicit int() cast on any Query() integer params before repo calls.

M8 note:
    Original GET /parity/events route preserved and extended; M10 adds severity,
    instrument, and feed_id query parameters (all default to "" = no filter).

Example:
    GET /parity/events
    GET /parity/events?severity=CRITICAL&instrument=AAPL
    GET /parity/events/01HQPARITY10000000000AAAA1
    GET /parity/summary
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.parity_repository import ParityRepositoryInterface
from libs.contracts.parity import ParityEvent, ParityInstrumentSummary

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency injection provider
# ---------------------------------------------------------------------------


def get_parity_repository() -> ParityRepositoryInterface:
    """
    Provide a ParityRepositoryInterface implementation.

    Returns:
        MockParityRepository bootstrap stub until SQL wiring is complete.

    Note:
        ISS-020 — Wire SqlParityRepository via lifespan DI container.
    """
    import os

    if os.environ.get("ENVIRONMENT", "test") != "test":
        from services.api.db import get_db
        from services.api.repositories.sql_parity_repository import SqlParityRepository

        db = next(get_db())
        return SqlParityRepository(db=db)

    from libs.contracts.mocks.mock_parity_repository import (  # pragma: no cover
        MockParityRepository,  # pragma: no cover
    )
    return MockParityRepository()  # pragma: no cover


# ---------------------------------------------------------------------------
# Serialization helpers (LL-008: explicit dict + JSONResponse)
# ---------------------------------------------------------------------------


def _serialize_parity_event(event: ParityEvent) -> dict[str, Any]:
    """
    Serialize one ParityEvent to a JSON-safe dict.

    Args:
        event: ParityEvent with datetime and str-enum fields.

    Returns:
        Dict with datetime fields as ISO strings; severity as plain string value.

    Example:
        d = _serialize_parity_event(event)
        assert isinstance(d["timestamp"], str)
    """
    return {
        "id": event.id,
        "feed_id_official": event.feed_id_official,
        "feed_id_shadow": event.feed_id_shadow,
        "instrument": event.instrument,
        "timestamp": event.timestamp.isoformat(),
        "delta": event.delta,
        "delta_pct": event.delta_pct,
        "severity": event.severity.value,
        "detected_at": event.detected_at.isoformat(),
    }


def _serialize_parity_event_list(
    events: list[ParityEvent],
    generated_at: datetime,
) -> dict[str, Any]:
    """
    Serialize a list of parity events into the list response shape.

    Args:
        events:       List of ParityEvent from the repository.
        generated_at: Response generation timestamp.

    Returns:
        Dict with 'events', 'total_count', and 'generated_at'.

    Example:
        payload = _serialize_parity_event_list(events, datetime.now(timezone.utc))
        assert payload["total_count"] == len(events)
    """
    return {
        "events": [_serialize_parity_event(e) for e in events],
        "total_count": len(events),
        "generated_at": generated_at.isoformat(),
    }


def _serialize_instrument_summary(summary: ParityInstrumentSummary) -> dict[str, Any]:
    """
    Serialize one ParityInstrumentSummary to a JSON-safe dict.

    Args:
        summary: ParityInstrumentSummary domain object.

    Returns:
        Dict with instrument, event counts, and worst_severity string.

    Example:
        d = _serialize_instrument_summary(summary)
        assert d["worst_severity"] in ("", "INFO", "WARNING", "CRITICAL")
    """
    return {
        "instrument": summary.instrument,
        "event_count": summary.event_count,
        "critical_count": summary.critical_count,
        "warning_count": summary.warning_count,
        "info_count": summary.info_count,
        "worst_severity": summary.worst_severity,
    }


def _serialize_parity_summary(
    summaries: list[ParityInstrumentSummary],
    generated_at: datetime,
) -> dict[str, Any]:
    """
    Serialize the per-instrument parity summary response.

    Args:
        summaries:    List of ParityInstrumentSummary (one per instrument).
        generated_at: Response generation timestamp.

    Returns:
        Dict with 'summaries', 'total_event_count', and 'generated_at'.

    Example:
        payload = _serialize_parity_summary(summaries, datetime.now(timezone.utc))
        assert payload["total_event_count"] == sum(s.event_count for s in summaries)
    """
    total = sum(s.event_count for s in summaries)
    return {
        "summaries": [_serialize_instrument_summary(s) for s in summaries],
        "total_event_count": total,
        "generated_at": generated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/parity/events")
def get_parity_events(
    severity: str = Query(
        default="", description="Filter by exact severity: CRITICAL, WARNING, or INFO"
    ),
    instrument: str = Query(
        default="", description="Filter by instrument/ticker symbol"
    ),
    feed_id: str = Query(
        default="",
        description="Filter by feed ULID (matches either official or shadow feed)",
    ),
    x_correlation_id: str = Header(default="no-corr"),
    repo: ParityRepositoryInterface = Depends(get_parity_repository),
) -> JSONResponse:
    """
    Return cross-feed parity discrepancy events, optionally filtered.

    M8 baseline: bare list with no query-parameter filtering.
    M10 extension: severity, instrument, feed_id query parameters added.
    All default to "" (empty = no filter) for full backward compatibility.

    Args:
        severity:         Exact severity filter ("CRITICAL"/"WARNING"/"INFO").
        instrument:       Instrument/ticker filter.  Empty = all instruments.
        feed_id:          Feed ULID filter (official or shadow).  Empty = all feeds.
        x_correlation_id: Request correlation ID for structured logging.
        repo:             Injected parity repository.

    Returns:
        JSONResponse 200 with shape: {events, total_count, generated_at}.

    Example:
        GET /parity/events?severity=CRITICAL&instrument=AAPL
    """
    corr = x_correlation_id or "no-corr"
    logger.info(
        "parity_events.request",
        operation="get_parity_events",
        correlation_id=corr,
        component="parity_router",
        severity_filter=severity,
        instrument_filter=instrument,
        feed_id_filter=feed_id,
    )
    events = repo.list(
        severity=severity,
        instrument=instrument,
        feed_id=feed_id,
        correlation_id=corr,
    )
    generated_at = datetime.now(timezone.utc)
    logger.info(
        "parity_events.response",
        operation="get_parity_events",
        correlation_id=corr,
        component="parity_router",
        event_count=len(events),
        result="success",
    )
    return JSONResponse(content=_serialize_parity_event_list(events, generated_at))


@router.get("/parity/events/{parity_event_id}")
def get_parity_event(
    parity_event_id: str,
    x_correlation_id: str = Header(default="no-corr"),
    repo: ParityRepositoryInterface = Depends(get_parity_repository),
) -> JSONResponse:
    """
    Return a single parity event by ULID.

    Args:
        parity_event_id:  ULID of the parity event.
        x_correlation_id: Request correlation ID for structured logging.
        repo:             Injected parity repository.

    Returns:
        JSONResponse 200 with the single ParityEvent serialized as JSON.

    Raises:
        HTTPException 404: If no parity event exists with the given ID.

    Example:
        GET /parity/events/01HQPARITY10000000000AAAA1
        → {"id": "...", "instrument": "AAPL", "severity": "CRITICAL", ...}
    """
    corr = x_correlation_id or "no-corr"
    logger.info(
        "parity_event.detail_requested",
        operation="get_parity_event",
        correlation_id=corr,
        component="parity_router",
        parity_event_id=parity_event_id,
    )
    try:
        event = repo.find_by_id(parity_event_id, correlation_id=corr)
    except NotFoundError as exc:
        logger.info(
            "parity_event.detail_not_found",
            operation="get_parity_event",
            correlation_id=corr,
            component="parity_router",
            parity_event_id=parity_event_id,
            result="not_found",
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    logger.info(
        "parity_event.detail_completed",
        operation="get_parity_event",
        correlation_id=corr,
        component="parity_router",
        parity_event_id=parity_event_id,
        result="success",
    )
    return JSONResponse(content=_serialize_parity_event(event))


@router.get("/parity/summary")
def get_parity_summary(
    x_correlation_id: str = Header(default="no-corr"),
    repo: ParityRepositoryInterface = Depends(get_parity_repository),
) -> JSONResponse:
    """
    Return per-instrument parity severity aggregates.

    Powers the parity dashboard index page with a compact overview of which
    instruments have outstanding parity issues.

    Args:
        x_correlation_id: Request correlation ID for structured logging.
        repo:             Injected parity repository.

    Returns:
        JSONResponse 200 with shape:
        {summaries: [{instrument, event_count, critical_count, warning_count,
                      info_count, worst_severity}],
         total_event_count: int,
         generated_at: str}.

    Example:
        GET /parity/summary
        → {"summaries": [{"instrument": "AAPL", "worst_severity": "CRITICAL", ...}],
           "total_event_count": 3, "generated_at": "..."}
    """
    corr = x_correlation_id or "no-corr"
    logger.info(
        "parity_summary.requested",
        operation="get_parity_summary",
        correlation_id=corr,
        component="parity_router",
    )
    summaries = repo.summarize(correlation_id=corr)
    generated_at = datetime.now(timezone.utc)
    logger.info(
        "parity_summary.completed",
        operation="get_parity_summary",
        correlation_id=corr,
        component="parity_router",
        instrument_count=len(summaries),
        result="success",
    )
    return JSONResponse(content=_serialize_parity_summary(summaries, generated_at))
