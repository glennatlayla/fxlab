"""
Integration tests for Order, OrderFill, and Position repository persistence.

Purpose:
    Verify that execution-layer repositories correctly persist and retrieve
    data through a real database session, including cross-session survival,
    relationship integrity, and concurrent access patterns.

Dependencies:
    - SQLAlchemy Session (via integration_db_session fixture).
    - libs.contracts.models: ORM models.
    - services.api.repositories: SQL repository implementations.

Example:
    pytest tests/integration/test_order_position_persistence.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from libs.contracts.models import (
    Deployment,
    Strategy,
    User,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Test IDs — deterministic ULIDs for reproducible tests.
_USER_ID = "01HTESTNG0SR000000000000A1"
_STRATEGY_ID = "01HTESTNG0STRT0000000000A1"
_DEPLOY_ID = "01HTESTNG0DPY00000000000A1"


def _seed_dependencies(db: Session) -> None:
    """
    Insert the minimum parent records needed for execution-layer FKs.

    Creates a User, Strategy, and Deployment in the correct FK order.
    Uses flush() to stay within the SAVEPOINT boundary (LL-S004).
    """
    user = User(
        id=_USER_ID,
        email="integ-test@fxlab.dev",
        hashed_password="not-a-real-hash",
        role="operator",
    )
    db.add(user)
    db.flush()

    strategy = Strategy(
        id=_STRATEGY_ID,
        name="Integration Test Strategy",
        code="# integration test strategy stub\npass",
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


# ---------------------------------------------------------------------------
# Tests: Order Repository Roundtrip
# ---------------------------------------------------------------------------


class TestOrderPersistenceRoundtrip:
    """Verify orders survive full save → retrieve → update cycle."""

    def test_order_persists_and_retrieves_by_id(
        self,
        integration_db_session: Session,
    ) -> None:
        """Saved order is retrievable by its generated ID."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        db = integration_db_session
        _seed_dependencies(db)
        repo = SqlOrderRepository(db=db)

        created = repo.save(
            client_order_id="integ-client-001",
            deployment_id=_DEPLOY_ID,
            strategy_id=_STRATEGY_ID,
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity="100",
            time_in_force="day",
            status="pending",
            correlation_id="integ-corr-001",
            execution_mode="paper",
        )

        retrieved = repo.get_by_id(created["id"])
        assert retrieved["id"] == created["id"]
        assert retrieved["client_order_id"] == "integ-client-001"
        assert retrieved["symbol"] == "AAPL"
        assert retrieved["status"] == "pending"

    def test_order_update_status_persists(
        self,
        integration_db_session: Session,
    ) -> None:
        """Status update is visible on subsequent retrieval."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        db = integration_db_session
        _seed_dependencies(db)
        repo = SqlOrderRepository(db=db)

        created = repo.save(
            client_order_id="integ-client-002",
            deployment_id=_DEPLOY_ID,
            strategy_id=_STRATEGY_ID,
            symbol="MSFT",
            side="sell",
            order_type="limit",
            quantity="50",
            time_in_force="gtc",
            status="pending",
            correlation_id="integ-corr-002",
            execution_mode="paper",
            limit_price="400.00",
        )

        now_iso = datetime.now(tz=timezone.utc).isoformat()
        updated = repo.update_status(
            order_id=created["id"],
            status="filled",
            filled_at=now_iso,
            average_fill_price="399.85",
            filled_quantity="50",
        )

        assert updated["status"] == "filled"
        assert updated["average_fill_price"] == "399.85"

        # Re-retrieve to confirm persistence
        refetched = repo.get_by_id(created["id"])
        assert refetched["status"] == "filled"

    def test_idempotent_lookup_by_client_order_id(
        self,
        integration_db_session: Session,
    ) -> None:
        """get_by_client_order_id supports idempotent duplicate detection."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        db = integration_db_session
        _seed_dependencies(db)
        repo = SqlOrderRepository(db=db)

        created = repo.save(
            client_order_id="integ-idem-001",
            deployment_id=_DEPLOY_ID,
            strategy_id=_STRATEGY_ID,
            symbol="TSLA",
            side="buy",
            order_type="market",
            quantity="10",
            time_in_force="day",
            status="submitted",
            correlation_id="integ-corr-003",
            execution_mode="paper",
        )

        found = repo.get_by_client_order_id("integ-idem-001")
        assert found is not None
        assert found["id"] == created["id"]

        not_found = repo.get_by_client_order_id("nonexistent-client-id")
        assert not_found is None

    def test_list_open_excludes_terminal_statuses(
        self,
        integration_db_session: Session,
    ) -> None:
        """list_open_by_deployment only returns non-terminal orders."""
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        db = integration_db_session
        _seed_dependencies(db)
        repo = SqlOrderRepository(db=db)

        # Create one pending and one filled order
        repo.save(
            client_order_id="integ-open-001",
            deployment_id=_DEPLOY_ID,
            strategy_id=_STRATEGY_ID,
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity="10",
            time_in_force="day",
            status="submitted",
            correlation_id="integ-corr-open1",
            execution_mode="paper",
        )
        repo.save(
            client_order_id="integ-open-002",
            deployment_id=_DEPLOY_ID,
            strategy_id=_STRATEGY_ID,
            symbol="AAPL",
            side="sell",
            order_type="market",
            quantity="10",
            time_in_force="day",
            status="filled",
            correlation_id="integ-corr-open2",
            execution_mode="paper",
        )

        open_orders = repo.list_open_by_deployment(deployment_id=_DEPLOY_ID)
        assert len(open_orders) == 1
        assert open_orders[0]["status"] == "submitted"


