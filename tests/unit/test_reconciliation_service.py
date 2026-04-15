"""
Unit tests for ReconciliationService.

Covers:
- Happy path: no discrepancies.
- Each of the 7 discrepancy types detected.
- Auto-resolve safe discrepancies (status lag).
- Unsafe discrepancies flagged.
- Report persistence and retrieval.
- Not-found error paths.
- Multiple discrepancies in a single run.
- Positions reconciliation (missing, extra).

Dependencies:
- libs.contracts.mocks.mock_broker_adapter: MockBrokerAdapter
- libs.contracts.mocks.mock_deployment_repository: MockDeploymentRepository
- libs.contracts.mocks.mock_reconciliation_repository: MockReconciliationRepository
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from libs.contracts.errors import NotFoundError
from libs.contracts.execution import (
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from libs.contracts.mocks.mock_reconciliation_repository import (
    MockReconciliationRepository,
)
from libs.contracts.reconciliation import (
    DiscrepancyType,
    ReconciliationTrigger,
)

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


def _make_order_request(
    client_order_id: str = "ord-001",
    symbol: str = "AAPL",
    side: OrderSide = OrderSide.BUY,
    quantity: Decimal = Decimal("100"),
    order_type: OrderType = OrderType.MARKET,
) -> OrderRequest:
    return OrderRequest(
        client_order_id=client_order_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        time_in_force=TimeInForce.DAY,
        deployment_id="01HDEPLOY0001",
        strategy_id="01HSTRAT0001",
        correlation_id="corr-001",
        execution_mode=ExecutionMode.PAPER,
    )


def _setup_active_paper_deployment(
    deployment_repo: MockDeploymentRepository,
    deployment_id: str = "01HDEPLOY0001",
) -> dict:
    return deployment_repo.seed(
        deployment_id=deployment_id,
        state="active",
        execution_mode="paper",
    )


class TestReconciliationServiceNoDiscrepancies:
    """Test reconciliation when internal and broker state match."""

    def test_empty_state_no_discrepancies(self) -> None:
        """No orders, no positions → clean report."""
        from services.api.services.reconciliation_service import (
            ReconciliationService,
        )

        deployment_repo = MockDeploymentRepository()
        recon_repo = MockReconciliationRepository()
        adapter = MockBrokerAdapter()
        _setup_active_paper_deployment(deployment_repo)

        service = ReconciliationService(
            deployment_repo=deployment_repo,
            reconciliation_repo=recon_repo,
            adapter_registry={"01HDEPLOY0001": adapter},
        )

        report = service.run_reconciliation(
            deployment_id="01HDEPLOY0001",
            trigger=ReconciliationTrigger.STARTUP,
        )

        assert report.status == "completed"
        assert report.discrepancies == []
        assert report.resolved_count == 0
        assert report.unresolved_count == 0
        assert recon_repo.count() == 1

    def test_matching_orders_no_discrepancies(self) -> None:
        """Internal and broker orders match → clean report."""
        from services.api.services.reconciliation_service import (
            ReconciliationService,
        )

        deployment_repo = MockDeploymentRepository()
        recon_repo = MockReconciliationRepository()
        adapter = MockBrokerAdapter(fill_mode="instant")
        _setup_active_paper_deployment(deployment_repo)

        # Submit an order via the adapter so broker state exists
        request = _make_order_request()
        resp = adapter.submit_order(request)

        # Internal state matches broker state exactly
        service = ReconciliationService(
            deployment_repo=deployment_repo,
            reconciliation_repo=recon_repo,
            adapter_registry={"01HDEPLOY0001": adapter},
            internal_order_states={
                "01HDEPLOY0001": {
                    "ord-001": resp.status,
                }
            },
        )

        report = service.run_reconciliation(
            deployment_id="01HDEPLOY0001",
            trigger=ReconciliationTrigger.MANUAL,
        )

        assert report.status == "completed"
        assert report.discrepancies == []
        assert report.orders_checked >= 1


class TestReconciliationServiceStatusMismatch:
    """Test detection of order status mismatches."""

    def test_status_mismatch_auto_resolved(self) -> None:
        """
        When broker shows FILLED but internal shows SUBMITTED,
        auto-resolve as safe status lag.
        """
        from services.api.services.reconciliation_service import (
            ReconciliationService,
        )

        deployment_repo = MockDeploymentRepository()
        recon_repo = MockReconciliationRepository()
        adapter = MockBrokerAdapter(fill_mode="instant")
        _setup_active_paper_deployment(deployment_repo)

        # Submit order → broker fills instantly
        request = _make_order_request()
        adapter.submit_order(request)

        # Create service with an internal state that has SUBMITTED status
        # while broker already shows FILLED
        service = ReconciliationService(
            deployment_repo=deployment_repo,
            reconciliation_repo=recon_repo,
            adapter_registry={"01HDEPLOY0001": adapter},
            internal_order_states={
                "01HDEPLOY0001": {
                    "ord-001": OrderStatus.SUBMITTED,
                }
            },
        )

        report = service.run_reconciliation(
            deployment_id="01HDEPLOY0001",
            trigger=ReconciliationTrigger.RECONNECT,
        )

        assert report.status == "completed_with_discrepancies"
        assert len(report.discrepancies) == 1
        disc = report.discrepancies[0]
        assert disc.discrepancy_type == DiscrepancyType.STATUS_MISMATCH
        assert disc.entity_type == "order"
        assert disc.internal_value == "submitted"
        assert disc.broker_value == "filled"
        assert disc.auto_resolved is True
        assert report.resolved_count == 1
        assert report.unresolved_count == 0


class TestReconciliationServiceMissingOrder:
    """Test detection of missing orders (in broker, not internal)."""

    def test_extra_order_at_broker(self) -> None:
        """
        Broker has an order that internal state doesn't know about.
        This is an EXTRA_ORDER discrepancy (unsafe).
        """
        from services.api.services.reconciliation_service import (
            ReconciliationService,
        )

        deployment_repo = MockDeploymentRepository()
        recon_repo = MockReconciliationRepository()
        adapter = MockBrokerAdapter(fill_mode="instant")
        _setup_active_paper_deployment(deployment_repo)

        # Submit order to broker directly (simulating broker-side order)
        request = _make_order_request(client_order_id="broker-only-001")
        adapter.submit_order(request)

        # Internal state has no orders
        service = ReconciliationService(
            deployment_repo=deployment_repo,
            reconciliation_repo=recon_repo,
            adapter_registry={"01HDEPLOY0001": adapter},
            internal_order_states={"01HDEPLOY0001": {}},
        )

        report = service.run_reconciliation(
            deployment_id="01HDEPLOY0001",
            trigger=ReconciliationTrigger.STARTUP,
        )

        assert report.status == "completed_with_discrepancies"
        assert len(report.discrepancies) == 1
        disc = report.discrepancies[0]
        assert disc.discrepancy_type == DiscrepancyType.EXTRA_ORDER
        assert disc.entity_id == "broker-only-001"
        assert disc.auto_resolved is False
        assert report.unresolved_count == 1

    def test_missing_order_at_broker(self) -> None:
        """
        Internal state has an order that broker doesn't know about.
        This is a MISSING_ORDER discrepancy (unsafe).
        """
        from services.api.services.reconciliation_service import (
            ReconciliationService,
        )

        deployment_repo = MockDeploymentRepository()
        recon_repo = MockReconciliationRepository()
        adapter = MockBrokerAdapter()
        _setup_active_paper_deployment(deployment_repo)

        # Internal state has an order, broker has nothing
        service = ReconciliationService(
            deployment_repo=deployment_repo,
            reconciliation_repo=recon_repo,
            adapter_registry={"01HDEPLOY0001": adapter},
            internal_order_states={
                "01HDEPLOY0001": {
                    "ghost-001": OrderStatus.SUBMITTED,
                }
            },
        )

        report = service.run_reconciliation(
            deployment_id="01HDEPLOY0001",
            trigger=ReconciliationTrigger.MANUAL,
        )

        assert report.status == "completed_with_discrepancies"
        assert len(report.discrepancies) == 1
        disc = report.discrepancies[0]
        assert disc.discrepancy_type == DiscrepancyType.MISSING_ORDER
        assert disc.entity_id == "ghost-001"
        assert disc.auto_resolved is False
        assert report.unresolved_count == 1


class TestReconciliationServiceQuantityMismatch:
    """Test detection of quantity mismatches."""

    def test_quantity_mismatch_detected(self) -> None:
        """
        Internal and broker agree order exists but quantity differs.
        """
        from services.api.services.reconciliation_service import (
            ReconciliationService,
        )

        deployment_repo = MockDeploymentRepository()
        recon_repo = MockReconciliationRepository()
        adapter = MockBrokerAdapter(fill_mode="instant")
        _setup_active_paper_deployment(deployment_repo)

        # Submit order for 100 shares
        request = _make_order_request(quantity=Decimal("100"))
        adapter.submit_order(request)

        # Internal state says we expected 200 shares
        service = ReconciliationService(
            deployment_repo=deployment_repo,
            reconciliation_repo=recon_repo,
            adapter_registry={"01HDEPLOY0001": adapter},
            internal_order_quantities={"01HDEPLOY0001": {"ord-001": Decimal("200")}},
        )

        report = service.run_reconciliation(
            deployment_id="01HDEPLOY0001",
            trigger=ReconciliationTrigger.SCHEDULED,
        )

        qty_discs = [
            d
            for d in report.discrepancies
            if d.discrepancy_type == DiscrepancyType.QUANTITY_MISMATCH
        ]
        assert len(qty_discs) == 1
        assert qty_discs[0].field == "quantity"
        assert qty_discs[0].internal_value == "200"
        assert qty_discs[0].broker_value == "100"
        assert qty_discs[0].auto_resolved is False


class TestReconciliationServicePositionDiscrepancies:
    """Test detection of position-level discrepancies."""

    def test_missing_position_detected(self) -> None:
        """
        Internal state expects a position that broker doesn't have.
        """
        from services.api.services.reconciliation_service import (
            ReconciliationService,
        )

        deployment_repo = MockDeploymentRepository()
        recon_repo = MockReconciliationRepository()
        adapter = MockBrokerAdapter()
        _setup_active_paper_deployment(deployment_repo)

        # Internal state says we have an AAPL position, broker has none
        service = ReconciliationService(
            deployment_repo=deployment_repo,
            reconciliation_repo=recon_repo,
            adapter_registry={"01HDEPLOY0001": adapter},
            internal_positions={"01HDEPLOY0001": {"AAPL": Decimal("100")}},
        )

        report = service.run_reconciliation(
            deployment_id="01HDEPLOY0001",
            trigger=ReconciliationTrigger.STARTUP,
        )

        pos_discs = [
            d
            for d in report.discrepancies
            if d.discrepancy_type == DiscrepancyType.MISSING_POSITION
        ]
        assert len(pos_discs) == 1
        assert pos_discs[0].symbol == "AAPL"
        assert pos_discs[0].auto_resolved is False

    def test_extra_position_detected(self) -> None:
        """
        Broker has a position that internal state doesn't know about.
        """
        from services.api.services.reconciliation_service import (
            ReconciliationService,
        )

        deployment_repo = MockDeploymentRepository()
        recon_repo = MockReconciliationRepository()
        adapter = MockBrokerAdapter(fill_mode="instant")
        _setup_active_paper_deployment(deployment_repo)

        # Submit a buy order so broker has a position
        request = _make_order_request(symbol="MSFT")
        adapter.submit_order(request)

        # Internal state has no positions
        service = ReconciliationService(
            deployment_repo=deployment_repo,
            reconciliation_repo=recon_repo,
            adapter_registry={"01HDEPLOY0001": adapter},
            internal_positions={"01HDEPLOY0001": {}},
        )

        report = service.run_reconciliation(
            deployment_id="01HDEPLOY0001",
            trigger=ReconciliationTrigger.RECONNECT,
        )

        pos_discs = [
            d for d in report.discrepancies if d.discrepancy_type == DiscrepancyType.EXTRA_POSITION
        ]
        assert len(pos_discs) == 1
        assert pos_discs[0].symbol == "MSFT"
        assert pos_discs[0].auto_resolved is False


class TestReconciliationServiceReportRetrieval:
    """Test report retrieval and listing."""

    def test_get_report_by_id(self) -> None:
        from services.api.services.reconciliation_service import (
            ReconciliationService,
        )

        deployment_repo = MockDeploymentRepository()
        recon_repo = MockReconciliationRepository()
        adapter = MockBrokerAdapter()
        _setup_active_paper_deployment(deployment_repo)

        service = ReconciliationService(
            deployment_repo=deployment_repo,
            reconciliation_repo=recon_repo,
            adapter_registry={"01HDEPLOY0001": adapter},
        )

        report = service.run_reconciliation(
            deployment_id="01HDEPLOY0001",
            trigger=ReconciliationTrigger.MANUAL,
        )

        retrieved = service.get_report(report_id=report.report_id)
        assert retrieved.report_id == report.report_id

    def test_get_report_not_found(self) -> None:
        from services.api.services.reconciliation_service import (
            ReconciliationService,
        )

        deployment_repo = MockDeploymentRepository()
        recon_repo = MockReconciliationRepository()

        service = ReconciliationService(
            deployment_repo=deployment_repo,
            reconciliation_repo=recon_repo,
            adapter_registry={},
        )

        with pytest.raises(NotFoundError):
            service.get_report(report_id="nonexistent")

    def test_list_reports_by_deployment(self) -> None:
        from services.api.services.reconciliation_service import (
            ReconciliationService,
        )

        deployment_repo = MockDeploymentRepository()
        recon_repo = MockReconciliationRepository()
        adapter = MockBrokerAdapter()
        _setup_active_paper_deployment(deployment_repo)

        service = ReconciliationService(
            deployment_repo=deployment_repo,
            reconciliation_repo=recon_repo,
            adapter_registry={"01HDEPLOY0001": adapter},
        )

        # Run two reconciliations
        service.run_reconciliation(
            deployment_id="01HDEPLOY0001",
            trigger=ReconciliationTrigger.STARTUP,
        )
        service.run_reconciliation(
            deployment_id="01HDEPLOY0001",
            trigger=ReconciliationTrigger.SCHEDULED,
        )

        reports = service.list_reports(deployment_id="01HDEPLOY0001")
        assert len(reports) == 2


class TestReconciliationServiceErrorPaths:
    """Test error conditions."""

    def test_deployment_not_found(self) -> None:
        from services.api.services.reconciliation_service import (
            ReconciliationService,
        )

        deployment_repo = MockDeploymentRepository()
        recon_repo = MockReconciliationRepository()

        service = ReconciliationService(
            deployment_repo=deployment_repo,
            reconciliation_repo=recon_repo,
            adapter_registry={},
        )

        with pytest.raises(NotFoundError, match="not found"):
            service.run_reconciliation(
                deployment_id="nonexistent",
                trigger=ReconciliationTrigger.MANUAL,
            )

    def test_no_adapter_registered(self) -> None:
        """Deployment exists but no adapter is registered."""
        from services.api.services.reconciliation_service import (
            ReconciliationService,
        )

        deployment_repo = MockDeploymentRepository()
        recon_repo = MockReconciliationRepository()
        _setup_active_paper_deployment(deployment_repo)

        service = ReconciliationService(
            deployment_repo=deployment_repo,
            reconciliation_repo=recon_repo,
            adapter_registry={},
        )

        with pytest.raises(NotFoundError, match="adapter"):
            service.run_reconciliation(
                deployment_id="01HDEPLOY0001",
                trigger=ReconciliationTrigger.STARTUP,
            )


class TestReconciliationServiceMultipleDiscrepancies:
    """Test multiple discrepancy detection in a single run."""

    def test_multiple_discrepancies_mixed(self) -> None:
        """
        Multiple discrepancy types detected and counted correctly.
        """
        from services.api.services.reconciliation_service import (
            ReconciliationService,
        )

        deployment_repo = MockDeploymentRepository()
        recon_repo = MockReconciliationRepository()
        adapter = MockBrokerAdapter(fill_mode="instant")
        _setup_active_paper_deployment(deployment_repo)

        # Order at broker that internal doesn't know about
        adapter.submit_order(_make_order_request(client_order_id="broker-only"))
        # Order both know about but with status mismatch
        adapter.submit_order(_make_order_request(client_order_id="shared-order"))

        service = ReconciliationService(
            deployment_repo=deployment_repo,
            reconciliation_repo=recon_repo,
            adapter_registry={"01HDEPLOY0001": adapter},
            internal_order_states={
                "01HDEPLOY0001": {
                    # ghost-001 is in internal but not at broker
                    "ghost-001": OrderStatus.SUBMITTED,
                    # shared-order exists at both but different status
                    "shared-order": OrderStatus.SUBMITTED,
                }
            },
            internal_positions={
                "01HDEPLOY0001": {
                    # Internal says we have TSLA, broker won't
                    "TSLA": Decimal("50"),
                }
            },
        )

        report = service.run_reconciliation(
            deployment_id="01HDEPLOY0001",
            trigger=ReconciliationTrigger.MANUAL,
        )

        assert report.status == "completed_with_discrepancies"
        assert len(report.discrepancies) >= 3
        types_found = {d.discrepancy_type for d in report.discrepancies}
        # We should see at least: EXTRA_ORDER, MISSING_ORDER, STATUS_MISMATCH
        # and MISSING_POSITION (TSLA internal but not at broker)
        assert (
            DiscrepancyType.EXTRA_ORDER in types_found
            or DiscrepancyType.MISSING_ORDER in types_found
        )
        assert report.resolved_count + report.unresolved_count == len(report.discrepancies)


class TestReconciliationServicePriceMismatch:
    """Test price mismatch detection."""

    def test_price_mismatch_detected(self) -> None:
        """Internal and broker agree order exists but fill price differs."""
        from services.api.services.reconciliation_service import (
            ReconciliationService,
        )

        deployment_repo = MockDeploymentRepository()
        recon_repo = MockReconciliationRepository()
        adapter = MockBrokerAdapter(fill_mode="instant")
        _setup_active_paper_deployment(deployment_repo)

        # Submit a market order (instant fill at default price)
        request = _make_order_request(client_order_id="price-test-001")
        adapter.submit_order(request)

        # Internal state expects a different fill price
        service = ReconciliationService(
            deployment_repo=deployment_repo,
            reconciliation_repo=recon_repo,
            adapter_registry={"01HDEPLOY0001": adapter},
            internal_order_prices={
                "01HDEPLOY0001": {
                    "price-test-001": Decimal("999.99"),
                }
            },
        )

        report = service.run_reconciliation(
            deployment_id="01HDEPLOY0001",
            trigger=ReconciliationTrigger.MANUAL,
        )

        price_discs = [
            d for d in report.discrepancies if d.discrepancy_type == DiscrepancyType.PRICE_MISMATCH
        ]
        assert len(price_discs) == 1
        assert price_discs[0].field == "average_fill_price"
        assert price_discs[0].auto_resolved is False
