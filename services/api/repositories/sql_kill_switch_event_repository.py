"""
SQL repository for kill switch event persistence.

Responsibilities:
- Persist kill switch activation events via SQLAlchemy.
- Support deactivation (setting deactivated_at timestamp).
- Query active events by scope and target.
- Generate ULID primary keys for new records.

Does NOT:
- Enforce kill switch business rules.
- Cancel orders or execute emergency postures.
- Contain business logic or orchestration.

Dependencies:
- SQLAlchemy Session (injected).
- libs.contracts.models.KillSwitchEvent ORM model.
- libs.contracts.errors.NotFoundError.

Error conditions:
- NotFoundError: raised by deactivate when event does not exist.

Example:
    db = next(get_db())
    repo = SqlKillSwitchEventRepository(db=db)
    event = repo.save(
        scope="global",
        target_id="global",
        activated_by="user:01HUSER...",
        activated_at="2026-04-11T10:00:00+00:00",
        reason="Daily loss limit breached",
    )
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.kill_switch_event_repository_interface import (
    KillSwitchEventRepositoryInterface,
)
from libs.contracts.models import KillSwitchEvent

logger = structlog.get_logger(__name__)


def _generate_ulid() -> str:
    """
    Generate a cryptographically random, time-ordered ULID.

    Returns:
        26-character ULID string (Crockford base32).
    """
    import ulid as _ulid

    return str(_ulid.ULID())


def _ks_event_to_dict(event: KillSwitchEvent) -> dict[str, Any]:
    """
    Convert a KillSwitchEvent ORM instance to a plain dict.

    Timestamp fields are converted to ISO 8601 strings for cross-layer
    transport. The mtth_ms field remains an integer or None.

    Args:
        event: KillSwitchEvent ORM instance.

    Returns:
        Dict with all event fields.
    """
    return {
        "id": event.id,
        "scope": event.scope,
        "target_id": event.target_id,
        "activated_by": event.activated_by,
        "activated_at": (event.activated_at.isoformat() if event.activated_at else None),
        "deactivated_at": (event.deactivated_at.isoformat() if event.deactivated_at else None),
        "reason": event.reason,
        "mtth_ms": event.mtth_ms,
        "created_at": (event.created_at.isoformat() if event.created_at else None),
        "updated_at": (event.updated_at.isoformat() if event.updated_at else None),
    }


class SqlKillSwitchEventRepository(KillSwitchEventRepositoryInterface):
    """
    SQL implementation of KillSwitchEventRepositoryInterface.

    Responsibilities:
    - Persist kill switch activation/deactivation events.
    - Query active events (deactivated_at IS NULL).
    - Filter by scope and target.
    - ULID generation for new records.

    Does NOT:
    - Enforce kill switch business rules (service layer responsibility).
    - Cancel orders or execute emergency postures.

    Dependencies:
    - db: SQLAlchemy Session, injected by the caller.

    Raises:
    - NotFoundError: when deactivating a non-existent event.

    Example:
        repo = SqlKillSwitchEventRepository(db=session)
        event = repo.save(
            scope="global",
            target_id="global",
            activated_by="system",
            activated_at="2026-04-11T10:00:00+00:00",
            reason="Manual halt",
        )
    """

    def __init__(self, db: Any) -> None:
        """
        Initialise with an active SQLAlchemy session.

        Args:
            db: SQLAlchemy Session for database operations.
        """
        self._db: Session = db

    def save(
        self,
        *,
        scope: str,
        target_id: str,
        activated_by: str,
        activated_at: str,
        reason: str,
        mtth_ms: int | None = None,
    ) -> dict[str, Any]:
        """
        Persist a new kill switch activation event.

        Args:
            scope: Kill switch scope ("global", "strategy", "symbol").
            target_id: Target identifier.
            activated_by: Identifier of the activating user or system.
            activated_at: ISO 8601 timestamp of activation.
            reason: Human-readable reason for activation.
            mtth_ms: Mean time to halt in milliseconds (optional).

        Returns:
            Dict with all event fields including generated id.
        """
        event_id = _generate_ulid()
        ts = datetime.fromisoformat(activated_at)

        record = KillSwitchEvent(
            id=event_id,
            scope=scope,
            target_id=target_id,
            activated_by=activated_by,
            activated_at=ts,
            reason=reason,
            mtth_ms=mtth_ms,
        )

        self._db.add(record)
        self._db.flush()

        logger.info(
            "kill_switch_event.saved",
            operation="kill_switch_event_save",
            component="SqlKillSwitchEventRepository",
            event_id=event_id,
            scope=scope,
            target_id=target_id,
        )

        return _ks_event_to_dict(record)

    def get_active(self, *, scope: str, target_id: str) -> dict[str, Any] | None:
        """
        Get the currently active kill switch for a scope + target.

        An event is "active" if deactivated_at is NULL.

        Args:
            scope: Kill switch scope.
            target_id: Target identifier.

        Returns:
            Dict with event fields, or None if no active event exists.
        """
        record = (
            self._db.query(KillSwitchEvent)
            .filter(
                KillSwitchEvent.scope == scope,
                KillSwitchEvent.target_id == target_id,
                KillSwitchEvent.deactivated_at.is_(None),
            )
            .first()
        )

        if record is None:
            return None
        return _ks_event_to_dict(record)

    def list_active(self) -> list[dict[str, Any]]:
        """
        List all currently active kill switch events.

        Returns:
            List of event dicts where deactivated_at is NULL,
            ordered by activated_at descending.
        """
        records = (
            self._db.query(KillSwitchEvent)
            .filter(KillSwitchEvent.deactivated_at.is_(None))
            .order_by(KillSwitchEvent.activated_at.desc())
            .all()
        )
        return [_ks_event_to_dict(r) for r in records]

    def deactivate(
        self,
        *,
        event_id: str,
        deactivated_at: str,
        mtth_ms: int | None = None,
    ) -> dict[str, Any]:
        """
        Deactivate a kill switch event.

        Args:
            event_id: ULID of the event to deactivate.
            deactivated_at: ISO 8601 timestamp of deactivation.
            mtth_ms: Mean time to halt in milliseconds (optional).

        Returns:
            Updated event dict.

        Raises:
            NotFoundError: If no event exists with this ID.
        """
        record = self._db.get(KillSwitchEvent, event_id)

        if record is None:
            raise NotFoundError(f"KillSwitchEvent with id={event_id!r} not found")

        record.deactivated_at = datetime.fromisoformat(deactivated_at)
        if mtth_ms is not None:
            record.mtth_ms = mtth_ms

        self._db.flush()

        logger.info(
            "kill_switch_event.deactivated",
            operation="kill_switch_event_deactivate",
            component="SqlKillSwitchEventRepository",
            event_id=event_id,
        )

        return _ks_event_to_dict(record)

    def list_by_scope(self, *, scope: str, limit: int = 100) -> list[dict[str, Any]]:
        """
        List kill switch events by scope (both active and deactivated).

        Args:
            scope: Kill switch scope.
            limit: Maximum number of events to return.

        Returns:
            List of event dicts ordered by activated_at descending.
        """
        records = (
            self._db.query(KillSwitchEvent)
            .filter(KillSwitchEvent.scope == scope)
            .order_by(KillSwitchEvent.activated_at.desc())
            .limit(limit)
            .all()
        )
        return [_ks_event_to_dict(r) for r in records]
