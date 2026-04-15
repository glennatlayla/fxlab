"""
Unit tests for the DeploymentService state machine.

Covers:
- create_deployment: happy path, initial state='created'
- submit_for_approval: created → pending_approval
- approve_deployment: pending_approval → approved
- activate_deployment: approved → activating → active with gate checks
- activate_deployment without emergency posture → ValidationError
- freeze_deployment: active → frozen
- unfreeze_deployment: frozen → active
- deactivate_deployment: active → deactivating → deactivated
- rollback_deployment: active → rolled_back, frozen → rolled_back
- Invalid transitions raise StateTransitionError with current/attempted state
- All transitions produce audit records
- get_deployment: found and not found
- get_deployment_health: returns health response

Per M2 spec: state machine validation, policy gate enforcement, audit event emission.
"""

from __future__ import annotations

import pytest

from libs.contracts.deployment import DeploymentCreateRequest, RiskLimits
from libs.contracts.errors import NotFoundError, StateTransitionError, ValidationError
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from services.api.services.deployment_service import DeploymentService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

STRATEGY_ID = "01HTESTSTRT000000000000001"
USER_ID = "01HTESTSRA0000000000000001"
CORRELATION_ID = "corr-test-001"


@pytest.fixture()
def repo() -> MockDeploymentRepository:
    return MockDeploymentRepository()


@pytest.fixture()
def service(repo: MockDeploymentRepository) -> DeploymentService:
    return DeploymentService(repo=repo)


def _create_request(
    *,
    execution_mode: str = "paper",
    emergency_posture: str = "flatten_all",
) -> DeploymentCreateRequest:
    """Helper to build a valid DeploymentCreateRequest."""
    return DeploymentCreateRequest(
        strategy_id=STRATEGY_ID,
        execution_mode=execution_mode,
        emergency_posture=emergency_posture,
    )


# ---------------------------------------------------------------------------
# create_deployment
# ---------------------------------------------------------------------------


