"""
Unit tests for Phase 4 execution ORM models and migration.

Covers:
- Table creation via Base.metadata.create_all (verifies DDL is valid)
- All 6 new tables exist: orders, order_fills, positions, execution_events,
  kill_switch_events, reconciliation_reports
- Primary key columns are present
- Check constraints enforce enum values (side, order_type, time_in_force,
  status, execution_mode, kill switch scope, reconciliation status/trigger)
- Foreign key relationships work (Order → Deployment, OrderFill → Order, etc.)
- Unique constraint on client_order_id
- Timestamp mixin columns present where applicable
- Nullable/not-nullable constraints enforced
- Migration file has matching revision chain (0009 depends on 0008)

Per M1 spec: "Unit tests for model validation (ULID, enum constraints, FK integrity)"
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.models import (
    Base,
    Deployment,
    ExecutionEvent,
    KillSwitchEvent,
    Order,
    OrderFill,
    Position,
    ReconciliationReport,
    Strategy,
    User,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc)

# Valid 26-char ULID strings (Crockford Base32: no I, L, O, U)
USER_ID = "01HTESTSRA0000000000000001"
STRATEGY_ID = "01HTESTSTRT000000000000001"
DEPLOYMENT_ID = "01HTESTDEP0000000000000001"
ORDER_ID = "01HTESTERD0000000000000001"


@pytest.fixture()
def db_session():
    """In-memory SQLite session with all tables created."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        # Seed prerequisite rows (User, Strategy, Deployment)
        session.add(
            User(
                id=USER_ID,
                email="test@fxlab.dev",
                hashed_password="$2b$12$testhashed00000000000000000000000000000000000000",
                role="admin",
                is_active=True,
            )
        )
        session.add(
            Strategy(
                id=STRATEGY_ID,
                name="TestStrategy",
                code="def entry(): pass",
                created_by=USER_ID,
            )
        )
        session.add(
            Deployment(
                id=DEPLOYMENT_ID,
                strategy_id=STRATEGY_ID,
                environment="paper",
                status="running",
                deployed_by=USER_ID,
            )
        )
        session.commit()
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Table existence tests
# ---------------------------------------------------------------------------


class TestExecutionTablesExist:
    """Verify all Phase 4 execution tables are created by DDL."""

    def test_orders_table_exists(self, db_session: Session) -> None:
        inspector = inspect(db_session.bind)
        assert "orders" in inspector.get_table_names()

    def test_order_fills_table_exists(self, db_session: Session) -> None:
        inspector = inspect(db_session.bind)
        assert "order_fills" in inspector.get_table_names()

    def test_positions_table_exists(self, db_session: Session) -> None:
        inspector = inspect(db_session.bind)
        assert "positions" in inspector.get_table_names()

    def test_execution_events_table_exists(self, db_session: Session) -> None:
        inspector = inspect(db_session.bind)
        assert "execution_events" in inspector.get_table_names()

    def test_kill_switch_events_table_exists(self, db_session: Session) -> None:
        inspector = inspect(db_session.bind)
        assert "kill_switch_events" in inspector.get_table_names()

    def test_reconciliation_reports_table_exists(self, db_session: Session) -> None:
        inspector = inspect(db_session.bind)
        assert "reconciliation_reports" in inspector.get_table_names()


# ---------------------------------------------------------------------------
# Order model tests
# ---------------------------------------------------------------------------


