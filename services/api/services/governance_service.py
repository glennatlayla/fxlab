"""
Governance service — business logic for override and approval workflows.

Responsibilities:
- Enforce separation of duties (submitter != reviewer) on all review actions.
- Orchestrate atomic multi-row writes (Override + OverrideWatermark + AuditEvent).
- Emit immutable audit events for every governance mutation.
- Provide the single source of truth for governance workflow rules.

Does NOT:
- Parse HTTP requests (controller responsibility).
- Access the database directly (repository responsibility).
- Format HTTP responses (controller responsibility).

Dependencies:
- OverrideRepositoryInterface (injected): override CRUD.
- ApprovalRepositoryInterface (injected): approval CRUD.
- audit_writer (injected): audit event recording (MockAuditCollector in tests,
  write_audit_event in production).

Error conditions:
- SeparationOfDutiesError: reviewer == submitter on any review action.
- NotFoundError: referenced override or approval does not exist.

Example:
    service = GovernanceService(
        override_repo=override_repo,
        approval_repo=approval_repo,
        audit_writer=audit_collector,
    )
    result = service.submit_override(
        submitter_id="01H...",
        object_id="01H...",
        object_type="candidate",
        override_type="grade_override",
        original_state={"grade": "C"},
        new_state={"grade": "B"},
        evidence_link="https://jira.example.com/browse/FX-123",
        rationale="Extended backtest justifies grade uplift.",
        correlation_id="corr-001",
    )
"""

from __future__ import annotations

from typing import Any, Protocol

import structlog

from libs.contracts.errors import NotFoundError, SeparationOfDutiesError
from libs.contracts.interfaces.approval_repository import ApprovalRepositoryInterface
from libs.contracts.interfaces.override_repository import OverrideRepositoryInterface
from services.api.services.interfaces.governance_service_interface import (
    GovernanceServiceInterface,
)

logger = structlog.get_logger(__name__)

# Spec-mandated SoD error message (M14-T3 spec, line 174).
_SOD_MESSAGE = "Separation of duties violation: submitter and reviewer must be different users"


class AuditWriter(Protocol):
    """
    Protocol for audit event writing.

    Satisfied by MockAuditCollector (tests) and a production adapter
    wrapping libs.contracts.audit.write_audit_event().
    """

    def write(
        self,
        *,
        actor: str,
        action: str,
        object_id: str,
        object_type: str,
        metadata: dict | None = None,
    ) -> str:
        """Write an audit event and return its ID."""
        ...