class TestCreateDeployment:
    """Tests for DeploymentService.create_deployment."""

    def test_creates_deployment_in_created_state(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        result = service.create_deployment(
            request=_create_request(),
            deployed_by=USER_ID,
            correlation_id=CORRELATION_ID,
        )
        assert result["state"] == "created"
        assert result["strategy_id"] == STRATEGY_ID
        assert result["execution_mode"] == "paper"
        assert result["emergency_posture"] == "flatten_all"
        assert repo.count() == 1

    def test_records_creation_transition(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        result = service.create_deployment(
            request=_create_request(),
            deployed_by=USER_ID,
            correlation_id=CORRELATION_ID,
        )
        transitions = repo.list_transitions(deployment_id=result["id"])
        # No transition on creation — the initial state doesn't come FROM anywhere
        assert len(transitions) == 0

    def test_create_with_custom_risk_limits(self, service: DeploymentService) -> None:
        req = DeploymentCreateRequest(
            strategy_id=STRATEGY_ID,
            execution_mode="live",
            emergency_posture="cancel_open",
            risk_limits=RiskLimits(max_position_size="50000", max_daily_loss="10000"),
        )
        result = service.create_deployment(
            request=req,
            deployed_by=USER_ID,
            correlation_id=CORRELATION_ID,
        )
        assert result["risk_limits"]["max_position_size"] == "50000"


# ---------------------------------------------------------------------------
# submit_for_approval
# ---------------------------------------------------------------------------


class TestSubmitForApproval:
    """Tests for created → pending_approval transition."""

    def test_valid_submission(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        deployment = service.create_deployment(
            request=_create_request(),
            deployed_by=USER_ID,
            correlation_id=CORRELATION_ID,
        )
        result = service.submit_for_approval(
            deployment_id=deployment["id"],
            actor=f"user:{USER_ID}",
            correlation_id=CORRELATION_ID,
        )
        assert result["state"] == "pending_approval"

    def test_records_transition_audit(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        deployment = service.create_deployment(
            request=_create_request(),
            deployed_by=USER_ID,
            correlation_id=CORRELATION_ID,
        )
        service.submit_for_approval(
            deployment_id=deployment["id"],
            actor=f"user:{USER_ID}",
            correlation_id=CORRELATION_ID,
        )
        transitions = repo.list_transitions(deployment_id=deployment["id"])
        assert len(transitions) == 1
        assert transitions[0]["from_state"] == "created"
        assert transitions[0]["to_state"] == "pending_approval"

    def test_invalid_from_active_state(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        deployment = repo.seed(state="active")
        with pytest.raises(StateTransitionError) as exc_info:
            service.submit_for_approval(
                deployment_id=deployment["id"],
                actor=f"user:{USER_ID}",
                correlation_id=CORRELATION_ID,
            )
        assert exc_info.value.current_state == "active"
        assert exc_info.value.attempted_state == "pending_approval"

    def test_not_found(self, service: DeploymentService) -> None:
        with pytest.raises(NotFoundError):
            service.submit_for_approval(
                deployment_id="01HNONEXSTNT000000000000001",
                actor=f"user:{USER_ID}",
                correlation_id=CORRELATION_ID,
            )


# ---------------------------------------------------------------------------
# approve_deployment
# ---------------------------------------------------------------------------


class TestApproveDeployment:
    """Tests for pending_approval → approved transition."""

    def test_valid_approval(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        deployment = repo.seed(state="pending_approval")
        result = service.approve_deployment(
            deployment_id=deployment["id"],
            actor=f"user:{USER_ID}",
            correlation_id=CORRELATION_ID,
        )
        assert result["state"] == "approved"

    def test_invalid_from_created(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        deployment = repo.seed(state="created")
        with pytest.raises(StateTransitionError):
            service.approve_deployment(
                deployment_id=deployment["id"],
                actor=f"user:{USER_ID}",
                correlation_id=CORRELATION_ID,
            )


# ---------------------------------------------------------------------------
# activate_deployment
# ---------------------------------------------------------------------------


class TestActivateDeployment:
    """Tests for approved → activating → active transition with policy gates."""

    def test_valid_activation(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        deployment = repo.seed(state="approved", emergency_posture="flatten_all")
        result = service.activate_deployment(
            deployment_id=deployment["id"],
            actor=f"user:{USER_ID}",
            correlation_id=CORRELATION_ID,
        )
        assert result["state"] == "active"

    def test_activation_records_two_transitions(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        """Activation goes approved → activating → active (2 transitions)."""
        deployment = repo.seed(state="approved", emergency_posture="flatten_all")
        service.activate_deployment(
            deployment_id=deployment["id"],
            actor=f"user:{USER_ID}",
            correlation_id=CORRELATION_ID,
        )
        transitions = repo.list_transitions(deployment_id=deployment["id"])
        assert len(transitions) == 2
        assert transitions[0]["from_state"] == "approved"
        assert transitions[0]["to_state"] == "activating"
        assert transitions[1]["from_state"] == "activating"
        assert transitions[1]["to_state"] == "active"

    def test_invalid_from_created(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        deployment = repo.seed(state="created")
        with pytest.raises(StateTransitionError):
            service.activate_deployment(
                deployment_id=deployment["id"],
                actor=f"user:{USER_ID}",
                correlation_id=CORRELATION_ID,
            )

    def test_no_emergency_posture_rejected(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        """Spec rule 6: deployment cannot activate without declared emergency posture."""
        deployment = repo.seed(state="approved", emergency_posture="")
        with pytest.raises(ValidationError, match="emergency posture"):
            service.activate_deployment(
                deployment_id=deployment["id"],
                actor=f"user:{USER_ID}",
                correlation_id=CORRELATION_ID,
            )


# ---------------------------------------------------------------------------
# freeze_deployment
# ---------------------------------------------------------------------------


class TestFreezeDeployment:
    """Tests for active → frozen transition."""

    def test_valid_freeze(self, service: DeploymentService, repo: MockDeploymentRepository) -> None:
        deployment = repo.seed(state="active")
        result = service.freeze_deployment(
            deployment_id=deployment["id"],
            reason="Risk limit breached",
            actor=f"user:{USER_ID}",
            correlation_id=CORRELATION_ID,
        )
        assert result["state"] == "frozen"

    def test_freeze_records_reason(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        deployment = repo.seed(state="active")
        service.freeze_deployment(
            deployment_id=deployment["id"],
            reason="Risk limit breached",
            actor=f"user:{USER_ID}",
            correlation_id=CORRELATION_ID,
        )
        transitions = repo.list_transitions(deployment_id=deployment["id"])
        assert transitions[0]["reason"] == "Risk limit breached"

    def test_invalid_from_created(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        deployment = repo.seed(state="created")
        with pytest.raises(StateTransitionError):
            service.freeze_deployment(
                deployment_id=deployment["id"],
                reason="test",
                actor=f"user:{USER_ID}",
                correlation_id=CORRELATION_ID,
            )


# ---------------------------------------------------------------------------
# unfreeze_deployment
# ---------------------------------------------------------------------------


class TestUnfreezeDeployment:
    """Tests for frozen → active transition."""

    def test_valid_unfreeze(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        deployment = repo.seed(state="frozen")
        result = service.unfreeze_deployment(
            deployment_id=deployment["id"],
            actor=f"user:{USER_ID}",
            correlation_id=CORRELATION_ID,
        )
        assert result["state"] == "active"

    def test_invalid_from_active(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        deployment = repo.seed(state="active")
        with pytest.raises(StateTransitionError):
            service.unfreeze_deployment(
                deployment_id=deployment["id"],
                actor=f"user:{USER_ID}",
                correlation_id=CORRELATION_ID,
            )


# ---------------------------------------------------------------------------
# deactivate_deployment
# ---------------------------------------------------------------------------


class TestDeactivateDeployment:
    """Tests for active/frozen → deactivating → deactivated."""

    def test_deactivate_from_active(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        deployment = repo.seed(state="active")
        result = service.deactivate_deployment(
            deployment_id=deployment["id"],
            actor=f"user:{USER_ID}",
            correlation_id=CORRELATION_ID,
        )
        assert result["state"] == "deactivated"

    def test_deactivate_from_frozen(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        deployment = repo.seed(state="frozen")
        result = service.deactivate_deployment(
            deployment_id=deployment["id"],
            actor=f"user:{USER_ID}",
            correlation_id=CORRELATION_ID,
        )
        assert result["state"] == "deactivated"

    def test_deactivation_records_two_transitions(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        """Deactivation goes active → deactivating → deactivated (2 transitions)."""
        deployment = repo.seed(state="active")
        service.deactivate_deployment(
            deployment_id=deployment["id"],
            actor=f"user:{USER_ID}",
            correlation_id=CORRELATION_ID,
        )
        transitions = repo.list_transitions(deployment_id=deployment["id"])
        assert len(transitions) == 2
        assert transitions[0]["to_state"] == "deactivating"
        assert transitions[1]["to_state"] == "deactivated"

    def test_invalid_from_created(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        deployment = repo.seed(state="created")
        with pytest.raises(StateTransitionError):
            service.deactivate_deployment(
                deployment_id=deployment["id"],
                actor=f"user:{USER_ID}",
                correlation_id=CORRELATION_ID,
            )


# ---------------------------------------------------------------------------
# rollback_deployment
# ---------------------------------------------------------------------------


class TestRollbackDeployment:
    """Tests for active/frozen → rolled_back."""

    def test_rollback_from_active(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        deployment = repo.seed(state="active")
        result = service.rollback_deployment(
            deployment_id=deployment["id"],
            actor=f"user:{USER_ID}",
            correlation_id=CORRELATION_ID,
        )
        assert result["state"] == "rolled_back"

    def test_rollback_from_frozen(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        deployment = repo.seed(state="frozen")
        result = service.rollback_deployment(
            deployment_id=deployment["id"],
            actor=f"user:{USER_ID}",
            correlation_id=CORRELATION_ID,
        )
        assert result["state"] == "rolled_back"

    def test_invalid_from_deactivated(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        deployment = repo.seed(state="deactivated")
        with pytest.raises(StateTransitionError):
            service.rollback_deployment(
                deployment_id=deployment["id"],
                actor=f"user:{USER_ID}",
                correlation_id=CORRELATION_ID,
            )


# ---------------------------------------------------------------------------
# get_deployment
# ---------------------------------------------------------------------------


class TestGetDeployment:
    """Tests for DeploymentService.get_deployment."""

    def test_found(self, service: DeploymentService, repo: MockDeploymentRepository) -> None:
        deployment = repo.seed(state="active")
        result = service.get_deployment(deployment_id=deployment["id"])
        assert result["id"] == deployment["id"]
        assert result["state"] == "active"

    def test_not_found(self, service: DeploymentService) -> None:
        with pytest.raises(NotFoundError):
            service.get_deployment(deployment_id="01HNONEXSTNT000000000000001")


# ---------------------------------------------------------------------------
# get_deployment_health
# ---------------------------------------------------------------------------


class TestGetDeploymentHealth:
    """Tests for DeploymentService.get_deployment_health."""

    def test_returns_health_response(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        deployment = repo.seed(state="active", emergency_posture="flatten_all")
        health = service.get_deployment_health(deployment_id=deployment["id"])
        assert health.deployment_id == deployment["id"]
        assert health.state == "active"
        assert health.emergency_posture == "flatten_all"
        assert health.open_order_count == 0

    def test_not_found(self, service: DeploymentService) -> None:
        with pytest.raises(NotFoundError):
            service.get_deployment_health(deployment_id="01HNONEXSTNT000000000000001")


# ---------------------------------------------------------------------------
# Full lifecycle
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    """Integration-style test for the full deployment lifecycle via service."""

    def test_create_submit_approve_activate_freeze_unfreeze_deactivate(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        """Exercise the complete happy path lifecycle."""
        # Create
        deployment = service.create_deployment(
            request=_create_request(),
            deployed_by=USER_ID,
            correlation_id=CORRELATION_ID,
        )
        assert deployment["state"] == "created"

        dep_id = deployment["id"]
        actor = f"user:{USER_ID}"

        # Submit for approval
        result = service.submit_for_approval(
            deployment_id=dep_id, actor=actor, correlation_id=CORRELATION_ID
        )
        assert result["state"] == "pending_approval"

        # Approve
        result = service.approve_deployment(
            deployment_id=dep_id, actor=actor, correlation_id=CORRELATION_ID
        )
        assert result["state"] == "approved"

        # Activate
        result = service.activate_deployment(
            deployment_id=dep_id, actor=actor, correlation_id=CORRELATION_ID
        )
        assert result["state"] == "active"

        # Freeze
        result = service.freeze_deployment(
            deployment_id=dep_id,
            reason="Manual intervention",
            actor=actor,
            correlation_id=CORRELATION_ID,
        )
        assert result["state"] == "frozen"

        # Unfreeze
        result = service.unfreeze_deployment(
            deployment_id=dep_id, actor=actor, correlation_id=CORRELATION_ID
        )
        assert result["state"] == "active"

        # Deactivate
        result = service.deactivate_deployment(
            deployment_id=dep_id, actor=actor, correlation_id=CORRELATION_ID
        )
        assert result["state"] == "deactivated"

        # Verify audit trail
        transitions = repo.list_transitions(deployment_id=dep_id)
        # create(0) + submit(1) + approve(1) + activate(2) + freeze(1) + unfreeze(1) + deactivate(2) = 8
        assert len(transitions) == 8

    def test_create_submit_approve_activate_rollback(
        self, service: DeploymentService, repo: MockDeploymentRepository
    ) -> None:
        """Rollback path from active state."""
        deployment = service.create_deployment(
            request=_create_request(),
            deployed_by=USER_ID,
            correlation_id=CORRELATION_ID,
        )
        dep_id = deployment["id"]
        actor = f"user:{USER_ID}"

        service.submit_for_approval(
            deployment_id=dep_id, actor=actor, correlation_id=CORRELATION_ID
        )
        service.approve_deployment(deployment_id=dep_id, actor=actor, correlation_id=CORRELATION_ID)
        service.activate_deployment(
            deployment_id=dep_id, actor=actor, correlation_id=CORRELATION_ID
        )
        result = service.rollback_deployment(
            deployment_id=dep_id, actor=actor, correlation_id=CORRELATION_ID
        )
        assert result["state"] == "rolled_back"
