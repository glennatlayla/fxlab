"""
SQL repository for strategy draft autosaves.

Responsibilities:
- Persist draft autosave records to the draft_autosaves table.
- Retrieve the latest autosave for a given user.
- Delete autosave records when the user discards their draft.

Does NOT:
- Validate draft content (partial drafts may be incomplete).
- Contain business logic or session management.
- Purge stale autosaves (background cleanup job responsibility).

Dependencies:
- SQLAlchemy Session (injected via get_db).
- libs.contracts.models.DraftAutosave ORM model.

Error conditions:
- Returns None from get_latest() when no autosave exists for the user.
- Returns False from delete() when the autosave_id does not exist.

Example:
    db = next(get_db())
    repo = SqlDraftAutosaveRepository(db=db)
    record = repo.create(
        user_id="01H...",
        draft_payload={"name": "MyStrategy"},
        form_step="parameters",
        session_id="sess-001",
        client_ts="2026-03-28T12:00:00",
    )
    latest = repo.get_latest(user_id="01H...")
    repo.delete(autosave_id=record["autosave_id"])
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import desc

from libs.contracts.models import DraftAutosave

logger = structlog.get_logger(__name__)

_counter: int = 0


def _generate_ulid() -> str:
    """
    Generate a time-ordered ULID-shaped ID for new autosave records.

    Returns:
        26-character string prefixed with timestamp milliseconds.
    """
    global _counter
    _counter += 1
    ts_ms = int(time.time() * 1000)
    return f"{ts_ms:013d}{_counter:013d}"[:26]


class SqlDraftAutosaveRepository:
    """
    SQLAlchemy-backed repository for strategy draft autosaves.

    Responsibilities:
    - Insert autosave rows on create().
    - Query the most recent autosave by user_id on get_latest().
    - Delete autosave rows by primary key on delete().

    Does NOT:
    - Validate draft content.
    - Contain business logic.

    Dependencies:
        db: SQLAlchemy Session, injected by the caller via get_db().

    Example:
        repo = SqlDraftAutosaveRepository(db=session)
        record = repo.create(user_id="01H...", draft_payload={...}, ...)
    """

    def __init__(self, db: Any) -> None:
        """
        Initialise with an active SQLAlchemy session.

        Args:
            db: An open SQLAlchemy Session from get_db().
        """
        self._db = db

    def create(
        self,
        *,
        user_id: str,
        draft_payload: dict[str, Any],
        form_step: str | None = None,
        session_id: str | None = None,
        client_ts: str | None = None,
        strategy_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Persist a new draft autosave record.

        Args:
            user_id: ULID of the user owning this draft.
            draft_payload: JSON blob of the partial strategy form state.
            form_step: Current form step identifier (e.g. 'parameters').
            session_id: Browser session identifier for recovery correlation.
            client_ts: ISO-8601 client-side timestamp of the autosave event.
            strategy_id: Optional FK to an existing Strategy being edited.

        Returns:
            Dict with autosave_id and saved_at (ISO-8601 string).

        Example:
            record = repo.create(
                user_id="01H...",
                draft_payload={"name": "S1"},
                form_step="parameters",
                session_id="sess-001",
                client_ts="2026-03-28T12:00:00",
            )
            # record == {"autosave_id": "01H...", "saved_at": "2026-03-28T..."}
        """
        autosave_id = _generate_ulid()
        now = datetime.now(tz=timezone.utc)

        row = DraftAutosave(
            id=autosave_id,
            user_id=user_id,
            strategy_id=strategy_id,
            draft_payload=draft_payload,
            form_step=form_step,
            session_id=session_id,
            client_ts=client_ts,
        )

        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)

        logger.debug(
            "draft.autosave.sql.created",
            autosave_id=autosave_id,
            user_id=user_id,
            form_step=form_step,
        )

        return {"autosave_id": autosave_id, "saved_at": now.isoformat()}

    def get_latest(self, user_id: str) -> dict[str, Any] | None:
        """
        Retrieve the most recent draft autosave for a user.

        Args:
            user_id: ULID of the user whose latest autosave to fetch.

        Returns:
            Dict with full autosave detail (autosave_id, user_id, draft_payload,
            form_step, session_id, client_ts, saved_at), or None if not found.

        Example:
            latest = repo.get_latest(user_id="01H...")
            if latest is None:
                return Response(status_code=204)
        """
        row: DraftAutosave | None = (
            self._db.query(DraftAutosave)
            .filter(DraftAutosave.user_id == user_id)
            .order_by(desc(DraftAutosave.updated_at))
            .first()
        )

        if row is None:
            return None

        return {
            "autosave_id": row.id,
            "user_id": row.user_id,
            "draft_payload": row.draft_payload,
            "form_step": row.form_step,
            "session_id": row.session_id,
            "client_ts": row.client_ts,
            "saved_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def delete(self, autosave_id: str) -> bool:
        """
        Delete a draft autosave record by primary key.

        Args:
            autosave_id: ULID primary key of the autosave to delete.

        Returns:
            True if the record was found and deleted, False if not found.

        Example:
            deleted = repo.delete(autosave_id="01H...")
            if not deleted:
                raise HTTPException(404, "Autosave not found")
        """
        row: DraftAutosave | None = self._db.get(DraftAutosave, autosave_id)
        if row is None:
            return False

        self._db.delete(row)
        self._db.commit()

        logger.debug("draft.autosave.sql.deleted", autosave_id=autosave_id)
        return True
