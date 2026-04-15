"""
Unit tests for SqlOrderRepository.

Tests use an in-memory SQLite database (not mocks) to verify real SQL
behaviour against the OrderRepositoryInterface contract.

Purpose:
    Verify that SqlOrderRepository correctly reads and updates order
    records in a real database, handling all CRUD operations and
    filter scenarios.

Dependencies:
    - SQLAlchemy: In-memory SQLite engine.
    - libs.contracts.models: ORM models (Order, Deployment, Strategy, User, Base).
    - libs.contracts.errors: NotFoundError.

Example:
    pytest tests/unit/test_sql_order_repository.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.errors import NotFoundError
from libs.contracts.models import Base, Deployment, Order, Strategy, User

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


def _seed_dependencies(db: Session) -> tuple[str, str]:
    """
    Create minimal User, Strategy, and Deployment records for Order foreign keys.

    Args:
        db: SQLAlchemy Session.

    Returns:
        Tuple of (strategy_id, deployment_id).
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

    db.add_all([user, strategy, deployment])
    db.flush()

    return strategy.id, deployment.id


def _seed_order(
    db: Session,
    *,
    order_id: str = "01KNZ3VJ2EZKT3145N0X1SF43B",
    client_order_id: str = "client-001",
    deployment_id: str = "01KNZ3VJ2EZKT3145N0X1SF43A",
    strategy_id: str = "01KNZ3VJ2EZKT3145N0X1SF439",
    symbol: str = "AAPL",
    side: str = "buy",
    order_type: str = "market",
    quantity: str = "100",
    time_in_force: str = "day",
    status: str = "pending",
    correlation_id: str = "corr-001",
    execution_mode: str = "paper",
    limit_price: str | None = None,
    stop_price: str | None = None,
    broker_order_id: str | None = None,
) -> Order:
    """Insert a test order directly into the DB."""
    order = Order(
        id=order_id,
        client_order_id=client_order_id,
        deployment_id=deployment_id,
        strategy_id=strategy_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        limit_price=limit_price,
        stop_price=stop_price,
        time_in_force=time_in_force,
        status=status,
        broker_order_id=broker_order_id,
        filled_quantity="0",
        correlation_id=correlation_id,
        execution_mode=execution_mode,
    )
    db.add(order)
    db.flush()
    return order


# ---------------------------------------------------------------------------
# Tests: save()
# ---------------------------------------------------------------------------


class TestSqlOrderRepositorySave:
    """Tests for save()."""

    def test_save_creates_record(self, test_db: Session):
        """Saving a new order creates a record in the database."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        repo = SqlOrderRepository(db=test_db)

        result = repo.save(
            client_order_id="client-001",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity="100",
            time_in_force="day",
            status="pending",
            correlation_id="corr-001",
            execution_mode="paper",
        )

        assert result is not None
        assert result["client_order_id"] == "client-001"
        assert result["symbol"] == "AAPL"
        assert result["status"] == "pending"
        assert result["filled_quantity"] == "0"

    def test_save_generates_ulid(self, test_db: Session):
        """Saved order has a generated ULID primary key."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        repo = SqlOrderRepository(db=test_db)

        result = repo.save(
            client_order_id="client-002",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            symbol="MSFT",
            side="sell",
            order_type="limit",
            quantity="50",
            time_in_force="gtc",
            status="submitted",
            correlation_id="corr-002",
            execution_mode="paper",
        )

        assert result["id"] is not None
        assert len(result["id"]) == 26  # ULID is 26 chars

    def test_save_returns_all_fields(self, test_db: Session):
        """Saved order dict contains all expected fields."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        repo = SqlOrderRepository(db=test_db)

        result = repo.save(
            client_order_id="client-003",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            symbol="TSLA",
            side="buy",
            order_type="market",
            quantity="10",
            time_in_force="day",
            status="pending",
            correlation_id="corr-003",
            execution_mode="paper",
        )

        assert "id" in result
        assert "client_order_id" in result
        assert "deployment_id" in result
        assert "strategy_id" in result
        assert "symbol" in result
        assert "side" in result
        assert "order_type" in result
        assert "quantity" in result
        assert "limit_price" in result
        assert "stop_price" in result
        assert "time_in_force" in result
        assert "status" in result
        assert "broker_order_id" in result
        assert "submitted_at" in result
        assert "filled_at" in result
        assert "cancelled_at" in result
        assert "average_fill_price" in result
        assert "filled_quantity" in result
        assert "rejected_reason" in result
        assert "correlation_id" in result
        assert "execution_mode" in result
        assert "created_at" in result
        assert "updated_at" in result

    def test_save_with_optional_fields(self, test_db: Session):
        """Saving with optional fields (limit_price, stop_price) stores them."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        repo = SqlOrderRepository(db=test_db)

        result = repo.save(
            client_order_id="client-004",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            symbol="AAPL",
            side="buy",
            order_type="stop_limit",
            quantity="100",
            time_in_force="day",
            status="pending",
            correlation_id="corr-004",
            execution_mode="paper",
            limit_price="150.00",
            stop_price="145.00",
            broker_order_id="broker-123",
        )

        assert result["limit_price"] == "150.00"
        assert result["stop_price"] == "145.00"
        assert result["broker_order_id"] == "broker-123"