class GovernanceService(GovernanceServiceInterface):
    """
    Production implementation of governance workflow business logic.

    Responsibilities:
    - Enforce separation of duties on all review/approval/rejection actions.
    - Delegate data persistence to repository interfaces.
    - Emit audit events via the injected audit_writer.

    Does NOT:
    - Know about HTTP, FastAPI, or response formatting.
    - Manage database sessions or transactions directly.

    Dependencies:
    - override_repo: OverrideRepositoryInterface (injected).
    - approval_repo: ApprovalRepositoryInterface (injected).
    - audit_writer: AuditWriter protocol (injected).

    Raises:
    - SeparationOfDutiesError: When reviewer == submitter.
    - NotFoundError: When referenced entity does not exist.

    Example:
        service = GovernanceService(
            override_repo=repo, approval_repo=arepo, audit_writer=audit,
        )
        result = service.approve_request(
            approval_id="01H...", reviewer_id="01H...", correlation_id="corr-1",
        )
    """

    def __init__(
        self,
        *,
        override_repo: OverrideRepositoryInterface,
        approval_repo: ApprovalRepositoryInterface,
        audit_writer: AuditWriter,
    ) -> None:
        """
        Initialise the governance service with injected dependencies.

        Args:
            override_repo: Repository for override CRUD operations.
            approval_repo: Repository for approval CRUD operations.
            audit_writer: Writer for immutable audit events.
        """
        self._override_repo = override_repo
        self._approval_repo = approval_repo
        self._audit = audit_writer

    # ------------------------------------------------------------------
    # submit_override
    # ------------------------------------------------------------------

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
        Submit a governance override request.

        Creates the override record and emits an audit event atomically.

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
        """
        logger.info(
            "governance.submit_override.started",
            component="GovernanceService",
            correlation_id=correlation_id,
            submitter_id=submitter_id,
            object_type=object_type,
            override_type=override_type,
        )

        result = self._override_repo.create(
            object_id=object_id,
            object_type=object_type,
            override_type=override_type,
            original_state=original_state,
            new_state=new_state,
            evidence_link=evidence_link,
            rationale=rationale,
            submitter_id=submitter_id,
        )

        self._audit.write(
            actor=f"user:{submitter_id}",
            action="override.submitted",
            object_id=result["override_id"],
            object_type="override",
            metadata={
                "target_id": object_id,
                "target_type": object_type,
                "override_type": override_type,
                "correlation_id": correlation_id,
            },
        )

        logger.info(
            "governance.submit_override.completed",
            component="GovernanceService",
            correlation_id=correlation_id,
            override_id=result["override_id"],
            result="success",
        )

        return result

    # ------------------------------------------------------------------
    # review_override
    # ------------------------------------------------------------------

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
        logger.info(
            "governance.review_override.started",
            component="GovernanceService",
            correlation_id=correlation_id,
            override_id=override_id,
            reviewer_id=reviewer_id,
            decision=decision,
        )

        # Fetch the existing override to check submitter identity.
        record = self._override_repo.get_by_id(override_id)
        if record is None:
            raise NotFoundError(f"Override '{override_id}' not found")

        # Enforce separation of duties — SoD check before any mutation.
        submitter_id = record.get("submitter_id", "")
        if reviewer_id == submitter_id:
            logger.warning(
                "governance.review_override.sod_violation",
                component="GovernanceService",
                correlation_id=correlation_id,
                override_id=override_id,
                reviewer_id=reviewer_id,
                submitter_id=submitter_id,
            )
            raise SeparationOfDutiesError(_SOD_MESSAGE)

        # Record the decision.
        updated = self._override_repo.update_decision(
            override_id=override_id,
            reviewer_id=reviewer_id,
            status=decision,
            decision_rationale=rationale,
        )

        # Emit audit event after successful mutation.
        self._audit.write(
            actor=f"user:{reviewer_id}",
            action="override.reviewed",
            object_id=override_id,
            object_type="override",
            metadata={
                "decision": decision,
                "correlation_id": correlation_id,
            },
        )

        logger.info(
            "governance.review_override.completed",
            component="GovernanceService",
            correlation_id=correlation_id,
            override_id=override_id,
            decision=decision,
            result="success",
        )

        return updated

    # ------------------------------------------------------------------
    # approve_request
    # ------------------------------------------------------------------

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
        logger.info(
            "governance.approve_request.started",
            component="GovernanceService",
            correlation_id=correlation_id,
            approval_id=approval_id,
            reviewer_id=reviewer_id,
        )

        record = self._approval_repo.get_by_id(approval_id)
        if record is None:
            raise NotFoundError(f"Approval request '{approval_id}' not found")

        # SoD check — the submitter field is 'requested_by' on ApprovalRequest.
        submitter_id = record.get("requested_by", "")
        if reviewer_id == submitter_id:
            logger.warning(
                "governance.approve_request.sod_violation",
                component="GovernanceService",
                correlation_id=correlation_id,
                approval_id=approval_id,
                reviewer_id=reviewer_id,
                submitter_id=submitter_id,
            )
            raise SeparationOfDutiesError(_SOD_MESSAGE)

        updated = self._approval_repo.update_decision(
            approval_id=approval_id,
            reviewer_id=reviewer_id,
            status="approved",
            decision_reason="Approved",
        )

        self._audit.write(
            actor=f"user:{reviewer_id}",
            action="approval.approved",
            object_id=approval_id,
            object_type="approval_request",
            metadata={
                "correlation_id": correlation_id,
            },
        )

        logger.info(
            "governance.approve_request.completed",
            component="GovernanceService",
            correlation_id=correlation_id,
            approval_id=approval_id,
            result="success",
        )

        return updated

    # ------------------------------------------------------------------
    # reject_request
    # ------------------------------------------------------------------

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
        logger.info(
            "governance.reject_request.started",
            component="GovernanceService",
            correlation_id=correlation_id,
            approval_id=approval_id,
            reviewer_id=reviewer_id,
        )

        record = self._approval_repo.get_by_id(approval_id)
        if record is None:
            raise NotFoundError(f"Approval request '{approval_id}' not found")

        submitter_id = record.get("requested_by", "")
        if reviewer_id == submitter_id:
            logger.warning(
                "governance.reject_request.sod_violation",
                component="GovernanceService",
                correlation_id=correlation_id,
                approval_id=approval_id,
                reviewer_id=reviewer_id,
                submitter_id=submitter_id,
            )
            raise SeparationOfDutiesError(_SOD_MESSAGE)

        updated = self._approval_repo.update_decision(
            approval_id=approval_id,
            reviewer_id=reviewer_id,
            status="rejected",
            decision_reason=rationale,
        )

        self._audit.write(
            actor=f"user:{reviewer_id}",
            action="approval.rejected",
            object_id=approval_id,
            object_type="approval_request",
            metadata={
                "rationale": rationale,
                "correlation_id": correlation_id,
            },
        )

        logger.info(
            "governance.reject_request.completed",
            component="GovernanceService",
            correlation_id=correlation_id,
            approval_id=approval_id,
            result="success",
        )

        return updated
