"""
Unit tests for SqlPnlSnapshotRepository.

Validates:
- Snapshot creation with ULID generation.
- Upsert semantics (update on duplicate deployment + date).
- Retrieval by deployment and date.
- Date range listing with chronological ordering.
- Deletion of all snapshots for a deployment.
- Edge cases: no snapshots, single snapshot, boundary dates.

Uses in-memory SQLite via SQLAlchemy for fast, isolated testing.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.models import Base, Deployment, PnlSnapshot, Strategy, User
from services.api.repositories.sql_pnl_snapshot_repository import (
    SqlPnlSnapshotRepository,
)

# ---------------------------------------------------------------------------
# Test Constants
# ---------------------------------------------------------------------------

_DEPLOY_ID = "01HDEPLOY00000000000000001"
_STRATEGY_ID = "01HSTRATEGY000000000000001"
_USER_ID = "01HUSER0000000000000000001"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session() -> Session:
    """
    Provide a clean in-memory SQLite session for each test.

    Creates all ORM tables, seeds required parent records (User,
    Strategy, Deployment), and yields a session. The session is
    rolled back and closed after the test.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()

    # Seed required parent records
    session.add(
        User(
            id=_USER_ID,
            email="test@example.com",
            hashed_password="$2b$12$fakehash",
            role="admin",
            is_active=True,
        )
    )
    session.add(
        Strategy(
            id=_STRATEGY_ID,
            name="Test Strategy",
            code="pass",
            version="1.0.0",
            created_by=_USER_ID,
            is_active=True,
        )
    )
    session.add(
        Deployment(
            id=_DEPLOY_ID,
            strategy_id=_STRATEGY_ID,
            environment="live",
            execution_mode="live",
            status="completed",
            state="active",
            emergency_posture="cancel_open",
            risk_limits={},
            deployed_by=_USER_ID,
        )
    )
    session.flush()

    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def repo(db_session: Session) -> SqlPnlSnapshotRepository:
    """Provide a SqlPnlSnapshotRepository backed by the test session."""
    return SqlPnlSnapshotRepository(db=db_session)


# ---------------------------------------------------------------------------
# Tests: save
# ---------------------------------------------------------------------------


class TestSave:
    """Tests for SqlPnlSnapshotRepository.save()."""

    def test_save_creates_new_snapshot(self, repo: SqlPnlSnapshotRepository) -> None:
        """Save creates a new record with ULID and all fields."""
        result = repo.save(
            deployment_id=_DEPLOY_ID,
            snapshot_date=date(2026, 4, 12),
            realized_pnl="1250.50",
            unrealized_pnl="340.25",
            commission="52.00",
            fees="3.50",
            positions_count=5,
        )

        assert result["id"] is not None
        assert len(result["id"]) == 26  # ULID length
        assert result["deployment_id"] == _DEPLOY_ID
        assert result["snapshot_date"] == "2026-04-12"
        assert result["realized_pnl"] == "1250.50"
        assert result["unrealized_pnl"] == "340.25"
        assert result["commission"] == "52.00"
        assert result["fees"] == "3.50"
        assert result["positions_count"] == 5
        assert result["created_at"] is not None

    def test_save_defaults_commission_and_fees(
        self,
        repo: SqlPnlSnapshotRepository,
    ) -> None:
        """Commission and fees default to '0' when not specified."""
        result = repo.save(
            deployment_id=_DEPLOY_ID,
            snapshot_date=date(2026, 4, 12),
            realized_pnl="100",
            unrealized_pnl="50",
        )

        assert result["commission"] == "0"
        assert result["fees"] == "0"
        assert result["positions_count"] == 0

    def test_save_upsert_updates_existing(
        self,
        repo: SqlPnlSnapshotRepository,
        db_session: Session,
    ) -> None:
        """Second save for same deployment + date updates, not duplicates."""
        first = repo.save(
            deployment_id=_DEPLOY_ID,
            snapshot_date=date(2026, 4, 12),
            realized_pnl="100",
            unrealized_pnl="50",
            commission="5",
        )

        second = repo.save(
            deployment_id=_DEPLOY_ID,
            snapshot_date=date(2026, 4, 12),
            realized_pnl="200",
            unrealized_pnl="80",
            commission="10",
        )

        # Same ID — upsert updated existing record
        assert second["id"] == first["id"]
        assert second["realized_pnl"] == "200"
        assert second["unrealized_pnl"] == "80"
        assert second["commission"] == "10"

        # Only one record in DB
        count = db_session.query(PnlSnapshot).count()
        assert count == 1


# ---------------------------------------------------------------------------
# Tests: get_by_deployment_and_date
# ---------------------------------------------------------------------------