# ---------------------------------------------------------------------------
# Tests: get_by_id()
# ---------------------------------------------------------------------------


class TestSqlOrderRepositoryGetById:
    """Tests for get_by_id()."""

    def test_get_by_id_returns_order(self, test_db: Session):
        """Seeded order is returned with all expected fields."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43B",
            client_order_id="client-001",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
        )

        repo = SqlOrderRepository(db=test_db)
        result = repo.get_by_id("01KNZ3VJ2EZKT3145N0X1SF43B")

        assert result is not None
        assert result["id"] == "01KNZ3VJ2EZKT3145N0X1SF43B"
        assert result["client_order_id"] == "client-001"
        assert result["status"] == "pending"
        assert result["symbol"] == "AAPL"

    def test_get_by_id_raises_not_found(self, test_db: Session):
        """Non-existent ID raises NotFoundError."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        repo = SqlOrderRepository(db=test_db)

        with pytest.raises(NotFoundError) as exc_info:
            repo.get_by_id("01KNZ3VJ2EZKT3145N0XFFFFF00")

        assert "not found" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Tests: get_by_client_order_id()
# ---------------------------------------------------------------------------


class TestSqlOrderRepositoryGetByClientOrderId:
    """Tests for get_by_client_order_id()."""

    def test_get_by_client_order_id_returns_order(self, test_db: Session):
        """Seeded order is returned by client_order_id."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        _seed_order(
            test_db,
            client_order_id="idempotency-key-001",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
        )

        repo = SqlOrderRepository(db=test_db)
        result = repo.get_by_client_order_id("idempotency-key-001")

        assert result is not None
        assert result["client_order_id"] == "idempotency-key-001"

    def test_get_by_client_order_id_returns_none_when_not_found(self, test_db: Session):
        """Non-existent client_order_id returns None (not raises)."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        repo = SqlOrderRepository(db=test_db)
        result = repo.get_by_client_order_id("nonexistent-key")

        assert result is None


# ---------------------------------------------------------------------------
# Tests: get_by_broker_order_id()
# ---------------------------------------------------------------------------


class TestSqlOrderRepositoryGetByBrokerOrderId:
    """Tests for get_by_broker_order_id()."""

    def test_get_by_broker_order_id_returns_order(self, test_db: Session):
        """Seeded order is returned by broker_order_id."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        _seed_order(
            test_db,
            client_order_id="client-005",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            broker_order_id="broker-456",
        )

        repo = SqlOrderRepository(db=test_db)
        result = repo.get_by_broker_order_id("broker-456")

        assert result is not None
        assert result["broker_order_id"] == "broker-456"

    def test_get_by_broker_order_id_returns_none_when_not_found(self, test_db: Session):
        """Non-existent broker_order_id returns None (not raises)."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        repo = SqlOrderRepository(db=test_db)
        result = repo.get_by_broker_order_id("nonexistent-broker-id")

        assert result is None


# ---------------------------------------------------------------------------
# Tests: list_by_deployment()
# ---------------------------------------------------------------------------