class TestOrderModel:
    """Tests for the Order ORM model."""

    def test_insert_valid_order(self, db_session: Session) -> None:
        order = Order(
            id=ORDER_ID,
            client_order_id="ord-test-001",
            deployment_id=DEPLOYMENT_ID,
            strategy_id=STRATEGY_ID,
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity="100",
            time_in_force="day",
            status="submitted",
            correlation_id="corr-test-001",
            execution_mode="paper",
            submitted_at=NOW,
        )
        db_session.add(order)
        db_session.commit()

        result = db_session.query(Order).filter_by(id=ORDER_ID).one()
        assert result.client_order_id == "ord-test-001"
        assert result.symbol == "AAPL"
        assert result.side == "buy"
        assert result.execution_mode == "paper"

    def test_client_order_id_unique_constraint(self, db_session: Session) -> None:
        order1 = Order(
            id=ORDER_ID,
            client_order_id="ord-dup",
            deployment_id=DEPLOYMENT_ID,
            strategy_id=STRATEGY_ID,
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity="100",
            correlation_id="corr-001",
            execution_mode="paper",
        )
        order2 = Order(
            id="01HTESTERD0000000000000002",
            client_order_id="ord-dup",  # duplicate
            deployment_id=DEPLOYMENT_ID,
            strategy_id=STRATEGY_ID,
            symbol="MSFT",
            side="sell",
            order_type="limit",
            quantity="50",
            limit_price="300.00",
            correlation_id="corr-002",
            execution_mode="paper",
        )
        db_session.add(order1)
        db_session.commit()
        db_session.add(order2)

        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_order_has_timestamp_columns(self, db_session: Session) -> None:
        inspector = inspect(db_session.bind)
        columns = {col["name"] for col in inspector.get_columns("orders")}
        assert "created_at" in columns
        assert "updated_at" in columns

    def test_order_nullable_fields(self, db_session: Session) -> None:
        """Optional fields (limit_price, stop_price, broker_order_id, etc.) accept None."""
        order = Order(
            id=ORDER_ID,
            client_order_id="ord-nullable",
            deployment_id=DEPLOYMENT_ID,
            strategy_id=STRATEGY_ID,
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity="100",
            correlation_id="corr-nullable",
            execution_mode="shadow",
        )
        db_session.add(order)
        db_session.commit()

        result = db_session.query(Order).filter_by(id=ORDER_ID).one()
        assert result.limit_price is None
        assert result.stop_price is None
        assert result.broker_order_id is None
        assert result.rejected_reason is None

    def test_order_fills_relationship(self, db_session: Session) -> None:
        order = Order(
            id=ORDER_ID,
            client_order_id="ord-rel",
            deployment_id=DEPLOYMENT_ID,
            strategy_id=STRATEGY_ID,
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity="100",
            correlation_id="corr-rel",
            execution_mode="paper",
        )
        fill = OrderFill(
            id="01HTESTF000000000000000001",
            order_id=ORDER_ID,
            fill_id="fill-001",
            price="175.50",
            quantity="100",
            filled_at=NOW,
            correlation_id="corr-rel",
        )
        db_session.add(order)
        db_session.add(fill)
        db_session.commit()

        result = db_session.query(Order).filter_by(id=ORDER_ID).one()
        assert len(result.fills) == 1
        assert result.fills[0].price == "175.50"

    def test_order_execution_events_relationship(self, db_session: Session) -> None:
        order = Order(
            id=ORDER_ID,
            client_order_id="ord-evt",
            deployment_id=DEPLOYMENT_ID,
            strategy_id=STRATEGY_ID,
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity="100",
            correlation_id="corr-evt",
            execution_mode="paper",
        )
        event = ExecutionEvent(
            id="01HTESTEVT0000000000000001",
            order_id=ORDER_ID,
            event_type="submitted",
            timestamp=NOW,
            details={"broker_order_id": "MOCK-001"},
            correlation_id="corr-evt",
        )
        db_session.add(order)
        db_session.add(event)
        db_session.commit()

        result = db_session.query(Order).filter_by(id=ORDER_ID).one()
        assert len(result.execution_events) == 1
        assert result.execution_events[0].event_type == "submitted"


# ---------------------------------------------------------------------------
# OrderFill model tests
# ---------------------------------------------------------------------------


