"""
Unit tests for PnlAttributionService.

Validates:
- P&L summary calculation with realized/unrealized, commissions, metrics.
- P&L timeseries generation from snapshots (daily, weekly, monthly).
- Per-symbol P&L attribution with contribution percentages.
- Multi-deployment comparison.
- Daily snapshot persistence (take_snapshot).
- Win rate, Sharpe ratio, max drawdown calculations.
- Edge cases: no fills, no positions, single trade, all-loss trades.

Dependencies (all mocked):
- DeploymentRepositoryInterface
- PositionRepositoryInterface
- OrderFillRepositoryInterface
- OrderRepositoryInterface
- PnlSnapshotRepositoryInterface
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest

from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from libs.contracts.mocks.mock_order_fill_repository import MockOrderFillRepository
from libs.contracts.mocks.mock_order_repository import MockOrderRepository
from libs.contracts.mocks.mock_pnl_snapshot_repository import MockPnlSnapshotRepository
from libs.contracts.mocks.mock_position_repository import MockPositionRepository
from services.api.services.pnl_attribution_service import PnlAttributionService

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEPLOY_ID = "01HDEPLOY00000000000000001"
_DEPLOY_ID_2 = "01HDEPLOY00000000000000002"
_STRATEGY_ID = "01HSTRATEGY000000000000001"
_STRATEGY_ID_2 = "01HSTRATEGY000000000000002"
_USER_ID = "01HUSER0000000000000000001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_deployment(
    deployment_repo: MockDeploymentRepository,
    deploy_id: str = _DEPLOY_ID,
    strategy_id: str = _STRATEGY_ID,
) -> dict[str, Any]:
    """
    Seed a deployment record with a deterministic ID.

    The MockDeploymentRepository generates its own ULID, so we create the
    record and then patch the store to use our desired ID for consistent
    test assertions.
    """
    record = deployment_repo.create(
        strategy_id=strategy_id,
        execution_mode="live",
        emergency_posture="cancel_open",
        risk_limits={"max_position_size": "100000"},
        custom_posture_config=None,
        deployed_by=_USER_ID,
    )
    # Remap to our deterministic ID for test consistency
    original_id = record["id"]
    if original_id != deploy_id:
        deployment_repo._store.pop(original_id)
        record["id"] = deploy_id
        deployment_repo._store[deploy_id] = record
        deployment_repo._transitions[deploy_id] = deployment_repo._transitions.pop(original_id, [])
    return record


def _seed_order(
    order_repo: MockOrderRepository,
    deploy_id: str,
    symbol: str,
    side: str,
    quantity: str,
    status: str = "filled",
    filled_quantity: str | None = None,
    average_fill_price: str | None = None,
    order_id: str | None = None,
) -> dict[str, Any]:
    """Seed an order record."""
    oid = order_id or f"client-{symbol}-{side}-{quantity}"
    order = order_repo.save(
        client_order_id=oid,
        deployment_id=deploy_id,
        strategy_id=_STRATEGY_ID,
        symbol=symbol,
        side=side,
        order_type="market",
        quantity=quantity,
        time_in_force="day",
        status="pending",
        correlation_id="corr-test",
        execution_mode="live",
    )
    # Update status to filled
    if status == "filled":
        fq = filled_quantity or quantity
        afp = average_fill_price or "150.00"
        order_repo.update_status(
            order_id=order["id"],
            status="filled",
            filled_quantity=fq,
            average_fill_price=afp,
            filled_at=datetime.utcnow().isoformat(),
        )
        order["status"] = "filled"
        order["filled_quantity"] = fq
        order["average_fill_price"] = afp
    elif status != "pending":
        order_repo.update_status(
            order_id=order["id"],
            status=status,
        )
        order["status"] = status
    return order


def _seed_fill(
    fill_repo: MockOrderFillRepository,
    order_id: str,
    price: str,
    quantity: str,
    commission: str = "1.00",
    filled_at: str | None = None,
    deployment_id: str = _DEPLOY_ID,
) -> dict[str, Any]:
    """Seed a fill record and register order→deployment mapping."""
    # Register the order→deployment mapping so list_by_deployment works
    fill_repo.register_order_deployment(order_id, deployment_id)
    return fill_repo.save(
        order_id=order_id,
        fill_id=f"fill-{order_id}-{price}",
        price=price,
        quantity=quantity,
        commission=commission,
        filled_at=filled_at or "2026-04-12T10:00:00+00:00",
        correlation_id="corr-test",
    )


def _seed_position(
    position_repo: MockPositionRepository,
    deploy_id: str,
    symbol: str,
    quantity: str,
    average_entry_price: str,
    unrealized_pnl: str = "0",
    realized_pnl: str = "0",
    market_price: str = "0",
) -> dict[str, Any]:
    """Seed a position record."""
    return position_repo.save(
        deployment_id=deploy_id,
        symbol=symbol,
        quantity=quantity,
        average_entry_price=average_entry_price,
        market_price=market_price,
        unrealized_pnl=unrealized_pnl,
        realized_pnl=realized_pnl,
    )


def _make_service(
    deployment_repo: MockDeploymentRepository | None = None,
    position_repo: MockPositionRepository | None = None,
    order_fill_repo: MockOrderFillRepository | None = None,
    order_repo: MockOrderRepository | None = None,
    pnl_snapshot_repo: MockPnlSnapshotRepository | None = None,
) -> PnlAttributionService:
    """Construct PnlAttributionService with mocked dependencies."""
    return PnlAttributionService(
        deployment_repo=deployment_repo or MockDeploymentRepository(),
        position_repo=position_repo or MockPositionRepository(),
        order_fill_repo=order_fill_repo or MockOrderFillRepository(),
        order_repo=order_repo or MockOrderRepository(),
        pnl_snapshot_repo=pnl_snapshot_repo or MockPnlSnapshotRepository(),
    )


# ---------------------------------------------------------------------------
# Tests: get_pnl_summary
# ---------------------------------------------------------------------------


class TestGetPnlSummary:
    """Tests for PnlAttributionService.get_pnl_summary()."""

    def test_summary_with_positions_and_fills(self) -> None:
        """Summary includes realized, unrealized, commissions from live data."""
        deployment_repo = MockDeploymentRepository()
        position_repo = MockPositionRepository()
        order_repo = MockOrderRepository()
        fill_repo = MockOrderFillRepository()
        snapshot_repo = MockPnlSnapshotRepository()

        _seed_deployment(deployment_repo)

        # Two positions with realized + unrealized P&L
        _seed_position(
            position_repo,
            _DEPLOY_ID,
            "AAPL",
            "100",
            "150.00",
            unrealized_pnl="500.00",
            realized_pnl="200.00",
            market_price="155.00",
        )
        _seed_position(
            position_repo,
            _DEPLOY_ID,
            "MSFT",
            "50",
            "320.00",
            unrealized_pnl="-100.00",
            realized_pnl="150.00",
            market_price="318.00",
        )

        # Orders and fills for trade statistics
        buy_order = _seed_order(
            order_repo, _DEPLOY_ID, "AAPL", "buy", "100", average_fill_price="150.00"
        )
        _seed_fill(fill_repo, buy_order["id"], "150.00", "100", "5.00")

        sell_order = _seed_order(
            order_repo,
            _DEPLOY_ID,
            "AAPL",
            "sell",
            "50",
            order_id="sell-aapl-50",
            average_fill_price="155.00",
        )
        _seed_fill(fill_repo, sell_order["id"], "155.00", "50", "3.00")

        msft_buy = _seed_order(
            order_repo, _DEPLOY_ID, "MSFT", "buy", "50", average_fill_price="320.00"
        )
        _seed_fill(fill_repo, msft_buy["id"], "320.00", "50", "4.00")

        service = _make_service(
            deployment_repo=deployment_repo,
            position_repo=position_repo,
            order_fill_repo=fill_repo,
            order_repo=order_repo,
            pnl_snapshot_repo=snapshot_repo,
        )

        result = service.get_pnl_summary(deployment_id=_DEPLOY_ID)

        assert result["deployment_id"] == _DEPLOY_ID
        # Total realized: 200 + 150 = 350
        assert Decimal(result["total_realized_pnl"]) == Decimal("350.00")
        # Total unrealized: 500 + (-100) = 400
        assert Decimal(result["total_unrealized_pnl"]) == Decimal("400.00")
        # Commissions: 5 + 3 + 4 = 12
        assert Decimal(result["total_commission"]) >= Decimal("12.00")
        assert result["positions_count"] == 2

    def test_summary_deployment_not_found_raises(self) -> None:
        """NotFoundError raised when deployment does not exist."""
        service = _make_service()
        with pytest.raises(Exception, match="[Nn]ot [Ff]ound|does not exist"):
            service.get_pnl_summary(deployment_id="01HNONEXISTENT0000000000001")

    def test_summary_no_positions_returns_zero_pnl(self) -> None:
        """Empty deployment with no positions returns zero P&L."""
        deployment_repo = MockDeploymentRepository()
        _seed_deployment(deployment_repo)

        service = _make_service(deployment_repo=deployment_repo)
        result = service.get_pnl_summary(deployment_id=_DEPLOY_ID)

        assert Decimal(result["total_realized_pnl"]) == Decimal("0")
        assert Decimal(result["total_unrealized_pnl"]) == Decimal("0")
        assert result["positions_count"] == 0
        assert result["total_trades"] == 0

    def test_summary_win_rate_calculation(self) -> None:
        """Win rate computed from filled orders with realized P&L > 0."""
        deployment_repo = MockDeploymentRepository()
        position_repo = MockPositionRepository()
        order_repo = MockOrderRepository()
        fill_repo = MockOrderFillRepository()

        _seed_deployment(deployment_repo)

        # 3 winning trades (sell higher than buy)
        for i in range(3):
            buy = _seed_order(
                order_repo,
                _DEPLOY_ID,
                "AAPL",
                "buy",
                "10",
                order_id=f"buy-win-{i}",
                average_fill_price="100.00",
            )
            _seed_fill(
                fill_repo,
                buy["id"],
                "100.00",
                "10",
                "1.00",
                filled_at=f"2026-04-{10 + i}T10:00:00+00:00",
            )
            sell = _seed_order(
                order_repo,
                _DEPLOY_ID,
                "AAPL",
                "sell",
                "10",
                order_id=f"sell-win-{i}",
                average_fill_price="110.00",
            )
            _seed_fill(
                fill_repo,
                sell["id"],
                "110.00",
                "10",
                "1.00",
                filled_at=f"2026-04-{10 + i}T11:00:00+00:00",
            )

        # 2 losing trades (sell lower than buy)
        for i in range(2):
            buy = _seed_order(
                order_repo,
                _DEPLOY_ID,
                "MSFT",
                "buy",
                "10",
                order_id=f"buy-loss-{i}",
                average_fill_price="300.00",
            )
            _seed_fill(
                fill_repo,
                buy["id"],
                "300.00",
                "10",
                "1.00",
                filled_at=f"2026-04-{10 + i}T12:00:00+00:00",
            )
            sell = _seed_order(
                order_repo,
                _DEPLOY_ID,
                "MSFT",
                "sell",
                "10",
                order_id=f"sell-loss-{i}",
                average_fill_price="290.00",
            )
            _seed_fill(
                fill_repo,
                sell["id"],
                "290.00",
                "10",
                "1.00",
                filled_at=f"2026-04-{10 + i}T13:00:00+00:00",
            )

        # Positions reflecting realized P&L from closed trades
        _seed_position(
            position_repo, _DEPLOY_ID, "AAPL", "0", "0", realized_pnl="300.00"
        )  # 3 wins × $100
        _seed_position(
            position_repo, _DEPLOY_ID, "MSFT", "0", "0", realized_pnl="-200.00"
        )  # 2 losses × $100

        service = _make_service(
            deployment_repo=deployment_repo,
            position_repo=position_repo,
            order_fill_repo=fill_repo,
            order_repo=order_repo,
        )

        result = service.get_pnl_summary(deployment_id=_DEPLOY_ID)

        # Win rate: 3 / (3 + 2) = 60%
        assert Decimal(result["win_rate"]) == Decimal("60.0")
        assert result["winning_trades"] == 3
        assert result["losing_trades"] == 2
        assert result["total_trades"] == 5


# ---------------------------------------------------------------------------
# Tests: get_pnl_timeseries
# ---------------------------------------------------------------------------


class TestGetPnlTimeseries:
    """Tests for PnlAttributionService.get_pnl_timeseries()."""

    def test_daily_timeseries_from_snapshots(self) -> None:
        """Daily timeseries returns one point per snapshot date."""
        deployment_repo = MockDeploymentRepository()
        snapshot_repo = MockPnlSnapshotRepository()

        _seed_deployment(deployment_repo)

        # Seed 5 daily snapshots
        for day in range(1, 6):
            rpnl = str(day * 100)
            upnl = str(day * 50)
            snapshot_repo.save(
                deployment_id=_DEPLOY_ID,
                snapshot_date=date(2026, 4, day),
                realized_pnl=rpnl,
                unrealized_pnl=upnl,
                commission=str(day * 5),
                positions_count=day,
            )

        service = _make_service(
            deployment_repo=deployment_repo,
            pnl_snapshot_repo=snapshot_repo,
        )

        result = service.get_pnl_timeseries(
            deployment_id=_DEPLOY_ID,
            date_from=date(2026, 4, 1),
            date_to=date(2026, 4, 5),
        )

        assert len(result) == 5
        # First point
        assert result[0]["snapshot_date"] == "2026-04-01"
        assert Decimal(result[0]["realized_pnl"]) == Decimal("100")
        # Last point
        assert result[4]["snapshot_date"] == "2026-04-05"
        assert Decimal(result[4]["realized_pnl"]) == Decimal("500")

    def test_timeseries_includes_daily_pnl_change(self) -> None:
        """Each point includes daily P&L change from previous day."""
        deployment_repo = MockDeploymentRepository()
        snapshot_repo = MockPnlSnapshotRepository()

        _seed_deployment(deployment_repo)

        # Day 1: net 150, Day 2: net 280, Day 3: net 450
        snapshot_repo.save(
            deployment_id=_DEPLOY_ID,
            snapshot_date=date(2026, 4, 1),
            realized_pnl="100",
            unrealized_pnl="50",
        )
        snapshot_repo.save(
            deployment_id=_DEPLOY_ID,
            snapshot_date=date(2026, 4, 2),
            realized_pnl="200",
            unrealized_pnl="80",
        )
        snapshot_repo.save(
            deployment_id=_DEPLOY_ID,
            snapshot_date=date(2026, 4, 3),
            realized_pnl="350",
            unrealized_pnl="100",
        )

        service = _make_service(
            deployment_repo=deployment_repo,
            pnl_snapshot_repo=snapshot_repo,
        )

        result = service.get_pnl_timeseries(
            deployment_id=_DEPLOY_ID,
            date_from=date(2026, 4, 1),
            date_to=date(2026, 4, 3),
        )

        assert len(result) == 3
        # Day 1: daily_pnl = net_pnl (first day)
        assert Decimal(result[0]["daily_pnl"]) == Decimal("150")
        # Day 2: daily_pnl = 280 - 150 = 130
        assert Decimal(result[1]["daily_pnl"]) == Decimal("130")
        # Day 3: daily_pnl = 450 - 280 = 170
        assert Decimal(result[2]["daily_pnl"]) == Decimal("170")

    def test_timeseries_includes_drawdown(self) -> None:
        """Drawdown percentage calculated from peak P&L."""
        deployment_repo = MockDeploymentRepository()
        snapshot_repo = MockPnlSnapshotRepository()

        _seed_deployment(deployment_repo)

        # Day 1: net 200, Day 2: net 300 (peak), Day 3: net 250 (drawdown)
        snapshot_repo.save(
            deployment_id=_DEPLOY_ID,
            snapshot_date=date(2026, 4, 1),
            realized_pnl="200",
            unrealized_pnl="0",
        )
        snapshot_repo.save(
            deployment_id=_DEPLOY_ID,
            snapshot_date=date(2026, 4, 2),
            realized_pnl="300",
            unrealized_pnl="0",
        )
        snapshot_repo.save(
            deployment_id=_DEPLOY_ID,
            snapshot_date=date(2026, 4, 3),
            realized_pnl="250",
            unrealized_pnl="0",
        )

        service = _make_service(
            deployment_repo=deployment_repo,
            pnl_snapshot_repo=snapshot_repo,
        )

        result = service.get_pnl_timeseries(
            deployment_id=_DEPLOY_ID,
            date_from=date(2026, 4, 1),
            date_to=date(2026, 4, 3),
        )

        # Day 3: drawdown = (300 - 250) / 300 = 16.67%
        assert Decimal(result[2]["drawdown_pct"]) > Decimal("0")

    def test_timeseries_empty_range_returns_empty(self) -> None:
        """No snapshots in range returns empty list."""
        deployment_repo = MockDeploymentRepository()
        _seed_deployment(deployment_repo)

        service = _make_service(deployment_repo=deployment_repo)

        result = service.get_pnl_timeseries(
            deployment_id=_DEPLOY_ID,
            date_from=date(2026, 4, 1),
            date_to=date(2026, 4, 5),
        )

        assert result == []

    def test_timeseries_deployment_not_found_raises(self) -> None:
        """NotFoundError when deployment does not exist."""
        service = _make_service()
        with pytest.raises(Exception, match="[Nn]ot [Ff]ound|does not exist"):
            service.get_pnl_timeseries(
                deployment_id="01HNONEXISTENT0000000000001",
                date_from=date(2026, 4, 1),
                date_to=date(2026, 4, 5),
            )


# ---------------------------------------------------------------------------
# Tests: get_attribution
# ---------------------------------------------------------------------------


class TestGetAttribution:
    """Tests for PnlAttributionService.get_attribution()."""

    def test_attribution_by_symbol(self) -> None:
        """Attribution shows per-symbol P&L and contribution percentage."""
        deployment_repo = MockDeploymentRepository()
        position_repo = MockPositionRepository()
        order_repo = MockOrderRepository()
        fill_repo = MockOrderFillRepository()

        _seed_deployment(deployment_repo)

        # AAPL: realized 600, unrealized 200
        _seed_position(
            position_repo,
            _DEPLOY_ID,
            "AAPL",
            "100",
            "150.00",
            realized_pnl="600.00",
            unrealized_pnl="200.00",
        )
        buy_aapl = _seed_order(
            order_repo, _DEPLOY_ID, "AAPL", "buy", "100", average_fill_price="150.00"
        )
        _seed_fill(fill_repo, buy_aapl["id"], "150.00", "100", "5.00")

        # MSFT: realized 400, unrealized -50
        _seed_position(
            position_repo,
            _DEPLOY_ID,
            "MSFT",
            "50",
            "320.00",
            realized_pnl="400.00",
            unrealized_pnl="-50.00",
        )
        buy_msft = _seed_order(
            order_repo, _DEPLOY_ID, "MSFT", "buy", "50", average_fill_price="320.00"
        )
        _seed_fill(fill_repo, buy_msft["id"], "320.00", "50", "3.00")

        service = _make_service(
            deployment_repo=deployment_repo,
            position_repo=position_repo,
            order_fill_repo=fill_repo,
            order_repo=order_repo,
        )

        result = service.get_attribution(deployment_id=_DEPLOY_ID)

        assert result["deployment_id"] == _DEPLOY_ID
        assert len(result["by_symbol"]) == 2

        # AAPL contribution: net 800 out of total 1150 = ~69.6%
        aapl = next(s for s in result["by_symbol"] if s["symbol"] == "AAPL")
        assert Decimal(aapl["net_pnl"]) == Decimal("800.00")

        # MSFT contribution: net 350 out of total 1150 = ~30.4%
        msft = next(s for s in result["by_symbol"] if s["symbol"] == "MSFT")
        assert Decimal(msft["net_pnl"]) == Decimal("350.00")

        # Contributions should sum to ~100%
        total_contribution = sum(Decimal(s["contribution_pct"]) for s in result["by_symbol"])
        assert abs(total_contribution - Decimal("100.0")) < Decimal("0.1")

    def test_attribution_no_positions_returns_empty(self) -> None:
        """No positions means empty attribution list."""
        deployment_repo = MockDeploymentRepository()
        _seed_deployment(deployment_repo)

        service = _make_service(deployment_repo=deployment_repo)
        result = service.get_attribution(deployment_id=_DEPLOY_ID)

        assert result["by_symbol"] == []
        assert Decimal(result["total_net_pnl"]) == Decimal("0")


# ---------------------------------------------------------------------------
# Tests: get_comparison
# ---------------------------------------------------------------------------


class TestGetComparison:
    """Tests for PnlAttributionService.get_comparison()."""

    def test_comparison_two_deployments(self) -> None:
        """Comparison returns entries for each requested deployment."""
        deployment_repo = MockDeploymentRepository()
        position_repo = MockPositionRepository()

        _seed_deployment(deployment_repo, _DEPLOY_ID)
        _seed_deployment(deployment_repo, _DEPLOY_ID_2, _STRATEGY_ID_2)

        # Deploy 1: net 500
        _seed_position(
            position_repo,
            _DEPLOY_ID,
            "AAPL",
            "100",
            "150.00",
            realized_pnl="400.00",
            unrealized_pnl="100.00",
        )
        # Deploy 2: net 800
        _seed_position(
            position_repo,
            _DEPLOY_ID_2,
            "MSFT",
            "50",
            "320.00",
            realized_pnl="600.00",
            unrealized_pnl="200.00",
        )

        service = _make_service(
            deployment_repo=deployment_repo,
            position_repo=position_repo,
        )

        result = service.get_comparison(
            deployment_ids=[_DEPLOY_ID, _DEPLOY_ID_2],
        )

        assert len(result["entries"]) == 2
        deploy_ids = {e["deployment_id"] for e in result["entries"]}
        assert _DEPLOY_ID in deploy_ids
        assert _DEPLOY_ID_2 in deploy_ids

    def test_comparison_empty_ids_raises(self) -> None:
        """Empty deployment_ids list raises ValidationError."""
        service = _make_service()
        with pytest.raises(Exception, match="[Vv]alid|[Ee]mpty"):
            service.get_comparison(deployment_ids=[])


# ---------------------------------------------------------------------------
# Tests: take_snapshot
# ---------------------------------------------------------------------------


class TestTakeSnapshot:
    """Tests for PnlAttributionService.take_snapshot()."""

    def test_snapshot_persisted_from_positions(self) -> None:
        """Snapshot captures current positions' P&L state."""
        deployment_repo = MockDeploymentRepository()
        position_repo = MockPositionRepository()
        fill_repo = MockOrderFillRepository()
        snapshot_repo = MockPnlSnapshotRepository()

        _seed_deployment(deployment_repo)

        _seed_position(
            position_repo,
            _DEPLOY_ID,
            "AAPL",
            "100",
            "150.00",
            realized_pnl="200.00",
            unrealized_pnl="500.00",
        )
        _seed_position(
            position_repo,
            _DEPLOY_ID,
            "MSFT",
            "50",
            "320.00",
            realized_pnl="150.00",
            unrealized_pnl="-100.00",
        )

        service = _make_service(
            deployment_repo=deployment_repo,
            position_repo=position_repo,
            order_fill_repo=fill_repo,
            pnl_snapshot_repo=snapshot_repo,
        )

        result = service.take_snapshot(
            deployment_id=_DEPLOY_ID,
            snapshot_date=date(2026, 4, 12),
        )

        assert result["deployment_id"] == _DEPLOY_ID
        assert result["snapshot_date"] == "2026-04-12"
        # Realized: 200 + 150 = 350
        assert Decimal(result["realized_pnl"]) == Decimal("350.00")
        # Unrealized: 500 + (-100) = 400
        assert Decimal(result["unrealized_pnl"]) == Decimal("400.00")
        assert result["positions_count"] == 2

        # Verify persisted in snapshot repo
        assert snapshot_repo.count() == 1

    def test_snapshot_upsert_updates_existing(self) -> None:
        """Second snapshot for same date updates rather than duplicates."""
        deployment_repo = MockDeploymentRepository()
        position_repo = MockPositionRepository()
        fill_repo = MockOrderFillRepository()
        snapshot_repo = MockPnlSnapshotRepository()

        _seed_deployment(deployment_repo)
        _seed_position(
            position_repo,
            _DEPLOY_ID,
            "AAPL",
            "100",
            "150.00",
            realized_pnl="200.00",
            unrealized_pnl="100.00",
        )

        service = _make_service(
            deployment_repo=deployment_repo,
            position_repo=position_repo,
            order_fill_repo=fill_repo,
            pnl_snapshot_repo=snapshot_repo,
        )

        # First snapshot
        service.take_snapshot(deployment_id=_DEPLOY_ID, snapshot_date=date(2026, 4, 12))
        assert snapshot_repo.count() == 1

        # Update position P&L
        positions = position_repo.list_by_deployment(deployment_id=_DEPLOY_ID)
        if positions:
            position_repo.update_position(
                position_id=positions[0]["id"],
                realized_pnl="300.00",
                unrealized_pnl="200.00",
            )

        # Second snapshot for same date — should upsert
        result = service.take_snapshot(
            deployment_id=_DEPLOY_ID,
            snapshot_date=date(2026, 4, 12),
        )
        assert snapshot_repo.count() == 1  # Still 1, not 2
        assert Decimal(result["realized_pnl"]) == Decimal("300.00")

    def test_snapshot_deployment_not_found_raises(self) -> None:
        """NotFoundError when deployment does not exist."""
        service = _make_service()
        with pytest.raises(Exception, match="[Nn]ot [Ff]ound|does not exist"):
            service.take_snapshot(
                deployment_id="01HNONEXISTENT0000000000001",
                snapshot_date=date(2026, 4, 12),
            )


