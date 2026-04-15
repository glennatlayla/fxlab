"""
Production audit writer adapter.

Bridges GovernanceService's AuditWriter protocol to the existing
libs.contracts.audit.write_audit_event() function, which commits
to the SQLAlchemy session.

Responsibilities:
- Accept audit event params matching the AuditWriter protocol.
- Delegate to write_audit_event() with the injected DB session.

Does NOT:
- Contain business logic.
- Manage database session lifecycle.

Dependencies:
- SQLAlchemy Session (injected).
- libs.contracts.audit.write_audit_event.

Example:
    from services.api.db import get_db
    db = next(get_db())
    writer = SqlAuditWriter(db=db)
    event_id = writer.write(
        actor="user:01H...",
        action="override.submitted",
        object_id="01H...",
        object_type="override",
    )
"""

from __future__ import annotations

from typing import Any

from libs.contracts.audit import write_audit_event


class SqlAuditWriter:
    """
    Production adapter for audit event writing.

    Satisfies the GovernanceService.AuditWriter protocol by delegating
    to write_audit_event() with the injected SQLAlchemy session.

    Responsibilities:
    - Bridge the protocol to the concrete audit writer.

    Does NOT:
    - Own the session lifecycle.

    Dependencies:
    - db: SQLAlchemy Session (injected).

    Example:
        writer = SqlAuditWriter(db=session)
        writer.write(actor="user:01H...", action="override.submitted", ...)
    """

    def __init__(self, db: Any) -> None:
        """
        Initialise with an active SQLAlchemy session.

        Args:
            db: An open SQLAlchemy Session.
        """
        self._db = db

    def write(
        self,
        *,
        actor: str,
        action: str,
        object_id: str,
        object_type: str,
        metadata: dict | None = None,
        source: str | None = None,
    ) -> str:
        """
        Write an immutable audit event via the injected session.

        Args:
            actor: Identity string (e.g. "user:<ulid>").
            action: Action verb (e.g. "override.submitted").
            object_id: ULID of affected entity.
            object_type: Entity type name.
            metadata: Optional context dict.
            source: Optional source client identifier (web-desktop, web-mobile, api).
                    Defaults to None for backwards compatibility.

        Returns:
            The ULID string assigned to the new audit event.
        """
        return write_audit_event(
            session=self._db,
            actor=actor,
            action=action,
            object_id=object_id,
            object_type=object_type,
            metadata=metadata,
            source=source,
        )