class TestOrderFillModel:
    """Tests for the OrderFill ORM model."""

    def test_insert_valid_fill(self, db_session: Session) -> None:
        # Pre-requisite order
        order = Order(
            id=ORDER_ID,
            client_order_id="ord-fill-test",
            deployment_id=DEPLOYMENT_ID,
            strategy_id=STRATEGY_ID,
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity="100",
            correlation_id="corr-fill",
            execution_mode="paper",
        )
        fill = OrderFill(
            id="01HTESTF000000000000000001",
            order_id=ORDER_ID,
            fill_id="fill-001",
            price="175.50",
            quantity="50",
            commission="1.00",
            filled_at=NOW,
            broker_execution_id="exec-001",
            correlation_id="corr-fill",
        )
        db_session.add(order)
        db_session.add(fill)
        db_session.commit()

        result = db_session.query(OrderFill).filter_by(id="01HTESTF000000000000000001").one()
        assert result.price == "175.50"
        assert result.quantity == "50"
        assert result.commission == "1.00"

    def test_fill_cascade_delete_with_order(self, db_session: Session) -> None:
        order = Order(
            id=ORDER_ID,
            client_order_id="ord-cascade",
            deployment_id=DEPLOYMENT_ID,
            strategy_id=STRATEGY_ID,
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity="100",
            correlation_id="corr-cascade",
            execution_mode="paper",
        )
        fill = OrderFill(
            id="01HTESTF000000000000000001",
            order_id=ORDER_ID,
            fill_id="fill-cascade",
            price="175.50",
            quantity="100",
            filled_at=NOW,
            correlation_id="corr-cascade",
        )
        db_session.add(order)
        db_session.add(fill)
        db_session.commit()

        # Delete order → fill should cascade
        db_session.delete(order)
        db_session.commit()

        assert db_session.query(OrderFill).count() == 0


# ---------------------------------------------------------------------------
# Position model tests
# ---------------------------------------------------------------------------


class TestPositionModel:
    """Tests for the Position ORM model."""

    def test_insert_valid_position(self, db_session: Session) -> None:
        pos = Position(
            id="01HTESTPS00000000000000001",
            deployment_id=DEPLOYMENT_ID,
            symbol="AAPL",
            quantity="100",
            average_entry_price="175.00",
            market_price="180.00",
            market_value="18000.00",
            unrealized_pnl="500.00",
            realized_pnl="0",
            cost_basis="17500.00",
        )
        db_session.add(pos)
        db_session.commit()

        result = db_session.query(Position).filter_by(id="01HTESTPS00000000000000001").one()
        assert result.symbol == "AAPL"
        assert result.quantity == "100"

    def test_position_defaults(self, db_session: Session) -> None:
        pos = Position(
            id="01HTESTPS00000000000000002",
            deployment_id=DEPLOYMENT_ID,
            symbol="MSFT",
        )
        db_session.add(pos)
        db_session.commit()

        result = db_session.query(Position).filter_by(id="01HTESTPS00000000000000002").one()
        assert result.quantity == "0"
        assert result.average_entry_price == "0"


# ---------------------------------------------------------------------------
# ExecutionEvent model tests
# ---------------------------------------------------------------------------


class TestExecutionEventModel:
    """Tests for the ExecutionEvent ORM model."""

    def test_insert_valid_event(self, db_session: Session) -> None:
        order = Order(
            id=ORDER_ID,
            client_order_id="ord-event",
            deployment_id=DEPLOYMENT_ID,
            strategy_id=STRATEGY_ID,
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity="100",
            correlation_id="corr-event",
            execution_mode="paper",
        )
        event = ExecutionEvent(
            id="01HTESTEVT0000000000000001",
            order_id=ORDER_ID,
            event_type="filled",
            timestamp=NOW,
            details={"fill_price": "175.50", "quantity": "100"},
            correlation_id="corr-event",
        )
        db_session.add(order)
        db_session.add(event)
        db_session.commit()

        result = db_session.query(ExecutionEvent).filter_by(id="01HTESTEVT0000000000000001").one()
        assert result.event_type == "filled"
        assert result.details["fill_price"] == "175.50"

    def test_event_cascade_delete_with_order(self, db_session: Session) -> None:
        order = Order(
            id=ORDER_ID,
            client_order_id="ord-evt-cascade",
            deployment_id=DEPLOYMENT_ID,
            strategy_id=STRATEGY_ID,
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity="100",
            correlation_id="corr-evt-cascade",
            execution_mode="paper",
        )
        event = ExecutionEvent(
            id="01HTESTEVT0000000000000002",
            order_id=ORDER_ID,
            event_type="submitted",
            timestamp=NOW,
            correlation_id="corr-evt-cascade",
        )
        db_session.add(order)
        db_session.add(event)
        db_session.commit()

        db_session.delete(order)
        db_session.commit()

        assert db_session.query(ExecutionEvent).count() == 0


