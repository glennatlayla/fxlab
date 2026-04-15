"""
Unit tests for compliance report API routes and service.

Covers M11 (Trade Execution Reports for Regulatory Compliance):
- GET /compliance/execution-report → detailed order records for regulatory review
- GET /compliance/best-execution → price improvement and slippage analysis
- GET /compliance/venue-routing → per-venue execution statistics
- GET /compliance/monthly-summary → monthly aggregate summary
- GET /compliance/execution-report/csv → CSV export of execution report

Dependencies:
- libs.contracts.compliance_report: ComplianceOrderRecord, ExecutionComplianceReport, etc.
- libs.contracts.interfaces.compliance_report_service_interface: ComplianceReportServiceInterface
- services.api.routes.compliance: set_compliance_report_service, router

TDD Approach:
These tests are written in RED (failing) state and will remain red until the
routes and service methods are implemented. They define the expected behaviour
for M11 endpoints.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from libs.contracts.compliance_report import (
    BestExecutionRecord,
    BestExecutionReport,
    ComplianceOrderRecord,
    ExecutionComplianceReport,
    MonthlySummary,
    VenueRoutingRecord,
    VenueRoutingReport,
)
from services.api.services.interfaces.compliance_report_service_interface import (
    ComplianceReportServiceInterface,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEP_ID = "01HTESTDEP0000000000000001"
STRAT_ID = "01HTESTSTRT000000000000001"


# ---------------------------------------------------------------------------
# Mock ComplianceReportService for route-level testing
# ---------------------------------------------------------------------------


class MockComplianceReportService(ComplianceReportServiceInterface):
    """
    Mock service for route-level testing of M11 endpoints.

    Responsibilities:
    - Provide seeded order data for testing compliance reports.
    - Return compliance analysis for testing aggregation endpoints.
    - Implement all ComplianceReportServiceInterface methods.

    Does NOT:
    - Persist data (in-memory only).
    - Contain business logic.

    Example:
        service = MockComplianceReportService()
        service.seed_orders(...)
        report = service.get_execution_report(...)
    """

    def __init__(self) -> None:
        """Initialize the mock service with empty state."""
        self._orders: dict[str, dict] = {}

    def get_execution_report(
        self,
        *,
        date_from: datetime,
        date_to: datetime,
        deployment_id: str | None = None,
    ) -> ExecutionComplianceReport:
        """
        Generate execution compliance report for all orders in a date range.

        Args:
            date_from: Inclusive start datetime for the reporting period.
            date_to: Inclusive end datetime for the reporting period.
            deployment_id: Optional filter to a specific deployment ULID.

        Returns:
            ExecutionComplianceReport containing summary statistics and records.
        """
        # Filter orders by date and deployment
        orders = [
            o
            for o in self._orders.values()
            if (o.get("submitted_at") or o.get("created_at")) >= date_from.isoformat()
            and (o.get("submitted_at") or o.get("created_at")) <= date_to.isoformat()
            and (deployment_id is None or o.get("deployment_id") == deployment_id)
        ]

        # Build ComplianceOrderRecord for each order
        records = []
        for o in orders:
            record = ComplianceOrderRecord(
                order_id=o["id"],
                client_order_id=o["client_order_id"],
                broker_order_id=o.get("broker_order_id"),
                symbol=o["symbol"],
                side=o["side"],
                order_type=o["order_type"],
                quantity=Decimal(o["quantity"]),
                filled_quantity=Decimal(o.get("filled_quantity") or "0"),
                average_fill_price=(
                    Decimal(o["average_fill_price"]) if o.get("average_fill_price") else None
                ),
                limit_price=Decimal(o["limit_price"]) if o.get("limit_price") else None,
                status=o["status"],
                execution_mode=o["execution_mode"],
                venue=o.get("venue", ""),
                submitted_at=(
                    datetime.fromisoformat(o["submitted_at"]) if o.get("submitted_at") else None
                ),
                filled_at=(datetime.fromisoformat(o["filled_at"]) if o.get("filled_at") else None),
                cancelled_at=(
                    datetime.fromisoformat(o["cancelled_at"]) if o.get("cancelled_at") else None
                ),
                commission=Decimal(o.get("commission") or "0"),
                correlation_id=o["correlation_id"],
            )
            records.append(record)

        # Compute totals
        total_orders = len(orders)
        total_filled = sum(1 for o in orders if o["status"] == "filled")
        total_cancelled = sum(1 for o in orders if o["status"] == "cancelled")
        total_rejected = sum(1 for o in orders if o["status"] == "rejected")
        total_volume = sum(Decimal(o.get("filled_quantity") or "0") for o in orders)
        total_commission = sum(Decimal(o.get("commission") or "0") for o in orders)

        report_id = f"comp-{date_from.strftime('%Y%m%d')}"

        return ExecutionComplianceReport(
            report_id=report_id,
            date_from=date_from,
            date_to=date_to,
            generated_at=datetime.now(timezone.utc),
            total_orders=total_orders,
            total_filled=total_filled,
            total_cancelled=total_cancelled,
            total_rejected=total_rejected,
            total_volume=total_volume,
            total_commission=total_commission,
            orders=records,
        )

    def get_best_execution(
        self,
        *,
        date_from: datetime,
        date_to: datetime,
        deployment_id: str | None = None,
    ) -> BestExecutionReport:
        """
        Generate best execution analysis report for filled orders.

        Args:
            date_from: Inclusive start datetime for the reporting period.
            date_to: Inclusive end datetime for the reporting period.
            deployment_id: Optional filter to a specific deployment ULID.

        Returns:
            BestExecutionReport with aggregate metrics and per-order records.
        """
        # Filter to filled orders in date range
        orders = [
            o
            for o in self._orders.values()
            if o["status"] == "filled"
            and (o.get("submitted_at") or o.get("created_at")) >= date_from.isoformat()
            and (o.get("submitted_at") or o.get("created_at")) <= date_to.isoformat()
            and (deployment_id is None or o.get("deployment_id") == deployment_id)
        ]

        # Build BestExecutionRecord for each filled order
        records = []
        latencies = []

        for o in orders:
            fill_price = Decimal(o.get("average_fill_price") or "0")
            limit_price = Decimal(o.get("limit_price") or "0")

            # Calculate slippage in basis points (simplified)
            slippage_bps = Decimal("0")
            if limit_price > 0:
                if o["side"] == "buy":
                    # For buy: positive slippage means we paid more than limit
                    slippage_bps = (fill_price - limit_price) / limit_price * Decimal("10000")
                else:
                    # For sell: positive slippage means we got less than limit
                    slippage_bps = (limit_price - fill_price) / limit_price * Decimal("10000")

            # Calculate fill latency in milliseconds
            latency_ms = None
            if o.get("submitted_at") and o.get("filled_at"):
                submitted = datetime.fromisoformat(o["submitted_at"])
                filled = datetime.fromisoformat(o["filled_at"])
                latency_ms = int((filled - submitted).total_seconds() * 1000)
                latencies.append(latency_ms)

            record = BestExecutionRecord(
                order_id=o["id"],
                symbol=o["symbol"],
                side=o["side"],
                fill_price=fill_price,
                nbbo_bid=None,  # Mock data doesn't include NBBO
                nbbo_ask=None,
                nbbo_midpoint=None,
                price_improvement=None,
                slippage_bps=slippage_bps,
                fill_latency_ms=latency_ms,
                venue=o.get("venue", ""),
                filled_at=(datetime.fromisoformat(o["filled_at"]) if o.get("filled_at") else None),
            )
            records.append(record)

        # Compute aggregate metrics
        avg_slippage_bps = (
            sum(Decimal(r.slippage_bps or "0") for r in records) / len(records) if records else None
        )
        avg_latency_ms = sum(latencies) // len(latencies) if latencies else None
        pct_with_improvement = Decimal("0")  # Simplified: no price improvement in mock

        report_id = f"best-exec-{date_from.strftime('%Y%m%d')}"

        return BestExecutionReport(
            report_id=report_id,
            date_from=date_from,
            date_to=date_to,
            generated_at=datetime.now(timezone.utc),
            total_analyzed=len(records),
            avg_price_improvement_bps=None,
            avg_slippage_bps=avg_slippage_bps,
            avg_fill_latency_ms=avg_latency_ms,
            pct_with_price_improvement=pct_with_improvement,
            records=records,
        )

    def get_venue_routing(
        self,
        *,
        date_from: datetime,
        date_to: datetime,
        deployment_id: str | None = None,
    ) -> VenueRoutingReport:
        """
        Generate venue routing report with per-venue execution statistics.

        Args:
            date_from: Inclusive start datetime for the reporting period.
            date_to: Inclusive end datetime for the reporting period.
            deployment_id: Optional filter to a specific deployment ULID.

        Returns:
            VenueRoutingReport with per-venue statistics.
        """
        # Filter orders by date and deployment
        orders = [
            o
            for o in self._orders.values()
            if (o.get("submitted_at") or o.get("created_at")) >= date_from.isoformat()
            and (o.get("submitted_at") or o.get("created_at")) <= date_to.isoformat()
            and (deployment_id is None or o.get("deployment_id") == deployment_id)
        ]

        # Group by venue
        venues_map: dict[str, list] = {}
        for o in orders:
            venue = o.get("venue", "UNKNOWN")
            if venue not in venues_map:
                venues_map[venue] = []
            venues_map[venue].append(o)

        # Build VenueRoutingRecord for each venue
        records = []
        for venue, venue_orders in venues_map.items():
            total = len(venue_orders)
            filled_count = sum(1 for o in venue_orders if o["status"] == "filled")
            fill_rate = (
                (Decimal(filled_count) / Decimal(total) * Decimal("100"))
                if total > 0
                else Decimal("0")
            )
            total_volume = sum(Decimal(o.get("filled_quantity") or "0") for o in venue_orders)

            # Calculate average fill latency for this venue
            latencies = []
            for o in venue_orders:
                if o["status"] == "filled" and o.get("submitted_at") and o.get("filled_at"):
                    submitted = datetime.fromisoformat(o["submitted_at"])
                    filled_dt = datetime.fromisoformat(o["filled_at"])
                    latency_ms = int((filled_dt - submitted).total_seconds() * 1000)
                    latencies.append(latency_ms)

            avg_latency = sum(latencies) // len(latencies) if latencies else None

            record = VenueRoutingRecord(
                venue=venue,
                total_orders=total,
                filled_orders=filled_count,
                fill_rate=fill_rate,
                total_volume=total_volume,
                avg_fill_latency_ms=avg_latency,
            )
            records.append(record)

        report_id = f"routing-{date_from.strftime('%Y%m%d')}"

        return VenueRoutingReport(
            report_id=report_id,
            date_from=date_from,
            date_to=date_to,
            generated_at=datetime.now(timezone.utc),
            venues=records,
        )

    def get_monthly_summary(
        self,
        *,
        month: str,
        deployment_id: str | None = None,
    ) -> MonthlySummary:
        """
        Generate monthly aggregate compliance summary.

        Args:
            month: Reporting month in "YYYY-MM" format.
            deployment_id: Optional filter to a specific deployment ULID.

        Returns:
            MonthlySummary with key metrics.
        """
        # Parse month string to dates
        year, month_num = month.split("-")
        date_from = datetime(int(year), int(month_num), 1, tzinfo=timezone.utc)
        # Last day of month
        next_month = date_from.replace(day=28) + timedelta(days=4)
        date_to = next_month - timedelta(days=next_month.day)
        date_to = date_to.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Filter orders for the month
        orders = [
            o
            for o in self._orders.values()
            if (o.get("submitted_at") or o.get("created_at")) >= date_from.isoformat()
            and (o.get("submitted_at") or o.get("created_at")) <= date_to.isoformat()
            and (deployment_id is None or o.get("deployment_id") == deployment_id)
        ]

        # Compute metrics
        total_orders = len(orders)
        total_filled = sum(1 for o in orders if o["status"] == "filled")
        total_cancelled = sum(1 for o in orders if o["status"] == "cancelled")
        total_rejected = sum(1 for o in orders if o["status"] == "rejected")
        total_volume = sum(Decimal(o.get("filled_quantity") or "0") for o in orders)
        total_commission = sum(Decimal(o.get("commission") or "0") for o in orders)

        fill_rate = (
            (Decimal(total_filled) / Decimal(total_orders) * Decimal("100"))
            if total_orders > 0
            else Decimal("0")
        )
        error_rate = (
            (Decimal(total_rejected) / Decimal(total_orders) * Decimal("100"))
            if total_orders > 0
            else Decimal("0")
        )

        unique_symbols = len({o["symbol"] for o in orders})
        unique_venues = len({o.get("venue", "UNKNOWN") for o in orders})

        # Calculate average fill latency
        latencies = []
        for o in orders:
            if o["status"] == "filled" and o.get("submitted_at") and o.get("filled_at"):
                submitted = datetime.fromisoformat(o["submitted_at"])
                filled = datetime.fromisoformat(o["filled_at"])
                latency_ms = int((filled - submitted).total_seconds() * 1000)
                latencies.append(latency_ms)

        avg_latency = sum(latencies) // len(latencies) if latencies else None

        report_id = f"monthly-{month}"

        return MonthlySummary(
            report_id=report_id,
            month=month,
            generated_at=datetime.now(timezone.utc),
            total_orders=total_orders,
            total_filled=total_filled,
            total_cancelled=total_cancelled,
            total_rejected=total_rejected,
            total_volume=total_volume,
            total_commission=total_commission,
            fill_rate=fill_rate,
            error_rate=error_rate,
            unique_symbols=unique_symbols,
            unique_venues=unique_venues,
            avg_fill_latency_ms=avg_latency,
        )

    def export_csv(
        self,
        *,
        report: ExecutionComplianceReport,
    ) -> str:
        """
        Export execution compliance report as CSV string.

        Args:
            report: ExecutionComplianceReport to export.

        Returns:
            CSV string with header row and one row per order.
        """
        if not report.orders:
            # Return header only
            return (
                "order_id,client_order_id,broker_order_id,symbol,side,order_type,quantity,"
                "filled_quantity,average_fill_price,limit_price,status,execution_mode,venue,"
                "submitted_at,filled_at,cancelled_at,commission,correlation_id\n"
            )

        # Build CSV with header and data rows
        lines = [
            "order_id,client_order_id,broker_order_id,symbol,side,order_type,quantity,"
            "filled_quantity,average_fill_price,limit_price,status,execution_mode,venue,"
            "submitted_at,filled_at,cancelled_at,commission,correlation_id"
        ]

        for order in report.orders:
            submitted_at = order.submitted_at.isoformat() if order.submitted_at else ""
            filled_at = order.filled_at.isoformat() if order.filled_at else ""
            cancelled_at = order.cancelled_at.isoformat() if order.cancelled_at else ""

            line = (
                f"{order.order_id},{order.client_order_id},{order.broker_order_id or ''},"
                f"{order.symbol},{order.side},{order.order_type},"
                f"{order.quantity},{order.filled_quantity},"
                f"{order.average_fill_price or ''},{order.limit_price or ''},{order.status},"
                f"{order.execution_mode},{order.venue},"
                f"{submitted_at},{filled_at},{cancelled_at},"
                f"{order.commission},{order.correlation_id}"
            )
            lines.append(line)

        return "\n".join(lines) + "\n"

    # Test helpers / introspection
    def seed_orders(self, orders: list[dict]) -> None:
        """
        Prepopulate order data for testing.

        Args:
            orders: List of order dicts to seed.
        """
        self._orders.clear()
        for order in orders:
            self._orders[order["id"]] = order

    def clear(self) -> None:
        """Remove all seeded data."""
        self._orders.clear()


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
def compliance_service() -> MockComplianceReportService:
    """Create and return a mock compliance report service."""
    return MockComplianceReportService()


@pytest.fixture()
def client(compliance_service: MockComplianceReportService) -> TestClient:
    """Create a FastAPI TestClient with the mock service injected."""
    from services.api.routes.compliance import (
        set_compliance_report_service,
    )

    set_compliance_report_service(compliance_service)
    from services.api.main import app

    return TestClient(app, raise_server_exceptions=False)


def _make_order(
    order_id: str = "ord-001",
    client_order_id: str = "client-001",
    symbol: str = "AAPL",
    side: str = "buy",
    status: str = "filled",
    execution_mode: str = "paper",
    quantity: str = "100",
    filled_quantity: str = "100",
    average_fill_price: str = "175.50",
    limit_price: str | None = None,
    deployment_id: str = DEP_ID,
    strategy_id: str = STRAT_ID,
    venue: str = "NYSE",
    commission: str = "1.50",
    submitted_at: str | None = None,
    filled_at: str | None = None,
    cancelled_at: str | None = None,
) -> dict:
    """
    Helper to create an order dict for testing.

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
        limit_price: Limit price (optional).
        deployment_id: Owning deployment ULID.
        strategy_id: Originating strategy ULID.
        venue: Execution venue.
        commission: Broker commission.
        submitted_at: ISO timestamp (auto-generated if None).
        filled_at: ISO timestamp (auto-generated if status == "filled").
        cancelled_at: ISO timestamp (auto-generated if status == "cancelled").

    Returns:
        Order dict instance.
    """
    now = datetime.now(timezone.utc)
    if submitted_at is None:
        submitted_at = now.isoformat()
    if filled_at is None and status == "filled":
        filled_at = (now + timedelta(seconds=1)).isoformat()
    if cancelled_at is None and status == "cancelled":
        cancelled_at = (now + timedelta(seconds=1)).isoformat()

    return {
        "id": order_id,
        "client_order_id": client_order_id,
        "broker_order_id": f"BRK-{order_id}",
        "deployment_id": deployment_id,
        "strategy_id": strategy_id,
        "symbol": symbol,
        "side": side,
        "order_type": "market",
        "quantity": quantity,
        "filled_quantity": filled_quantity if status == "filled" else "0",
        "average_fill_price": average_fill_price if status == "filled" else None,
        "limit_price": limit_price,
        "status": status,
        "execution_mode": execution_mode,
        "venue": venue,
        "correlation_id": f"corr-{order_id}",
        "submitted_at": submitted_at,
        "filled_at": filled_at,
        "cancelled_at": cancelled_at,
        "created_at": now.isoformat(),
        "commission": commission,
    }


# ---------------------------------------------------------------------------
# GET /compliance/execution-report
# ---------------------------------------------------------------------------


class TestComplianceExecutionReport:
    """Tests for GET /compliance/execution-report."""

    def test_execution_report_returns_orders(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        compliance_service: MockComplianceReportService,
    ) -> None:
        """GET /execution-report returns orders with summary statistics."""
        now = datetime.now(timezone.utc)
        orders = [
            _make_order(order_id="ord-001", symbol="AAPL", venue="NYSE"),
            _make_order(order_id="ord-002", symbol="TSLA", venue="NASDAQ"),
            _make_order(order_id="ord-003", symbol="MSFT", status="cancelled", venue="NYSE"),
        ]
        compliance_service.seed_orders(orders)

        date_from = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        date_to = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

        resp = client.get(
            f"/compliance/execution-report?date_from={date_from}&date_to={date_to}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "report_id" in data
        assert "total_orders" in data
        assert "total_filled" in data
        assert "total_cancelled" in data
        assert "orders" in data
        assert data["total_orders"] == 3
        assert data["total_filled"] == 2
        assert data["total_cancelled"] == 1

    def test_execution_report_requires_date_params(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """GET /execution-report missing dates returns 422."""
        resp = client.get(
            "/compliance/execution-report",
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_execution_report_requires_auth(
        self,
        client: TestClient,
    ) -> None:
        """GET /execution-report without auth returns 401."""
        now = datetime.now(timezone.utc).isoformat()
        resp = client.get(
            f"/compliance/execution-report?date_from={now}&date_to={now}",
        )
        assert resp.status_code in (401, 403)

    def test_execution_report_empty_range(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        compliance_service: MockComplianceReportService,
    ) -> None:
        """GET /execution-report with no matching orders returns empty report."""
        far_past = datetime.now(timezone.utc).replace(year=1900).isoformat()

        resp = client.get(
            f"/compliance/execution-report?date_from={far_past}&date_to={far_past}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_orders"] == 0
        assert data["orders"] == []


# ---------------------------------------------------------------------------
# GET /compliance/best-execution
# ---------------------------------------------------------------------------


class TestComplianceBestExecution:
    """Tests for GET /compliance/best-execution."""

    def test_best_execution_returns_analysis(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        compliance_service: MockComplianceReportService,
    ) -> None:
        """GET /best-execution returns filled orders with price analysis."""
        now = datetime.now(timezone.utc)
        orders = [
            _make_order(
                order_id="ord-001",
                symbol="AAPL",
                status="filled",
                average_fill_price="175.50",
                limit_price="175.00",
            ),
            _make_order(
                order_id="ord-002",
                symbol="TSLA",
                status="filled",
                average_fill_price="245.25",
            ),
        ]
        compliance_service.seed_orders(orders)

        date_from = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        date_to = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

        resp = client.get(
            f"/compliance/best-execution?date_from={date_from}&date_to={date_to}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "report_id" in data
        assert "total_analyzed" in data
        assert "records" in data
        assert data["total_analyzed"] == 2
        assert len(data["records"]) == 2

    def test_best_execution_empty(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        compliance_service: MockComplianceReportService,
    ) -> None:
        """GET /best-execution with no filled orders returns empty report."""
        now = datetime.now(timezone.utc)
        orders = [
            _make_order(order_id="ord-001", status="cancelled"),
            _make_order(order_id="ord-002", status="pending"),
        ]
        compliance_service.seed_orders(orders)

        date_from = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        date_to = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

        resp = client.get(
            f"/compliance/best-execution?date_from={date_from}&date_to={date_to}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_analyzed"] == 0


# ---------------------------------------------------------------------------
# GET /compliance/venue-routing
# ---------------------------------------------------------------------------


class TestComplianceVenueRouting:
    """Tests for GET /compliance/venue-routing."""

    def test_venue_routing_returns_venues(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        compliance_service: MockComplianceReportService,
    ) -> None:
        """GET /venue-routing returns per-venue statistics."""
        now = datetime.now(timezone.utc)
        orders = [
            _make_order(order_id="ord-001", symbol="AAPL", venue="NYSE", status="filled"),
            _make_order(order_id="ord-002", symbol="TSLA", venue="NASDAQ", status="filled"),
            _make_order(order_id="ord-003", symbol="MSFT", venue="NYSE", status="cancelled"),
        ]
        compliance_service.seed_orders(orders)

        date_from = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        date_to = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

        resp = client.get(
            f"/compliance/venue-routing?date_from={date_from}&date_to={date_to}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "report_id" in data
        assert "venues" in data
        venues = data["venues"]
        assert len(venues) == 2  # NYSE and NASDAQ
        venues_names = {v["venue"] for v in venues}
        assert "NYSE" in venues_names
        assert "NASDAQ" in venues_names

    def test_venue_routing_requires_auth(
        self,
        client: TestClient,
    ) -> None:
        """GET /venue-routing without auth returns 401."""
        now = datetime.now(timezone.utc).isoformat()
        resp = client.get(
            f"/compliance/venue-routing?date_from={now}&date_to={now}",
        )
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /compliance/monthly-summary
# ---------------------------------------------------------------------------


class TestComplianceMonthlySummary:
    """Tests for GET /compliance/monthly-summary."""

    def test_monthly_summary_returns_data(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        compliance_service: MockComplianceReportService,
    ) -> None:
        """GET /monthly-summary returns monthly aggregate metrics."""
        now = datetime.now(timezone.utc)
        orders = [
            _make_order(order_id="ord-001", status="filled"),
            _make_order(order_id="ord-002", status="filled"),
            _make_order(order_id="ord-003", status="cancelled"),
        ]
        compliance_service.seed_orders(orders)

        month = now.strftime("%Y-%m")

        resp = client.get(
            f"/compliance/monthly-summary?month={month}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "report_id" in data
        assert "month" in data
        assert "total_orders" in data
        assert "fill_rate" in data
        assert data["month"] == month
        assert data["total_orders"] == 3
        assert data["total_filled"] == 2

    def test_monthly_summary_requires_month(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """GET /monthly-summary missing month returns 422."""
        resp = client.get(
            "/compliance/monthly-summary",
            headers=auth_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /compliance/execution-report/csv
# ---------------------------------------------------------------------------


class TestComplianceExport:
    """Tests for GET /compliance/execution-report/csv."""

    def test_csv_export_returns_csv_content_type(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        compliance_service: MockComplianceReportService,
    ) -> None:
        """GET /execution-report/csv returns CSV with text/csv Content-Type."""
        now = datetime.now(timezone.utc)
        orders = [_make_order(order_id="ord-001")]
        compliance_service.seed_orders(orders)

        date_from = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        date_to = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

        resp = client.get(
            f"/compliance/execution-report/csv?date_from={date_from}&date_to={date_to}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "").lower()

    def test_csv_export_contains_header_and_data(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        compliance_service: MockComplianceReportService,
    ) -> None:
        """GET /execution-report/csv contains header and data rows."""
        now = datetime.now(timezone.utc)
        orders = [
            _make_order(order_id="ord-001", symbol="AAPL"),
            _make_order(order_id="ord-002", symbol="TSLA"),
        ]
        compliance_service.seed_orders(orders)

        date_from = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        date_to = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

        resp = client.get(
            f"/compliance/execution-report/csv?date_from={date_from}&date_to={date_to}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        csv_lines = resp.text.strip().split("\n")
        assert len(csv_lines) >= 3  # Header + 2 data rows
        assert "order_id" in csv_lines[0]
        assert "symbol" in csv_lines[0]


__all__ = [
    "TestComplianceExecutionReport",
    "TestComplianceBestExecution",
    "TestComplianceVenueRouting",
    "TestComplianceMonthlySummary",
    "TestComplianceExport",
]
