"""
SQL repository for approval requests.

Purpose:
    Persist and retrieve approval request records via SQLAlchemy, providing
    a production-grade replacement for the in-memory MockApprovalRepository.

Responsibilities:
    - Retrieve approval requests by primary key (get_by_id).
    - Record reviewer decisions (approve/reject) with timestamp tracking.

Does NOT:
    - Enforce separation-of-duties (service layer responsibility).
    - Emit audit events (service layer responsibility).
    - Contain business logic or workflow orchestration.

Dependencies:
    - SQLAlchemy Session (injected via get_db per request).
    - libs.contracts.models.ApprovalRequest ORM model.
    - libs.contracts.errors.NotFoundError.

Error conditions:
    - get_by_id: returns None when approval_id does not exist.
    - update_decision: raises NotFoundError when approval_id does not exist.

Example:
    db = next(get_db())
    repo = SqlApprovalRepository(db=db)
    detail = repo.get_by_id("01HAPPROVAL...")
    result = repo.update_decision(
        approval_id="01HAPPROVAL...",
        reviewer_id="01HREVIEWER...",
        status="approved",
        decision_reason="All criteria met.",
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.approval_repository import ApprovalRepositoryInterface
from libs.contracts.models import ApprovalRequest

logger = structlog.get_logger(__name__)


class SqlApprovalRepository(ApprovalRepositoryInterface):
    """
    SQLAlchemy-backed repository for approval requests.

    Responsibilities:
    - Query approval_requests table by primary key.
    - Update approval decisions with reviewer info and timestamps.

    Does NOT:
    - Contain business logic or SoD enforcement.
    - Call session.commit() — uses flush() to stay within the
      request-scoped transaction managed by get_db().

    Dependencies:
        db: SQLAlchemy Session, injected by the caller.

    Example:
        repo = SqlApprovalRepository(db=session)
        detail = repo.get_by_id("01HAPPROVAL...")
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def _to_dict(self, record: ApprovalRequest) -> dict[str, Any]:
        """
        Convert an ApprovalRequest ORM instance to a plain dict.

        Returns a dict with keys matching the MockApprovalRepository output
        format so callers (GovernanceService) don't need to change.

        Args:
            record: The ORM model instance.

        Returns:
            Dict with all approval detail fields.
        """
        return {
            "approval_id": record.id,
            "id": record.id,
            "candidate_id": record.candidate_id,
            "requested_by": record.requested_by,
            "status": record.status,
            "reviewer_id": record.reviewer_id,
            "decision_reason": record.decision_reason,
            "decided_at": record.decided_at.isoformat() if record.decided_at else None,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    def get_by_id(self, approval_id: str) -> dict[str, Any] | None:
        """
        Retrieve an approval request by primary key.

        Args:
            approval_id: ULID primary key of the approval record.

        Returns:
            Dict with full approval detail, or None if not found.

        Example:
            detail = repo.get_by_id("01HAPPROVAL...")
            # detail["status"] == "pending"
        """
        record = self._db.get(ApprovalRequest, approval_id)
        if record is None:
            return None
        return self._to_dict(record)

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

        Updates the approval record with the reviewer's identity, decision
        status, rationale, and timestamps.  Uses session.flush() rather than
        commit() so the caller's request-scoped transaction controls atomicity.

        Args:
            approval_id: ULID of the approval being decided.
            reviewer_id: ULID of the reviewer making the decision.
            status: New status — must be 'approved' or 'rejected'.
            decision_reason: Reviewer's justification for the decision.

        Returns:
            Dict with updated approval detail.

        Raises:
            NotFoundError: If approval_id does not exist in the database.

        Example:
            result = repo.update_decision(
                approval_id="01HAPPROVAL...",
                reviewer_id="01HREVIEWER...",
                status="approved",
                decision_reason="All criteria met.",
            )
            # result["status"] == "approved"
        """
        record = self._db.get(ApprovalRequest, approval_id)
        if record is None:
            raise NotFoundError(f"Approval request '{approval_id}' not found")

        now: datetime = datetime.now(tz=timezone.utc)
        record.status = status
        record.reviewer_id = reviewer_id
        record.decision_reason = decision_reason
        record.decided_at = now
        record.updated_at = now  # type: ignore[assignment]

        self._db.flush()

        logger.debug(
            "approval_repository.decision_recorded",
            approval_id=approval_id,
            reviewer_id=reviewer_id,
            status=status,
            component="sql_approval_repository",
        )

        return self._to_dict(record)

    def count_by_status(self, status: str) -> int:
        """
        Count approval requests by status.

        Args:
            status: Status string to filter by (e.g., 'pending', 'approved', 'rejected').

        Returns:
            Count of approval records with the given status.

        Example:
            pending_count = repo.count_by_status("pending")
        """
        count = self._db.query(ApprovalRequest).filter(ApprovalRequest.status == status).count()
        return count