# ---------------------------------------------------------------------------
# KillSwitchEvent model tests
# ---------------------------------------------------------------------------


class TestKillSwitchEventModel:
    """Tests for the KillSwitchEvent ORM model."""

    def test_insert_valid_kill_switch(self, db_session: Session) -> None:
        ks = KillSwitchEvent(
            id="01HTESTKS00000000000000001",
            scope="global",
            target_id="global",
            activated_by=f"user:{USER_ID}",
            activated_at=NOW,
            reason="Daily loss limit breached",
        )
        db_session.add(ks)
        db_session.commit()

        result = db_session.query(KillSwitchEvent).filter_by(id="01HTESTKS00000000000000001").one()
        assert result.scope == "global"
        assert result.reason == "Daily loss limit breached"
        assert result.deactivated_at is None
        assert result.mtth_ms is None

    def test_kill_switch_with_mtth(self, db_session: Session) -> None:
        ks = KillSwitchEvent(
            id="01HTESTKS00000000000000002",
            scope="strategy",
            target_id=STRATEGY_ID,
            activated_by=f"user:{USER_ID}",
            activated_at=NOW,
            reason="Manual halt",
            mtth_ms=1500,
        )
        db_session.add(ks)
        db_session.commit()

        result = db_session.query(KillSwitchEvent).filter_by(id="01HTESTKS00000000000000002").one()
        assert result.mtth_ms == 1500


# ---------------------------------------------------------------------------
# ReconciliationReport model tests
# ---------------------------------------------------------------------------


class TestReconciliationReportModel:
    """Tests for the ReconciliationReport ORM model."""

    def test_insert_valid_report(self, db_session: Session) -> None:
        report = ReconciliationReport(
            id="01HTESTRCN0000000000000001",
            deployment_id=DEPLOYMENT_ID,
            trigger="startup",
            started_at=NOW,
            status="running",
        )
        db_session.add(report)
        db_session.commit()

        result = (
            db_session.query(ReconciliationReport).filter_by(id="01HTESTRCN0000000000000001").one()
        )
        assert result.trigger == "startup"
        assert result.status == "running"
        assert result.resolved_count == 0
        assert result.unresolved_count == 0

    def test_report_with_discrepancies(self, db_session: Session) -> None:
        discrepancies = [
            {"type": "missing_order", "order_id": "ord-123", "severity": "high"},
            {"type": "quantity_mismatch", "order_id": "ord-456", "expected": "100", "actual": "90"},
        ]
        report = ReconciliationReport(
            id="01HTESTRCN0000000000000002",
            deployment_id=DEPLOYMENT_ID,
            trigger="scheduled",
            started_at=NOW,
            completed_at=NOW,
            status="completed",
            discrepancies=discrepancies,
            resolved_count=1,
            unresolved_count=1,
        )
        db_session.add(report)
        db_session.commit()

        result = (
            db_session.query(ReconciliationReport).filter_by(id="01HTESTRCN0000000000000002").one()
        )
        assert len(result.discrepancies) == 2
        assert result.resolved_count == 1
        assert result.unresolved_count == 1


