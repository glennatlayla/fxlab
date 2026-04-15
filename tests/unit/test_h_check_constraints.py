"""
Database CHECK constraint validation tests.

Verify that enum-like String columns on ORM models are guarded by
CheckConstraint definitions in __table_args__, preventing invalid values
from reaching the database.

These tests validate the column-level constraints EXIST on each model.
Integration tests would verify that the database rejects invalid INSERTs,
but unit tests confirm the ORM schema is correctly defined.

Dependencies:
    - libs.contracts.models (ORM models with CheckConstraint table args)

Example:
    pytest tests/unit/test_h_check_constraints.py -v
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint

# ---------------------------------------------------------------------------
# Helper: extract CheckConstraint names from a model's __table_args__
# ---------------------------------------------------------------------------


def _get_check_constraint_names(model_class: type) -> set[str]:
    """
    Extract all named CheckConstraint names from a model's table.

    Args:
        model_class: A SQLAlchemy ORM model class.

    Returns:
        Set of constraint names found on the table.
    """
    names: set[str] = set()
    for constraint in model_class.__table__.constraints:
        if isinstance(constraint, CheckConstraint) and constraint.name:
            names.add(constraint.name)
    return names


# ---------------------------------------------------------------------------
# Test: users.role
# ---------------------------------------------------------------------------


class TestUserRoleConstraint:
    """
    users.role must be constrained to the RBAC roles used by the auth system.

    Valid values: admin, operator, reviewer, viewer
    (from ROLE_SCOPES in services/api/auth.py — the authoritative source)
    """

    def test_user_has_role_check_constraint(self) -> None:
        """User model must define a CHECK constraint on the role column."""
        from libs.contracts.models import User

        names = _get_check_constraint_names(User)
        assert "chk_users_role" in names, (
            f"User model missing 'chk_users_role' CheckConstraint. Found: {names}"
        )


# ---------------------------------------------------------------------------
# Test: runs.status + runs.run_type
# ---------------------------------------------------------------------------


class TestRunConstraints:
    """
    runs.status must be constrained to RunStatus enum values.
    runs.run_type must be constrained to valid execution types.
    """

    def test_run_has_status_check_constraint(self) -> None:
        """Run model must define a CHECK constraint on status."""
        from libs.contracts.models import Run

        names = _get_check_constraint_names(Run)
        assert "chk_runs_status" in names, (
            f"Run model missing 'chk_runs_status' CheckConstraint. Found: {names}"
        )

    def test_run_has_run_type_check_constraint(self) -> None:
        """Run model must define a CHECK constraint on run_type."""
        from libs.contracts.models import Run

        names = _get_check_constraint_names(Run)
        assert "chk_runs_run_type" in names, (
            f"Run model missing 'chk_runs_run_type' CheckConstraint. Found: {names}"
        )


# ---------------------------------------------------------------------------
# Test: strategies (no enum column, but strategy_builds.build_status)
# ---------------------------------------------------------------------------


class TestStrategyBuildConstraints:
    """strategy_builds.build_status must be constrained."""

    def test_strategy_build_has_status_check_constraint(self) -> None:
        """StrategyBuild model must define a CHECK constraint on build_status."""
        from libs.contracts.models import StrategyBuild

        names = _get_check_constraint_names(StrategyBuild)
        assert "chk_strategy_builds_build_status" in names, (
            f"StrategyBuild missing 'chk_strategy_builds_build_status'. Found: {names}"
        )


# ---------------------------------------------------------------------------
# Test: candidates.status
# ---------------------------------------------------------------------------


class TestCandidateConstraints:
    """candidates.status must be constrained."""

    def test_candidate_has_status_check_constraint(self) -> None:
        """Candidate model must define a CHECK constraint on status."""
        from libs.contracts.models import Candidate

        names = _get_check_constraint_names(Candidate)
        assert "chk_candidates_status" in names, (
            f"Candidate missing 'chk_candidates_status'. Found: {names}"
        )


# ---------------------------------------------------------------------------
# Test: deployments.status + deployments.environment
# ---------------------------------------------------------------------------


class TestDeploymentConstraints:
    """deployments columns must be constrained."""

    def test_deployment_has_status_check_constraint(self) -> None:
        """Deployment model must define a CHECK constraint on status."""
        from libs.contracts.models import Deployment

        names = _get_check_constraint_names(Deployment)
        assert "chk_deployments_status" in names, (
            f"Deployment missing 'chk_deployments_status'. Found: {names}"
        )

    def test_deployment_has_environment_check_constraint(self) -> None:
        """Deployment model must define a CHECK constraint on environment."""
        from libs.contracts.models import Deployment

        names = _get_check_constraint_names(Deployment)
        assert "chk_deployments_environment" in names, (
            f"Deployment missing 'chk_deployments_environment'. Found: {names}"
        )


# ---------------------------------------------------------------------------
# Test: overrides.status
# ---------------------------------------------------------------------------


class TestOverrideConstraints:
    """overrides.status must be constrained."""

    def test_override_has_status_check_constraint(self) -> None:
        """Override model must define a CHECK constraint on status."""
        from libs.contracts.models import Override

        names = _get_check_constraint_names(Override)
        assert "chk_overrides_status" in names, (
            f"Override missing 'chk_overrides_status'. Found: {names}"
        )


# ---------------------------------------------------------------------------
# Test: approval_requests.status
# ---------------------------------------------------------------------------


class TestApprovalRequestConstraints:
    """approval_requests.status must be constrained."""

    def test_approval_request_has_status_check_constraint(self) -> None:
        """ApprovalRequest must define a CHECK constraint on status."""
        from libs.contracts.models import ApprovalRequest

        names = _get_check_constraint_names(ApprovalRequest)
        assert "chk_approval_requests_status" in names, (
            f"ApprovalRequest missing 'chk_approval_requests_status'. Found: {names}"
        )


# ---------------------------------------------------------------------------
# Test: promotion_requests.status + target_environment
# ---------------------------------------------------------------------------


class TestPromotionRequestConstraints:
    """promotion_requests columns must be constrained."""

    def test_promotion_request_has_status_check_constraint(self) -> None:
        """PromotionRequest must define a CHECK constraint on status."""
        from libs.contracts.models import PromotionRequest

        names = _get_check_constraint_names(PromotionRequest)
        assert "chk_promotion_requests_status" in names, (
            f"PromotionRequest missing 'chk_promotion_requests_status'. Found: {names}"
        )

    def test_promotion_request_has_target_environment_check_constraint(self) -> None:
        """PromotionRequest must define a CHECK on target_environment."""
        from libs.contracts.models import PromotionRequest

        names = _get_check_constraint_names(PromotionRequest)
        assert "chk_promotion_requests_target_environment" in names, (
            f"PromotionRequest missing 'chk_promotion_requests_target_environment'. Found: {names}"
        )


# ---------------------------------------------------------------------------
# Test: feed_health_events.status
# ---------------------------------------------------------------------------


class TestFeedHealthEventConstraints:
    """feed_health_events.status must be constrained."""

    def test_feed_health_event_has_status_check_constraint(self) -> None:
        """FeedHealthEvent must define a CHECK constraint on status."""
        from libs.contracts.models import FeedHealthEvent

        names = _get_check_constraint_names(FeedHealthEvent)
        assert "chk_feed_health_events_status" in names, (
            f"FeedHealthEvent missing 'chk_feed_health_events_status'. Found: {names}"
        )


# ---------------------------------------------------------------------------
# Test: parity_events.status
# ---------------------------------------------------------------------------


class TestParityEventConstraints:
    """parity_events.status must be constrained."""

    def test_parity_event_has_status_check_constraint(self) -> None:
        """ParityEvent must define a CHECK constraint on status."""
        from libs.contracts.models import ParityEvent

        names = _get_check_constraint_names(ParityEvent)
        assert "chk_parity_events_status" in names, (
            f"ParityEvent missing 'chk_parity_events_status'. Found: {names}"
        )


# ---------------------------------------------------------------------------
# Test: certification_events.status
# ---------------------------------------------------------------------------


class TestCertificationEventConstraints:
    """certification_events.status must be constrained."""

    def test_certification_event_has_status_check_constraint(self) -> None:
        """CertificationEvent must define a CHECK constraint on status."""
        from libs.contracts.models import CertificationEvent

        names = _get_check_constraint_names(CertificationEvent)
        assert "chk_certification_events_status" in names, (
            f"CertificationEvent missing 'chk_certification_events_status'. Found: {names}"
        )


# ---------------------------------------------------------------------------
# Test: trials.status
# ---------------------------------------------------------------------------


class TestTrialConstraints:
    """trials.status must be constrained."""

    def test_trial_has_status_check_constraint(self) -> None:
        """Trial must define a CHECK constraint on status."""
        from libs.contracts.models import Trial

        names = _get_check_constraint_names(Trial)
        assert "chk_trials_status" in names, f"Trial missing 'chk_trials_status'. Found: {names}"
