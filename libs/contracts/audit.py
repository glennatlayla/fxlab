"""
Audit event schemas and write function.

Every mutation writes an immutable audit event.

Responsibilities:
- Define the AuditEventSchema Pydantic contract.
- Provide write_audit_event() for persisting audit events via a SQLAlchemy session.

Does NOT:
- Contain business logic.
- Manage database connections.

Example:
    from libs.contracts.audit import write_audit_event
    write_audit_event(
        session=db,
        actor="user:01HQ...",
        action="strategy.created",
        object_id="01HQ...",
        object_type="strategy",
        metadata={"name": "My Strategy"},
    )
"""

from datetime import datetime
from typing import Any

import ulid as _ulid
from pydantic import BaseModel, ConfigDict, Field


class AuditEventSchema(BaseModel):
    """
    Audit event payload.

    Immutable ledger entry for all mutations.
    """

    id: str = Field(..., description="ULID primary key")
    actor: str = Field(..., description="User email or system identity")
    action: str = Field(..., description="Action verb (e.g., create_draft, approve_promotion)")
    object_id: str | None = Field(None, description="ULID of affected object")
    object_type: str | None = Field(None, description="Type of affected object")
    source: str | None = Field(None, description="Source client (web-desktop, web-mobile, api)")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Action-specific context")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Event timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "01HQZX3Y7Z8F9G0H1J2K3L4M5N",
                "actor": "analyst@fxlab.io",
                "action": "approve_promotion",
                "object_id": "01HQZX3Y7Z8F9G0H1J2K3L4M5P",
                "object_type": "promotion_request",
                "source": "web-desktop",
                "metadata": {
                    "target_environment": "paper",
                    "decision": "approved",
                    "evidence_link": "https://jira.example.com/TICKET-123",
                },
                "created_at": "2026-03-19T21:56:00Z",
            }
        }
    )


def write_audit_event(
    session: Any,
    actor: str,
    action: str,
    object_id: str,
    object_type: str,
    metadata: dict[str, Any] | None = None,
    source: str | None = None,
) -> str:
    """
    Write an immutable audit event to the ledger via the given SQLAlchemy session.

    Args:
        session: Active SQLAlchemy Session to use for the write.
        actor: Identity string identifying who performed the action.
               Format: "user:<ulid>" or "system:<name>".
        action: Dot-notation action verb, e.g. "strategy.created".
        object_id: ULID of the affected entity.
        object_type: Entity type name, e.g. "strategy", "run".
        metadata: Optional dict of action-specific context.
        source: Optional source client identifier (web-desktop, web-mobile, api).
                Defaults to None for backwards compatibility.

    Returns:
        The ULID string assigned to the new audit event.

    Raises:
        sqlalchemy.exc.SQLAlchemyError: If the database write fails.

    Example:
        event_id = write_audit_event(
            session=db,
            actor="user:01HQ...",
            action="run.started",
            object_id="01HQ...",
            object_type="run",
            metadata={"trigger": "scheduled"},
            source="web-desktop",
        )
    """
    from libs.contracts.models import AuditEvent  # lazy import to avoid circular deps

    event_id = str(_ulid.ULID())
    event = AuditEvent(
        id=event_id,
        actor=actor,
        action=action,
        object_id=object_id,
        object_type=object_type,
        # 'metadata' is reserved by SQLAlchemy; the ORM attribute is event_metadata.
        event_metadata=metadata if metadata is not None else {},
        source=source,
    )
    session.add(event)
    session.flush()  # Emit SQL but keep transaction open for atomicity.
    return event_id


__all__ = [
    "AuditEventSchema",
    "write_audit_event",
]