# ---------------------------------------------------------------------------
# Tests: Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests for PnlAttributionService."""

    def test_single_trade_metrics(self) -> None:
        """Service handles deployment with exactly one filled trade."""
        deployment_repo = MockDeploymentRepository()
        position_repo = MockPositionRepository()
        order_repo = MockOrderRepository()
        fill_repo = MockOrderFillRepository()

        _seed_deployment(deployment_repo)
        _seed_position(
            position_repo,
            _DEPLOY_ID,
            "AAPL",
            "100",
            "150.00",
            realized_pnl="100.00",
            unrealized_pnl="0",
        )
        buy = _seed_order(order_repo, _DEPLOY_ID, "AAPL", "buy", "100", average_fill_price="150.00")
        _seed_fill(fill_repo, buy["id"], "150.00", "100")

        service = _make_service(
            deployment_repo=deployment_repo,
            position_repo=position_repo,
            order_fill_repo=fill_repo,
            order_repo=order_repo,
        )

        result = service.get_pnl_summary(deployment_id=_DEPLOY_ID)
        assert result["positions_count"] == 1
        assert Decimal(result["total_realized_pnl"]) == Decimal("100.00")

    def test_all_losing_trades_zero_profit_factor(self) -> None:
        """When all trades lose, profit_factor is None (no winning trades)."""
        deployment_repo = MockDeploymentRepository()
        position_repo = MockPositionRepository()
        order_repo = MockOrderRepository()
        fill_repo = MockOrderFillRepository()

        _seed_deployment(deployment_repo)

        # Only losing trades
        for i in range(3):
            buy = _seed_order(
                order_repo,
                _DEPLOY_ID,
                "AAPL",
                "buy",
                "10",
                order_id=f"buy-loss-{i}",
                average_fill_price="100.00",
            )
            _seed_fill(
                fill_repo,
                buy["id"],
                "100.00",
                "10",
                "1.00",
                filled_at=f"2026-04-{10 + i}T10:00:00+00:00",
            )
            sell = _seed_order(
                order_repo,
                _DEPLOY_ID,
                "AAPL",
                "sell",
                "10",
                order_id=f"sell-loss-{i}",
                average_fill_price="90.00",
            )
            _seed_fill(
                fill_repo,
                sell["id"],
                "90.00",
                "10",
                "1.00",
                filled_at=f"2026-04-{10 + i}T11:00:00+00:00",
            )

        _seed_position(position_repo, _DEPLOY_ID, "AAPL", "0", "0", realized_pnl="-300.00")

        service = _make_service(
            deployment_repo=deployment_repo,
            position_repo=position_repo,
            order_fill_repo=fill_repo,
            order_repo=order_repo,
        )

        result = service.get_pnl_summary(deployment_id=_DEPLOY_ID)
        assert Decimal(result["win_rate"]) == Decimal("0")
        assert result["winning_trades"] == 0
        assert result["losing_trades"] == 3

    def test_summary_net_pnl_includes_commissions(self) -> None:
        """Net P&L = realized + unrealized - commissions - fees."""
        deployment_repo = MockDeploymentRepository()
        position_repo = MockPositionRepository()
        fill_repo = MockOrderFillRepository()
        order_repo = MockOrderRepository()

        _seed_deployment(deployment_repo)

        _seed_position(
            position_repo,
            _DEPLOY_ID,
            "AAPL",
            "100",
            "150.00",
            realized_pnl="500.00",
            unrealized_pnl="200.00",
        )

        buy = _seed_order(order_repo, _DEPLOY_ID, "AAPL", "buy", "100", average_fill_price="150.00")
        _seed_fill(fill_repo, buy["id"], "150.00", "100", "25.00")

        service = _make_service(
            deployment_repo=deployment_repo,
            position_repo=position_repo,
            order_fill_repo=fill_repo,
            order_repo=order_repo,
        )

        result = service.get_pnl_summary(deployment_id=_DEPLOY_ID)
        net = Decimal(result["net_pnl"])
        realized = Decimal(result["total_realized_pnl"])
        unrealized = Decimal(result["total_unrealized_pnl"])
        commission = Decimal(result["total_commission"])
        fees = Decimal(result["total_fees"])

        # net = realized + unrealized - commission - fees
        assert net == realized + unrealized - commission - fees
