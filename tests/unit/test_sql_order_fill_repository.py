"""
Unit tests for SqlOrderFillRepository.

Tests use an in-memory SQLite database (not mocks) to verify real SQL
behaviour against the OrderFillRepositoryInterface contract.

Purpose:
    Verify that SqlOrderFillRepository correctly persists and retrieves
    individual fill events in a real database, handling all query scenarios.

Dependencies:
    - SQLAlchemy: In-memory SQLite engine.
    - libs.contracts.models: ORM models (OrderFill, Order, Deployment, Strategy, User, Base).
    - libs.contracts.errors: NotFoundError.

Example:
    pytest tests/unit/test_sql_order_fill_repository.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.models import Base, Deployment, Order, OrderFill, Strategy, User

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


def _seed_dependencies(db: Session) -> tuple[str, str, str]:
    """
    Create minimal User, Strategy, and Deployment records for Order foreign keys.

    Also returns an order_id that can be used for OrderFill records.

    Args:
        db: SQLAlchemy Session.

    Returns:
        Tuple of (strategy_id, deployment_id, order_id).
    """
    # User
    user = User(
        id="01KNZ3VJ2EZKT3145N0X1SF438",
        email="test@example.com",
        hashed_password="hashed",
        role="operator",
        is_active=True,
    )

    # Strategy
    strategy = Strategy(
        id="01KNZ3VJ2EZKT3145N0X1SF439",
        name="Test Strategy",
        code="# test code",
        version="1.0.0",
        created_by=user.id,
        is_active=True,
    )

    # Deployment
    deployment = Deployment(
        id="01KNZ3VJ2EZKT3145N0X1SF43A",
        strategy_id=strategy.id,
        environment="paper",
        status="pending",
        state="created",
        execution_mode="paper",
        emergency_posture="flatten_all",
        risk_limits={},
        custom_posture_config=None,
        deployed_by=user.id,
    )

    # Order (parent for fills)
    order = Order(
        id="01KNZ3VJ2EZKT3145N0X1SF43B",
        client_order_id="client-001",
        deployment_id=deployment.id,
        strategy_id=strategy.id,
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity="100",
        time_in_force="day",
        status="pending",
        filled_quantity="0",
        correlation_id="corr-001",
        execution_mode="paper",
    )

    db.add_all([user, strategy, deployment, order])
    db.flush()

    return strategy.id, deployment.id, order.id


def _seed_order_fill(
    db: Session,
    *,
    fill_id: str = "01KNZ3VJ2EZKT3145N0X1SF43C",
    order_id: str = "01KNZ3VJ2EZKT3145N0X1SF43B",
    fill_id_broker: str = "fill-001",
    price: str = "150.25",
    quantity: str = "50",
    commission: str = "1.00",
    filled_at: datetime | None = None,
    broker_execution_id: str | None = None,
    correlation_id: str = "corr-001",
) -> OrderFill:
    """Insert a test order fill directly into the DB."""
    if filled_at is None:
        filled_at = datetime(2026, 4, 11, 14, 30, 0, tzinfo=timezone.utc)

    fill = OrderFill(
        id=fill_id,
        order_id=order_id,
        fill_id=fill_id_broker,
        price=price,
        quantity=quantity,
        commission=commission,
        filled_at=filled_at,
        broker_execution_id=broker_execution_id,
        correlation_id=correlation_id,
    )
    db.add(fill)
    db.flush()
    return fill


# ---------------------------------------------------------------------------
# Tests: save()
# ---------------------------------------------------------------------------


class TestSqlOrderFillRepositorySave:
    """Tests for save()."""

    def test_save_creates_record(self, test_db: Session):
        """Saving a new fill creates a record in the database."""
        from services.api.repositories.sql_order_fill_repository import (
            SqlOrderFillRepository,
        )

        strategy_id, deployment_id, order_id = _seed_dependencies(test_db)
        repo = SqlOrderFillRepository(db=test_db)

        result = repo.save(
            order_id=order_id,
            fill_id="fill-001",
            price="150.25",
            quantity="50",
            commission="1.00",
            filled_at="2026-04-11T14:30:00+00:00",
            correlation_id="corr-abc",
        )

        assert result is not None
        assert result["order_id"] == order_id
        assert result["fill_id"] == "fill-001"
        assert result["price"] == "150.25"
        assert result["quantity"] == "50"
        assert result["commission"] == "1.00"
        assert result["correlation_id"] == "corr-abc"

    def test_save_generates_ulid(self, test_db: Session):
        """Save generates a valid ULID primary key."""
        from services.api.repositories.sql_order_fill_repository import (
            SqlOrderFillRepository,
        )

        strategy_id, deployment_id, order_id = _seed_dependencies(test_db)
        repo = SqlOrderFillRepository(db=test_db)

        result = repo.save(
            order_id=order_id,
            fill_id="fill-001",
            price="150.25",
            quantity="50",
            commission="1.00",
            filled_at="2026-04-11T14:30:00+00:00",
            correlation_id="corr-abc",
        )

        assert result["id"] is not None
        assert len(result["id"]) == 26  # ULID is 26 chars

    def test_save_parses_filled_at_iso_string(self, test_db: Session):
        """Save parses filled_at ISO string to datetime."""
        from services.api.repositories.sql_order_fill_repository import (
            SqlOrderFillRepository,
        )

        strategy_id, deployment_id, order_id = _seed_dependencies(test_db)
        repo = SqlOrderFillRepository(db=test_db)

        result = repo.save(
            order_id=order_id,
            fill_id="fill-001",
            price="150.25",
            quantity="50",
            commission="1.00",
            filled_at="2026-04-11T14:30:00+00:00",
            correlation_id="corr-abc",
        )

        assert result["filled_at"] is not None
        # filled_at should be ISO format string
        assert "2026-04-11" in result["filled_at"]


# ---------------------------------------------------------------------------
# Tests: list_by_order()
# ---------------------------------------------------------------------------


class TestSqlOrderFillRepositoryListByOrder:
    """Tests for list_by_order()."""

    def test_list_by_order_returns_fills_chronologically(self, test_db: Session):
        """Fills are returned ordered by filled_at ascending (earliest first)."""
        from services.api.repositories.sql_order_fill_repository import (
            SqlOrderFillRepository,
        )

        strategy_id, deployment_id, order_id = _seed_dependencies(test_db)

        # Seed two fills with different timestamps
        _seed_order_fill(
            test_db,
            fill_id="01KNZ3VJ2EZKT3145N0X1SF43C",
            order_id=order_id,
            filled_at=datetime(2026, 4, 11, 14, 30, 0, tzinfo=timezone.utc),
        )
        _seed_order_fill(
            test_db,
            fill_id="01KNZ3VJ2EZKT3145N0X1SF43D",
            order_id=order_id,
            filled_at=datetime(2026, 4, 11, 14, 35, 0, tzinfo=timezone.utc),
        )

        repo = SqlOrderFillRepository(db=test_db)
        result = repo.list_by_order(order_id=order_id)

        assert len(result) == 2
        # First fill is the earlier one (14:30)
        assert result[0]["id"] == "01KNZ3VJ2EZKT3145N0X1SF43C"
        # Second fill is the later one (14:35)
        assert result[1]["id"] == "01KNZ3VJ2EZKT3145N0X1SF43D"

    def test_list_by_order_returns_empty_for_no_fills(self, test_db: Session):
        """No fills returns empty list (not error)."""
        from services.api.repositories.sql_order_fill_repository import (
            SqlOrderFillRepository,
        )

        strategy_id, deployment_id, order_id = _seed_dependencies(test_db)
        repo = SqlOrderFillRepository(db=test_db)

        result = repo.list_by_order(order_id=order_id)

        assert result == []


# ---------------------------------------------------------------------------
# Tests: list_by_deployment()
# ---------------------------------------------------------------------------


class TestSqlOrderFillRepositoryListByDeployment:
    """Tests for list_by_deployment()."""

    def test_list_by_deployment_returns_fills_across_orders(self, test_db: Session):
        """Fills from multiple orders in the same deployment are all returned."""
        from services.api.repositories.sql_order_fill_repository import (
            SqlOrderFillRepository,
        )

        strategy_id, deployment_id, order_id_1 = _seed_dependencies(test_db)

        # Create second order in same deployment
        order_2 = Order(
            id="01KNZ3VJ2EZKT3145N0X1SF43E",
            client_order_id="client-002",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            symbol="MSFT",
            side="sell",
            order_type="market",
            quantity="50",
            time_in_force="day",
            status="pending",
            filled_quantity="0",
            correlation_id="corr-002",
            execution_mode="paper",
        )
        test_db.add(order_2)
        test_db.flush()

        # Seed fills for both orders
        _seed_order_fill(
            test_db,
            fill_id="01KNZ3VJ2EZKT3145N0X1SF43C",
            order_id=order_id_1,
            filled_at=datetime(2026, 4, 11, 14, 30, 0, tzinfo=timezone.utc),
        )
        _seed_order_fill(
            test_db,
            fill_id="01KNZ3VJ2EZKT3145N0X1SF43D",
            order_id=order_2.id,
            filled_at=datetime(2026, 4, 11, 14, 35, 0, tzinfo=timezone.utc),
        )

        repo = SqlOrderFillRepository(db=test_db)
        result = repo.list_by_deployment(deployment_id=deployment_id)

        assert len(result) == 2
        # Results should be ordered by filled_at descending (most recent first)
        assert result[0]["id"] == "01KNZ3VJ2EZKT3145N0X1SF43D"  # 14:35
        assert result[1]["id"] == "01KNZ3VJ2EZKT3145N0X1SF43C"  # 14:30

    def test_list_by_deployment_returns_empty_for_no_fills(self, test_db: Session):
        """No fills in deployment returns empty list (not error)."""
        from services.api.repositories.sql_order_fill_repository import (
            SqlOrderFillRepository,
        )

        strategy_id, deployment_id, order_id = _seed_dependencies(test_db)
        repo = SqlOrderFillRepository(db=test_db)

        result = repo.list_by_deployment(deployment_id=deployment_id)

        assert result == []
