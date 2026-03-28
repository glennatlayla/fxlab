"""
Audit Explorer API endpoints (Phase 3 — M9: Symbol Lineage & Audit Explorer Backend).

Purpose:
    Provide read-only HTTP endpoints for the operator audit explorer UI,
    allowing operators to list and inspect audit events per §8.7 of the
    Phase 3 workplan.

Responsibilities:
    - GET /audit          — filtered, cursor-paginated list of AuditEventRecord.
    - GET /audit/{id}     — single AuditEventRecord by ULID.
    - Provide get_audit_explorer_repository() DI factory for dependency injection.
    - Serialize AuditEventRecord and AuditExplorerResponse via JSONResponse.

Does NOT:
    - Write audit events (write-side is write_audit_event() in libs/contracts/audit.py).
    - Contain business logic or query construction.
    - Connect to any database directly (delegated to the repository implementation).

Dependencies:
    - AuditExplorerRepositoryInterface (injected via Depends).
    - AuditEventRecord, AuditExplorerResponse (domain contracts).
    - NotFoundError (domain exception → HTTP 404).

Error conditions:
    - GET /audit/{id} raises HTTP 404 when the repository raises NotFoundError.

Known lessons:
    LL-007: All Optional[str] fields use str="" to avoid pydantic-core cross-arch failure.
    LL-008: Use JSONResponse + model_dump() instead of response_model= for serialization.
    LL-010: Explicit int() cast on Query() limit parameter before repository call.

Example:
    GET /audit?actor=analyst@fxlab.io&limit=20
    GET /audit/01HQAUDIT0AAAAAAAAAAAAAAAA1
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from libs.contracts.audit_explorer import AuditEventRecord, AuditExplorerResponse
from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.audit_explorer_repository import (
    AuditExplorerRepositoryInterface,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency injection provider
# ---------------------------------------------------------------------------


def get_audit_explorer_repository() -> AuditExplorerRepositoryInterface:
    """
    DI factory for AuditExplorerRepositoryInterface.

    Returns a MockAuditExplorerRepository bootstrap stub.  The real SQL-backed
    implementation will be wired in the lifespan DI container (ISS-021).

    Returns:
        AuditExplorerRepositoryInterface implementation.
    """
    from libs.contracts.mocks.mock_audit_explorer_repository import (  # pragma: no cover
        MockAuditExplorerRepository,  # pragma: no cover
    )
    return MockAuditExplorerRepository()  # pragma: no cover


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_audit_record(record: AuditEventRecord) -> dict:
    """
    Serialize a single AuditEventRecord to a JSON-safe dict.

    Args:
        record: AuditEventRecord domain object.

    Returns:
        JSON-serializable dict with all AuditEventRecord fields.
        Datetime fields are rendered as ISO 8601 strings.

    Example:
        d = _serialize_audit_record(record)
        # d["actor"] == "analyst@fxlab.io"
    """
    return {
        "id": record.id,
        "actor": record.actor,
        "action": record.action,
        "object_id": record.object_id,
        "object_type": record.object_type,
        "correlation_id": record.correlation_id,
        "event_metadata": record.event_metadata,
        "created_at": record.created_at.isoformat(),
    }


def _serialize_audit_list(
    records: list[AuditEventRecord],
    generated_at: datetime,
) -> dict:
    """
    Serialize an audit event list response to a JSON-safe dict.

    Args:
        records:      List of AuditEventRecord objects.
        generated_at: Timestamp when the response was assembled.

    Returns:
        JSON-serializable dict matching the AuditExplorerResponse shape:
        {events, next_cursor, total_count, generated_at}.

    Note:
        next_cursor is always "" in this implementation because the mock repository
        does not implement cursor pagination.  The real SQL repository will provide
        meaningful cursors once ISS-021 is resolved.
    """
    return {
        "events": [_serialize_audit_record(r) for r in records],
        "next_cursor": "",
        "total_count": len(records),
        "generated_at": generated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("")
def list_audit_events(
    actor: str = Query(default="", description="Filter by actor identity string"),
    action_type: str = Query(
        default="", description="Filter by action verb prefix, e.g. 'run'"
    ),
    target_type: str = Query(
        default="", description="Filter by object_type, e.g. 'run'"
    ),
    target_id: str = Query(default="", description="Filter by object_id ULID"),
    cursor: str = Query(default="", description="Opaque cursor for next-page retrieval"),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum events to return"),
    x_correlation_id: str = Header(default="no-corr"),
    repo: AuditExplorerRepositoryInterface = Depends(get_audit_explorer_repository),
) -> JSONResponse:
    """
    Return a filtered list of audit events.

    Supports optional query-parameter filtering on actor, action_type (prefix),
    target_type, and target_id.  Results are capped by limit.  Cursor pagination
    is accepted but not applied in the mock implementation.

    Args:
        actor:            Filter by actor identity string.  Empty = no filter.
        action_type:      Filter by action verb prefix.  Empty = no filter.
        target_type:      Filter by object_type.  Empty = no filter.
        target_id:        Filter by object_id.  Empty = no filter.
        cursor:           Opaque pagination cursor.  Ignored in mock.
        limit:            Maximum number of events (LL-010: cast to int before use).
        x_correlation_id: Request-scoped tracing ID from HTTP header.
        repo:             Injected AuditExplorerRepositoryInterface.

    Returns:
        JSONResponse 200 with shape: {events, next_cursor, total_count, generated_at}.

    Example:
        GET /audit?actor=analyst@fxlab.io&limit=10
        → {"events": [...], "next_cursor": "", "total_count": 2, "generated_at": "..."}
    """
    corr = x_correlation_id or "no-corr"
    logger.info(
        "audit.list_requested",
        operation="list_audit_events",
        correlation_id=corr,
        component="audit_router",
        actor_filter=actor,
        action_type_filter=action_type,
        target_type_filter=target_type,
        target_id_filter=target_id,
        limit=limit,
    )
    records = repo.list(
        actor=actor,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        cursor=cursor,
        limit=int(limit),  # LL-010: explicit cast
        correlation_id=corr,
    )
    generated_at = datetime.now(timezone.utc)
    logger.info(
        "audit.list_completed",
        operation="list_audit_events",
        correlation_id=corr,
        component="audit_router",
        result="success",
        event_count=len(records),
    )
    return JSONResponse(content=_serialize_audit_list(records, generated_at))


@router.get("/{audit_event_id}")
def get_audit_event(
    audit_event_id: str,
    x_correlation_id: str = Header(default="no-corr"),
    repo: AuditExplorerRepositoryInterface = Depends(get_audit_explorer_repository),
) -> JSONResponse:
    """
    Return a single audit event by ULID.

    Args:
        audit_event_id:   ULID of the audit event to retrieve.
        x_correlation_id: Request-scoped tracing ID from HTTP header.
        repo:             Injected AuditExplorerRepositoryInterface.

    Returns:
        JSONResponse 200 with a single AuditEventRecord serialized as JSON.

    Raises:
        HTTPException 404: If no audit event exists with the given ID.

    Example:
        GET /audit/01HQAUDIT0AAAAAAAAAAAAAAAA1
        → {"id": "01HQAUDIT0AAAAAAAAAAAAAAAA1", "actor": "...", ...}
    """
    corr = x_correlation_id or "no-corr"
    logger.info(
        "audit.detail_requested",
        operation="get_audit_event",
        correlation_id=corr,
        component="audit_router",
        audit_event_id=audit_event_id,
    )
    try:
        record = repo.find_by_id(audit_event_id, correlation_id=corr)
    except NotFoundError as exc:
        logger.info(
            "audit.detail_not_found",
            operation="get_audit_event",
            correlation_id=corr,
            component="audit_router",
            audit_event_id=audit_event_id,
            result="not_found",
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    logger.info(
        "audit.detail_completed",
        operation="get_audit_event",
        correlation_id=corr,
        component="audit_router",
        audit_event_id=audit_event_id,
        result="success",
    )
    return JSONResponse(content=_serialize_audit_record(record))
