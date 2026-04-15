"""
In-memory mock repository for approval requests.

Used in unit tests to provide fast, I/O-free behaviour that mirrors
the SqlApprovalRepository interface.

Responsibilities:
- Implement ApprovalRepositoryInterface with an in-memory dict store.
- Support introspection helpers for test assertions.
- Support seed() for prepopulating test data.

Does NOT:
- Persist data across process restarts.
- Enforce separation-of-duties (service layer responsibility).

Example:
    repo = MockApprovalRepository()
    repo.seed(
        approval_id="01HAPPROVAL0000000000000001",
        requested_by="01HUSER0000000000000000001",
        status="pending",
    )
    detail = repo.get_by_id("01HAPPROVAL0000000000000001")
    assert detail["status"] == "pending"
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.approval_repository import ApprovalRepositoryInterface

_STUB_PREFIX = "01HMOCKAPPROVAL"
_counter = 0


def _generate_id() -> str:
    global _counter
    _counter += 1
    return f"{_STUB_PREFIX}{_counter:011d}"


class MockApprovalRepository(ApprovalRepositoryInterface):
    """
    In-memory implementation of ApprovalRepositoryInterface.

    Responsibilities:
    - Mirror SqlApprovalRepository behaviour with an in-memory dict store.
    - Provide test introspection helpers (count(), clear(), get_all()).
    - Provide seed() for prepopulating data in tests.

    Does NOT:
    - Persist data.
    - Enforce business rules.

    Example:
        repo = MockApprovalRepository()
        repo.seed(approval_id="01H...", requested_by="01H...", status="pending")
        result = repo.update_decision(
            approval_id="01H...", reviewer_id="01H...",
            status="approved", decision_reason="Good to go",
        )
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def seed(
        self,
        *,
        approval_id: str | None = None,
        requested_by: str,
        status: str = "pending",
        candidate_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Prepopulate an approval request for testing.

        Args:
            approval_id: Optional ULID; auto-generated if omitted.
            requested_by: ULID of the user who created the request.
            status: Initial status (default 'pending').
            candidate_id: Optional FK to candidate.

        Returns:
            Dict with the seeded approval record.
        """
        if approval_id is None:
            approval_id = _generate_id()
        now = datetime.now(tz=timezone.utc)

        record: dict[str, Any] = {
            "approval_id": approval_id,
            "id": approval_id,
            "candidate_id": candidate_id,
            "requested_by": requested_by,
            "status": status,
            "reviewer_id": None,
            "decision_reason": None,
            "decided_at": None,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        self._store[approval_id] = record
        return dict(record)

    def get_by_id(self, approval_id: str) -> dict[str, Any] | None:
        """
        Retrieve an approval request by primary key.

        Args:
            approval_id: ULID primary key.

        Returns:
            Approval detail dict, or None if not found.
        """
        return self._store.get(approval_id)

    def update_decision(
        self,
        *,
        approval_id: str,
        reviewer_id: str,
        status: str,
        decision_reason: str,
    ) -> dict[str, Any]:
        """
        Record a reviewer's decision on an approval request.

        Args:
            approval_id: ULID of the approval being decided.
            reviewer_id: ULID of the reviewer.
            status: New status — 'approved' or 'rejected'.
            decision_reason: Reviewer's justification.

        Returns:
            Dict with updated approval detail.

        Raises:
            NotFoundError: If approval_id does not exist.
        """
        record = self._store.get(approval_id)
        if record is None:
            raise NotFoundError(f"Approval request '{approval_id}' not found")

        now = datetime.now(tz=timezone.utc)
        record["status"] = status
        record["reviewer_id"] = reviewer_id
        record["decision_reason"] = decision_reason
        record["decided_at"] = now.isoformat()
        record["updated_at"] = now.isoformat()
        return dict(record)

    def count_by_status(self, status: str) -> int:
        """
        Count approval requests by status.

        Args:
            status: Status string to filter by (e.g., 'pending', 'approved', 'rejected').

        Returns:
            Count of approval records with the given status.
        """
        return sum(1 for record in self._store.values() if record["status"] == status)

    # ------------------------------------------------------------------
    # Test introspection helpers
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return the number of approvals in the mock store."""
        return len(self._store)

    def clear(self) -> None:
        """Remove all records from the mock store."""
        self._store.clear()

    def get_all(self) -> list[dict[str, Any]]:
        """Return all approval records."""
        return list(self._store.values())
