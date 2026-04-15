"""
Unit tests for ExecutionAnalysisService.

Covers:
- Drift computation: fill price, timing, slippage, fill rate.
- Severity classification per configured thresholds.
- Order timeline reconstruction.
- Correlation ID search.
- Error paths (not found).

Dependencies:
- libs.contracts.mocks.mock_broker_adapter: MockBrokerAdapter
- libs.contracts.mocks.mock_deployment_repository: MockDeploymentRepository
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from libs.contracts.drift import (
    DriftSeverity,
)
from libs.contracts.errors import NotFoundError
from libs.contracts.execution import (
    ExecutionMode,
    OrderEvent,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)
from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

DEP_ID = "01HDEPLOY0001"


def _make_order_request(
    client_order_id: str = "ord-001",
    symbol: str = "AAPL",
) -> OrderRequest:
    return OrderRequest(
        client_order_id=client_order_id,
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("100"),
        time_in_force=TimeInForce.DAY,
        deployment_id=DEP_ID,
        strategy_id="01HSTRAT0001",
        correlation_id="corr-001",
        execution_mode=ExecutionMode.PAPER,
    )


def _setup(fill_mode: str = "instant"):
    deployment_repo = MockDeploymentRepository()
    deployment_repo.seed(
        deployment_id=DEP_ID,
        state="active",
        execution_mode="paper",
    )
    adapter = MockBrokerAdapter(fill_mode=fill_mode)

    from services.api.services.execution_analysis_service import (
        ExecutionAnalysisService,
    )

    service = ExecutionAnalysisService(
        deployment_repo=deployment_repo,
        adapter_registry={DEP_ID: adapter},
    )
    return service, deployment_repo, adapter


# ------------------------------------------------------------------
# Drift computation
# ------------------------------------------------------------------


class TestDriftComputation:
    """Test drift metric computation."""

    def test_no_orders_empty_report(self) -> None:
        service, _, _ = _setup()
        report = service.compute_drift(deployment_id=DEP_ID, window="1h")
        assert report.deployment_id == DEP_ID
        assert report.window == "1h"
        assert report.total_metrics == 0
        assert report.max_severity == DriftSeverity.NEGLIGIBLE

    def test_with_orders_produces_metrics(self) -> None:
        service, _, adapter = _setup()
        # Submit and fill an order
        adapter.submit_order(_make_order_request())

        # Provide expected values for drift comparison
        service.set_expected_prices(
            deployment_id=DEP_ID,
            expected={"ord-001": Decimal("175.00")},
        )

        report = service.compute_drift(deployment_id=DEP_ID, window="1h")
        assert report.total_metrics >= 1
        assert report.report_id != ""

    def test_deployment_not_found(self) -> None:
        service, _, _ = _setup()
        with pytest.raises(NotFoundError):
            service.compute_drift(deployment_id="nonexistent", window="1h")

    def test_severity_classification(self) -> None:
        """Large drift should be classified as significant or critical."""
        service, _, adapter = _setup()
        adapter.submit_order(_make_order_request())

        # Set wildly different expected price to trigger high severity
        service.set_expected_prices(
            deployment_id=DEP_ID,
            expected={"ord-001": Decimal("1.00")},
        )

        report = service.compute_drift(deployment_id=DEP_ID, window="1h")
        # With such extreme drift, should have significant or critical severity
        severity_values = [m.severity for m in report.metrics]
        assert any(
            s in (DriftSeverity.SIGNIFICANT, DriftSeverity.CRITICAL) for s in severity_values
        )


# ------------------------------------------------------------------
# Order timeline
# ------------------------------------------------------------------


class TestOrderTimeline:
    """Test order timeline reconstruction."""

    def test_timeline_with_events(self) -> None:
        service, _, adapter = _setup()
        # Submit order to create events
        adapter.submit_order(_make_order_request())

        # Register events for the order
        now = datetime.now(timezone.utc)
        service.register_event(
            OrderEvent(
                event_id="evt-001",
                order_id="ord-001",
                event_type="signal",
                timestamp=now,
                details={"strategy": "momentum"},
                correlation_id="corr-001",
            )
        )
        service.register_event(
            OrderEvent(
                event_id="evt-002",
                order_id="ord-001",
                event_type="submitted",
                timestamp=now,
                details={"broker_order_id": "BRK-001"},
                correlation_id="corr-001",
            )
        )

        timeline = service.get_order_timeline(order_id="ord-001")
        assert timeline.order_id == "ord-001"
        assert len(timeline.events) >= 2

    def test_timeline_not_found(self) -> None:
        service, _, _ = _setup()
        with pytest.raises(NotFoundError):
            service.get_order_timeline(order_id="nonexistent")


# ------------------------------------------------------------------
# Correlation ID search
# ------------------------------------------------------------------


class TestCorrelationSearch:
    """Test correlation ID search."""

    def test_search_finds_events(self) -> None:
        service, _, _ = _setup()
        now = datetime.now(timezone.utc)
        service.register_event(
            OrderEvent(
                event_id="evt-001",
                order_id="ord-001",
                event_type="submitted",
                timestamp=now,
                correlation_id="corr-ABC",
            )
        )
        service.register_event(
            OrderEvent(
                event_id="evt-002",
                order_id="ord-002",
                event_type="filled",
                timestamp=now,
                correlation_id="corr-ABC",
            )
        )
        service.register_event(
            OrderEvent(
                event_id="evt-003",
                order_id="ord-003",
                event_type="submitted",
                timestamp=now,
                correlation_id="corr-OTHER",
            )
        )

        results = service.search_by_correlation_id(correlation_id="corr-ABC")
        assert len(results) == 2
        assert all(e.correlation_id == "corr-ABC" for e in results)

    def test_search_no_matches(self) -> None:
        service, _, _ = _setup()
        results = service.search_by_correlation_id(correlation_id="nonexistent")
        assert results == []