# ---------------------------------------------------------------------------
# Tests: OrderFill Repository Roundtrip
# ---------------------------------------------------------------------------


class TestOrderFillPersistenceRoundtrip:
    """Verify fills persist with correct parent order relationship."""

    def test_fill_persists_and_lists_by_order(
        self,
        integration_db_session: Session,
    ) -> None:
        """Saved fill is retrievable by parent order ID."""
        from services.api.repositories.sql_order_fill_repository import (
            SqlOrderFillRepository,
        )
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        db = integration_db_session
        _seed_dependencies(db)
        order_repo = SqlOrderRepository(db=db)
        fill_repo = SqlOrderFillRepository(db=db)

        order = order_repo.save(
            client_order_id="integ-fill-order-001",
            deployment_id=_DEPLOY_ID,
            strategy_id=_STRATEGY_ID,
            symbol="GOOG",
            side="buy",
            order_type="market",
            quantity="20",
            time_in_force="day",
            status="submitted",
            correlation_id="integ-corr-fill",
            execution_mode="paper",
        )

        now_iso = datetime.now(tz=timezone.utc).isoformat()
        fill_repo.save(
            order_id=order["id"],
            fill_id="broker-fill-001",
            price="175.50",
            quantity="10",
            commission="0.50",
            filled_at=now_iso,
            correlation_id="integ-corr-fill",
        )
        fill_repo.save(
            order_id=order["id"],
            fill_id="broker-fill-002",
            price="175.60",
            quantity="10",
            commission="0.50",
            filled_at=now_iso,
            correlation_id="integ-corr-fill",
        )

        fills = fill_repo.list_by_order(order_id=order["id"])
        assert len(fills) == 2
        assert fills[0]["price"] == "175.50"
        assert fills[1]["price"] == "175.60"

    def test_fills_list_by_deployment_spans_orders(
        self,
        integration_db_session: Session,
    ) -> None:
        """list_by_deployment returns fills across multiple orders."""
        from services.api.repositories.sql_order_fill_repository import (
            SqlOrderFillRepository,
        )
        from services.api.repositories.sql_order_repository import (
            SqlOrderRepository,
        )

        db = integration_db_session
        _seed_dependencies(db)
        order_repo = SqlOrderRepository(db=db)
        fill_repo = SqlOrderFillRepository(db=db)

        order1 = order_repo.save(
            client_order_id="integ-dep-fill-001",
            deployment_id=_DEPLOY_ID,
            strategy_id=_STRATEGY_ID,
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity="10",
            time_in_force="day",
            status="filled",
            correlation_id="integ-dep-fill-corr1",
            execution_mode="paper",
        )
        order2 = order_repo.save(
            client_order_id="integ-dep-fill-002",
            deployment_id=_DEPLOY_ID,
            strategy_id=_STRATEGY_ID,
            symbol="MSFT",
            side="buy",
            order_type="market",
            quantity="5",
            time_in_force="day",
            status="filled",
            correlation_id="integ-dep-fill-corr2",
            execution_mode="paper",
        )

        now_iso = datetime.now(tz=timezone.utc).isoformat()
        fill_repo.save(
            order_id=order1["id"],
            fill_id="dep-fill-001",
            price="150.00",
            quantity="10",
            commission="1.00",
            filled_at=now_iso,
            correlation_id="integ-dep-fill-corr1",
        )
        fill_repo.save(
            order_id=order2["id"],
            fill_id="dep-fill-002",
            price="400.00",
            quantity="5",
            commission="1.00",
            filled_at=now_iso,
            correlation_id="integ-dep-fill-corr2",
        )

        all_fills = fill_repo.list_by_deployment(deployment_id=_DEPLOY_ID)
        assert len(all_fills) == 2


