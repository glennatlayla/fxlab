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
from sqlalchemy.orm import Session

from libs.contracts.audit_explorer import AuditEventRecord
from libs.contracts.compact import ViewMode
from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.audit_explorer_repository import (
    AuditExplorerRepositoryInterface,
)
from services.api.auth import AuthenticatedUser, require_scope
from services.api.db import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency injection provider
# ---------------------------------------------------------------------------


def get_audit_explorer_repository(
    db: Session = Depends(get_db),
) -> AuditExplorerRepositoryInterface:
    """
    DI factory for AuditExplorerRepositoryInterface.

    Always returns the DB-backed repository bound to the current request's session.

    Args:
        db: SQLAlchemy session injected by FastAPI dependency injection.

    Returns:
        AuditExplorerRepositoryInterface implementation (SQL-backed).
    """
    from services.api.repositories.sql_audit_explorer_repository import SqlAuditExplorerRepository

    return SqlAuditExplorerRepository(db=db)


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


def _serialize_audit_record_compact(record: AuditEventRecord) -> dict:
    """
    Serialize a single AuditEventRecord to compact form (mobile-optimized).

    Omits correlation_id and event_metadata to reduce bandwidth.

    Args:
        record: AuditEventRecord domain object.

    Returns:
        Compact JSON-serializable dict with essential fields only.

    Example:
        d = _serialize_audit_record_compact(record)
        # Smaller payload than full serialization
    """
    return {
        "id": record.id,
        "actor": record.actor,
        "operation": record.action,
        "object_type": record.object_type,
        "object_id": record.object_id,
        "outcome": "success",  # Inferred from lack of error_message
        "created_at": record.created_at.isoformat(),
    }


def _serialize_audit_list(
    records: list[AuditEventRecord],
    generated_at: datetime,
    view_mode: ViewMode = ViewMode.FULL,
) -> dict:
    """
    Serialize an audit event list response to a JSON-safe dict.

    Args:
        records:      List of AuditEventRecord objects.
        generated_at: Timestamp when the response was assembled.
        view_mode:    Response detail level (FULL or COMPACT).

    Returns:
        JSON-serializable dict matching the AuditExplorerResponse shape:
        {events, next_cursor, total_count, generated_at}.
        - If view_mode=FULL: includes full event metadata.
        - If view_mode=COMPACT: omits correlation_id and event_metadata.

    Note:
        next_cursor is always "" in this implementation because the mock repository
        does not implement cursor pagination.  The real SQL repository will provide
        meaningful cursors once ISS-021 is resolved.
    """
    if view_mode == ViewMode.COMPACT:
        serializer = _serialize_audit_record_compact
    else:
        serializer = _serialize_audit_record

    return {
        "events": [serializer(r) for r in records],
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
    action_type: str = Query(default="", description="Filter by action verb prefix, e.g. 'run'"),
    target_type: str = Query(default="", description="Filter by object_type, e.g. 'run'"),
    target_id: str = Query(default="", description="Filter by object_id ULID"),
    cursor: str = Query(default="", description="Opaque cursor for next-page retrieval"),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum events to return"),
    view: ViewMode = Query(ViewMode.FULL, description="Response detail level: 'full' or 'compact'"),
    x_correlation_id: str = Header(default="no-corr"),
    repo: AuditExplorerRepositoryInterface = Depends(get_audit_explorer_repository),
    user: AuthenticatedUser = Depends(require_scope("audit:read")),
) -> JSONResponse:
    """
    Return a filtered list of audit events with optional compact view.

    Supports optional query-parameter filtering on actor, action_type (prefix),
    target_type, and target_id.  Results are capped by limit.  Cursor pagination
    is accepted but not applied in the mock implementation.

    Supports compact view for mobile clients: ?view=compact returns lightweight
    representations omitting correlation_id and detailed event metadata.

    Args:
        actor:            Filter by actor identity string.  Empty = no filter.
        action_type:      Filter by action verb prefix.  Empty = no filter.
        target_type:      Filter by object_type.  Empty = no filter.
        target_id:        Filter by object_id.  Empty = no filter.
        cursor:           Opaque pagination cursor.  Ignored in mock.
        limit:            Maximum number of events (LL-010: cast to int before use).
        view:             Response detail level ('full' for complete events, 'compact' for mobile).
        x_correlation_id: Request-scoped tracing ID from HTTP header.
        repo:             Injected AuditExplorerRepositoryInterface.

    Returns:
        JSONResponse 200 with shape: {events, next_cursor, total_count, generated_at}.
        - If view=full: includes full event metadata and correlation_id.
        - If view=compact: omits correlation_id and event_metadata for smaller payload.

    Example:
        GET /audit?actor=analyst@fxlab.io&limit=10&view=compact
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
        view_mode=view.value,
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
        view_mode=view.value,
    )
    return JSONResponse(content=_serialize_audit_list(records, generated_at, view_mode=view))


@router.get("/{audit_event_id}")
def get_audit_event(
    audit_event_id: str,
    view: ViewMode = Query(ViewMode.FULL, description="Response detail level: 'full' or 'compact'"),
    x_correlation_id: str = Header(default="no-corr"),
    repo: AuditExplorerRepositoryInterface = Depends(get_audit_explorer_repository),
    user: AuthenticatedUser = Depends(require_scope("audit:read")),
) -> JSONResponse:
    """
    Return a single audit event by ULID with optional compact view.

    Supports compact view for mobile clients: ?view=compact returns lightweight
    representation omitting correlation_id and detailed event metadata.

    Args:
        audit_event_id:   ULID of the audit event to retrieve.
        view:             Response detail level ('full' for complete event, 'compact' for mobile).
        x_correlation_id: Request-scoped tracing ID from HTTP header.
        repo:             Injected AuditExplorerRepositoryInterface.

    Returns:
        JSONResponse 200 with a single AuditEventRecord serialized as JSON.
        - If view=full: includes full event metadata and correlation_id.
        - If view=compact: omits correlation_id and event_metadata for smaller payload.

    Raises:
        HTTPException 404: If no audit event exists with the given ID.

    Example:
        GET /audit/01HQAUDIT0AAAAAAAAAAAAAAAA1?view=compact
        → {"id": "01HQAUDIT0AAAAAAAAAAAAAAAA1", "actor": "...", ...}
    """
    corr = x_correlation_id or "no-corr"
    logger.info(
        "audit.detail_requested",
        operation="get_audit_event",
        correlation_id=corr,
        component="audit_router",
        audit_event_id=audit_event_id,
        view_mode=view.value,
    )
    try:
        record = repo.find_by_id(audit_event_id, correlation_id=corr)
    except NotFoundError:
        logger.info(
            "audit.detail_not_found",
            operation="get_audit_event",
            correlation_id=corr,
            component="audit_router",
            audit_event_id=audit_event_id,
            result="not_found",
        )
        raise HTTPException(status_code=404, detail="Audit event not found.") from None
    logger.info(
        "audit.detail_completed",
        operation="get_audit_event",
        correlation_id=corr,
        component="audit_router",
        audit_event_id=audit_event_id,
        result="success",
        view_mode=view.value,
    )

    if view == ViewMode.COMPACT:
        content = _serialize_audit_record_compact(record)
    else:
        content = _serialize_audit_record(record)

    return JSONResponse(content=content)
