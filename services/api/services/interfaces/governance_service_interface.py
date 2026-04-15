"""
GovernanceServiceInterface — port for governance business logic.

Purpose:
    Define the contract for governance workflow operations so that route
    handlers depend on an abstraction, not a concrete implementation.

Responsibilities:
    - submit_override() → atomic override + watermark + audit event creation.
    - review_override() → SoD enforcement + decision recording + audit event.
    - approve_request() → SoD enforcement + approval recording + audit event.
    - reject_request() → SoD enforcement + rejection recording + audit event.

Does NOT:
    - Parse HTTP requests (controller responsibility).
    - Manage database sessions (injected by caller).

Dependencies:
    - OverrideRepositoryInterface (injected)
    - ApprovalRepositoryInterface (injected)
    - SQLAlchemy Session (injected for transactional scope)

Error conditions:
    - SeparationOfDutiesError: reviewer == submitter.
    - NotFoundError: referenced entity does not exist.
    - ExternalServiceError: database write failure.

Example:
    service = GovernanceService(
        override_repo=override_repo,
        approval_repo=approval_repo,
        db=session,
    )
    result = service.submit_override(submitter_id="01H...", payload={...})
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class GovernanceServiceInterface(ABC):
    """
    Abstract port for governance workflow business logic.

    Implementations:
    - GovernanceService         — production implementation
    - (mock not needed — unit tests mock the interface itself)
    """

    @abstractmethod
    def submit_override(
        self,
        *,
        submitter_id: str,
        object_id: str,
        object_type: str,
        override_type: str,
        original_state: dict[str, Any] | None,
        new_state: dict[str, Any] | None,
        evidence_link: str,
        rationale: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Submit a governance override request atomically.

        Creates Override + OverrideWatermark + AuditEvent in a single
        database transaction. If any step fails, all are rolled back.

        Args:
            submitter_id: ULID of the requesting operator.
            object_id: ULID of the target entity being overridden.
            object_type: Entity type classifier (candidate, deployment).
            override_type: Override category (e.g. grade_override).
            original_state: JSON snapshot of entity state before override.
            new_state: JSON snapshot of proposed state after override.
            evidence_link: Absolute HTTP/HTTPS URI to supporting evidence.
            rationale: Submitter's free-text justification (≥20 chars).
            correlation_id: Request-scoped tracing ID.

        Returns:
            Dict with override_id and status='pending'.

        Raises:
            ExternalServiceError: If the database transaction fails.
        """
        ...

    @abstractmethod
    def review_override(
        self,
        *,
        override_id: str,
        reviewer_id: str,
        decision: str,
        rationale: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Record a reviewer's decision on an existing override.

        Enforces separation of duties: reviewer must differ from submitter.

        Args:
            override_id: ULID of the override being decided.
            reviewer_id: ULID of the reviewer making the decision.
            decision: 'approved' or 'rejected'.
            rationale: Reviewer's justification for the decision.
            correlation_id: Request-scoped tracing ID.

        Returns:
            Dict with updated override detail.

        Raises:
            SeparationOfDutiesError: If reviewer_id == submitter_id.
            NotFoundError: If override_id does not exist.
        """
        ...

    @abstractmethod
    def approve_request(
        self,
        *,
        approval_id: str,
        reviewer_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Approve a pending approval request.

        Enforces separation of duties: reviewer must differ from submitter.

        Args:
            approval_id: ULID of the approval request to approve.
            reviewer_id: ULID of the reviewing operator.
            correlation_id: Request-scoped tracing ID.

        Returns:
            Dict with approval_id and status='approved'.

        Raises:
            SeparationOfDutiesError: If reviewer_id == requested_by.
            NotFoundError: If approval_id does not exist.
        """
        ...

    @abstractmethod
    def reject_request(
        self,
        *,
        approval_id: str,
        reviewer_id: str,
        rationale: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """
        Reject a pending approval request with mandatory rationale.

        Enforces separation of duties: reviewer must differ from submitter.

        Args:
            approval_id: ULID of the approval request to reject.
            reviewer_id: ULID of the reviewing operator.
            rationale: Mandatory rejection reason (≥10 chars).
            correlation_id: Request-scoped tracing ID.

        Returns:
            Dict with approval_id, status='rejected', and rationale.

        Raises:
            SeparationOfDutiesError: If reviewer_id == requested_by.
            NotFoundError: If approval_id does not exist.
        """
        ...
