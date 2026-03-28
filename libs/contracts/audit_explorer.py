"""
Audit Explorer read contracts (Phase 3 — M9: Symbol Lineage & Audit Explorer Backend).

Purpose:
    Provide the query-side (read) data shapes for the audit explorer UI, distinct
    from the write-side AuditEventSchema in libs/contracts/audit.py.

Responsibilities:
    - AuditEventRecord — single queryable audit event (matches Phase 1 AuditEvent ORM).
    - AuditExplorerResponse — cursor-paginated list of audit events.

Does NOT:
    - Write audit events (see libs/contracts/audit.py write_audit_event()).
    - Contain business logic.
    - Access the database directly.

Note on object_id / object_type:
    These fields use `str = ""` (empty string default) rather than `Optional[str]`
    to avoid the pydantic-core cross-arch stub failure (LL-007).  An empty string
    indicates "not applicable" for system-level events that target no specific object.

Example:
    record = AuditEventRecord(
        id="01HQAUDIT0AAAAAAAAAAAAAAAA",
        actor="analyst@fxlab.io",
        action="approve_promotion",
        object_id="01HQPROM0AAAAAAAAAAAAAAA0",
        object_type="promotion_request",
        correlation_id="corr-abc",
        event_metadata={},
        created_at=datetime.now(timezone.utc),
    )
    response = AuditExplorerResponse(
        events=[record],
        next_cursor="",
        total_count=1,
        generated_at=datetime.now(timezone.utc),
    )
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel, Field


class AuditEventRecord(BaseModel):
    """
    Query-side representation of a single audit ledger entry.

    Maps to the Phase 1 AuditEvent ORM model columns.  Used exclusively
    for read operations through the audit explorer API.

    Responsibilities:
        - Carry all display fields required by §8.7 audit explorer display rules:
          timestamp, actor, action, target object type and ID, correlation_id.
        - Serialize cleanly to JSON for the explorer frontend.

    Does NOT:
        - Persist data (write-side handled by write_audit_event() in audit.py).
        - Contain governance logic.

    Note on object_id / object_type:
        Uses `str = ""` (not Optional[str]) to avoid pydantic-core cross-arch
        stub failure (LL-007).  Empty string = "not applicable".

    Example:
        r = AuditEventRecord(
            id="01HQAUDIT0AAAAAAAAAAAAAAAA",
            actor="system:scheduler",
            action="run.started",
            object_id="01HQRUN0AAAAAAAAAAAAAAAA0",
            object_type="run",
            correlation_id="corr-123",
            event_metadata={"trigger": "scheduled"},
            created_at=datetime.now(timezone.utc),
        )
    """

    id: str = Field(..., description="ULID of the audit event")
    actor: str = Field(..., description="User email or system identity that performed the action")
    action: str = Field(
        ..., description="Dot-notation action verb, e.g. 'run.started', 'approve_promotion'"
    )
    object_id: str = Field(
        default="",
        description=(
            "ULID of the affected entity.  Empty string when not applicable.  "
            "Uses str (not Optional[str]) to avoid pydantic-core cross-arch stub (LL-007)."
        ),
    )
    object_type: str = Field(
        default="",
        description=(
            "Type of the affected entity, e.g. 'run', 'strategy', 'promotion_request'.  "
            "Empty string when not applicable.  "
            "Uses str (not Optional[str]) to avoid pydantic-core cross-arch stub (LL-007)."
        ),
    )
    correlation_id: str = Field(
        default="",
        description="Request-scoped correlation ID propagated from the originating API call",
    )
    event_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific context (evidence links, target environment, etc.)",
    )
    created_at: datetime = Field(..., description="Timestamp when the audit event was recorded")

    class Config:
        from_attributes = True


class AuditExplorerResponse(BaseModel):
    """
    Cursor-paginated audit event list response.

    Purpose:
        Returned by GET /audit to provide the operator audit explorer with a
        filterable, cursor-paginated view of all audit ledger entries per §8.7.

    Responsibilities:
        - Wrap a list of AuditEventRecord objects.
        - Carry cursor pagination state (next_cursor, total_count).
        - Carry a generation timestamp for staleness detection.

    Does NOT:
        - Include mutation endpoints — audit explorer is read-only.
        - Cache data (caching is the repository's responsibility).

    Example:
        resp = AuditExplorerResponse(
            events=[...],
            next_cursor="01HQAUDIT0BBBBBBBBBBBBBBB",
            total_count=250,
            generated_at=datetime.now(timezone.utc),
        )
    """

    events: list[AuditEventRecord] = Field(
        default_factory=list,
        description="Audit event records for this page",
    )
    next_cursor: str = Field(
        default="",
        description=(
            "Opaque cursor for the next page.  Empty string when no more pages exist.  "
            "Uses str (not Optional[str]) to avoid pydantic-core cross-arch stub (LL-007)."
        ),
    )
    total_count: int = Field(..., ge=0, description="Total number of matching audit events")
    generated_at: datetime = Field(..., description="Response generation timestamp")
