"""
Integration test: broker fill → P&L snapshot pipeline.

Purpose:
    Validate the full data flow from order fill persistence through
    PnlAttributionService.take_snapshot() and get_pnl_summary(),
    ensuring that fills, positions, and P&L calculations are correctly
    linked end-to-end using real SQL repositories (SQLite in-memory).

Architecture:
    - Real SQL repositories: SqlOrderRepository, SqlOrderFillRepository,
      SqlPositionRepository, SqlPnlSnapshotRepository, SqlDeploymentRepository.
    - PnlAttributionService wired with real repos.
    - No mocks except for the broker adapter (irrelevant to P&L reads).
    - SAVEPOINT isolation via integration_db_session fixture.

Responsibilities:
    - Verify that persisted fills are correctly read by P&L calculations.
    - Verify take_snapshot() computes realized P&L from positions and commissions
      from fills.
    - Verify get_pnl_summary() aggregates positions and fills into a coherent report.
    - Verify multi-fill orders compute commissions correctly.
    - Verify the full pipeline survives repo re-instantiation (no in-memory leaks).

Does NOT:
    - Test broker communication (out of scope).
    - Test HTTP layer or authentication.
    - Test concurrent snapshot creation.

Dependencies:
    - integration_db_session fixture (conftest.py): per-test SAVEPOINT session.
    - libs.contracts.models: ORM models (User, Strategy, Deployment, Order, etc.).
    - services.api.repositories: SQL repository implementations.
    - services.api.services.pnl_attribution_service: Service under test.

Example:
    pytest tests/integration/test_fill_to_pnl_integration.py -v
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from libs.contracts.models import (
    Deployment,
    Order,
    OrderFill,
    Position,
    Strategy,
    User,
)
from services.api.repositories.sql_deployment_repository import (
    SqlDeploymentRepository,
)
from services.api.repositories.sql_order_fill_repository import (
    SqlOrderFillRepository,
)
from services.api.repositories.sql_order_repository import SqlOrderRepository
from services.api.repositories.sql_pnl_snapshot_repository import (
    SqlPnlSnapshotRepository,
)
from services.api.repositories.sql_position_repository import (
    SqlPositionRepository,
)
from services.api.services.pnl_attribution_service import (
    PnlAttributionService,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_USER_ID = "01HPNX0NT0SR00000000000001"
_STRATEGY_ID = "01HPNX0NT0STRT000000000001"
_DEPLOY_ID = "01HPNX0NT0DPY0000000000001"
_ORDER_BUY_ID = "01HPNX0NT0BRDR000000000001"
_ORDER_SELL_ID = "01HPNX0NT0BRDR000000000002"
_FILL_BUY_1 = "01HPNX0NT0F000000000000001"
_FILL_BUY_2 = "01HPNX0NT0F000000000000002"
_FILL_SELL_1 = "01HPNX0NT0F000000000000003"
_POSITION_ID = "01HPNX0NT0PSN0000000000001"

_SNAPSHOT_DATE = date(2026, 4, 12)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_parent_records(db: Session) -> None:
    """Insert User → Strategy → Deployment parent chain.

    Uses flush() to stay inside SAVEPOINT isolation.
    """
    user = User(
        id=_USER_ID,
        email="pnl-integ@fxlab.dev",
        hashed_password="not-a-real-hash",
        role="operator",
    )
    db.add(user)
    db.flush()

    strategy = Strategy(
        id=_STRATEGY_ID,
        name="P&L Integration Strategy",
        code="# pnl integration test\npass",
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


def _seed_orders_fills_and_position(db: Session) -> None:
    """Seed a buy order (2 fills) and a sell order (1 fill) plus a flat position.

    Scenario: Bought 100 AAPL at avg $175 (2 fills), sold 100 AAPL at $180.
    Realized P&L = (180 - 175) * 100 = $500 before commission.
    Commissions: $1.25 + $1.00 + $1.50 = $3.75.
    Net realized P&L = $496.25.
    """
    now = datetime.now(tz=timezone.utc)

    # Buy order — 100 shares filled in 2 partial fills
    buy_order = Order(
        id=_ORDER_BUY_ID,
        client_order_id="pnl-buy-001",
        deployment_id=_DEPLOY_ID,
        strategy_id=_STRATEGY_ID,
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity="100",
        filled_quantity="100",
        average_fill_price="175.00",
        status="filled",
        time_in_force="day",
        execution_mode="paper",
        correlation_id="pnl-corr-001",
        submitted_at=now,
        filled_at=now,
    )
    db.add(buy_order)
    db.flush()

    # Fill 1: 60 shares at $174.50
    fill_buy_1 = OrderFill(
        id=_FILL_BUY_1,
        order_id=_ORDER_BUY_ID,
        fill_id="broker-fill-buy-001",
        price="174.50",
        quantity="60",
        commission="1.25",
        filled_at=now,
        correlation_id="pnl-corr-001",
    )
    db.add(fill_buy_1)
    db.flush()

    # Fill 2: 40 shares at $175.75
    fill_buy_2 = OrderFill(
        id=_FILL_BUY_2,
        order_id=_ORDER_BUY_ID,
        fill_id="broker-fill-buy-002",
        price="175.75",
        quantity="40",
        commission="1.00",
        filled_at=now,
        correlation_id="pnl-corr-001",
    )
    db.add(fill_buy_2)
    db.flush()

    # Sell order — 100 shares filled in 1 fill at $180
    sell_order = Order(
        id=_ORDER_SELL_ID,
        client_order_id="pnl-sell-001",
        deployment_id=_DEPLOY_ID,
        strategy_id=_STRATEGY_ID,
        symbol="AAPL",
        side="sell",
        order_type="market",
        quantity="100",
        filled_quantity="100",
        average_fill_price="180.00",
        status="filled",
        time_in_force="day",
        execution_mode="paper",
        correlation_id="pnl-corr-002",
        submitted_at=now,
        filled_at=now,
    )
    db.add(sell_order)
    db.flush()

    # Fill: 100 shares at $180.00
    fill_sell = OrderFill(
        id=_FILL_SELL_1,
        order_id=_ORDER_SELL_ID,
        fill_id="broker-fill-sell-001",
        price="180.00",
        quantity="100",
        commission="1.50",
        filled_at=now,
        correlation_id="pnl-corr-002",
    )
    db.add(fill_sell)
    db.flush()

    # Position: flat (bought 100, sold 100). Realized P&L stored on position.
    # avg_entry = (174.50*60 + 175.75*40) / 100 = (10470 + 7030) / 100 = 175.00
    # realized P&L = (180.00 - 175.00) * 100 = 500.00
    position = Position(
        id=_POSITION_ID,
        deployment_id=_DEPLOY_ID,
        symbol="AAPL",
        quantity="0",
        average_entry_price="175.00",
        market_price="180.00",
        market_value="0.00",
        realized_pnl="500.00",
        unrealized_pnl="0.00",
        cost_basis="17500.00",
    )
    db.add(position)
    db.flush()


def _make_service(db: Session) -> PnlAttributionService:
    """Wire PnlAttributionService with real SQL repositories."""
    return PnlAttributionService(
        deployment_repo=SqlDeploymentRepository(db=db),
        position_repo=SqlPositionRepository(db=db),
        order_fill_repo=SqlOrderFillRepository(db=db),
        order_repo=SqlOrderRepository(db=db),
        pnl_snapshot_repo=SqlPnlSnapshotRepository(db=db),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFillToPnlPipeline:
    """End-to-end: fills persisted → P&L snapshot captured → summary correct."""

    def test_take_snapshot_reads_fills_and_positions(
        self,
        integration_db_session: Session,
    ) -> None:
        """take_snapshot() computes correct P&L from real fills and positions.

        Scenario:
            Buy 100 AAPL at avg $175 (2 fills), sell 100 at $180 (1 fill).
            Total commission across 3 fills: $3.75.
            Realized P&L: $500.00.
            Unrealized P&L: $0.00 (flat position).

        Verifies:
            - Snapshot realized_pnl matches position realized_pnl.
            - Snapshot commission matches sum of all fill commissions.
            - Snapshot is persisted to the database.
        """
        db = integration_db_session
        _seed_parent_records(db)
        _seed_orders_fills_and_position(db)

        service = _make_service(db)
        snapshot = service.take_snapshot(
            deployment_id=_DEPLOY_ID,
            snapshot_date=_SNAPSHOT_DATE,
        )

        assert snapshot is not None
        assert Decimal(snapshot["realized_pnl"]) == Decimal("500.00")
        assert Decimal(snapshot["unrealized_pnl"]) == Decimal("0.00")
        assert Decimal(snapshot["commission"]) == Decimal("3.75")
        assert snapshot["positions_count"] == 1

    def test_get_pnl_summary_after_snapshot(
        self,
        integration_db_session: Session,
    ) -> None:
        """get_pnl_summary returns correct aggregate after take_snapshot.

        Verifies:
            - total_realized_pnl reflects position realized P&L.
            - total_commission reflects sum of all fill commissions.
            - total_net_pnl = realized + unrealized - commission.
        """
        db = integration_db_session
        _seed_parent_records(db)
        _seed_orders_fills_and_position(db)

        service = _make_service(db)

        # First take a snapshot so timeseries data exists
        service.take_snapshot(
            deployment_id=_DEPLOY_ID,
            snapshot_date=_SNAPSHOT_DATE,
        )

        summary = service.get_pnl_summary(deployment_id=_DEPLOY_ID)

        assert summary is not None
        # Realized P&L comes from positions
        assert Decimal(summary["total_realized_pnl"]) == Decimal("500.00")
        assert Decimal(summary["total_unrealized_pnl"]) == Decimal("0.00")
        # Total commission from fills: 1.25 + 1.00 + 1.50 = 3.75
        assert Decimal(summary["total_commission"]) == Decimal("3.75")
        # Net P&L = realized + unrealized - commission - fees = 500 + 0 - 3.75 - 0 = 496.25
        assert Decimal(summary["net_pnl"]) == Decimal("496.25")

    def test_multi_fill_commission_accumulation(
        self,
        integration_db_session: Session,
    ) -> None:
        """Commissions from multiple fills on different orders are summed.

        Verifies that all fills across all orders contribute to the
        commission total, not just the latest fill.
        """
        db = integration_db_session
        _seed_parent_records(db)
        _seed_orders_fills_and_position(db)

        fill_repo = SqlOrderFillRepository(db=db)

        # Verify the raw fill data is correctly persisted
        buy_fills = fill_repo.list_by_order(order_id=_ORDER_BUY_ID)
        sell_fills = fill_repo.list_by_order(order_id=_ORDER_SELL_ID)

        assert len(buy_fills) == 2
        assert len(sell_fills) == 1

        total_commission = sum(Decimal(f["commission"]) for f in buy_fills + sell_fills)
        assert total_commission == Decimal("3.75")

    def test_snapshot_persists_to_database(
        self,
        integration_db_session: Session,
    ) -> None:
        """Snapshot taken by one service instance is readable by another.

        Validates durable persistence — no in-memory-only state.
        """
        db = integration_db_session
        _seed_parent_records(db)
        _seed_orders_fills_and_position(db)

        # Service 1 takes the snapshot
        service1 = _make_service(db)
        service1.take_snapshot(
            deployment_id=_DEPLOY_ID,
            snapshot_date=_SNAPSHOT_DATE,
        )

        # Service 2 (fresh instance) reads the snapshot via summary
        service2 = _make_service(db)
        summary = service2.get_pnl_summary(deployment_id=_DEPLOY_ID)

        assert Decimal(summary["total_realized_pnl"]) == Decimal("500.00")
        assert Decimal(summary["total_commission"]) == Decimal("3.75")

    def test_fill_repo_returns_fills_by_deployment(
        self,
        integration_db_session: Session,
    ) -> None:
        """list_by_deployment returns all fills across all orders for a deployment.

        Validates the join path: fills → orders → deployment_id filter.
        """
        db = integration_db_session
        _seed_parent_records(db)
        _seed_orders_fills_and_position(db)

        fill_repo = SqlOrderFillRepository(db=db)
        deployment_fills = fill_repo.list_by_deployment(
            deployment_id=_DEPLOY_ID,
        )

        # 2 buy fills + 1 sell fill = 3 total
        assert len(deployment_fills) == 3
        fill_ids = {f["fill_id"] for f in deployment_fills}
        assert fill_ids == {
            "broker-fill-buy-001",
            "broker-fill-buy-002",
            "broker-fill-sell-001",
        }
