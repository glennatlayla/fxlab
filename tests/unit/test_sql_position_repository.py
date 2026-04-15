"""
Unit tests for SqlPositionRepository.

Tests use an in-memory SQLite database (not mocks) to verify real SQL
behaviour against the PositionRepositoryInterface contract.

Purpose:
    Verify that SqlPositionRepository correctly persists, retrieves, and
    updates position records in a real database, including pessimistic
    locking semantics.

Dependencies:
    - SQLAlchemy: In-memory SQLite engine.
    - libs.contracts.models: ORM models (Position, Deployment, Strategy, User, Base).
    - libs.contracts.errors: NotFoundError, ExternalServiceError.

Example:
    pytest tests/unit/test_sql_position_repository.py -v
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.errors import NotFoundError
from libs.contracts.models import Base, Deployment, Position, Strategy, User

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
    Create minimal User, Strategy, and Deployment records for Position foreign keys.

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


def _seed_position(
    db: Session,
    *,
    position_id: str = "01KNZ3VJ2EZKT3145N0X1SF43B",
    deployment_id: str = "01KNZ3VJ2EZKT3145N0X1SF43A",
    symbol: str = "AAPL",
    quantity: str = "100",
    average_entry_price: str = "150.00",
    market_price: str = "155.00",
    market_value: str = "15500.00",
    unrealized_pnl: str = "500.00",
    realized_pnl: str = "0.00",
    cost_basis: str = "15000.00",
) -> Position:
    """Insert a test position directly into the DB."""
    position = Position(
        id=position_id,
        deployment_id=deployment_id,
        symbol=symbol,
        quantity=quantity,
        average_entry_price=average_entry_price,
        market_price=market_price,
        market_value=market_value,
        unrealized_pnl=unrealized_pnl,
        realized_pnl=realized_pnl,
        cost_basis=cost_basis,
    )
    db.add(position)
    db.flush()
    return position


# ---------------------------------------------------------------------------
# Tests: save()
# ---------------------------------------------------------------------------


class TestSqlPositionRepositorySave:
    """Tests for save()."""

    def test_save_creates_record(self, test_db: Session):
        """Saving a new position creates a record in the database."""
        from services.api.repositories.sql_position_repository import (
            SqlPositionRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        repo = SqlPositionRepository(db=test_db)

        result = repo.save(
            deployment_id=deployment_id,
            symbol="AAPL",
            quantity="100",
            average_entry_price="150.00",
            market_price="155.00",
            market_value="15500.00",
            unrealized_pnl="500.00",
            realized_pnl="0.00",
            cost_basis="15000.00",
        )

        assert result is not None
        assert result["deployment_id"] == deployment_id
        assert result["symbol"] == "AAPL"
        assert result["quantity"] == "100"
        assert result["average_entry_price"] == "150.00"
        assert result["market_price"] == "155.00"
        assert result["unrealized_pnl"] == "500.00"

    def test_save_generates_ulid(self, test_db: Session):
        """Save generates a valid ULID primary key."""
        from services.api.repositories.sql_position_repository import (
            SqlPositionRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        repo = SqlPositionRepository(db=test_db)

        result = repo.save(
            deployment_id=deployment_id,
            symbol="AAPL",
            quantity="100",
            average_entry_price="150.00",
        )

        assert result["id"] is not None
        assert len(result["id"]) == 26  # ULID is 26 chars

    def test_save_applies_default_values(self, test_db: Session):
        """Save applies default values for optional monetary fields."""
        from services.api.repositories.sql_position_repository import (
            SqlPositionRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        repo = SqlPositionRepository(db=test_db)

        result = repo.save(
            deployment_id=deployment_id,
            symbol="AAPL",
            quantity="100",
            average_entry_price="150.00",
            # market_price, market_value, etc. use defaults
        )

        assert result["market_price"] == "0"
        assert result["market_value"] == "0"
        assert result["unrealized_pnl"] == "0"
        assert result["realized_pnl"] == "0"
        assert result["cost_basis"] == "0"


# ---------------------------------------------------------------------------
# Tests: get_by_deployment_and_symbol()
# ---------------------------------------------------------------------------


class TestSqlPositionRepositoryGetByDeploymentAndSymbol:
    """Tests for get_by_deployment_and_symbol()."""

    def test_get_by_deployment_and_symbol_returns_position(self, test_db: Session):
        """Seeded position is retrieved by deployment and symbol."""
        from services.api.repositories.sql_position_repository import (
            SqlPositionRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        _seed_position(test_db, deployment_id=deployment_id, symbol="AAPL")

        repo = SqlPositionRepository(db=test_db)
        result = repo.get_by_deployment_and_symbol(deployment_id=deployment_id, symbol="AAPL")

        assert result is not None
        assert result["deployment_id"] == deployment_id
        assert result["symbol"] == "AAPL"
        assert result["quantity"] == "100"

    def test_get_by_deployment_and_symbol_returns_none_when_not_found(self, test_db: Session):
        """Non-existent position returns None (not raises)."""
        from services.api.repositories.sql_position_repository import (
            SqlPositionRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        repo = SqlPositionRepository(db=test_db)

        result = repo.get_by_deployment_and_symbol(
            deployment_id=deployment_id, symbol="NONEXISTENT"
        )

        assert result is None


# ---------------------------------------------------------------------------
# Tests: list_by_deployment()
# ---------------------------------------------------------------------------


class TestSqlPositionRepositoryListByDeployment:
    """Tests for list_by_deployment()."""

    def test_list_by_deployment_lists_all_positions(self, test_db: Session):
        """All positions for a deployment are returned."""
        from services.api.repositories.sql_position_repository import (
            SqlPositionRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        _seed_position(test_db, deployment_id=deployment_id, symbol="AAPL")
        _seed_position(
            test_db,
            position_id="01KNZ3VJ2EZKT3145N0X1SF43C",
            deployment_id=deployment_id,
            symbol="MSFT",
        )

        repo = SqlPositionRepository(db=test_db)
        result = repo.list_by_deployment(deployment_id=deployment_id)

        assert len(result) == 2
        symbols = {pos["symbol"] for pos in result}
        assert symbols == {"AAPL", "MSFT"}

    def test_list_by_deployment_returns_empty_list_when_no_positions(self, test_db: Session):
        """No positions in deployment returns empty list (not error)."""
        from services.api.repositories.sql_position_repository import (
            SqlPositionRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        repo = SqlPositionRepository(db=test_db)

        result = repo.list_by_deployment(deployment_id=deployment_id)

        assert result == []


# ---------------------------------------------------------------------------
# Tests: update_position()
# ---------------------------------------------------------------------------


class TestSqlPositionRepositoryUpdatePosition:
    """Tests for update_position()."""

    def test_update_position_updates_fields(self, test_db: Session):
        """Update modifies specified fields."""
        from services.api.repositories.sql_position_repository import (
            SqlPositionRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        pos = _seed_position(test_db, deployment_id=deployment_id)

        repo = SqlPositionRepository(db=test_db)
        result = repo.update_position(
            position_id=pos.id,
            market_price="160.00",
            unrealized_pnl="1000.00",
        )

        assert result["market_price"] == "160.00"
        assert result["unrealized_pnl"] == "1000.00"
        # Unchanged fields should retain their values
        assert result["quantity"] == "100"

    def test_update_position_raises_not_found_for_missing_id(self, test_db: Session):
        """Updating non-existent position raises NotFoundError."""
        from services.api.repositories.sql_position_repository import (
            SqlPositionRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        repo = SqlPositionRepository(db=test_db)

        with pytest.raises(NotFoundError):
            repo.update_position(
                position_id="01HNONEXISTENT0000000000000",
                market_price="160.00",
            )

    def test_update_position_updates_only_provided_fields(self, test_db: Session):
        """Only non-None fields are updated; others retain original values."""
        from services.api.repositories.sql_position_repository import (
            SqlPositionRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        pos = _seed_position(
            test_db,
            deployment_id=deployment_id,
            quantity="100",
            market_price="155.00",
            unrealized_pnl="500.00",
        )

        repo = SqlPositionRepository(db=test_db)
        # Only update market_price
        result = repo.update_position(position_id=pos.id, market_price="160.00")

        assert result["market_price"] == "160.00"
        assert result["quantity"] == "100"  # Unchanged
        assert result["unrealized_pnl"] == "500.00"  # Unchanged


# ---------------------------------------------------------------------------
# Tests: get_for_update()
# ---------------------------------------------------------------------------


class TestSqlPositionRepositoryGetForUpdate:
    """Tests for get_for_update()."""

    def test_get_for_update_returns_position_on_sqlite(self, test_db: Session):
        """SQLite returns position without FOR UPDATE (not supported)."""
        from services.api.repositories.sql_position_repository import (
            SqlPositionRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        _seed_position(test_db, deployment_id=deployment_id, symbol="AAPL")

        repo = SqlPositionRepository(db=test_db)
        result = repo.get_for_update(deployment_id=deployment_id, symbol="AAPL")

        assert result is not None
        assert result["deployment_id"] == deployment_id
        assert result["symbol"] == "AAPL"

    def test_get_for_update_returns_none_when_not_found(self, test_db: Session):
        """Non-existent position returns None (not raises)."""
        from services.api.repositories.sql_position_repository import (
            SqlPositionRepository,
        )

        strategy_id, deployment_id = _seed_dependencies(test_db)
        repo = SqlPositionRepository(db=test_db)

        result = repo.get_for_update(deployment_id=deployment_id, symbol="NONEXISTENT")

        assert result is None