class TestGetByDeploymentAndDate:
    """Tests for SqlPnlSnapshotRepository.get_by_deployment_and_date()."""

    def test_get_existing_snapshot(self, repo: SqlPnlSnapshotRepository) -> None:
        """Returns snapshot dict when it exists."""
        repo.save(
            deployment_id=_DEPLOY_ID,
            snapshot_date=date(2026, 4, 12),
            realized_pnl="500",
            unrealized_pnl="200",
        )

        result = repo.get_by_deployment_and_date(
            deployment_id=_DEPLOY_ID,
            snapshot_date=date(2026, 4, 12),
        )

        assert result is not None
        assert result["deployment_id"] == _DEPLOY_ID
        assert result["snapshot_date"] == "2026-04-12"

    def test_get_nonexistent_returns_none(self, repo: SqlPnlSnapshotRepository) -> None:
        """Returns None when no snapshot exists for date."""
        result = repo.get_by_deployment_and_date(
            deployment_id=_DEPLOY_ID,
            snapshot_date=date(2026, 4, 15),
        )
        assert result is None


# ---------------------------------------------------------------------------
# Tests: list_by_deployment
# ---------------------------------------------------------------------------


class TestListByDeployment:
    """Tests for SqlPnlSnapshotRepository.list_by_deployment()."""

    def test_list_returns_chronological_order(
        self,
        repo: SqlPnlSnapshotRepository,
    ) -> None:
        """Snapshots returned in ascending date order."""
        for day in [5, 1, 3, 2, 4]:
            repo.save(
                deployment_id=_DEPLOY_ID,
                snapshot_date=date(2026, 4, day),
                realized_pnl=str(day * 100),
                unrealized_pnl=str(day * 50),
            )

        result = repo.list_by_deployment(
            deployment_id=_DEPLOY_ID,
            date_from=date(2026, 4, 1),
            date_to=date(2026, 4, 5),
        )

        assert len(result) == 5
        dates = [r["snapshot_date"] for r in result]
        assert dates == [
            "2026-04-01",
            "2026-04-02",
            "2026-04-03",
            "2026-04-04",
            "2026-04-05",
        ]

    def test_list_filters_by_date_range(
        self,
        repo: SqlPnlSnapshotRepository,
    ) -> None:
        """Only snapshots within date_from..date_to are returned."""
        for day in range(1, 11):
            repo.save(
                deployment_id=_DEPLOY_ID,
                snapshot_date=date(2026, 4, day),
                realized_pnl=str(day * 100),
                unrealized_pnl="0",
            )

        result = repo.list_by_deployment(
            deployment_id=_DEPLOY_ID,
            date_from=date(2026, 4, 3),
            date_to=date(2026, 4, 7),
        )

        assert len(result) == 5
        assert result[0]["snapshot_date"] == "2026-04-03"
        assert result[4]["snapshot_date"] == "2026-04-07"

    def test_list_empty_range_returns_empty(
        self,
        repo: SqlPnlSnapshotRepository,
    ) -> None:
        """No snapshots in range returns empty list."""
        repo.save(
            deployment_id=_DEPLOY_ID,
            snapshot_date=date(2026, 4, 1),
            realized_pnl="100",
            unrealized_pnl="50",
        )

        result = repo.list_by_deployment(
            deployment_id=_DEPLOY_ID,
            date_from=date(2026, 5, 1),
            date_to=date(2026, 5, 30),
        )

        assert result == []


# ---------------------------------------------------------------------------
# Tests: delete_by_deployment
# ---------------------------------------------------------------------------


class TestDeleteByDeployment:
    """Tests for SqlPnlSnapshotRepository.delete_by_deployment()."""

    def test_delete_removes_all_for_deployment(
        self,
        repo: SqlPnlSnapshotRepository,
        db_session: Session,
    ) -> None:
        """All snapshots for the deployment are deleted."""
        for day in range(1, 6):
            repo.save(
                deployment_id=_DEPLOY_ID,
                snapshot_date=date(2026, 4, day),
                realized_pnl=str(day * 100),
                unrealized_pnl="0",
            )

        count = repo.delete_by_deployment(deployment_id=_DEPLOY_ID)

        assert count == 5
        remaining = db_session.query(PnlSnapshot).count()
        assert remaining == 0

    def test_delete_nonexistent_returns_zero(
        self,
        repo: SqlPnlSnapshotRepository,
    ) -> None:
        """Deleting for a deployment with no snapshots returns 0."""
        count = repo.delete_by_deployment(deployment_id=_DEPLOY_ID)
        assert count == 0
