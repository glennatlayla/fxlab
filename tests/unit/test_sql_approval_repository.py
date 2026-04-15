"""
Unit tests for SqlApprovalRepository.

Tests use an in-memory SQLite database (not mocks) to verify real SQL
behaviour against the ApprovalRepositoryInterface contract.

Purpose:
    Verify that SqlApprovalRepository correctly reads and updates
    approval records in a real database.

Dependencies:
    - SQLAlchemy: In-memory SQLite engine.
    - libs.contracts.models: ORM models (ApprovalRequest, Base).
    - libs.contracts.errors: NotFoundError.

Example:
    pytest tests/unit/test_sql_approval_repository.py -v
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.errors import NotFoundError
from libs.contracts.models import ApprovalRequest, Base

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_db():
    """Create an in-memory SQLite database with all tables for each test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    yield session
    session.close()


def _seed_approval(
    db: Session,
    *,
    approval_id: str = "01HAPPROVAL0000000000000001",
    candidate_id: str = "01HCANDIDATE000000000000001",
    requested_by: str = "01HUSER0000000000000000001",
    status: str = "pending",
) -> ApprovalRequest:
    """Insert a test approval request directly into the DB."""
    record = ApprovalRequest(
        id=approval_id,
        candidate_id=candidate_id,
        requested_by=requested_by,
        status=status,
    )
    db.add(record)
    db.flush()
    return record


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSqlApprovalRepositoryGetById:
    """Tests for get_by_id()."""

    def test_get_by_id_returns_record_when_exists(self, test_db: Session):
        """Seeded record is returned with all expected fields."""
        from services.api.repositories.sql_approval_repository import (
            SqlApprovalRepository,
        )

        _seed_approval(test_db, approval_id="01HAPPROVAL0000000000000001")
        repo = SqlApprovalRepository(db=test_db)
        result = repo.get_by_id("01HAPPROVAL0000000000000001")
        assert result is not None
        assert result["approval_id"] == "01HAPPROVAL0000000000000001"
        assert result["status"] == "pending"
        assert result["requested_by"] == "01HUSER0000000000000000001"
        assert result["reviewer_id"] is None
        assert result["decision_reason"] is None

    def test_get_by_id_returns_none_when_not_found(self, test_db: Session):
        """Non-existent ID returns None (not raises)."""
        from services.api.repositories.sql_approval_repository import (
            SqlApprovalRepository,
        )

        repo = SqlApprovalRepository(db=test_db)
        result = repo.get_by_id("01HNONEXISTENT0000000000000")
        assert result is None


class TestSqlApprovalRepositoryUpdateDecision:
    """Tests for update_decision()."""

    def test_update_decision_approve_updates_record(self, test_db: Session):
        """Approving a pending request sets status and reviewer."""
        from services.api.repositories.sql_approval_repository import (
            SqlApprovalRepository,
        )

        _seed_approval(test_db)
        repo = SqlApprovalRepository(db=test_db)
        result = repo.update_decision(
            approval_id="01HAPPROVAL0000000000000001",
            reviewer_id="01HREVIEWER000000000000001",
            status="approved",
            decision_reason="All criteria met.",
        )
        assert result["status"] == "approved"
        assert result["reviewer_id"] == "01HREVIEWER000000000000001"
        assert result["decision_reason"] == "All criteria met."

    def test_update_decision_reject_updates_record(self, test_db: Session):
        """Rejecting a pending request stores the rationale."""
        from services.api.repositories.sql_approval_repository import (
            SqlApprovalRepository,
        )

        _seed_approval(test_db)
        repo = SqlApprovalRepository(db=test_db)
        result = repo.update_decision(
            approval_id="01HAPPROVAL0000000000000001",
            reviewer_id="01HREVIEWER000000000000001",
            status="rejected",
            decision_reason="Evidence link is stale.",
        )
        assert result["status"] == "rejected"
        assert result["decision_reason"] == "Evidence link is stale."

    def test_update_decision_raises_not_found_for_missing_id(self, test_db: Session):
        """Updating a non-existent approval raises NotFoundError."""
        from services.api.repositories.sql_approval_repository import (
            SqlApprovalRepository,
        )

        repo = SqlApprovalRepository(db=test_db)
        with pytest.raises(NotFoundError):
            repo.update_decision(
                approval_id="01HNONEXISTENT0000000000000",
                reviewer_id="01HREVIEWER000000000000001",
                status="approved",
                decision_reason="n/a",
            )

    def test_update_decision_sets_decided_at_timestamp(self, test_db: Session):
        """decided_at must be set after a decision is recorded."""
        from services.api.repositories.sql_approval_repository import (
            SqlApprovalRepository,
        )

        _seed_approval(test_db)
        repo = SqlApprovalRepository(db=test_db)
        result = repo.update_decision(
            approval_id="01HAPPROVAL0000000000000001",
            reviewer_id="01HREVIEWER000000000000001",
            status="approved",
            decision_reason="Approved.",
        )
        assert result["decided_at"] is not None

    def test_update_decision_sets_updated_at_timestamp(self, test_db: Session):
        """updated_at must change after a decision is recorded."""
        from services.api.repositories.sql_approval_repository import (
            SqlApprovalRepository,
        )

        _seed_approval(test_db)
        repo = SqlApprovalRepository(db=test_db)

        # Read initial updated_at
        before = repo.get_by_id("01HAPPROVAL0000000000000001")
        assert before is not None

        result = repo.update_decision(
            approval_id="01HAPPROVAL0000000000000001",
            reviewer_id="01HREVIEWER000000000000001",
            status="approved",
            decision_reason="Approved.",
        )
        assert result["updated_at"] is not None
