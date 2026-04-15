"""
OverrideRepositoryInterface — port for governance override data access.

Purpose:
    Define the contract that all override repository implementations must
    honour, so that the governance service depends on an abstraction rather
    than a concrete database adapter.

Responsibilities:
    - create() → persist a new override request and return its ID + status.
    - get_by_id() → retrieve a single override by ULID.
    - update_decision() → record the reviewer's decision on an override.

Does NOT:
    - Enforce separation-of-duties (service layer responsibility).
    - Emit audit events (service layer responsibility).
    - Contain business logic.

Dependencies:
    - libs.contracts.errors: NotFoundError.

Error conditions:
    - get_by_id raises NotFoundError when override_id does not exist.

Example:
    class SqlOverrideRepository(OverrideRepositoryInterface):
        def create(self, *, object_id, ...) -> dict: ...
        def get_by_id(self, override_id, ...) -> dict: ...
        def update_decision(self, override_id, ...) -> dict: ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class OverrideRepositoryInterface(ABC):
    """
    Abstract port for governance override data access.

    Implementations:
    - MockOverrideRepository   — in-memory, for unit tests
    - SqlOverrideRepository    — SQLAlchemy-backed, for production
    """

    @abstractmethod
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
        Persist a new governance override request.

        Args:
            object_id: ULID of the target entity being overridden.
            object_type: Entity type classifier (candidate, deployment).
            override_type: Override category (e.g. grade_override).
            original_state: JSON snapshot of entity state before override.
            new_state: JSON snapshot of proposed entity state after override.
            evidence_link: Absolute HTTP/HTTPS URI to supporting evidence.
            rationale: Submitter's free-text justification (≥20 chars).
            submitter_id: ULID of the requesting operator.

        Returns:
            Dict with at least override_id and status='pending'.
        """
        ...

    @abstractmethod
    def get_by_id(self, override_id: str) -> dict[str, Any] | None:
        """
        Retrieve an override by primary key.

        Args:
            override_id: ULID primary key of the override record.

        Returns:
            Dict with full override detail, or None if not found.
        """
        ...

    @abstractmethod
    def update_decision(
        self,
        *,
        override_id: str,
        reviewer_id: str,
        status: str,
        decision_rationale: str,
    ) -> dict[str, Any]:
        """
        Record a reviewer's decision (approve/reject) on an override.

        Args:
            override_id: ULID of the override being decided.
            reviewer_id: ULID of the reviewer making the decision.
            status: New status — must be 'approved' or 'rejected'.
            decision_rationale: Reviewer's justification for the decision.

        Returns:
            Dict with updated override detail.

        Raises:
            NotFoundError: If override_id does not exist.
        """
        ...
