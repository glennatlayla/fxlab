"""
Non-nullable foreign key validation tests.

Audit-trail columns that reference the acting user (created_by, submitted_by,
submitter_id, requested_by, deployed_by) must be NOT NULL to ensure every
mutation in the system has a traceable actor — a SOC 2 compliance requirement.

Dependencies:
    - libs.contracts.models

Example:
    pytest tests/unit/test_h_nonnullable_fks.py -v
"""

from __future__ import annotations


def _column_is_nullable(model_class: type, column_name: str) -> bool:
    """
    Check whether a column on a SQLAlchemy model is nullable.

    Args:
        model_class: A SQLAlchemy ORM model class.
        column_name: Name of the column to check.

    Returns:
        True if the column allows NULL, False if NOT NULL.
    """
    col = model_class.__table__.columns[column_name]
    return col.nullable


class TestStrategyCreatedByNotNull:
    """Strategy.created_by must be NOT NULL — every strategy has a creator."""

    def test_strategy_created_by_is_not_nullable(self) -> None:
        """created_by column must reject NULL."""
        from libs.contracts.models import Strategy

        assert not _column_is_nullable(Strategy, "created_by"), (
            "Strategy.created_by must be NOT NULL for audit traceability"
        )


class TestCandidateSubmittedByNotNull:
    """Candidate.submitted_by must be NOT NULL — every candidate has a submitter."""

    def test_candidate_submitted_by_is_not_nullable(self) -> None:
        """submitted_by column must reject NULL."""
        from libs.contracts.models import Candidate

        assert not _column_is_nullable(Candidate, "submitted_by"), (
            "Candidate.submitted_by must be NOT NULL for audit traceability"
        )


class TestDeploymentDeployedByNotNull:
    """Deployment.deployed_by must be NOT NULL — every deployment has a deployer."""

    def test_deployment_deployed_by_is_not_nullable(self) -> None:
        """deployed_by column must reject NULL."""
        from libs.contracts.models import Deployment

        assert not _column_is_nullable(Deployment, "deployed_by"), (
            "Deployment.deployed_by must be NOT NULL for audit traceability"
        )


class TestOverrideSubmitterNotNull:
    """Override.submitter_id must be NOT NULL — every override has a submitter."""

    def test_override_submitter_id_is_not_nullable(self) -> None:
        """submitter_id column must reject NULL."""
        from libs.contracts.models import Override

        assert not _column_is_nullable(Override, "submitter_id"), (
            "Override.submitter_id must be NOT NULL for audit traceability"
        )


class TestApprovalRequestRequestedByNotNull:
    """ApprovalRequest.requested_by must be NOT NULL — every request has a requester."""

    def test_approval_request_requested_by_is_not_nullable(self) -> None:
        """requested_by column must reject NULL."""
        from libs.contracts.models import ApprovalRequest

        assert not _column_is_nullable(ApprovalRequest, "requested_by"), (
            "ApprovalRequest.requested_by must be NOT NULL for audit traceability"
        )


class TestPromotionRequestRequesterNotNull:
    """PromotionRequest.requester_id must be NOT NULL."""

    def test_promotion_request_requester_id_is_not_nullable(self) -> None:
        """requester_id column must reject NULL."""
        from libs.contracts.models import PromotionRequest

        assert not _column_is_nullable(PromotionRequest, "requester_id"), (
            "PromotionRequest.requester_id must be NOT NULL for audit traceability"
        )
