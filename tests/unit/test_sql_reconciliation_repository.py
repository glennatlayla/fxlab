"""
Unit tests for SqlReconciliationRepository.

Purpose:
    Verify the SQL reconciliation repository correctly persists, retrieves,
    and queries reconciliation reports using an in-memory SQLite database.

Dependencies:
    - SQLAlchemy (in-memory SQLite engine).
    - libs.contracts.models: ORM models.
    - services.api.repositories.sql_reconciliation_repository.
    - libs.contracts.reconciliation: ReconciliationReport, Pydantic model.

Example:
    pytest tests/unit/test_sql_reconciliation_repository.py -v
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.models import (
    Base,
    Deployment,
    Strategy,
    User,
)
from libs.contracts.reconciliation import (
    Discrepancy,
    DiscrepancyType,
    ReconciliationReport,
    ReconciliationTrigger,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_USER_ID = "01HTESTNG0SR000000000000D1"
_STRATEGY_ID = "01HTESTNG0STRT0000000000D1"
_DEPLOY_ID = "01HTESTNG0DPY00000000000D1"


@pytest.fixture()
def db_session() -> Session:
    """Create a fresh in-memory SQLite session for each test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _seed_dependencies(db: Session) -> None:
    """Insert minimum parent records needed for reconciliation report FKs."""
    user = User(
        id=_USER_ID,
        email="recon-test@fxlab.dev",
        hashed_password="not-a-real-hash",
        role="operator",
    )
    db.add(user)
    db.flush()

    strategy = Strategy(
        id=_STRATEGY_ID,
        name="Recon Test Strategy",
        code="# recon test strategy\npass",
        version="1.0.0",
        created_by=_USER_ID,
    )
    db.add(strategy)
    db.flush()

    deployment = Deployment(
        id=_DEPLOY_ID,
        strategy_id=_STRATEGY_ID,
        environment="paper",
        status="running",
        state="active",
        execution_mode="paper",
        emergency_posture="flatten_all",
        deployed_by=_USER_ID,
    )
    db.add(deployment)
    db.flush()


def _make_report(
    *,
    report_id: str = "01HTESTNG0RCN00000000000D1",
    deployment_id: str = _DEPLOY_ID,
    trigger: ReconciliationTrigger = ReconciliationTrigger.STARTUP,
    status: str = "completed",
    discrepancies: list[Discrepancy] | None = None,
    resolved_count: int = 0,
    unresolved_count: int = 0,
) -> ReconciliationReport:
    """Helper to create ReconciliationReport Pydantic instances for tests."""
    return ReconciliationReport(
        report_id=report_id,
        deployment_id=deployment_id,
        trigger=trigger,
        discrepancies=discrepancies or [],
        resolved_count=resolved_count,
        unresolved_count=unresolved_count,
        status=status,
        orders_checked=10,
        positions_checked=5,
    )


# ---------------------------------------------------------------------------
# Tests: Save
# ---------------------------------------------------------------------------


class TestSqlReconciliationRepositorySave:
    """Verify save persists reconciliation reports correctly."""

    def test_save_persists_report(self, db_session: Session) -> None:
        """Saved report is retrievable by ID."""
        from services.api.repositories.sql_reconciliation_repository import (
            SqlReconciliationRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlReconciliationRepository(db=db_session)

        report = _make_report()
        repo.save(report)

        retrieved = repo.get_by_id(report.report_id)
        assert retrieved is not None
        assert retrieved.report_id == report.report_id
        assert retrieved.deployment_id == _DEPLOY_ID

    def test_save_persists_discrepancies(self, db_session: Session) -> None:
        """Discrepancies are serialised to JSON and retrieved correctly."""
        from services.api.repositories.sql_reconciliation_repository import (
            SqlReconciliationRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlReconciliationRepository(db=db_session)

        disc = Discrepancy(
            discrepancy_type=DiscrepancyType.STATUS_MISMATCH,
            entity_type="order",
            entity_id="ord-001",
            field="status",
            internal_value="submitted",
            broker_value="filled",
            auto_resolved=True,
            resolution="Updated internal status to filled",
        )
        report = _make_report(
            discrepancies=[disc],
            resolved_count=1,
            unresolved_count=0,
        )
        repo.save(report)

        retrieved = repo.get_by_id(report.report_id)
        assert retrieved is not None
        assert len(retrieved.discrepancies) == 1
        assert retrieved.discrepancies[0].discrepancy_type == DiscrepancyType.STATUS_MISMATCH
        assert retrieved.resolved_count == 1


# ---------------------------------------------------------------------------
# Tests: Get By ID
# ---------------------------------------------------------------------------


class TestSqlReconciliationRepositoryGetById:
    """Verify get_by_id handles found and not-found cases."""

    def test_get_by_id_returns_none_when_not_found(self, db_session: Session) -> None:
        """Non-existent report ID returns None."""
        from services.api.repositories.sql_reconciliation_repository import (
            SqlReconciliationRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlReconciliationRepository(db=db_session)

        result = repo.get_by_id("01HNONEXISTENT0000000000D1")
        assert result is None


# ---------------------------------------------------------------------------
# Tests: List By Deployment
# ---------------------------------------------------------------------------


class TestSqlReconciliationRepositoryListByDeployment:
    """Verify list_by_deployment filters and orders correctly."""

    def test_list_by_deployment_returns_reports_most_recent_first(
        self, db_session: Session
    ) -> None:
        """Multiple reports are returned with most recent first."""
        from services.api.repositories.sql_reconciliation_repository import (
            SqlReconciliationRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlReconciliationRepository(db=db_session)

        report1 = _make_report(report_id="01HTESTNG0RCN00000000000D1")
        report2 = _make_report(
            report_id="01HTESTNG0RCN00000000000D2",
            trigger=ReconciliationTrigger.SCHEDULED,
        )

        repo.save(report1)
        repo.save(report2)

        reports = repo.list_by_deployment(deployment_id=_DEPLOY_ID)
        assert len(reports) == 2

    def test_list_by_deployment_respects_limit(self, db_session: Session) -> None:
        """Limit parameter restricts result count."""
        from services.api.repositories.sql_reconciliation_repository import (
            SqlReconciliationRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlReconciliationRepository(db=db_session)

        for i in range(5):
            report = _make_report(
                report_id=f"01HTESTNG0RCN0000000000{i:02d}D1",
            )
            repo.save(report)

        reports = repo.list_by_deployment(deployment_id=_DEPLOY_ID, limit=3)
        assert len(reports) == 3

    def test_list_by_deployment_returns_empty_for_no_reports(self, db_session: Session) -> None:
        """No reports returns empty list."""
        from services.api.repositories.sql_reconciliation_repository import (
            SqlReconciliationRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlReconciliationRepository(db=db_session)

        reports = repo.list_by_deployment(deployment_id=_DEPLOY_ID)
        assert reports == []