class TestSqlOrderRepositoryListByDeployment:
    """Tests for list_by_deployment()."""

    def test_list_by_deployment_lists_all_orders(self, test_db: Session):
        """All orders for a deployment are returned."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)

        # Seed three orders
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43B",
            client_order_id="client-001",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
        )
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43C",
            client_order_id="client-002",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
        )
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43D",
            client_order_id="client-003",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
        )

        repo = SqlOrderRepository(db=test_db)
        result = repo.list_by_deployment(deployment_id=deployment_id)

        assert len(result) == 3
        assert all(o["deployment_id"] == deployment_id for o in result)

    def test_list_by_deployment_filters_by_status(self, test_db: Session):
        """Orders are filtered by status when provided."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)

        # Seed orders with different statuses
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43B",
            client_order_id="client-001",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            status="pending",
        )
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43C",
            client_order_id="client-002",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            status="submitted",
        )
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43D",
            client_order_id="client-003",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            status="filled",
        )

        repo = SqlOrderRepository(db=test_db)
        result = repo.list_by_deployment(deployment_id=deployment_id, status="submitted")

        assert len(result) == 1
        assert result[0]["status"] == "submitted"
        assert result[0]["client_order_id"] == "client-002"

    def test_list_by_deployment_empty_list(self, test_db: Session):
        """Empty list returned when no orders exist for deployment."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)

        repo = SqlOrderRepository(db=test_db)
        result = repo.list_by_deployment(deployment_id=deployment_id)

        assert result == []


# ---------------------------------------------------------------------------
# Tests: list_open_by_deployment()
# ---------------------------------------------------------------------------


class TestSqlOrderRepositoryListOpenByDeployment:
    """Tests for list_open_by_deployment()."""

    def test_list_open_by_deployment_returns_non_terminal(self, test_db: Session):
        """Non-terminal orders (pending, submitted, partial_fill) are returned."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)

        # Seed open orders
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43B",
            client_order_id="client-001",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            status="pending",
        )
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43C",
            client_order_id="client-002",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            status="submitted",
        )
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43D",
            client_order_id="client-003",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            status="partial_fill",
        )

        repo = SqlOrderRepository(db=test_db)
        result = repo.list_open_by_deployment(deployment_id=deployment_id)

        assert len(result) == 3
        statuses = {o["status"] for o in result}
        assert statuses == {"pending", "submitted", "partial_fill"}

    def test_list_open_by_deployment_excludes_terminal(self, test_db: Session):
        """Terminal orders (filled, cancelled, rejected, expired) are excluded."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)

        # Seed open and terminal orders
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43B",
            client_order_id="client-001",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            status="pending",
        )
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43C",
            client_order_id="client-002",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            status="filled",
        )
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43D",
            client_order_id="client-003",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            status="cancelled",
        )
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43E",
            client_order_id="client-004",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            status="rejected",
        )
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43F",
            client_order_id="client-005",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            status="expired",
        )

        repo = SqlOrderRepository(db=test_db)
        result = repo.list_open_by_deployment(deployment_id=deployment_id)

        assert len(result) == 1
        assert result[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# Tests: update_status()
# ---------------------------------------------------------------------------


class TestSqlOrderRepositoryUpdateStatus:
    """Tests for update_status()."""

    def test_update_status_updates_status_field(self, test_db: Session):
        """Status field is updated correctly."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43B",
            client_order_id="client-001",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            status="pending",
        )

        repo = SqlOrderRepository(db=test_db)
        result = repo.update_status(
            order_id="01KNZ3VJ2EZKT3145N0X1SF43B",
            status="submitted",
        )

        assert result["status"] == "submitted"

    def test_update_status_updates_optional_fields(self, test_db: Session):
        """Optional fields are updated when provided."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43B",
            client_order_id="client-001",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            status="pending",
        )

        repo = SqlOrderRepository(db=test_db)
        now = datetime.now(tz=timezone.utc).isoformat()
        result = repo.update_status(
            order_id="01KNZ3VJ2EZKT3145N0X1SF43B",
            status="submitted",
            broker_order_id="broker-789",
            submitted_at=now,
            average_fill_price="150.25",
            filled_quantity="50",
        )

        assert result["status"] == "submitted"
        assert result["broker_order_id"] == "broker-789"
        assert result["submitted_at"] is not None
        assert result["average_fill_price"] == "150.25"
        assert result["filled_quantity"] == "50"

    def test_update_status_raises_not_found(self, test_db: Session):
        """Updating non-existent order raises NotFoundError."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        repo = SqlOrderRepository(db=test_db)

        with pytest.raises(NotFoundError) as exc_info:
            repo.update_status(
                order_id="01KNZ3VJ2EZKT3145N0XFFFFF00",
                status="submitted",
            )

        assert "not found" in str(exc_info.value).lower()


