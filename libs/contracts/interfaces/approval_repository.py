"""
ApprovalRepositoryInterface — port for approval request data access.

Purpose:
    Define the contract that all approval repository implementations must
    honour, so that the governance service depends on an abstraction rather
    than a concrete database adapter.

Responsibilities:
    - get_by_id() → retrieve a single approval request by ULID.
    - update_decision() → record the reviewer's decision on an approval.

Does NOT:
    - Enforce separation-of-duties (service layer responsibility).
    - Emit audit events (service layer responsibility).
    - Contain business logic.

Dependencies:
    - libs.contracts.errors: NotFoundError.

Error conditions:
    - get_by_id raises NotFoundError when approval_id does not exist.
    - update_decision raises NotFoundError when approval_id does not exist.

Example:
    class SqlApprovalRepository(ApprovalRepositoryInterface):
        def get_by_id(self, approval_id) -> dict: ...
        def update_decision(self, *, approval_id, ...) -> dict: ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ApprovalRepositoryInterface(ABC):
    """
    Abstract port for approval request data access.

    Implementations:
    - MockApprovalRepository   — in-memory, for unit tests
    - SqlApprovalRepository    — SQLAlchemy-backed, for production
    """

    @abstractmethod
    def get_by_id(self, approval_id: str) -> dict[str, Any] | None:
        """
        Retrieve an approval request by primary key.

        Args:
            approval_id: ULID primary key of the approval record.

        Returns:
            Dict with full approval detail, or None if not found.
        """
        ...

    @abstractmethod
    def update_decision(
        self,
        *,
        approval_id: str,
        reviewer_id: str,
        status: str,
        decision_reason: str,
    ) -> dict[str, Any]:
        """
        Record a reviewer's decision (approve/reject) on an approval request.

        Args:
            approval_id: ULID of the approval being decided.
            reviewer_id: ULID of the reviewer making the decision.
            status: New status — must be 'approved' or 'rejected'.
            decision_reason: Reviewer's justification for the decision.

        Returns:
            Dict with updated approval detail.

        Raises:
            NotFoundError: If approval_id does not exist.
        """
        ...

    @abstractmethod
    def count_by_status(self, status: str) -> int:
        """
        Count approval requests by status.

        Args:
            status: Status string to filter by (e.g., 'pending', 'approved', 'rejected').

        Returns:
            Count of approval records with the given status.
        """
        ...
