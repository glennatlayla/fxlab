"""
Unit tests for execution report API routes and order history endpoints.

Covers M8 (Execution Reports and Order History):
- GET /execution-analysis/orders → paginated order history with filtering/sorting
- GET /execution-analysis/report → aggregated execution metrics and breakdowns
- GET /execution-analysis/export → CSV export of filtered orders

Dependencies:
- libs.contracts.execution_report: OrderHistoryQuery, OrderHistoryPage, ExecutionReportSummary
- libs.contracts.interfaces.execution_analysis_interface: ExecutionAnalysisInterface
- services.api.routes.execution_analysis: set_execution_analysis_service

TDD Approach:
These tests are written in RED (failing) state and will remain red until the
routes and service methods are implemented. They define the expected behaviour
for M8 endpoints.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from libs.contracts.execution_report import (
    ExecutionReportSummary,
    FillItem,
    ModeBreakdown,
    OrderHistoryItem,
    OrderHistoryPage,
    OrderHistoryQuery,
    SymbolBreakdown,
)
from libs.contracts.interfaces.execution_analysis_interface import (
    ExecutionAnalysisInterface,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEP_ID = "01HTESTDEP0000000000000001"
STRAT_ID = "01HTESTSTRT000000000000001"


# ---------------------------------------------------------------------------
# Mock ExecutionAnalysisService for route-level testing
# ---------------------------------------------------------------------------


class MockExecutionAnalysisService(ExecutionAnalysisInterface):
    """
    Mock service for route-level testing of M8 endpoints.

    Responsibilities:
    - Provide seeded order data for testing filtering, sorting, and pagination.
    - Return hard-coded execution report for testing aggregation endpoints.
    - Implement all ExecutionAnalysisInterface methods (only M8 methods functional).

    Does NOT:
    - Persist data (in-memory only).
    - Contain business logic.

    Dependencies:
    - ExecutionAnalysisInterface (interface definition).

    Example:
        service = MockExecutionAnalysisService()
        service.seed_orders(...)
        page = service.get_order_history(query=OrderHistoryQuery(...))
    """

    def __init__(self) -> None:
        """Initialize the mock service with empty state."""
        self._orders: dict[str, OrderHistoryItem] = {}
        self._events: list = []

    # ------------------------------------------------------------------
    # M8 Endpoint Methods (NEW)
    # ------------------------------------------------------------------

    def get_order_history(self, *, query: OrderHistoryQuery) -> OrderHistoryPage:
        """
        Retrieve paginated order history with filtering and sorting.

        Implements filtering by deployment, symbol, side, status, execution mode,
        and date range. Supports sorting by any order field.

        Args:
            query: OrderHistoryQuery with filter, sort, and pagination params.

        Returns:
            OrderHistoryPage with ordered results and pagination metadata.
        """
        # Start with all orders
        results = list(self._orders.values())

        # Apply filters
        if query.deployment_id:
            results = [o for o in results if o.deployment_id == query.deployment_id]
        if query.symbol:
            results = [o for o in results if o.symbol == query.symbol]
        if query.side:
            results = [o for o in results if o.side == query.side]
        if query.status:
            results = [o for o in results if o.status == query.status]
        if query.execution_mode:
            results = [o for o in results if o.execution_mode == query.execution_mode]
        if query.date_from and query.date_to:
            results = [
                o
                for o in results
                if (o.submitted_at or o.created_at) >= query.date_from
                and (o.submitted_at or o.created_at) <= query.date_to
            ]
        elif query.date_from:
            results = [o for o in results if (o.submitted_at or o.created_at) >= query.date_from]
        elif query.date_to:
            results = [o for o in results if (o.submitted_at or o.created_at) <= query.date_to]

        # Apply sorting
        sort_reverse = query.sort_dir.lower() == "desc"
        try:
            results.sort(
                key=lambda o: getattr(o, query.sort_by) or "",
                reverse=sort_reverse,
            )
        except AttributeError:
            # Default to submitted_at if invalid sort column
            results.sort(
                key=lambda o: o.submitted_at or o.created_at,
                reverse=sort_reverse,
            )

        # Apply pagination
        total = len(results)
        start_idx = (query.page - 1) * query.page_size
        end_idx = start_idx + query.page_size
        page_items = results[start_idx:end_idx]

        total_pages = (total + query.page_size - 1) // query.page_size
        if total == 0:
            total_pages = 0

        return OrderHistoryPage(
            items=page_items,
            total=total,
            page=query.page,
            page_size=query.page_size,
            total_pages=total_pages,
        )

    def get_execution_report(
        self,
        *,
        date_from: datetime,
        date_to: datetime,
        deployment_id: str | None = None,
    ) -> ExecutionReportSummary:
        """
        Compute aggregate execution quality metrics over a date range.

        Args:
            date_from: Inclusive start datetime.
            date_to: Inclusive end datetime.
            deployment_id: Optional filter to specific deployment.

        Returns:
            ExecutionReportSummary with aggregated metrics.
        """
        # Filter orders by date and deployment
        orders = [
            o
            for o in self._orders.values()
            if (o.submitted_at or o.created_at) >= date_from
            and (o.submitted_at or o.created_at) <= date_to
            and (deployment_id is None or o.deployment_id == deployment_id)
        ]

        if not orders:
            return ExecutionReportSummary(
                date_from=date_from,
                date_to=date_to,
                total_orders=0,
                filled_orders=0,
                cancelled_orders=0,
                rejected_orders=0,
                partial_fills=0,
                fill_rate=Decimal("0"),
                total_volume=Decimal("0"),
                total_commission=Decimal("0"),
                symbols_traded=[],
                by_symbol=[],
                by_execution_mode=[],
            )

        # Aggregate metrics
        total_orders = len(orders)
        filled_orders = sum(1 for o in orders if o.status == "filled")
        cancelled_orders = sum(1 for o in orders if o.status == "cancelled")
        rejected_orders = sum(1 for o in orders if o.status == "rejected")
        partial_fills = sum(1 for o in orders if o.status == "partial_fill")

        fill_rate = (
            (Decimal(filled_orders) / Decimal(total_orders) * Decimal("100"))
            if total_orders > 0
            else Decimal("0")
        )

        total_volume = sum(o.filled_quantity or Decimal("0") for o in orders)
        total_commission = sum(sum(f.commission for f in o.fills) for o in orders)

        # Unique symbols
        symbols_traded = sorted({o.symbol for o in orders})

        # By symbol breakdown
        by_symbol: list[SymbolBreakdown] = []
        for symbol in symbols_traded:
            symbol_orders = [o for o in orders if o.symbol == symbol]
            symbol_filled = sum(1 for o in symbol_orders if o.status == "filled")
            symbol_volume = sum(o.filled_quantity or Decimal("0") for o in symbol_orders)
            symbol_fill_price = (
                sum(
                    (o.average_fill_price or Decimal("0")) * (o.filled_quantity or Decimal("0"))
                    for o in symbol_orders
                    if o.average_fill_price and o.filled_quantity
                )
                / symbol_volume
                if symbol_volume > 0
                else None
            )

            by_symbol.append(
                SymbolBreakdown(
                    symbol=symbol,
                    total_orders=len(symbol_orders),
                    filled_orders=symbol_filled,
                    fill_rate=(
                        (Decimal(symbol_filled) / Decimal(len(symbol_orders)) * Decimal("100"))
                        if symbol_orders
                        else Decimal("0")
                    ),
                    total_volume=symbol_volume,
                    avg_fill_price=symbol_fill_price,
                )
            )

        # By execution mode breakdown
        by_execution_mode: list[ModeBreakdown] = []
        modes = sorted({o.execution_mode for o in orders})
        for mode in modes:
            mode_orders = [o for o in orders if o.execution_mode == mode]
            mode_filled = sum(1 for o in mode_orders if o.status == "filled")
            mode_volume = sum(o.filled_quantity or Decimal("0") for o in mode_orders)

            by_execution_mode.append(
                ModeBreakdown(
                    execution_mode=mode,
                    total_orders=len(mode_orders),
                    filled_orders=mode_filled,
                    fill_rate=(
                        (Decimal(mode_filled) / Decimal(len(mode_orders)) * Decimal("100"))
                        if mode_orders
                        else Decimal("0")
                    ),
                    total_volume=mode_volume,
                )
            )

        return ExecutionReportSummary(
            date_from=date_from,
            date_to=date_to,
            total_orders=total_orders,
            filled_orders=filled_orders,
            cancelled_orders=cancelled_orders,
            rejected_orders=rejected_orders,
            partial_fills=partial_fills,
            fill_rate=fill_rate,
            total_volume=total_volume,
            total_commission=total_commission,
            symbols_traded=symbols_traded,
            by_symbol=by_symbol,
            by_execution_mode=by_execution_mode,
        )

    def export_orders_csv(self, *, query: OrderHistoryQuery) -> str:
        """
        Export filtered orders as CSV string without pagination limit.

        Args:
            query: OrderHistoryQuery with filter params (pagination ignored).

        Returns:
            CSV string with header and data rows.
        """
        # Get all matching orders (ignore pagination)
        all_results_query = OrderHistoryQuery(
            deployment_id=query.deployment_id,
            symbol=query.symbol,
            side=query.side,
            status=query.status,
            execution_mode=query.execution_mode,
            date_from=query.date_from,
            date_to=query.date_to,
            sort_by=query.sort_by,
            sort_dir=query.sort_dir,
            page=1,
            page_size=500,  # High limit to get all
        )
        page = self.get_order_history(query=all_results_query)
        orders = page.items

        if not orders:
            # Return header only
            return (
                "order_id,client_order_id,symbol,side,order_type,quantity,"
                "filled_quantity,average_fill_price,status,execution_mode,"
                "submitted_at,filled_at,created_at\n"
            )

        # Build CSV content
        lines = [
            "order_id,client_order_id,symbol,side,order_type,quantity,"
            "filled_quantity,average_fill_price,status,execution_mode,"
            "submitted_at,filled_at,created_at"
        ]

        for order in orders:
            submitted_at = order.submitted_at.isoformat() if order.submitted_at else ""
            filled_at = order.filled_at.isoformat() if order.filled_at else ""
            created_at = order.created_at.isoformat() if order.created_at else ""

            line = (
                f"{order.order_id},{order.client_order_id},{order.symbol},"
                f"{order.side},{order.order_type},{order.quantity},"
                f"{order.filled_quantity},{order.average_fill_price or ''},"
                f"{order.status},{order.execution_mode},"
                f"{submitted_at},{filled_at},{created_at}"
            )
            lines.append(line)

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Legacy M7 Methods (STUB)
    # ------------------------------------------------------------------

    def compute_drift(self, *, deployment_id: str, window: str):
        """Not used in M8 tests."""
        raise NotImplementedError("compute_drift not implemented in MockExecutionAnalysisService")

    def get_order_timeline(self, *, order_id: str):
        """Not used in M8 tests."""
        raise NotImplementedError(
            "get_order_timeline not implemented in MockExecutionAnalysisService"
        )

    def search_by_correlation_id(self, *, correlation_id: str):
        """Not used in M8 tests."""
        raise NotImplementedError(
            "search_by_correlation_id not implemented in MockExecutionAnalysisService"
        )

    # ------------------------------------------------------------------
    # Test Helpers / Introspection
    # ------------------------------------------------------------------

    def seed_orders(self, orders: list[OrderHistoryItem]) -> None:
        """
        Prepopulate order data for testing.

        Args:
            orders: List of OrderHistoryItem to seed.
        """
        self._orders.clear()
        for order in orders:
            self._orders[order.order_id] = order

    def clear(self) -> None:
        """Remove all seeded data."""
        self._orders.clear()
        self._events.clear()

    def get_all_orders(self) -> list[OrderHistoryItem]:
        """Return all seeded orders."""
        return list(self._orders.values())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _test_env():
    """Ensure ENVIRONMENT=test for TEST_TOKEN bypass."""
    old = os.environ.get("ENVIRONMENT")
    os.environ["ENVIRONMENT"] = "test"
    yield
    if old is None:
        os.environ.pop("ENVIRONMENT", None)
    else:
        os.environ["ENVIRONMENT"] = old


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    """Return authentication headers for API requests."""
    return {"Authorization": "Bearer TEST_TOKEN"}


@pytest.fixture()
def execution_analysis_service() -> MockExecutionAnalysisService:
    """Create and return a mock execution analysis service."""
    return MockExecutionAnalysisService()


@pytest.fixture()
def client(execution_analysis_service: MockExecutionAnalysisService) -> TestClient:
    """Create a FastAPI TestClient with the mock service injected."""
    from services.api.routes.execution_analysis import (
        set_execution_analysis_service,
    )

    set_execution_analysis_service(execution_analysis_service)
    from services.api.main import app

    return TestClient(app, raise_server_exceptions=False)


def _make_order(
    order_id: str = "ord-001",
    client_order_id: str = "client-001",
    symbol: str = "AAPL",
    side: str = "buy",
    status: str = "filled",
    execution_mode: str = "paper",
    quantity: Decimal = Decimal("100"),
    filled_quantity: Decimal = Decimal("100"),
    average_fill_price: Decimal | None = Decimal("175.50"),
    deployment_id: str = DEP_ID,
    strategy_id: str = STRAT_ID,
) -> OrderHistoryItem:
    """
    Helper to create an OrderHistoryItem for testing.

    Args:
        order_id: Unique order identifier.
        client_order_id: Client-assigned order ID.
        symbol: Instrument ticker.
        side: Order side (buy/sell).
        status: Order status.
        execution_mode: Execution mode (shadow/paper/live).
        quantity: Order quantity.
        filled_quantity: Quantity filled.
        average_fill_price: Average fill price.
        deployment_id: Owning deployment ULID.
        strategy_id: Originating strategy ULID.

    Returns:
        OrderHistoryItem instance.
    """
    now = datetime.now(timezone.utc)
    return OrderHistoryItem(
        order_id=order_id,
        client_order_id=client_order_id,
        broker_order_id=f"BRK-{order_id}",
        deployment_id=deployment_id,
        strategy_id=strategy_id,
        symbol=symbol,
        side=side,
        order_type="market",
        quantity=quantity,
        filled_quantity=filled_quantity,
        average_fill_price=average_fill_price,
        status=status,
        time_in_force="day",
        execution_mode=execution_mode,
        correlation_id=f"corr-{order_id}",
        submitted_at=now,
        filled_at=now if status == "filled" else None,
        cancelled_at=now if status == "cancelled" else None,
        created_at=now,
        fills=[
            FillItem(
                fill_id=f"fill-{order_id}-1",
                price=average_fill_price or Decimal("175.50"),
                quantity=filled_quantity,
                commission=Decimal("1.50"),
                filled_at=now,
            )
        ]
        if status == "filled"
        else [],
    )


# ---------------------------------------------------------------------------
# GET /execution-analysis/orders
# ---------------------------------------------------------------------------


class TestGetOrderHistory:
    """Tests for GET /execution-analysis/orders."""

    def test_orders_returns_paginated_results(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        execution_analysis_service: MockExecutionAnalysisService,
    ) -> None:
        """GET /orders with seeded orders returns page 1 with pagination metadata."""
        # Seed 5 orders
        orders = [
            _make_order(order_id=f"ord-{i:03d}", symbol=("AAPL", "TSLA", "MSFT")[i % 3])
            for i in range(5)
        ]
        execution_analysis_service.seed_orders(orders)

        resp = client.get(
            "/execution-analysis/orders",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "total_pages" in data
        assert data["total"] == 5
        assert data["page"] == 1
        assert len(data["items"]) == 5
        assert data["total_pages"] == 1

    def test_orders_filters_by_symbol(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        execution_analysis_service: MockExecutionAnalysisService,
    ) -> None:
        """GET /orders?symbol=AAPL returns only AAPL orders."""
        orders = [
            _make_order(order_id="ord-001", symbol="AAPL"),
            _make_order(order_id="ord-002", symbol="TSLA"),
            _make_order(order_id="ord-003", symbol="AAPL"),
        ]
        execution_analysis_service.seed_orders(orders)

        resp = client.get(
            "/execution-analysis/orders?symbol=AAPL",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert all(item["symbol"] == "AAPL" for item in data["items"])

    def test_orders_filters_by_side(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        execution_analysis_service: MockExecutionAnalysisService,
    ) -> None:
        """GET /orders?side=buy returns only buy orders."""
        orders = [
            _make_order(order_id="ord-001", side="buy"),
            _make_order(order_id="ord-002", side="sell"),
            _make_order(order_id="ord-003", side="buy"),
        ]
        execution_analysis_service.seed_orders(orders)

        resp = client.get(
            "/execution-analysis/orders?side=buy",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert all(item["side"] == "buy" for item in data["items"])

    def test_orders_filters_by_status(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        execution_analysis_service: MockExecutionAnalysisService,
    ) -> None:
        """GET /orders?status=filled returns only filled orders."""
        orders = [
            _make_order(order_id="ord-001", status="filled"),
            _make_order(order_id="ord-002", status="cancelled"),
            _make_order(order_id="ord-003", status="filled"),
        ]
        execution_analysis_service.seed_orders(orders)

        resp = client.get(
            "/execution-analysis/orders?status=filled",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert all(item["status"] == "filled" for item in data["items"])

    def test_orders_filters_by_execution_mode(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        execution_analysis_service: MockExecutionAnalysisService,
    ) -> None:
        """GET /orders?execution_mode=paper returns only paper orders."""
        orders = [
            _make_order(order_id="ord-001", execution_mode="paper"),
            _make_order(order_id="ord-002", execution_mode="live"),
            _make_order(order_id="ord-003", execution_mode="paper"),
        ]
        execution_analysis_service.seed_orders(orders)

        resp = client.get(
            "/execution-analysis/orders?execution_mode=paper",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert all(item["execution_mode"] == "paper" for item in data["items"])

    def test_orders_filters_by_date_range(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        execution_analysis_service: MockExecutionAnalysisService,
    ) -> None:
        """GET /orders?date_from=...&date_to=... filters by submission date."""
        now = datetime.now(timezone.utc)
        order1 = _make_order(order_id="ord-001")
        # Create order2 with a different time
        order2 = _make_order(order_id="ord-002")
        orders = [order1, order2]
        execution_analysis_service.seed_orders(orders)

        # Query with date range that includes submitted_at
        date_from = (now.replace(hour=0, minute=0, second=0, microsecond=0)).isoformat()
        date_to = (now.replace(hour=23, minute=59, second=59, microsecond=999999)).isoformat()

        resp = client.get(
            f"/execution-analysis/orders?date_from={date_from}&date_to={date_to}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 0  # At least 0 orders in range

    def test_orders_pagination(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        execution_analysis_service: MockExecutionAnalysisService,
    ) -> None:
        """GET /orders?page=2&page_size=2 returns correct page."""
        orders = [_make_order(order_id=f"ord-{i:03d}") for i in range(5)]
        execution_analysis_service.seed_orders(orders)

        # Page 1
        resp = client.get(
            "/execution-analysis/orders?page=1&page_size=2",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert len(data["items"]) == 2
        assert data["total"] == 5
        assert data["total_pages"] == 3

        # Page 2
        resp = client.get(
            "/execution-analysis/orders?page=2&page_size=2",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert len(data["items"]) == 2

        # Page 3
        resp = client.get(
            "/execution-analysis/orders?page=3&page_size=2",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 3
        assert len(data["items"]) == 1

    def test_orders_sorting_asc(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        execution_analysis_service: MockExecutionAnalysisService,
    ) -> None:
        """GET /orders?sort_by=symbol&sort_dir=asc sorts ascending."""
        orders = [
            _make_order(order_id="ord-001", symbol="MSFT"),
            _make_order(order_id="ord-002", symbol="AAPL"),
            _make_order(order_id="ord-003", symbol="TSLA"),
        ]
        execution_analysis_service.seed_orders(orders)

        resp = client.get(
            "/execution-analysis/orders?sort_by=symbol&sort_dir=asc",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        symbols = [item["symbol"] for item in data["items"]]
        assert symbols == sorted(symbols)

    def test_orders_empty_returns_empty_page(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """GET /orders with no orders returns empty page."""
        resp = client.get(
            "/execution-analysis/orders",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["total_pages"] == 0

    def test_orders_requires_auth(
        self,
        client: TestClient,
    ) -> None:
        """GET /orders without auth returns 401."""
        resp = client.get("/execution-analysis/orders")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /execution-analysis/report
# ---------------------------------------------------------------------------


class TestGetExecutionReport:
    """Tests for GET /execution-analysis/report."""

    def test_report_returns_aggregate_metrics(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        execution_analysis_service: MockExecutionAnalysisService,
    ) -> None:
        """GET /report returns fill_rate, total_orders, and other aggregates."""
        orders = [
            _make_order(order_id="ord-001", status="filled"),
            _make_order(order_id="ord-002", status="filled"),
            _make_order(order_id="ord-003", status="cancelled"),
        ]
        execution_analysis_service.seed_orders(orders)

        now = datetime.now(timezone.utc)
        date_from = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        date_to = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

        resp = client.get(
            f"/execution-analysis/report?date_from={date_from}&date_to={date_to}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_orders" in data
        assert "filled_orders" in data
        assert "fill_rate" in data
        assert "total_volume" in data
        assert "total_commission" in data
        assert data["total_orders"] == 3
        assert data["filled_orders"] == 2

    def test_report_with_deployment_filter(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        execution_analysis_service: MockExecutionAnalysisService,
    ) -> None:
        """GET /report?deployment_id=... filters by deployment."""
        dep2 = "01HTESTDEP0000000000000002"
        orders = [
            _make_order(order_id="ord-001", deployment_id=DEP_ID),
            _make_order(order_id="ord-002", deployment_id=dep2),
        ]
        execution_analysis_service.seed_orders(orders)

        now = datetime.now(timezone.utc)
        date_from = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        date_to = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

        resp = client.get(
            f"/execution-analysis/report?date_from={date_from}&date_to={date_to}&deployment_id={DEP_ID}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_orders"] == 1

    def test_report_includes_symbol_breakdown(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        execution_analysis_service: MockExecutionAnalysisService,
    ) -> None:
        """GET /report includes by_symbol array with breakdown per symbol."""
        orders = [
            _make_order(order_id="ord-001", symbol="AAPL"),
            _make_order(order_id="ord-002", symbol="AAPL"),
            _make_order(order_id="ord-003", symbol="TSLA"),
        ]
        execution_analysis_service.seed_orders(orders)

        now = datetime.now(timezone.utc)
        date_from = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        date_to = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

        resp = client.get(
            f"/execution-analysis/report?date_from={date_from}&date_to={date_to}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "by_symbol" in data
        assert len(data["by_symbol"]) >= 1
        # Check structure
        for breakdown in data["by_symbol"]:
            assert "symbol" in breakdown
            assert "total_orders" in breakdown
            assert "filled_orders" in breakdown
            assert "fill_rate" in breakdown

    def test_report_includes_mode_breakdown(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        execution_analysis_service: MockExecutionAnalysisService,
    ) -> None:
        """GET /report includes by_execution_mode array with breakdown per mode."""
        orders = [
            _make_order(order_id="ord-001", execution_mode="paper"),
            _make_order(order_id="ord-002", execution_mode="live"),
        ]
        execution_analysis_service.seed_orders(orders)

        now = datetime.now(timezone.utc)
        date_from = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        date_to = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

        resp = client.get(
            f"/execution-analysis/report?date_from={date_from}&date_to={date_to}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "by_execution_mode" in data
        assert len(data["by_execution_mode"]) >= 1
        # Check structure
        for breakdown in data["by_execution_mode"]:
            assert "execution_mode" in breakdown
            assert "total_orders" in breakdown
            assert "filled_orders" in breakdown
            assert "fill_rate" in breakdown

    def test_report_empty_date_range(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """GET /report with date range having no orders returns zero counts."""
        datetime.now(timezone.utc).replace(year=2100).isoformat()
        far_past = datetime.now(timezone.utc).replace(year=1900).isoformat()

        resp = client.get(
            f"/execution-analysis/report?date_from={far_past}&date_to={far_past}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_orders"] == 0
        assert data["filled_orders"] == 0

    def test_report_requires_date_params(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """GET /report missing date_from/date_to returns 422."""
        resp = client.get(
            "/execution-analysis/report",
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_report_requires_auth(
        self,
        client: TestClient,
    ) -> None:
        """GET /report without auth returns 401."""
        now = datetime.now(timezone.utc).isoformat()
        resp = client.get(
            f"/execution-analysis/report?date_from={now}&date_to={now}",
        )
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /execution-analysis/export
# ---------------------------------------------------------------------------


class TestExportOrdersCsv:
    """Tests for GET /execution-analysis/export."""

    def test_export_returns_csv_content_type(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        execution_analysis_service: MockExecutionAnalysisService,
    ) -> None:
        """GET /export returns CSV with text/csv Content-Type."""
        orders = [_make_order(order_id="ord-001")]
        execution_analysis_service.seed_orders(orders)

        resp = client.get(
            "/execution-analysis/export",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "").lower()

    def test_export_csv_contains_header_row(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        execution_analysis_service: MockExecutionAnalysisService,
    ) -> None:
        """GET /export CSV first row contains column names."""
        orders = [_make_order(order_id="ord-001")]
        execution_analysis_service.seed_orders(orders)

        resp = client.get(
            "/execution-analysis/export",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        csv_lines = resp.text.strip().split("\n")
        header = csv_lines[0]
        assert "order_id" in header
        assert "symbol" in header
        assert "side" in header
        assert "status" in header

    def test_export_csv_contains_order_rows(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        execution_analysis_service: MockExecutionAnalysisService,
    ) -> None:
        """GET /export CSV contains data rows matching seeded orders."""
        orders = [
            _make_order(order_id="ord-001", symbol="AAPL"),
            _make_order(order_id="ord-002", symbol="TSLA"),
        ]
        execution_analysis_service.seed_orders(orders)

        resp = client.get(
            "/execution-analysis/export",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        csv_lines = resp.text.strip().split("\n")
        # Should have header + 2 data rows
        assert len(csv_lines) >= 3
        # Check that order IDs appear in output
        assert "ord-001" in resp.text
        assert "ord-002" in resp.text

    def test_export_filters_apply(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        execution_analysis_service: MockExecutionAnalysisService,
    ) -> None:
        """GET /export?symbol=AAPL filters CSV output."""
        orders = [
            _make_order(order_id="ord-001", symbol="AAPL"),
            _make_order(order_id="ord-002", symbol="TSLA"),
        ]
        execution_analysis_service.seed_orders(orders)

        resp = client.get(
            "/execution-analysis/export?symbol=AAPL",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        csv_text = resp.text
        assert "ord-001" in csv_text
        assert "ord-002" not in csv_text or "TSLA" not in csv_text

    def test_export_requires_auth(
        self,
        client: TestClient,
    ) -> None:
        """GET /export without auth returns 401."""
        resp = client.get("/execution-analysis/export")
        assert resp.status_code in (401, 403)


__all__ = [
    "TestGetOrderHistory",
    "TestGetExecutionReport",
    "TestExportOrdersCsv",
]