# ---------------------------------------------------------------------------
# Check constraint tests (SQLite only partially enforces these, but we
# verify the DDL is valid and the constraints exist in the metadata)
# ---------------------------------------------------------------------------


class TestCheckConstraintsDDL:
    """Verify check constraints are defined in table metadata."""

    def test_orders_check_constraints_in_metadata(self) -> None:
        """Orders table should have 5 check constraints."""
        table = Order.__table__
        constraint_names = {c.name for c in table.constraints if hasattr(c, "sqltext")}
        expected = {
            "chk_orders_side",
            "chk_orders_order_type",
            "chk_orders_time_in_force",
            "chk_orders_status",
            "chk_orders_execution_mode",
        }
        assert expected.issubset(constraint_names)

    def test_kill_switch_check_constraint_in_metadata(self) -> None:
        table = KillSwitchEvent.__table__
        constraint_names = {c.name for c in table.constraints if hasattr(c, "sqltext")}
        assert "chk_kill_switch_events_scope" in constraint_names

    def test_reconciliation_check_constraints_in_metadata(self) -> None:
        table = ReconciliationReport.__table__
        constraint_names = {c.name for c in table.constraints if hasattr(c, "sqltext")}
        expected = {
            "chk_reconciliation_reports_status",
            "chk_reconciliation_reports_trigger",
        }
        assert expected.issubset(constraint_names)


# ---------------------------------------------------------------------------
# Migration chain test
# ---------------------------------------------------------------------------


class TestMigrationChain:
    """Verify migration 0009 has correct revision chain."""

    def test_migration_revision_chain(self) -> None:
        """Migration 0009 should depend on 0008."""
        import importlib

        mod = importlib.import_module("migrations.versions.20260411_0009_add_execution_tables")
        assert mod.revision == "0009"
        assert mod.down_revision == "0008"

    def test_migration_has_upgrade_and_downgrade(self) -> None:
        """Migration must define both upgrade() and downgrade()."""
        import importlib

        mod = importlib.import_module("migrations.versions.20260411_0009_add_execution_tables")
        assert callable(getattr(mod, "upgrade", None))
        assert callable(getattr(mod, "downgrade", None))


# ---------------------------------------------------------------------------
# Index existence tests
# ---------------------------------------------------------------------------


class TestIndexes:
    """Verify key indexes are defined in model metadata (column-level index=True)."""

    def test_orders_indexed_columns(self) -> None:
        """Order table should have index=True on key lookup columns."""
        table = Order.__table__
        indexed_cols = {c.name for c in table.columns if c.index}
        expected = {"deployment_id", "strategy_id", "symbol", "correlation_id", "broker_order_id"}
        assert expected.issubset(indexed_cols)

    def test_execution_events_indexed_columns(self) -> None:
        table = ExecutionEvent.__table__
        indexed_cols = {c.name for c in table.columns if c.index}
        assert "correlation_id" in indexed_cols
        assert "order_id" in indexed_cols
        assert "event_type" in indexed_cols

    def test_positions_indexed_columns(self) -> None:
        table = Position.__table__
        indexed_cols = {c.name for c in table.columns if c.index}
        assert "deployment_id" in indexed_cols
        assert "symbol" in indexed_cols

    def test_kill_switch_events_indexed_columns(self) -> None:
        table = KillSwitchEvent.__table__
        indexed_cols = {c.name for c in table.columns if c.index}
        assert "scope" in indexed_cols
        assert "target_id" in indexed_cols


# ---------------------------------------------------------------------------
# __all__ exports test
# ---------------------------------------------------------------------------


class TestModelExports:
    """Verify new models are in __all__."""

    def test_execution_models_in_all(self) -> None:
        from libs.contracts import models

        expected = {
            "Order",
            "OrderFill",
            "Position",
            "ExecutionEvent",
            "KillSwitchEvent",
            "ReconciliationReport",
        }
        assert expected.issubset(set(models.__all__))
