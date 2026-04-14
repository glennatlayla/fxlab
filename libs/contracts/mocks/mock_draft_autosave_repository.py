"""
In-memory mock repository for strategy draft autosaves.

Used in test mode (ENVIRONMENT=test / unset) to provide fast, I/O-free
behaviour that mirrors the SqlDraftAutosaveRepository interface.

Responsibilities:
- Provide an in-memory dict store matching SqlDraftAutosaveRepository's behaviour.
- Support introspection helpers for test assertions.

Does NOT:
- Persist data across process restarts.
- Validate draft content.

Example:
    repo = MockDraftAutosaveRepository()
    record = repo.create(
        user_id="01H...",
        draft_payload={"name": "S1"},
        form_step="parameters",
        session_id="sess-001",
        client_ts="2026-03-28T12:00:00",
    )
    latest = repo.get_latest(user_id="01H...")
    assert latest["autosave_id"] == record["autosave_id"]
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

_STUB_PREFIX = "01HMOCKSAVE"
_counter = 0


def _generate_id() -> str:
    global _counter
    _counter += 1
    return f"{_STUB_PREFIX}{_counter:015d}"


class MockDraftAutosaveRepository:
    """
    In-memory implementation of the draft autosave repository interface.

    Responsibilities:
    - Mirror SqlDraftAutosaveRepository's create() / get_latest() / delete().
    - Provide test introspection helpers (count(), clear()).

    Does NOT:
    - Persist data.
    - Validate draft content.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

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
        Create a new in-memory draft autosave record.

        Args:
            user_id: ULID of the user owning this draft.
            draft_payload: Partial strategy form state JSON blob.
            form_step: Current form step identifier.
            session_id: Browser session identifier.
            client_ts: ISO-8601 client-side timestamp.
            strategy_id: Optional FK to existing Strategy.

        Returns:
            Dict with autosave_id and saved_at (ISO-8601).
        """
        autosave_id = _generate_id()
        now = datetime.now(tz=timezone.utc)

        self._store[autosave_id] = {
            "autosave_id": autosave_id,
            "user_id": user_id,
            "strategy_id": strategy_id,
            "draft_payload": draft_payload,
            "form_step": form_step,
            "session_id": session_id,
            "client_ts": client_ts,
            "saved_at": now,
        }

        return {"autosave_id": autosave_id, "saved_at": now.isoformat()}

    def get_latest(self, user_id: str) -> dict[str, Any] | None:
        """
        Return the most recent autosave for the given user, or None.

        Args:
            user_id: ULID of the user.

        Returns:
            Autosave detail dict, or None if no autosave exists.
        """
        user_saves = [rec for rec in self._store.values() if rec["user_id"] == user_id]
        if not user_saves:
            return None

        latest = max(user_saves, key=lambda r: r["saved_at"])
        return {
            **latest,
            "saved_at": (
                latest["saved_at"].isoformat()
                if hasattr(latest["saved_at"], "isoformat")
                else latest["saved_at"]
            ),
        }

    def delete(self, autosave_id: str) -> bool:
        """
        Delete an autosave record by ID.

        Args:
            autosave_id: Primary key of the autosave to delete.

        Returns:
            True if deleted, False if not found.
        """
        if autosave_id not in self._store:
            return False
        del self._store[autosave_id]
        return True

    def purge_expired(self, max_age_days: int = 30) -> int:
        """
        Delete all autosave records older than max_age_days.

        Args:
            max_age_days: Number of days; autosaves older than this are deleted.
                         Defaults to 30 days.

        Returns:
            Count of records deleted (0 if none).
        """
        cutoff_time = datetime.now(tz=timezone.utc) - timedelta(days=max_age_days)

        # Find all autosaves older than the cutoff time.
        ids_to_delete = [
            autosave_id
            for autosave_id, record in self._store.items()
            if isinstance(record["saved_at"], datetime) and record["saved_at"] < cutoff_time
        ]

        # Delete them.
        deleted_count = len(ids_to_delete)
        for autosave_id in ids_to_delete:
            del self._store[autosave_id]

        return deleted_count

    # ------------------------------------------------------------------
    # Test introspection helpers
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return the number of autosaves in the mock store."""
        return len(self._store)

    def clear(self) -> None:
        """Remove all records from the mock store."""
        self._store.clear()

    def get_all(self) -> list[dict[str, Any]]:
        """Return all autosave records."""
        return list(self._store.values())
