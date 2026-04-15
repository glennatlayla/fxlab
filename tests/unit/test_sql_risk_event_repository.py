"""
Unit tests for SqlRiskEventRepository.

Purpose:
    Verify the SQL risk event repository correctly persists and queries
    risk events using an in-memory SQLite database.

Dependencies:
    - SQLAlchemy (in-memory SQLite engine).
    - libs.contracts.models: ORM models (including new RiskEvent).
    - services.api.repositories.sql_risk_event_repository.
    - libs.contracts.risk: RiskEvent Pydantic model.

Example:
    pytest tests/unit/test_sql_risk_event_repository.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.models import (
    Base,
    Deployment,
    Order,
    Strategy,
    User,
)
from libs.contracts.risk import RiskEvent, RiskEventSeverity

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_USER_ID = "01HTESTNG0SR000000000000E1"
_STRATEGY_ID = "01HTESTNG0STRT0000000000E1"
_DEPLOY_ID = "01HTESTNG0DPY00000000000E1"
_ORDER_ID = "01HTESTNG0ORD00000000000E1"


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
    """Insert minimum parent records needed for risk event FKs."""
    user = User(
        id=_USER_ID,
        email="risk-test@fxlab.dev",
        hashed_password="not-a-real-hash",
        role="operator",
    )
    db.add(user)
    db.flush()

    strategy = Strategy(
        id=_STRATEGY_ID,
        name="Risk Test Strategy",
        code="# risk test strategy\npass",
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
        client_order_id="risk-test-order-001",
        deployment_id=_DEPLOY_ID,
        strategy_id=_STRATEGY_ID,
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity="100",
        time_in_force="day",
        status="submitted",
        correlation_id="risk-corr-001",
        execution_mode="paper",
    )
    db.add(order)
    db.flush()


def _make_risk_event(
    *,
    event_id: str = "01HTESTNG0RSK00000000000E1",
    deployment_id: str = _DEPLOY_ID,
    check_name: str = "daily_loss",
    severity: RiskEventSeverity = RiskEventSeverity.CRITICAL,
    passed: bool = False,
    reason: str = "Daily loss $6000 exceeds limit $5000",
    order_client_id: str | None = "risk-test-order-001",
    symbol: str | None = "AAPL",
    correlation_id: str | None = "risk-corr-001",
) -> RiskEvent:
    """Helper to create RiskEvent Pydantic instances for tests."""
    return RiskEvent(
        event_id=event_id,
        deployment_id=deployment_id,
        check_name=check_name,
        severity=severity,
        passed=passed,
        reason=reason,
        current_value="6000",
        limit_value="5000",
        order_client_id=order_client_id,
        symbol=symbol,
        correlation_id=correlation_id,
    )


# ---------------------------------------------------------------------------
# Tests: Save
# ---------------------------------------------------------------------------


class TestSqlRiskEventRepositorySave:
    """Verify save persists risk events correctly."""

    def test_save_persists_event(self, db_session: Session) -> None:
        """Saved event is queryable from the database."""
        from services.api.repositories.sql_risk_event_repository import (
            SqlRiskEventRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlRiskEventRepository(db=db_session)

        event = _make_risk_event()
        repo.save(event)

        events = repo.list_by_deployment(deployment_id=_DEPLOY_ID)
        assert len(events) == 1
        assert events[0].check_name == "daily_loss"
        assert events[0].severity == RiskEventSeverity.CRITICAL
        assert events[0].passed is False

    def test_save_multiple_events(self, db_session: Session) -> None:
        """Multiple events for same deployment are all persisted."""
        from services.api.repositories.sql_risk_event_repository import (
            SqlRiskEventRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlRiskEventRepository(db=db_session)

        event1 = _make_risk_event(event_id="01HTESTNG0RSK00000000000E1")
        event2 = _make_risk_event(
            event_id="01HTESTNG0RSK00000000000E2",
            check_name="position_limit",
            severity=RiskEventSeverity.WARNING,
            passed=True,
            reason=None,
        )

        repo.save(event1)
        repo.save(event2)

        events = repo.list_by_deployment(deployment_id=_DEPLOY_ID)
        assert len(events) == 2


# ---------------------------------------------------------------------------
# Tests: List By Deployment
# ---------------------------------------------------------------------------


class TestSqlRiskEventRepositoryListByDeployment:
    """Verify list_by_deployment filters, orders, and limits correctly."""

    def test_list_by_deployment_filters_by_severity(self, db_session: Session) -> None:
        """Severity filter returns only matching events."""
        from services.api.repositories.sql_risk_event_repository import (
            SqlRiskEventRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlRiskEventRepository(db=db_session)

        repo.save(
            _make_risk_event(
                event_id="01HTESTNG0RSK00000000000E1",
                severity=RiskEventSeverity.CRITICAL,
            )
        )
        repo.save(
            _make_risk_event(
                event_id="01HTESTNG0RSK00000000000E2",
                severity=RiskEventSeverity.INFO,
                passed=True,
                reason=None,
            )
        )
        repo.save(
            _make_risk_event(
                event_id="01HTESTNG0RSK00000000000E3",
                severity=RiskEventSeverity.CRITICAL,
            )
        )

        critical_events = repo.list_by_deployment(deployment_id=_DEPLOY_ID, severity="critical")
        assert len(critical_events) == 2
        assert all(e.severity == RiskEventSeverity.CRITICAL for e in critical_events)

    def test_list_by_deployment_respects_limit(self, db_session: Session) -> None:
        """Limit parameter restricts result count."""
        from services.api.repositories.sql_risk_event_repository import (
            SqlRiskEventRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlRiskEventRepository(db=db_session)

        for i in range(5):
            repo.save(
                _make_risk_event(
                    event_id=f"01HTESTNG0RSK0000000000{i:02d}E1",
                )
            )

        events = repo.list_by_deployment(deployment_id=_DEPLOY_ID, limit=3)
        assert len(events) == 3

    def test_list_by_deployment_returns_empty_for_no_events(self, db_session: Session) -> None:
        """No events returns empty list."""
        from services.api.repositories.sql_risk_event_repository import (
            SqlRiskEventRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlRiskEventRepository(db=db_session)

        events = repo.list_by_deployment(deployment_id=_DEPLOY_ID)
        assert events == []

    def test_list_by_deployment_returns_most_recent_first(self, db_session: Session) -> None:
        """Events are returned in reverse chronological order."""
        from services.api.repositories.sql_risk_event_repository import (
            SqlRiskEventRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlRiskEventRepository(db=db_session)

        event1 = RiskEvent(
            event_id="01HTESTNG0RSK00000000000E1",
            deployment_id=_DEPLOY_ID,
            check_name="check_a",
            severity=RiskEventSeverity.INFO,
            passed=True,
            created_at=datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc),
        )
        event2 = RiskEvent(
            event_id="01HTESTNG0RSK00000000000E2",
            deployment_id=_DEPLOY_ID,
            check_name="check_b",
            severity=RiskEventSeverity.CRITICAL,
            passed=False,
            reason="Limit breached",
            created_at=datetime(2026, 4, 11, 10, 5, 0, tzinfo=timezone.utc),
        )

        repo.save(event1)
        repo.save(event2)

        events = repo.list_by_deployment(deployment_id=_DEPLOY_ID)
        assert events[0].check_name == "check_b"
        assert events[1].check_name == "check_a"