# ---------------------------------------------------------------------------
# Tests: Position Repository Roundtrip
# ---------------------------------------------------------------------------


class TestPositionPersistenceRoundtrip:
    """Verify positions persist with update and locking semantics."""

    def test_position_save_and_retrieve_by_symbol(
        self,
        integration_db_session: Session,
    ) -> None:
        """Saved position is retrievable by deployment + symbol."""
        from services.api.repositories.sql_position_repository import (
            SqlPositionRepository,
        )

        db = integration_db_session
        _seed_dependencies(db)
        repo = SqlPositionRepository(db=db)

        created = repo.save(
            deployment_id=_DEPLOY_ID,
            symbol="AAPL",
            quantity="100",
            average_entry_price="150.00",
            market_price="155.00",
            market_value="15500.00",
            unrealized_pnl="500.00",
        )

        found = repo.get_by_deployment_and_symbol(
            deployment_id=_DEPLOY_ID,
            symbol="AAPL",
        )
        assert found is not None
        assert found["id"] == created["id"]
        assert found["quantity"] == "100"
        assert found["market_price"] == "155.00"

    def test_position_update_reflects_on_retrieval(
        self,
        integration_db_session: Session,
    ) -> None:
        """Updated position fields persist correctly."""
        from services.api.repositories.sql_position_repository import (
            SqlPositionRepository,
        )

        db = integration_db_session
        _seed_dependencies(db)
        repo = SqlPositionRepository(db=db)

        created = repo.save(
            deployment_id=_DEPLOY_ID,
            symbol="MSFT",
            quantity="50",
            average_entry_price="400.00",
        )

        repo.update_position(
            position_id=created["id"],
            quantity="75",
            market_price="410.00",
            unrealized_pnl="750.00",
        )

        refetched = repo.get_by_deployment_and_symbol(
            deployment_id=_DEPLOY_ID,
            symbol="MSFT",
        )
        assert refetched is not None
        assert refetched["quantity"] == "75"
        assert refetched["market_price"] == "410.00"
        assert refetched["unrealized_pnl"] == "750.00"
        # Fields not updated should retain original values
        assert refetched["average_entry_price"] == "400.00"

    def test_get_for_update_returns_position(
        self,
        integration_db_session: Session,
    ) -> None:
        """get_for_update returns the position for locking (SQLite: no-op lock)."""
        from services.api.repositories.sql_position_repository import (
            SqlPositionRepository,
        )

        db = integration_db_session
        _seed_dependencies(db)
        repo = SqlPositionRepository(db=db)

        repo.save(
            deployment_id=_DEPLOY_ID,
            symbol="TSLA",
            quantity="25",
            average_entry_price="250.00",
        )

        locked = repo.get_for_update(
            deployment_id=_DEPLOY_ID,
            symbol="TSLA",
        )
        assert locked is not None
        assert locked["symbol"] == "TSLA"
        assert locked["quantity"] == "25"

    def test_list_by_deployment_returns_all_positions(
        self,
        integration_db_session: Session,
    ) -> None:
        """Multiple positions for same deployment are all returned."""
        from services.api.repositories.sql_position_repository import (
            SqlPositionRepository,
        )

        db = integration_db_session
        _seed_dependencies(db)
        repo = SqlPositionRepository(db=db)

        repo.save(
            deployment_id=_DEPLOY_ID,
            symbol="AAPL",
            quantity="100",
            average_entry_price="150.00",
        )
        repo.save(
            deployment_id=_DEPLOY_ID,
            symbol="GOOG",
            quantity="20",
            average_entry_price="175.00",
        )

        positions = repo.list_by_deployment(deployment_id=_DEPLOY_ID)
        assert len(positions) == 2
        symbols = {p["symbol"] for p in positions}
        assert symbols == {"AAPL", "GOOG"}