class TestOrderOptimisticLocking:
    """Verify row_version-based optimistic locking on order updates."""

    def test_order_has_row_version_column(self) -> None:
        """Order ORM model must have an integer row_version column."""
        col = Order.__table__.columns["row_version"]
        assert str(col.type) == "INTEGER", f"row_version must be INTEGER, got {col.type}"
        assert not col.nullable, "row_version must be NOT NULL"

    def test_new_order_has_row_version_one(self, test_db: Session) -> None:
        """Newly saved orders start with row_version=1."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        repo = SqlOrderRepository(db=test_db)
        order = repo.save(
            client_order_id="client-rv-001",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity="100",
            time_in_force="day",
            status="pending",
            correlation_id="corr-rv-001",
            execution_mode="live",
        )
        assert order["row_version"] == 1

    def test_update_status_bumps_row_version(self, test_db: Session) -> None:
        """Every update_status call increments row_version by 1."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43V",
            client_order_id="client-rv-002",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            status="pending",
        )
        repo = SqlOrderRepository(db=test_db)

        result = repo.update_status(
            order_id="01KNZ3VJ2EZKT3145N0X1SF43V",
            status="submitted",
        )
        assert result["row_version"] == 2

        result = repo.update_status(
            order_id="01KNZ3VJ2EZKT3145N0X1SF43V",
            status="filled",
        )
        assert result["row_version"] == 3

    def test_update_status_with_expected_version_succeeds(self, test_db: Session) -> None:
        """Providing correct expected_version allows the update to proceed."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43W",
            client_order_id="client-rv-003",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            status="pending",
        )
        repo = SqlOrderRepository(db=test_db)

        # row_version starts at 1 — expect 1, should succeed
        result = repo.update_status(
            order_id="01KNZ3VJ2EZKT3145N0X1SF43W",
            status="submitted",
            expected_version=1,
        )
        assert result["status"] == "submitted"
        assert result["row_version"] == 2

    def test_update_status_with_wrong_expected_version_raises(self, test_db: Session) -> None:
        """Providing wrong expected_version raises OptimisticLockError."""
        from services.api.repositories import OptimisticLockError
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43X",
            client_order_id="client-rv-004",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            status="pending",
        )
        repo = SqlOrderRepository(db=test_db)

        # row_version is 1 — expect 99, should fail
        with pytest.raises(OptimisticLockError):
            repo.update_status(
                order_id="01KNZ3VJ2EZKT3145N0X1SF43X",
                status="submitted",
                expected_version=99,
            )

    def test_concurrent_update_second_writer_detects_conflict(self, test_db: Session) -> None:
        """Simulate two workers reading version 1, first succeeds, second is rejected."""
        from services.api.repositories import OptimisticLockError
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43Y",
            client_order_id="client-rv-005",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            status="pending",
        )
        repo = SqlOrderRepository(db=test_db)

        # Both "workers" read version 1
        read_version = 1

        # Worker A updates first — succeeds, bumps to version 2
        result = repo.update_status(
            order_id="01KNZ3VJ2EZKT3145N0X1SF43Y",
            status="submitted",
            expected_version=read_version,
        )
        assert result["row_version"] == 2

        # Worker B tries to update with stale version 1 — fails
        with pytest.raises(OptimisticLockError):
            repo.update_status(
                order_id="01KNZ3VJ2EZKT3145N0X1SF43Y",
                status="cancelled",
                expected_version=read_version,
            )

    def test_update_without_expected_version_still_bumps(self, test_db: Session) -> None:
        """When expected_version is omitted (backward compat), row_version still increments."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        _seed_order(
            test_db,
            order_id="01KNZ3VJ2EZKT3145N0X1SF43Z",
            client_order_id="client-rv-006",
            deployment_id=deployment_id,
            strategy_id=strategy_id,
            status="pending",
        )
        repo = SqlOrderRepository(db=test_db)

        # No expected_version — should still work and bump version
        result = repo.update_status(
            order_id="01KNZ3VJ2EZKT3145N0X1SF43Z",
            status="filled",
        )
        assert result["row_version"] == 2
