"""Tests for database schema model constraints and ULID primary keys.

Tests verify AC1: All tables support ULID primary keys and include created_at/updated_at.
"""

import pytest
from sqlalchemy import inspect

from libs.contracts.models import (
    Strategy,
    User,
)


class TestAC1ULIDPrimaryKeys:
    """AC1: All tables support ULID primary keys."""

    def test_ac1_strategy_table_has_ulid_primary_key(self, in_memory_db):
        """Verify Strategy table uses ULID as primary key."""
        inspector = inspect(in_memory_db.bind)
        columns = {col["name"]: col for col in inspector.get_columns("strategies")}

        assert "id" in columns
        pk_constraints = inspector.get_pk_constraint("strategies")
        assert "id" in pk_constraints["constrained_columns"]

        # Attempt to insert non-ULID should fail type/length constraints.
        # The @validates decorator fires at attribute-assignment time (during
        # construction), so the exception is raised before commit().
        with pytest.raises(Exception):  # ValueError from @validates or IntegrityError
            strategy = Strategy(
                id="not-a-ulid",  # Too short, wrong format
                name="Test Strategy",
                code="def entry(): pass",
            )
            in_memory_db.add(strategy)
            in_memory_db.commit()

    def test_ac1_strategy_build_table_has_ulid_primary_key(self, in_memory_db):
        """Verify StrategyBuild table uses ULID as primary key."""
        inspector = inspect(in_memory_db.bind)
        pk_constraints = inspector.get_pk_constraint("strategy_builds")
        assert "id" in pk_constraints["constrained_columns"]

    def test_ac1_candidate_table_has_ulid_primary_key(self, in_memory_db):
        """Verify Candidate table uses ULID as primary key."""
        inspector = inspect(in_memory_db.bind)
        pk_constraints = inspector.get_pk_constraint("candidates")
        assert "id" in pk_constraints["constrained_columns"]

    def test_ac1_deployment_table_has_ulid_primary_key(self, in_memory_db):
        """Verify Deployment table uses ULID as primary key."""
        inspector = inspect(in_memory_db.bind)
        pk_constraints = inspector.get_pk_constraint("deployments")
        assert "id" in pk_constraints["constrained_columns"]

    def test_ac1_run_table_has_ulid_primary_key(self, in_memory_db):
        """Verify Run table uses ULID as primary key."""
        inspector = inspect(in_memory_db.bind)
        pk_constraints = inspector.get_pk_constraint("runs")
        assert "id" in pk_constraints["constrained_columns"]

    def test_ac1_trial_table_has_ulid_primary_key(self, in_memory_db):
        """Verify Trial table uses ULID as primary key."""
        inspector = inspect(in_memory_db.bind)
        pk_constraints = inspector.get_pk_constraint("trials")
        assert "id" in pk_constraints["constrained_columns"]

    def test_ac1_artifact_table_has_ulid_primary_key(self, in_memory_db):
        """Verify Artifact table uses ULID as primary key."""
        inspector = inspect(in_memory_db.bind)
        pk_constraints = inspector.get_pk_constraint("artifacts")
        assert "id" in pk_constraints["constrained_columns"]

    def test_ac1_audit_event_table_has_ulid_primary_key(self, in_memory_db):
        """Verify AuditEvent table uses ULID as primary key."""
        inspector = inspect(in_memory_db.bind)
        pk_constraints = inspector.get_pk_constraint("audit_events")
        assert "id" in pk_constraints["constrained_columns"]

    def test_ac1_feed_table_has_ulid_primary_key(self, in_memory_db):
        """Verify Feed table uses ULID as primary key."""
        inspector = inspect(in_memory_db.bind)
        pk_constraints = inspector.get_pk_constraint("feeds")
        assert "id" in pk_constraints["constrained_columns"]

    def test_ac1_feed_health_event_table_has_ulid_primary_key(self, in_memory_db):
        """Verify FeedHealthEvent table uses ULID as primary key."""
        inspector = inspect(in_memory_db.bind)
        pk_constraints = inspector.get_pk_constraint("feed_health_events")
        assert "id" in pk_constraints["constrained_columns"]

    def test_ac1_parity_event_table_has_ulid_primary_key(self, in_memory_db):
        """Verify ParityEvent table uses ULID as primary key."""
        inspector = inspect(in_memory_db.bind)
        pk_constraints = inspector.get_pk_constraint("parity_events")
        assert "id" in pk_constraints["constrained_columns"]

    def test_ac1_override_table_has_ulid_primary_key(self, in_memory_db):
        """Verify Override table uses ULID as primary key."""
        inspector = inspect(in_memory_db.bind)
        pk_constraints = inspector.get_pk_constraint("overrides")
        assert "id" in pk_constraints["constrained_columns"]

    def test_ac1_approval_request_table_has_ulid_primary_key(self, in_memory_db):
        """Verify ApprovalRequest table uses ULID as primary key."""
        inspector = inspect(in_memory_db.bind)
        pk_constraints = inspector.get_pk_constraint("approval_requests")
        assert "id" in pk_constraints["constrained_columns"]

    def test_ac1_user_table_has_ulid_primary_key(self, in_memory_db):
        """Verify User table uses ULID as primary key."""
        inspector = inspect(in_memory_db.bind)
        pk_constraints = inspector.get_pk_constraint("users")
        assert "id" in pk_constraints["constrained_columns"]


