"""
Unit tests for SqlExecutionEventRepository.

Purpose:
    Verify the SQL execution event repository correctly persists, retrieves,
    and queries execution events using an in-memory SQLite database.

Dependencies:
    - SQLAlchemy (in-memory SQLite engine).
    - libs.contracts.models: ORM models.
    - services.api.repositories.sql_execution_event_repository.

Example:
    pytest tests/unit/test_sql_execution_event_repository.py -v
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

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_USER_ID = "01HTESTNG0SR000000000000B1"
_STRATEGY_ID = "01HTESTNG0STRT0000000000B1"
_DEPLOY_ID = "01HTESTNG0DPY00000000000B1"
_ORDER_ID = "01HTESTNG0ORD00000000000B1"
_ORDER_ID_2 = "01HTESTNG0ORD00000000000B2"


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
    """Insert minimum parent records needed for execution event FKs."""
    user = User(
        id=_USER_ID,
        email="ee-test@fxlab.dev",
        hashed_password="not-a-real-hash",
        role="operator",
    )
    db.add(user)
    db.flush()

    strategy = Strategy(
        id=_STRATEGY_ID,
        name="EE Test Strategy",
        code="# test strategy\npass",
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
        client_order_id="ee-test-order-001",
        deployment_id=_DEPLOY_ID,
        strategy_id=_STRATEGY_ID,
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity="100",
        time_in_force="day",
        status="submitted",
        correlation_id="ee-corr-001",
        execution_mode="paper",
    )
    db.add(order)

    order2 = Order(
        id=_ORDER_ID_2,
        client_order_id="ee-test-order-002",
        deployment_id=_DEPLOY_ID,
        strategy_id=_STRATEGY_ID,
        symbol="MSFT",
        side="sell",
        order_type="limit",
        quantity="50",
        limit_price="400.00",
        time_in_force="gtc",
        status="submitted",
        correlation_id="ee-corr-002",
        execution_mode="paper",
    )
    db.add(order2)
    db.flush()


# ---------------------------------------------------------------------------
# Tests: Save
# ---------------------------------------------------------------------------


class TestSqlExecutionEventRepositorySave:
    """Verify save creates execution event records."""

    def test_save_creates_record(self, db_session: Session) -> None:
        """Saved event is retrievable and has correct fields."""
        from services.api.repositories.sql_execution_event_repository import (
            SqlExecutionEventRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlExecutionEventRepository(db=db_session)

        now_iso = datetime.now(tz=timezone.utc).isoformat()
        event = repo.save(
            order_id=_ORDER_ID,
            event_type="submitted",
            timestamp=now_iso,
            details={"broker_order_id": "ALPACA-12345"},
            correlation_id="ee-corr-001",
        )

        assert event["order_id"] == _ORDER_ID
        assert event["event_type"] == "submitted"
        assert event["correlation_id"] == "ee-corr-001"
        assert event["details"] == {"broker_order_id": "ALPACA-12345"}

    def test_save_generates_ulid(self, db_session: Session) -> None:
        """Generated ID is a 26-character ULID."""
        from services.api.repositories.sql_execution_event_repository import (
            SqlExecutionEventRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlExecutionEventRepository(db=db_session)

        now_iso = datetime.now(tz=timezone.utc).isoformat()
        event = repo.save(
            order_id=_ORDER_ID,
            event_type="filled",
            timestamp=now_iso,
            correlation_id="ee-corr-001",
        )

        assert len(event["id"]) == 26

    def test_save_with_empty_details(self, db_session: Session) -> None:
        """Save with no details defaults to empty dict."""
        from services.api.repositories.sql_execution_event_repository import (
            SqlExecutionEventRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlExecutionEventRepository(db=db_session)

        now_iso = datetime.now(tz=timezone.utc).isoformat()
        event = repo.save(
            order_id=_ORDER_ID,
            event_type="risk_checked",
            timestamp=now_iso,
            correlation_id="ee-corr-001",
        )

        assert event["details"] == {} or event["details"] is None


# ---------------------------------------------------------------------------
# Tests: List By Order
# ---------------------------------------------------------------------------


class TestSqlExecutionEventRepositoryListByOrder:
    """Verify list_by_order returns events chronologically."""

    def test_list_by_order_returns_events_chronologically(self, db_session: Session) -> None:
        """Events are returned in timestamp ascending order."""
        from services.api.repositories.sql_execution_event_repository import (
            SqlExecutionEventRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlExecutionEventRepository(db=db_session)

        repo.save(
            order_id=_ORDER_ID,
            event_type="submitted",
            timestamp="2026-04-11T10:00:00+00:00",
            correlation_id="ee-corr-001",
        )
        repo.save(
            order_id=_ORDER_ID,
            event_type="filled",
            timestamp="2026-04-11T10:01:00+00:00",
            correlation_id="ee-corr-001",
        )

        events = repo.list_by_order(order_id=_ORDER_ID)
        assert len(events) == 2
        assert events[0]["event_type"] == "submitted"
        assert events[1]["event_type"] == "filled"

    def test_list_by_order_returns_empty_for_no_events(self, db_session: Session) -> None:
        """No events returns empty list."""
        from services.api.repositories.sql_execution_event_repository import (
            SqlExecutionEventRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlExecutionEventRepository(db=db_session)

        events = repo.list_by_order(order_id=_ORDER_ID)
        assert events == []


# ---------------------------------------------------------------------------
# Tests: Search By Correlation ID
# ---------------------------------------------------------------------------


class TestSqlExecutionEventRepositorySearchByCorrelationId:
    """Verify correlation ID search spans orders."""

    def test_search_by_correlation_id_returns_matching_events(self, db_session: Session) -> None:
        """Search returns all events matching the correlation ID."""
        from services.api.repositories.sql_execution_event_repository import (
            SqlExecutionEventRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlExecutionEventRepository(db=db_session)

        repo.save(
            order_id=_ORDER_ID,
            event_type="submitted",
            timestamp="2026-04-11T10:00:00+00:00",
            correlation_id="shared-corr-001",
        )
        repo.save(
            order_id=_ORDER_ID_2,
            event_type="submitted",
            timestamp="2026-04-11T10:00:01+00:00",
            correlation_id="shared-corr-001",
        )
        repo.save(
            order_id=_ORDER_ID,
            event_type="cancelled",
            timestamp="2026-04-11T10:05:00+00:00",
            correlation_id="different-corr",
        )

        results = repo.search_by_correlation_id(correlation_id="shared-corr-001")
        assert len(results) == 2

    def test_search_by_correlation_id_returns_empty_for_no_match(self, db_session: Session) -> None:
        """Search for non-existent correlation ID returns empty list."""
        from services.api.repositories.sql_execution_event_repository import (
            SqlExecutionEventRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlExecutionEventRepository(db=db_session)

        results = repo.search_by_correlation_id(correlation_id="nonexistent")
        assert results == []


# ---------------------------------------------------------------------------
# Tests: List By Deployment
# ---------------------------------------------------------------------------


class TestSqlExecutionEventRepositoryListByDeployment:
    """Verify list_by_deployment joins through orders table."""

    def test_list_by_deployment_returns_events_across_orders(self, db_session: Session) -> None:
        """Events from multiple orders in same deployment are all returned."""
        from services.api.repositories.sql_execution_event_repository import (
            SqlExecutionEventRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlExecutionEventRepository(db=db_session)

        repo.save(
            order_id=_ORDER_ID,
            event_type="submitted",
            timestamp="2026-04-11T10:00:00+00:00",
            correlation_id="ee-corr-001",
        )
        repo.save(
            order_id=_ORDER_ID_2,
            event_type="submitted",
            timestamp="2026-04-11T10:00:01+00:00",
            correlation_id="ee-corr-002",
        )

        events = repo.list_by_deployment(deployment_id=_DEPLOY_ID)
        assert len(events) == 2

    def test_list_by_deployment_respects_limit(self, db_session: Session) -> None:
        """Limit parameter restricts result count."""
        from services.api.repositories.sql_execution_event_repository import (
            SqlExecutionEventRepository,
        )

        _seed_dependencies(db_session)
        repo = SqlExecutionEventRepository(db=db_session)

        for i in range(5):
            repo.save(
                order_id=_ORDER_ID,
                event_type="risk_checked",
                timestamp=f"2026-04-11T10:0{i}:00+00:00",
                correlation_id=f"ee-corr-limit-{i}",
            )

        events = repo.list_by_deployment(deployment_id=_DEPLOY_ID, limit=3)
        assert len(events) == 3
