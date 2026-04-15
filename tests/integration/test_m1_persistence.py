"""
Integration tests for M1 repositories: ExecutionEvent, KillSwitchEvent,
ReconciliationReport, and RiskEvent.

Purpose:
    Verify that M1 repositories correctly persist and retrieve data
    through a real database session with SAVEPOINT isolation (LL-S004).

Dependencies:
    - SQLAlchemy Session (via integration_db_session fixture).
    - libs.contracts.models: ORM models.
    - services.api.repositories: SQL repository implementations.

Example:
    pytest tests/integration/test_m1_persistence.py -v
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from libs.contracts.models import (
    Deployment,
    Order,
    Strategy,
    User,
)
from libs.contracts.reconciliation import (
    Discrepancy,
    DiscrepancyType,
    ReconciliationReport,
    ReconciliationTrigger,
)
from libs.contracts.risk import RiskEvent, RiskEventSeverity

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_USER_ID = "01HTESTNG0SR000000000000F1"
_STRATEGY_ID = "01HTESTNG0STRT0000000000F1"
_DEPLOY_ID = "01HTESTNG0DPY00000000000F1"
_ORDER_ID = "01HTESTNG0ORD00000000000F1"


def _seed_dependencies(db: Session) -> None:
    """Insert minimum parent records for M1 integration tests."""
    user = User(
        id=_USER_ID,
        email="m1-integ@fxlab.dev",
        hashed_password="not-a-real-hash",
        role="operator",
    )
    db.add(user)
    db.flush()

    strategy = Strategy(
        id=_STRATEGY_ID,
        name="M1 Integration Strategy",
        code="# m1 integration strategy\npass",
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

    order = Order(
        id=_ORDER_ID,
        client_order_id="m1-integ-order-001",
        deployment_id=_DEPLOY_ID,
        strategy_id=_STRATEGY_ID,
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity="100",
        time_in_force="day",
        status="submitted",
        correlation_id="m1-corr-001",
        execution_mode="paper",
    )
    db.add(order)
    db.flush()


# ---------------------------------------------------------------------------
# Tests: Execution Event Persistence
# ---------------------------------------------------------------------------


class TestExecutionEventPersistenceRoundtrip:
    """Verify execution events survive full save → retrieve cycle."""

    def test_event_persists_and_retrieves_by_order(self, integration_db_session: Session) -> None:
        """Saved execution event is retrievable by order."""
        from services.api.repositories.sql_execution_event_repository import (
            SqlExecutionEventRepository,
        )

        db = integration_db_session
        _seed_dependencies(db)
        repo = SqlExecutionEventRepository(db=db)

        repo.save(
            order_id=_ORDER_ID,
            event_type="submitted",
            timestamp="2026-04-11T10:00:00+00:00",
            details={"broker_order_id": "ALPACA-001"},
            correlation_id="m1-corr-001",
        )
        repo.save(
            order_id=_ORDER_ID,
            event_type="filled",
            timestamp="2026-04-11T10:01:00+00:00",
            details={"fill_price": "150.25"},
            correlation_id="m1-corr-001",
        )

        events = repo.list_by_order(order_id=_ORDER_ID)
        assert len(events) == 2
        assert events[0]["event_type"] == "submitted"
        assert events[1]["event_type"] == "filled"

    def test_event_searchable_by_correlation_id(self, integration_db_session: Session) -> None:
        """Events are findable via correlation ID search."""
        from services.api.repositories.sql_execution_event_repository import (
            SqlExecutionEventRepository,
        )

        db = integration_db_session
        _seed_dependencies(db)
        repo = SqlExecutionEventRepository(db=db)

        repo.save(
            order_id=_ORDER_ID,
            event_type="risk_checked",
            timestamp="2026-04-11T10:00:00+00:00",
            correlation_id="m1-corr-001",
        )

        results = repo.search_by_correlation_id(correlation_id="m1-corr-001")
        assert len(results) == 1
        assert results[0]["event_type"] == "risk_checked"


# ---------------------------------------------------------------------------
# Tests: Kill Switch Event Persistence
# ---------------------------------------------------------------------------


class TestKillSwitchEventPersistenceRoundtrip:
    """Verify kill switch events survive restart (persist and retrieve)."""

    def test_kill_switch_persists_and_lists_active(self, integration_db_session: Session) -> None:
        """Active kill switch event survives save → list_active cycle."""
        from services.api.repositories.sql_kill_switch_event_repository import (
            SqlKillSwitchEventRepository,
        )

        db = integration_db_session
        repo = SqlKillSwitchEventRepository(db=db)

        repo.save(
            scope="global",
            target_id="global",
            activated_by="user:m1-test",
            activated_at="2026-04-11T10:00:00+00:00",
            reason="Integration test halt",
        )

        active = repo.list_active()
        assert len(active) == 1
        assert active[0]["scope"] == "global"
        assert active[0]["deactivated_at"] is None

    def test_kill_switch_deactivation_persists(self, integration_db_session: Session) -> None:
        """Deactivated event is no longer listed as active."""
        from services.api.repositories.sql_kill_switch_event_repository import (
            SqlKillSwitchEventRepository,
        )

        db = integration_db_session
        repo = SqlKillSwitchEventRepository(db=db)

        event = repo.save(
            scope="strategy",
            target_id="01HTESTNG0STRT0000000000F1",
            activated_by="system",
            activated_at="2026-04-11T10:00:00+00:00",
            reason="Auto halt",
        )

        repo.deactivate(
            event_id=event["id"],
            deactivated_at="2026-04-11T10:05:00+00:00",
            mtth_ms=300,
        )

        active = repo.list_active()
        assert len(active) == 0

        # Still visible in list_by_scope (includes deactivated)
        all_events = repo.list_by_scope(scope="strategy")
        assert len(all_events) == 1
        assert all_events[0]["mtth_ms"] == 300


# ---------------------------------------------------------------------------
# Tests: Reconciliation Report Persistence
# ---------------------------------------------------------------------------


class TestReconciliationReportPersistenceRoundtrip:
    """Verify reconciliation reports persist with discrepancy JSON."""

    def test_report_persists_with_discrepancies(self, integration_db_session: Session) -> None:
        """Report with discrepancies survives save → retrieve cycle."""
        from services.api.repositories.sql_reconciliation_repository import (
            SqlReconciliationRepository,
        )

        db = integration_db_session
        _seed_dependencies(db)
        repo = SqlReconciliationRepository(db=db)

        disc = Discrepancy(
            discrepancy_type=DiscrepancyType.STATUS_MISMATCH,
            entity_type="order",
            entity_id="ord-001",
            field="status",
            internal_value="submitted",
            broker_value="filled",
            auto_resolved=True,
            resolution="Updated internal status",
        )

        report = ReconciliationReport(
            report_id="01HTESTNG0RCN00000000000F1",
            deployment_id=_DEPLOY_ID,
            trigger=ReconciliationTrigger.STARTUP,
            discrepancies=[disc],
            resolved_count=1,
            unresolved_count=0,
            status="completed",
        )

        repo.save(report)

        retrieved = repo.get_by_id("01HTESTNG0RCN00000000000F1")
        assert retrieved is not None
        assert len(retrieved.discrepancies) == 1
        assert retrieved.discrepancies[0].entity_id == "ord-001"
        assert retrieved.resolved_count == 1

    def test_reports_queryable_by_deployment(self, integration_db_session: Session) -> None:
        """Multiple reports are listable by deployment."""
        from services.api.repositories.sql_reconciliation_repository import (
            SqlReconciliationRepository,
        )

        db = integration_db_session
        _seed_dependencies(db)
        repo = SqlReconciliationRepository(db=db)

        for i in range(3):
            report = ReconciliationReport(
                report_id=f"01HTESTNG0RCN0000000000{i}F1",
                deployment_id=_DEPLOY_ID,
                trigger=ReconciliationTrigger.SCHEDULED,
                status="completed",
            )
            repo.save(report)

        reports = repo.list_by_deployment(deployment_id=_DEPLOY_ID)
        assert len(reports) == 3


# ---------------------------------------------------------------------------
# Tests: Risk Event Persistence
# ---------------------------------------------------------------------------


class TestRiskEventPersistenceRoundtrip:
    """Verify risk events persist to new risk_events table."""

    def test_risk_event_persists_and_retrieves(self, integration_db_session: Session) -> None:
        """Saved risk event is retrievable by deployment."""
        from services.api.repositories.sql_risk_event_repository import (
            SqlRiskEventRepository,
        )

        db = integration_db_session
        _seed_dependencies(db)
        repo = SqlRiskEventRepository(db=db)

        event = RiskEvent(
            event_id="01HTESTNG0RSK00000000000F1",
            deployment_id=_DEPLOY_ID,
            check_name="daily_loss",
            severity=RiskEventSeverity.CRITICAL,
            passed=False,
            reason="Daily loss $6000 exceeds limit $5000",
            current_value="6000",
            limit_value="5000",
            correlation_id="m1-corr-001",
        )

        repo.save(event)

        events = repo.list_by_deployment(deployment_id=_DEPLOY_ID)
        assert len(events) == 1
        assert events[0].check_name == "daily_loss"
        assert events[0].severity == RiskEventSeverity.CRITICAL

    def test_risk_events_filterable_by_severity(self, integration_db_session: Session) -> None:
        """Severity filter returns only matching events."""
        from services.api.repositories.sql_risk_event_repository import (
            SqlRiskEventRepository,
        )

        db = integration_db_session
        _seed_dependencies(db)
        repo = SqlRiskEventRepository(db=db)

        repo.save(
            RiskEvent(
                event_id="01HTESTNG0RSK00000000000F1",
                deployment_id=_DEPLOY_ID,
                check_name="daily_loss",
                severity=RiskEventSeverity.CRITICAL,
                passed=False,
                reason="Critical",
            )
        )
        repo.save(
            RiskEvent(
                event_id="01HTESTNG0RSK00000000000F2",
                deployment_id=_DEPLOY_ID,
                check_name="position_limit",
                severity=RiskEventSeverity.INFO,
                passed=True,
            )
        )

        critical = repo.list_by_deployment(deployment_id=_DEPLOY_ID, severity="critical")
        assert len(critical) == 1
        assert critical[0].severity == RiskEventSeverity.CRITICAL
