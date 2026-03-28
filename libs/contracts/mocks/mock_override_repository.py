"""
In-memory mock repository for governance override requests.

Used in test mode (ENVIRONMENT=test / unset) to provide fast, I/O-free
behaviour that mirrors the SqlOverrideRepository interface.

Responsibilities:
- Provide an in-memory dict store matching SqlOverrideRepository's behaviour.
- Support introspection helpers for test assertions.

Does NOT:
- Persist data across process restarts.
- Enforce separation-of-duties.

Example:
    repo = MockOverrideRepository()
    record = repo.create(
        object_id="01H...", object_type="candidate",
        override_type="grade_override",
        original_state={"grade": "C"}, new_state={"grade": "B"},
        evidence_link="https://jira.example.com/browse/FX-123",
        rationale="3-year backtest justifies grade B uplift.",
        submitter_id="01H...",
    )
    assert repo.count() == 1
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_STUB_PREFIX = "01HMOCKOVERRIDE"
_counter = 0


def _generate_id() -> str:
    global _counter
    _counter += 1
    return f"{_STUB_PREFIX}{_counter:011d}"


class MockOverrideRepository:
    """
    In-memory implementation of the override repository interface.

    Responsibilities:
    - Mirror SqlOverrideRepository's create() / get_by_id() interface.
    - Provide test introspection helpers (count(), clear()).

    Does NOT:
    - Persist data.
    - Enforce business rules.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def create(
        self,
        *,
        object_id: str,
        object_type: str,
        override_type: str,
        original_state: dict[str, Any] | None,
        new_state: dict[str, Any] | None,
        evidence_link: str,
        rationale: str,
        submitter_id: str,
    ) -> dict[str, Any]:
        """
        Create a new in-memory override record.

        Args:
            object_id: ULID of the target entity.
            object_type: Entity type classifier.
            override_type: Override category.
            original_state: Pre-override entity state snapshot.
            new_state: Post-override entity state snapshot.
            evidence_link: Evidence URI.
            rationale: Justification text.
            submitter_id: ULID of submitter.

        Returns:
            Dict with override_id and status='pending'.
        """
        override_id = _generate_id()
        now = datetime.now(tz=timezone.utc)

        self._store[override_id] = {
            "override_id": override_id,
            "id": override_id,
            "object_id": object_id,
            "object_type": object_type,
            "override_type": override_type,
            "original_state": original_state,
            "new_state": new_state,
            "evidence_link": evidence_link,
            "rationale": rationale,
            "submitter_id": submitter_id,
            "status": "pending",
            "reviewed_by": None,
            "reviewed_at": None,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

        return {"override_id": override_id, "status": "pending"}

    def get_by_id(self, override_id: str) -> dict[str, Any] | None:
        """
        Retrieve an override record by ID.

        Args:
            override_id: Primary key of the override record.

        Returns:
            Override detail dict, or None if not found.
        """
        return self._store.get(override_id)

    # ------------------------------------------------------------------
    # Test introspection helpers
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return the number of overrides in the mock store."""
        return len(self._store)

    def clear(self) -> None:
        """Remove all records from the mock store."""
        self._store.clear()

    def get_all(self) -> list[dict[str, Any]]:
        """Return all override records."""
        return list(self._store.values())
