"""
Unit tests verifying required database indexes exist on ORM models (INFRA-3).

Purpose:
    Ensure all columns that will be queried in production have database
    indexes defined. This test inspects SQLAlchemy metadata to verify
    indexes exist — it does NOT require a running database.

Dependencies:
    - SQLAlchemy: In-memory SQLite engine for metadata inspection.
    - libs.contracts.models: ORM models (Base and all model classes).

Example:
    pytest tests/unit/test_missing_indexes.py -v
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect

from libs.contracts.models import Base

# ---------------------------------------------------------------------------
# Fixture: create all tables and return an inspector
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def inspector():
    """Create an in-memory SQLite database with all tables and return an inspector."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return inspect(engine)


# ---------------------------------------------------------------------------
# Helper: check that a column is indexed
# ---------------------------------------------------------------------------


def _column_is_indexed(insp, table_name: str, column_name: str) -> bool:
    """
    Check if a column has any index (standalone, composite, unique, or PK).

    Args:
        insp: SQLAlchemy Inspector instance.
        table_name: Name of the database table.
        column_name: Name of the column to check.

    Returns:
        True if the column participates in at least one index or constraint.
    """
    # Check regular indexes
    indexes = insp.get_indexes(table_name)
    for idx in indexes:
        if column_name in idx["column_names"]:
            return True

    # Check unique constraints
    unique_constraints = insp.get_unique_constraints(table_name)
    for uc in unique_constraints:
        if column_name in uc["column_names"]:
            return True

    # Check primary keys
    pk = insp.get_pk_constraint(table_name)
    return column_name in pk.get("constrained_columns", [])


# ---------------------------------------------------------------------------
# Test cases — one per required index
# ---------------------------------------------------------------------------


class TestFeedIndexes:
    """Verify indexes on feeds table."""

    def test_feeds_feed_type_indexed(self, inspector) -> None:
        """feeds.feed_type must be indexed for type-based filtering."""
        assert _column_is_indexed(inspector, "feeds", "feed_type")


class TestAuditEventIndexes:
    """Verify indexes on audit_events table."""

    def test_audit_events_actor_indexed(self, inspector) -> None:
        """audit_events.actor must be indexed for actor lookups."""
        assert _column_is_indexed(inspector, "audit_events", "actor")

    def test_audit_events_action_indexed(self, inspector) -> None:
        """audit_events.action must be indexed for action filtering."""
        assert _column_is_indexed(inspector, "audit_events", "action")

    def test_audit_events_object_id_indexed(self, inspector) -> None:
        """audit_events.object_id must be indexed for object lookups."""
        assert _column_is_indexed(inspector, "audit_events", "object_id")


class TestApprovalRequestIndexes:
    """Verify indexes on approval_requests table."""

    def test_approval_requests_requested_by_indexed(self, inspector) -> None:
        """approval_requests.requested_by must be indexed."""
        assert _column_is_indexed(inspector, "approval_requests", "requested_by")

    def test_approval_requests_reviewer_id_indexed(self, inspector) -> None:
        """approval_requests.reviewer_id must be indexed."""
        assert _column_is_indexed(inspector, "approval_requests", "reviewer_id")

    def test_approval_requests_candidate_id_indexed(self, inspector) -> None:
        """approval_requests.candidate_id must be indexed."""
        assert _column_is_indexed(inspector, "approval_requests", "candidate_id")


class TestCertificationEventIndexes:
    """Verify indexes on certification_events table."""

    def test_certification_events_certification_type_indexed(self, inspector) -> None:
        """certification_events.certification_type must be indexed."""
        assert _column_is_indexed(inspector, "certification_events", "certification_type")


class TestPromotionRequestIndexes:
    """Verify indexes on promotion_requests table."""

    def test_promotion_requests_requester_id_indexed(self, inspector) -> None:
        """promotion_requests.requester_id must be indexed."""
        assert _column_is_indexed(inspector, "promotion_requests", "requester_id")

    def test_promotion_requests_reviewer_id_indexed(self, inspector) -> None:
        """promotion_requests.reviewer_id must be indexed."""
        assert _column_is_indexed(inspector, "promotion_requests", "reviewer_id")


class TestRevokedTokenIndexes:
    """Verify revoked_tokens table exists with JTI primary key."""

    def test_revoked_tokens_jti_is_primary_key(self, inspector) -> None:
        """revoked_tokens.jti must be the primary key (indexed implicitly)."""
        assert _column_is_indexed(inspector, "revoked_tokens", "jti")