class TestAC1TimestampColumns:
    """AC1: All tables include created_at/updated_at columns."""

    def test_ac1_strategy_has_timestamp_columns(self, in_memory_db):
        """Verify Strategy table has created_at and updated_at."""
        inspector = inspect(in_memory_db.bind)
        columns = {col["name"]: col for col in inspector.get_columns("strategies")}

        assert "created_at" in columns
        assert "updated_at" in columns

    def test_ac1_strategy_build_has_timestamp_columns(self, in_memory_db):
        """Verify StrategyBuild table has created_at and updated_at."""
        inspector = inspect(in_memory_db.bind)
        columns = {col["name"]: col for col in inspector.get_columns("strategy_builds")}

        assert "created_at" in columns
        assert "updated_at" in columns

    def test_ac1_candidate_has_timestamp_columns(self, in_memory_db):
        """Verify Candidate table has created_at and updated_at."""
        inspector = inspect(in_memory_db.bind)
        columns = {col["name"]: col for col in inspector.get_columns("candidates")}

        assert "created_at" in columns
        assert "updated_at" in columns

    def test_ac1_deployment_has_timestamp_columns(self, in_memory_db):
        """Verify Deployment table has created_at and updated_at."""
        inspector = inspect(in_memory_db.bind)
        columns = {col["name"]: col for col in inspector.get_columns("deployments")}

        assert "created_at" in columns
        assert "updated_at" in columns

    def test_ac1_run_has_timestamp_columns(self, in_memory_db):
        """Verify Run table has created_at and updated_at."""
        inspector = inspect(in_memory_db.bind)
        columns = {col["name"]: col for col in inspector.get_columns("runs")}

        assert "created_at" in columns
        assert "updated_at" in columns

    def test_ac1_trial_has_timestamp_columns(self, in_memory_db):
        """Verify Trial table has created_at and updated_at."""
        inspector = inspect(in_memory_db.bind)
        columns = {col["name"]: col for col in inspector.get_columns("trials")}

        assert "created_at" in columns
        assert "updated_at" in columns

    def test_ac1_artifact_has_timestamp_columns(self, in_memory_db):
        """Verify Artifact table has created_at and updated_at."""
        inspector = inspect(in_memory_db.bind)
        columns = {col["name"]: col for col in inspector.get_columns("artifacts")}

        assert "created_at" in columns
        assert "updated_at" in columns

    def test_ac1_audit_event_has_timestamp_columns(self, in_memory_db):
        """Verify AuditEvent table has created_at."""
        inspector = inspect(in_memory_db.bind)
        columns = {col["name"]: col for col in inspector.get_columns("audit_events")}

        # Audit events are immutable, so updated_at may not be present
        assert "created_at" in columns

    def test_ac1_feed_has_timestamp_columns(self, in_memory_db):
        """Verify Feed table has created_at and updated_at."""
        inspector = inspect(in_memory_db.bind)
        columns = {col["name"]: col for col in inspector.get_columns("feeds")}

        assert "created_at" in columns
        assert "updated_at" in columns

    def test_ac1_override_has_timestamp_columns(self, in_memory_db):
        """Verify Override table has created_at and updated_at."""
        inspector = inspect(in_memory_db.bind)
        columns = {col["name"]: col for col in inspector.get_columns("overrides")}

        assert "created_at" in columns
        assert "updated_at" in columns

    def test_ac1_approval_request_has_timestamp_columns(self, in_memory_db):
        """Verify ApprovalRequest table has created_at and updated_at."""
        inspector = inspect(in_memory_db.bind)
        columns = {col["name"]: col for col in inspector.get_columns("approval_requests")}

        assert "created_at" in columns
        assert "updated_at" in columns

    def test_ac1_user_has_timestamp_columns(self, in_memory_db):
        """Verify User table has created_at and updated_at."""
        inspector = inspect(in_memory_db.bind)
        columns = {col["name"]: col for col in inspector.get_columns("users")}

        assert "created_at" in columns
        assert "updated_at" in columns

    def test_ac1_timestamps_auto_populate_on_create(self, in_memory_db, sample_ulid):
        """Verify created_at and updated_at auto-populate on row creation."""
        # This test will fail until default timestamp logic is implemented
        user = User(
            id=sample_ulid,
            email="test@example.com",
            hashed_password="hashed",
            role="operator",
        )
        in_memory_db.add(user)
        in_memory_db.commit()
        in_memory_db.refresh(user)

        assert user.created_at is not None
        assert user.updated_at is not None

    def test_ac1_updated_at_changes_on_update(self, in_memory_db, sample_ulid):
        """Verify updated_at changes when a row is updated."""
        # This test will fail until auto-update timestamp logic is implemented
        user = User(
            id=sample_ulid,
            email="test@example.com",
            hashed_password="hashed",
            role="operator",
        )
        in_memory_db.add(user)
        in_memory_db.commit()
        in_memory_db.refresh(user)

        original_updated_at = user.updated_at

        # Simulate time passing and update
        user.email = "updated@example.com"
        in_memory_db.commit()
        in_memory_db.refresh(user)

        assert user.updated_at > original_updated_at
