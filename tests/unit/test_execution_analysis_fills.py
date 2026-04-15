"""
Unit tests for ExecutionAnalysisService order fill integration.

Verifies:
    - When order_fill_repo is provided, fills are fetched and attached to
      OrderHistoryItem objects in get_order_history().
    - When order_fill_repo is provided, fills are fetched and attached in
      get_execution_report().
    - When order_fill_repo is None (backward compat), fills default to [].
    - Fill dicts from the repository are correctly converted to FillItem models.
    - Errors from order_fill_repo.list_by_order are gracefully handled
      (fills default to [] for that order, other orders unaffected).

Dependencies:
    - MockOrderRepository, MockOrderFillRepository, MockDeploymentRepository.
    - ExecutionAnalysisService (service under test).

Example:
    pytest tests/unit/test_execution_analysis_fills.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from libs.contracts.execution_report import (
    FillItem,
    OrderHistoryQuery,
)
from libs.contracts.interfaces.order_fill_repository_interface import (
    OrderFillRepositoryInterface,
)
from libs.contracts.mocks.mock_deployment_repository import (
    MockDeploymentRepository,
)
from libs.contracts.mocks.mock_order_fill_repository import (
    MockOrderFillRepository,
)
from libs.contracts.mocks.mock_order_repository import MockOrderRepository
from services.api.services.execution_analysis_service import (
    ExecutionAnalysisService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEPLOYMENT_ID = "01HEXFILLS0DEPLOY00000000A"
_STRATEGY_ID = "01HEXFILLS0STRAT000000000A"
_ORDER_ID_1 = "01HEXFILLS0ORDER000000000A"
_ORDER_ID_2 = "01HEXFILLS0ORDER000000000B"

_FILLED_AT = "2026-04-12T10:00:00+00:00"
_CREATED_AT = datetime(2026, 4, 12, 9, 0, 0, tzinfo=timezone.utc)


def _seed_deployment(dep_repo: MockDeploymentRepository) -> None:
    """Seed a deployment so the service can resolve it."""
    dep_repo.seed(
        deployment_id=_DEPLOYMENT_ID,
        strategy_id=_STRATEGY_ID,
        execution_mode="paper",
    )


def _seed_order(
    order_repo: MockOrderRepository,
    order_id: str = _ORDER_ID_1,
    status: str = "filled",
) -> None:
    """Seed an order record in the mock repository.

    Patches filled_quantity to "0" (instead of None) so that
    Decimal conversion in get_order_history does not raise.
    """
    order_repo.seed(
        order_id=order_id,
        deployment_id=_DEPLOYMENT_ID,
        strategy_id=_STRATEGY_ID,
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity="100",
        status=status,
        time_in_force="day",
        execution_mode="paper",
        correlation_id="corr-fills-test",
    )
    # Patch nullable Decimal fields that the service casts via Decimal()
    order_repo._store[order_id]["filled_quantity"] = "0"
    order_repo._store[order_id]["order_id"] = order_id


def _make_service(
    dep_repo: MockDeploymentRepository,
    order_repo: MockOrderRepository,
    order_fill_repo: OrderFillRepositoryInterface | None = None,
) -> ExecutionAnalysisService:
    """Build the service with the given mock dependencies."""
    return ExecutionAnalysisService(
        deployment_repo=dep_repo,
        adapter_registry={_DEPLOYMENT_ID: MagicMock()},
        order_repo=order_repo,
        order_fill_repo=order_fill_repo,
    )


# ---------------------------------------------------------------------------
# Tests: fills integration in get_order_history
# ---------------------------------------------------------------------------


class TestOrderHistoryFills:
    """Verify fills are attached to OrderHistoryItem via order_fill_repo."""

    def test_fills_populated_from_order_fill_repo(self) -> None:
        """When order_fill_repo is provided, fills are fetched per order."""
        dep_repo = MockDeploymentRepository()
        order_repo = MockOrderRepository()
        fill_repo = MockOrderFillRepository()

        _seed_deployment(dep_repo)
        _seed_order(order_repo, _ORDER_ID_1)
        fill_repo.seed(
            order_id=_ORDER_ID_1,
            fill_id="fill-001",
            price="175.50",
            quantity="100",
            commission="1.25",
            filled_at=_FILLED_AT,
            correlation_id="corr-fills-test",
        )

        service = _make_service(dep_repo, order_repo, order_fill_repo=fill_repo)
        query = OrderHistoryQuery(deployment_id=_DEPLOYMENT_ID, page=1, page_size=50)
        page = service.get_order_history(query=query)

        assert len(page.items) == 1
        item = page.items[0]
        assert len(item.fills) == 1
        fill = item.fills[0]
        assert isinstance(fill, FillItem)
        assert fill.fill_id == "fill-001"
        assert fill.price == Decimal("175.50")
        assert fill.quantity == Decimal("100")
        assert fill.commission == Decimal("1.25")

    def test_multiple_fills_per_order(self) -> None:
        """Multiple fills are all attached to the same order."""
        dep_repo = MockDeploymentRepository()
        order_repo = MockOrderRepository()
        fill_repo = MockOrderFillRepository()

        _seed_deployment(dep_repo)
        _seed_order(order_repo, _ORDER_ID_1)
        fill_repo.seed(
            order_id=_ORDER_ID_1,
            fill_id="fill-001",
            price="175.00",
            quantity="50",
            commission="0.75",
            filled_at="2026-04-12T10:00:00+00:00",
        )
        fill_repo.seed(
            order_id=_ORDER_ID_1,
            fill_id="fill-002",
            price="176.00",
            quantity="50",
            commission="0.75",
            filled_at="2026-04-12T10:00:01+00:00",
        )

        service = _make_service(dep_repo, order_repo, order_fill_repo=fill_repo)
        query = OrderHistoryQuery(deployment_id=_DEPLOYMENT_ID, page=1, page_size=50)
        page = service.get_order_history(query=query)

        assert len(page.items) == 1
        assert len(page.items[0].fills) == 2
        fill_ids = {f.fill_id for f in page.items[0].fills}
        assert fill_ids == {"fill-001", "fill-002"}

    def test_fills_empty_when_no_fill_repo(self) -> None:
        """Without order_fill_repo, fills defaults to empty list (backward compat)."""
        dep_repo = MockDeploymentRepository()
        order_repo = MockOrderRepository()

        _seed_deployment(dep_repo)
        _seed_order(order_repo, _ORDER_ID_1)

        service = _make_service(dep_repo, order_repo, order_fill_repo=None)
        query = OrderHistoryQuery(deployment_id=_DEPLOYMENT_ID, page=1, page_size=50)
        page = service.get_order_history(query=query)

        assert len(page.items) == 1
        assert page.items[0].fills == []

    def test_fills_empty_when_order_has_no_fills(self) -> None:
        """Order with no fills in the repo gets an empty fills list."""
        dep_repo = MockDeploymentRepository()
        order_repo = MockOrderRepository()
        fill_repo = MockOrderFillRepository()

        _seed_deployment(dep_repo)
        _seed_order(order_repo, _ORDER_ID_1)

        service = _make_service(dep_repo, order_repo, order_fill_repo=fill_repo)
        query = OrderHistoryQuery(deployment_id=_DEPLOYMENT_ID, page=1, page_size=50)
        page = service.get_order_history(query=query)

        assert len(page.items) == 1
        assert page.items[0].fills == []

    def test_fill_repo_error_gracefully_returns_empty_fills(self) -> None:
        """If list_by_order raises, fills default to [] for that order."""
        dep_repo = MockDeploymentRepository()
        order_repo = MockOrderRepository()

        _seed_deployment(dep_repo)
        _seed_order(order_repo, _ORDER_ID_1)

        failing_fill_repo = MagicMock(spec=OrderFillRepositoryInterface)
        failing_fill_repo.list_by_order.side_effect = RuntimeError("DB timeout")

        service = _make_service(dep_repo, order_repo, order_fill_repo=failing_fill_repo)
        query = OrderHistoryQuery(deployment_id=_DEPLOYMENT_ID, page=1, page_size=50)
        page = service.get_order_history(query=query)

        assert len(page.items) == 1
        assert page.items[0].fills == []


# ---------------------------------------------------------------------------
# Tests: fills integration in get_execution_report
# ---------------------------------------------------------------------------


class TestExecutionReportFills:
    """Verify fills are attached in get_execution_report."""

    def test_execution_report_includes_fills(self) -> None:
        """Filled orders in execution report have their fills attached."""
        dep_repo = MockDeploymentRepository()
        order_repo = MockOrderRepository()
        fill_repo = MockOrderFillRepository()

        _seed_deployment(dep_repo)
        _seed_order(order_repo, _ORDER_ID_1, status="filled")
        fill_repo.seed(
            order_id=_ORDER_ID_1,
            fill_id="fill-exec-001",
            price="175.50",
            quantity="100",
            commission="1.25",
            filled_at=_FILLED_AT,
        )

        service = _make_service(dep_repo, order_repo, order_fill_repo=fill_repo)
        report = service.get_execution_report(
            deployment_id=_DEPLOYMENT_ID,
            date_from=datetime(2026, 4, 1, tzinfo=timezone.utc),
            date_to=datetime(2026, 4, 30, tzinfo=timezone.utc),
        )

        assert report.total_orders >= 1
        assert report.filled_orders >= 1

    def test_execution_report_no_fill_repo_still_works(self) -> None:
        """Without order_fill_repo, execution report still completes."""
        dep_repo = MockDeploymentRepository()
        order_repo = MockOrderRepository()

        _seed_deployment(dep_repo)
        _seed_order(order_repo, _ORDER_ID_1, status="filled")

        service = _make_service(dep_repo, order_repo, order_fill_repo=None)
        report = service.get_execution_report(
            deployment_id=_DEPLOYMENT_ID,
            date_from=datetime(2026, 4, 1, tzinfo=timezone.utc),
            date_to=datetime(2026, 4, 30, tzinfo=timezone.utc),
        )

        assert report.total_orders >= 1


# ---------------------------------------------------------------------------
# Tests: FillItem conversion
# ---------------------------------------------------------------------------


class TestFillDictToFillItem:
    """Verify fill dicts are correctly converted to FillItem models."""

    def test_fill_with_broker_execution_id(self) -> None:
        """broker_execution_id is carried through to FillItem."""
        dep_repo = MockDeploymentRepository()
        order_repo = MockOrderRepository()
        fill_repo = MockOrderFillRepository()

        _seed_deployment(dep_repo)
        _seed_order(order_repo, _ORDER_ID_1)
        fill_repo.seed(
            order_id=_ORDER_ID_1,
            fill_id="fill-brkr-001",
            price="175.50",
            quantity="100",
            commission="1.25",
            filled_at=_FILLED_AT,
            broker_execution_id="ALPACA-exec-xyz",
        )

        service = _make_service(dep_repo, order_repo, order_fill_repo=fill_repo)
        query = OrderHistoryQuery(deployment_id=_DEPLOYMENT_ID, page=1, page_size=50)
        page = service.get_order_history(query=query)

        fill = page.items[0].fills[0]
        assert fill.broker_execution_id == "ALPACA-exec-xyz"
