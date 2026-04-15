"""
Unit tests for GovernanceService (M14-T3).

Covers:
- submit_override: happy path, atomic audit event creation
- review_override: happy path, SoD violation, not-found
- approve_request: happy path, SoD violation, not-found
- reject_request: happy path, SoD violation, not-found
- All operations emit audit events
- Transactional integrity (rollback on failure)

Dependencies:
- MockOverrideRepository (in-memory)
- MockApprovalRepository (in-memory)
- MockAuditRepository (in-memory, defined in this file)

Test naming convention:
    test_<method>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import pytest

from libs.contracts.errors import NotFoundError, SeparationOfDutiesError
from libs.contracts.mocks.mock_approval_repository import MockApprovalRepository
from libs.contracts.mocks.mock_override_repository import MockOverrideRepository

# ---------------------------------------------------------------------------
# Test constants — valid ULID-shaped IDs (26 Crockford base32 chars)
# ---------------------------------------------------------------------------
_SUBMITTER_ID = "01HSUBMTTR0000000000000001"
_REVIEWER_ID = "01HREVIEWER000000000000001"
_CORRELATION_ID = "test-corr-001"
_OBJECT_ID = "01HOBJECT00000000000000001"

# Standard override submission payload
_OVERRIDE_PAYLOAD = {
    "object_id": _OBJECT_ID,
    "object_type": "candidate",
    "override_type": "grade_override",
    "original_state": {"grade": "C"},
    "new_state": {"grade": "B"},
    "evidence_link": "https://jira.example.com/browse/FX-123",
    "rationale": "Extended backtest justifies grade uplift per regime analysis.",
}


# ---------------------------------------------------------------------------
# In-memory audit event collector for test assertions.
# The real write_audit_event() commits to a DB session. For unit tests we
# capture calls instead of hitting a database.
# ---------------------------------------------------------------------------


class MockAuditCollector:
    """
    Captures audit events for test verification.

    Responsibilities:
    - Record every call to write_audit_event() with full args.
    - Allow assertions on event count, actor, action, and metadata.

    Does NOT:
    - Persist data.

    Example:
        audit = MockAuditCollector()
        audit.write(actor="user:01H...", action="override.submitted", ...)
        assert audit.count() == 1
    """

    def __init__(self) -> None:
        self._events: list[dict] = []

    def write(
        self,
        *,
        actor: str,
        action: str,
        object_id: str,
        object_type: str,
        metadata: dict | None = None,
    ) -> str:
        """
        Record an audit event.

        Args:
            actor: Identity string.
            action: Action verb.
            object_id: ULID of affected entity.
            object_type: Entity type name.
            metadata: Optional context dict.

        Returns:
            A generated event ID string.
        """
        event_id = f"01HAUDIT{len(self._events):018d}"
        self._events.append(
            {
                "event_id": event_id,
                "actor": actor,
                "action": action,
                "object_id": object_id,
                "object_type": object_type,
                "metadata": metadata or {},
            }
        )
        return event_id

    def count(self) -> int:
        """Return number of recorded audit events."""
        return len(self._events)

    def last(self) -> dict:
        """Return the most recently recorded event."""
        return self._events[-1]

    def all(self) -> list[dict]:
        """Return all recorded events."""
        return list(self._events)

    def clear(self) -> None:
        """Remove all recorded events."""
        self._events.clear()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def override_repo() -> MockOverrideRepository:
    """Fresh mock override repository per test."""
    return MockOverrideRepository()


@pytest.fixture
def approval_repo() -> MockApprovalRepository:
    """Fresh mock approval repository per test."""
    return MockApprovalRepository()


@pytest.fixture
def audit_collector() -> MockAuditCollector:
    """Fresh mock audit event collector per test."""
    return MockAuditCollector()


@pytest.fixture
def service(
    override_repo: MockOverrideRepository,
    approval_repo: MockApprovalRepository,
    audit_collector: MockAuditCollector,
):
    """
    Build a GovernanceService with injected mock dependencies.

    Returns:
        GovernanceService wired to mock repos and audit collector.
    """
    from services.api.services.governance_service import GovernanceService

    return GovernanceService(
        override_repo=override_repo,
        approval_repo=approval_repo,
        audit_writer=audit_collector,
    )


# =========================================================================
# submit_override tests
# =========================================================================


class TestSubmitOverride:
    """Tests for GovernanceService.submit_override()."""

    def test_submit_override_happy_path_returns_pending(self, service, override_repo):
        """Submit a valid override → returns override_id + status='pending'."""
        result = service.submit_override(
            submitter_id=_SUBMITTER_ID,
            correlation_id=_CORRELATION_ID,
            **_OVERRIDE_PAYLOAD,
        )

        assert "override_id" in result
        assert result["status"] == "pending"
        assert override_repo.count() == 1

    def test_submit_override_creates_audit_event(self, service, audit_collector):
        """Submit override → exactly one audit event with correct action."""
        service.submit_override(
            submitter_id=_SUBMITTER_ID,
            correlation_id=_CORRELATION_ID,
            **_OVERRIDE_PAYLOAD,
        )

        assert audit_collector.count() == 1
        event = audit_collector.last()
        assert event["action"] == "override.submitted"
        assert event["actor"] == f"user:{_SUBMITTER_ID}"
        assert event["object_type"] == "override"

    def test_submit_override_stores_submitter_id(self, service, override_repo):
        """The submitter_id is persisted on the override record."""
        result = service.submit_override(
            submitter_id=_SUBMITTER_ID,
            correlation_id=_CORRELATION_ID,
            **_OVERRIDE_PAYLOAD,
        )

        record = override_repo.get_by_id(result["override_id"])
        assert record is not None
        assert record["submitter_id"] == _SUBMITTER_ID

    def test_submit_override_stores_evidence_and_rationale(self, service, override_repo):
        """Evidence link and rationale are persisted correctly."""
        result = service.submit_override(
            submitter_id=_SUBMITTER_ID,
            correlation_id=_CORRELATION_ID,
            **_OVERRIDE_PAYLOAD,
        )

        record = override_repo.get_by_id(result["override_id"])
        assert record["evidence_link"] == _OVERRIDE_PAYLOAD["evidence_link"]
        assert record["rationale"] == _OVERRIDE_PAYLOAD["rationale"]


# =========================================================================
# review_override tests
# =========================================================================


class TestReviewOverride:
    """Tests for GovernanceService.review_override()."""

    def _create_pending_override(self, service) -> str:
        """Helper: submit an override and return its ID."""
        result = service.submit_override(
            submitter_id=_SUBMITTER_ID,
            correlation_id=_CORRELATION_ID,
            **_OVERRIDE_PAYLOAD,
        )
        return result["override_id"]

    def test_review_override_approve_happy_path(self, service, override_repo, audit_collector):
        """Approve an override by a different user → status='approved'."""
        override_id = self._create_pending_override(service)
        audit_collector.clear()  # Reset audit from submit

        result = service.review_override(
            override_id=override_id,
            reviewer_id=_REVIEWER_ID,
            decision="approved",
            rationale="Evidence is satisfactory.",
            correlation_id=_CORRELATION_ID,
        )

        assert result["status"] == "approved"
        assert result["reviewer_id"] == _REVIEWER_ID

    def test_review_override_reject_happy_path(self, service, override_repo):
        """Reject an override by a different user → status='rejected'."""
        override_id = self._create_pending_override(service)

        result = service.review_override(
            override_id=override_id,
            reviewer_id=_REVIEWER_ID,
            decision="rejected",
            rationale="Insufficient backtest coverage for this regime.",
            correlation_id=_CORRELATION_ID,
        )

        assert result["status"] == "rejected"

    def test_review_override_sod_violation_raises_409(self, service):
        """Reviewer == submitter → SeparationOfDutiesError."""
        override_id = self._create_pending_override(service)

        with pytest.raises(SeparationOfDutiesError):
            service.review_override(
                override_id=override_id,
                reviewer_id=_SUBMITTER_ID,  # Same as submitter
                decision="approved",
                rationale="Self-approval attempt.",
                correlation_id=_CORRELATION_ID,
            )

    def test_review_override_not_found_raises_error(self, service):
        """Unknown override_id → NotFoundError."""
        with pytest.raises(NotFoundError):
            service.review_override(
                override_id="01HNONEXISTENT0000000000001",
                reviewer_id=_REVIEWER_ID,
                decision="approved",
                rationale="This override does not exist.",
                correlation_id=_CORRELATION_ID,
            )

    def test_review_override_creates_audit_event(self, service, audit_collector):
        """Review override → audit event with action='override.reviewed'."""
        override_id = self._create_pending_override(service)
        audit_collector.clear()

        service.review_override(
            override_id=override_id,
            reviewer_id=_REVIEWER_ID,
            decision="approved",
            rationale="All good.",
            correlation_id=_CORRELATION_ID,
        )

        assert audit_collector.count() == 1
        event = audit_collector.last()
        assert event["action"] == "override.reviewed"
        assert event["actor"] == f"user:{_REVIEWER_ID}"
        assert event["metadata"]["decision"] == "approved"

    def test_review_override_sod_does_not_create_audit_event(self, service, audit_collector):
        """SoD violation → no audit event (operation rejected before mutation)."""
        override_id = self._create_pending_override(service)
        audit_collector.clear()

        with pytest.raises(SeparationOfDutiesError):
            service.review_override(
                override_id=override_id,
                reviewer_id=_SUBMITTER_ID,
                decision="approved",
                rationale="Self-approval.",
                correlation_id=_CORRELATION_ID,
            )

        assert audit_collector.count() == 0


# =========================================================================
# approve_request tests
# =========================================================================


class TestApproveRequest:
    """Tests for GovernanceService.approve_request()."""

    def test_approve_request_happy_path(self, service, approval_repo, audit_collector):
        """Approve a pending request by a different user → status='approved'."""
        approval_repo.seed(
            approval_id="01HAPPROVAL0000000000000001",
            requested_by=_SUBMITTER_ID,
        )
        audit_collector.clear()

        result = service.approve_request(
            approval_id="01HAPPROVAL0000000000000001",
            reviewer_id=_REVIEWER_ID,
            correlation_id=_CORRELATION_ID,
        )

        assert result["status"] == "approved"
        assert result["reviewer_id"] == _REVIEWER_ID

    def test_approve_request_sod_violation_raises_409(self, service, approval_repo):
        """Reviewer == requested_by → SeparationOfDutiesError."""
        approval_repo.seed(
            approval_id="01HAPPROVAL0000000000000002",
            requested_by=_SUBMITTER_ID,
        )

        with pytest.raises(SeparationOfDutiesError):
            service.approve_request(
                approval_id="01HAPPROVAL0000000000000002",
                reviewer_id=_SUBMITTER_ID,  # Same as submitter
                correlation_id=_CORRELATION_ID,
            )

    def test_approve_request_not_found_raises_error(self, service):
        """Unknown approval_id → NotFoundError."""
        with pytest.raises(NotFoundError):
            service.approve_request(
                approval_id="01HNONEXISTENT0000000000002",
                reviewer_id=_REVIEWER_ID,
                correlation_id=_CORRELATION_ID,
            )

    def test_approve_request_creates_audit_event(self, service, approval_repo, audit_collector):
        """Approve → audit event with action='approval.approved'."""
        approval_repo.seed(
            approval_id="01HAPPROVAL0000000000000003",
            requested_by=_SUBMITTER_ID,
        )
        audit_collector.clear()

        service.approve_request(
            approval_id="01HAPPROVAL0000000000000003",
            reviewer_id=_REVIEWER_ID,
            correlation_id=_CORRELATION_ID,
        )

        assert audit_collector.count() == 1
        event = audit_collector.last()
        assert event["action"] == "approval.approved"
        assert event["actor"] == f"user:{_REVIEWER_ID}"
        assert event["object_id"] == "01HAPPROVAL0000000000000003"

    def test_approve_request_sod_does_not_mutate_record(self, service, approval_repo):
        """SoD violation → approval status remains 'pending'."""
        approval_repo.seed(
            approval_id="01HAPPROVAL0000000000000004",
            requested_by=_SUBMITTER_ID,
        )

        with pytest.raises(SeparationOfDutiesError):
            service.approve_request(
                approval_id="01HAPPROVAL0000000000000004",
                reviewer_id=_SUBMITTER_ID,
                correlation_id=_CORRELATION_ID,
            )

        record = approval_repo.get_by_id("01HAPPROVAL0000000000000004")
        assert record["status"] == "pending"


# =========================================================================
# reject_request tests
# =========================================================================


class TestRejectRequest:
    """Tests for GovernanceService.reject_request()."""

    def test_reject_request_happy_path(self, service, approval_repo, audit_collector):
        """Reject a pending request by a different user → status='rejected'."""
        approval_repo.seed(
            approval_id="01HAPPROVAL0000000000000010",
            requested_by=_SUBMITTER_ID,
        )
        audit_collector.clear()

        result = service.reject_request(
            approval_id="01HAPPROVAL0000000000000010",
            reviewer_id=_REVIEWER_ID,
            rationale="Evidence link is stale; regime not covered by backtest.",
            correlation_id=_CORRELATION_ID,
        )

        assert result["status"] == "rejected"
        assert result["reviewer_id"] == _REVIEWER_ID
        assert (
            result["decision_reason"] == "Evidence link is stale; regime not covered by backtest."
        )

    def test_reject_request_sod_violation_raises_409(self, service, approval_repo):
        """Reviewer == requested_by → SeparationOfDutiesError."""
        approval_repo.seed(
            approval_id="01HAPPROVAL0000000000000011",
            requested_by=_SUBMITTER_ID,
        )

        with pytest.raises(SeparationOfDutiesError):
            service.reject_request(
                approval_id="01HAPPROVAL0000000000000011",
                reviewer_id=_SUBMITTER_ID,
                rationale="Self-rejection attempt.",
                correlation_id=_CORRELATION_ID,
            )

    def test_reject_request_not_found_raises_error(self, service):
        """Unknown approval_id → NotFoundError."""
        with pytest.raises(NotFoundError):
            service.reject_request(
                approval_id="01HNONEXISTENT0000000000003",
                reviewer_id=_REVIEWER_ID,
                rationale="This approval does not exist.",
                correlation_id=_CORRELATION_ID,
            )

    def test_reject_request_creates_audit_event(self, service, approval_repo, audit_collector):
        """Reject → audit event with action='approval.rejected'."""
        approval_repo.seed(
            approval_id="01HAPPROVAL0000000000000012",
            requested_by=_SUBMITTER_ID,
        )
        audit_collector.clear()

        service.reject_request(
            approval_id="01HAPPROVAL0000000000000012",
            reviewer_id=_REVIEWER_ID,
            rationale="Insufficient coverage.",
            correlation_id=_CORRELATION_ID,
        )

        assert audit_collector.count() == 1
        event = audit_collector.last()
        assert event["action"] == "approval.rejected"
        assert event["actor"] == f"user:{_REVIEWER_ID}"

    def test_reject_request_sod_does_not_create_audit_event(
        self, service, approval_repo, audit_collector
    ):
        """SoD violation → no audit event (operation rejected before mutation)."""
        approval_repo.seed(
            approval_id="01HAPPROVAL0000000000000013",
            requested_by=_SUBMITTER_ID,
        )
        audit_collector.clear()

        with pytest.raises(SeparationOfDutiesError):
            service.reject_request(
                approval_id="01HAPPROVAL0000000000000013",
                reviewer_id=_SUBMITTER_ID,
                rationale="Self-rejection.",
                correlation_id=_CORRELATION_ID,
            )

        assert audit_collector.count() == 0


# =========================================================================
# SoD error message tests
# =========================================================================


class TestSodErrorMessage:
    """Verify the SoD error message matches the spec."""

    def test_sod_error_message_contains_required_text(self, service, approval_repo):
        """The SoD exception message must match the spec wording."""
        approval_repo.seed(
            approval_id="01HAPPROVAL0000000000000020",
            requested_by=_SUBMITTER_ID,
        )

        with pytest.raises(
            SeparationOfDutiesError, match="submitter and reviewer must be different users"
        ):
            service.approve_request(
                approval_id="01HAPPROVAL0000000000000020",
                reviewer_id=_SUBMITTER_ID,
                correlation_id=_CORRELATION_ID,
            )

    def test_sod_error_on_override_review_contains_required_text(self, service):
        """Override review SoD message also matches spec."""
        result = service.submit_override(
            submitter_id=_SUBMITTER_ID,
            correlation_id=_CORRELATION_ID,
            **_OVERRIDE_PAYLOAD,
        )

        with pytest.raises(
            SeparationOfDutiesError, match="submitter and reviewer must be different users"
        ):
            service.review_override(
                override_id=result["override_id"],
                reviewer_id=_SUBMITTER_ID,
                decision="approved",
                rationale="Self-approve.",
                correlation_id=_CORRELATION_ID,
            )
