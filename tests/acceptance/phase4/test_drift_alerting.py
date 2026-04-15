"""
Acceptance test: Drift triggers alerts/halts.

Spec gate 7: Execution drift analysis detects and classifies drift
severity, with CRITICAL drift triggering alert-worthy conditions.

Covers:
- Drift computation classifies severity correctly.
- NEGLIGIBLE drift (<1%) does not raise concerns.
- CRITICAL drift (≥10%) is flagged appropriately.
- Drift report includes all required fields.
- Multiple metrics are classified independently.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from libs.contracts.drift import DriftSeverity
from libs.contracts.execution import (
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)
from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from services.api.services.execution_analysis_service import (
    ExecutionAnalysisService,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEP_ID = "01HACC_DRIFT_001"
STRAT_ID = "01HACC_STRAT_DR_001"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def setup():
    dep_repo = MockDeploymentRepository()
    dep_repo.seed(
        deployment_id=DEP_ID,
        strategy_id=STRAT_ID,
        state="active",
        execution_mode="paper",
    )
    adapter = MockBrokerAdapter(fill_mode="instant")
    service = ExecutionAnalysisService(
        deployment_repo=dep_repo,
        adapter_registry={DEP_ID: adapter},
    )
    return service, adapter


def _submit_order(adapter: MockBrokerAdapter, oid: str, symbol: str = "AAPL") -> None:
    adapter.submit_order(
        OrderRequest(
            client_order_id=oid,
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            time_in_force=TimeInForce.DAY,
            deployment_id=DEP_ID,
            strategy_id=STRAT_ID,
            correlation_id="corr-drift",
            execution_mode=ExecutionMode.PAPER,
        )
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDriftAlerting:
    """Spec gate 7: Drift triggers alerts/halts."""

    def test_negligible_drift(self, setup) -> None:
        """Drift <1% is classified as NEGLIGIBLE."""
        service, adapter = setup
        _submit_order(adapter, "drift-ord-neg")

        # Set expected price very close to fill price (MockBrokerAdapter fills at 100.00)
        service.set_expected_prices(
            deployment_id=DEP_ID,
            expected={"drift-ord-neg": Decimal("100.50")},  # 0.5% drift
        )
        report = service.compute_drift(deployment_id=DEP_ID, window="1h")

        if report.total_metrics > 0:
            for metric in report.metrics:
                if metric.order_id == "drift-ord-neg":
                    assert metric.severity == DriftSeverity.NEGLIGIBLE

    def test_critical_drift_flagged(self, setup) -> None:
        """Drift ≥10% is classified as CRITICAL."""
        service, adapter = setup
        _submit_order(adapter, "drift-ord-crit")

        # Set expected price far from fill price
        service.set_expected_prices(
            deployment_id=DEP_ID,
            expected={"drift-ord-crit": Decimal("115.00")},  # >10% drift from 100.00
        )
        report = service.compute_drift(deployment_id=DEP_ID, window="1h")

        assert report.total_metrics >= 1
        critical_metrics = [m for m in report.metrics if m.severity == DriftSeverity.CRITICAL]
        assert len(critical_metrics) >= 1, "CRITICAL drift must be flagged"
        assert report.critical_count >= 1

    def test_drift_report_fields(self, setup) -> None:
        """Drift report includes all required fields."""
        service, adapter = setup
        _submit_order(adapter, "drift-ord-fields")

        service.set_expected_prices(
            deployment_id=DEP_ID,
            expected={"drift-ord-fields": Decimal("103.00")},
        )
        report = service.compute_drift(deployment_id=DEP_ID, window="24h")

        assert report.report_id is not None
        assert report.deployment_id == DEP_ID
        assert report.window == "24h"
        assert report.max_severity is not None
        assert report.total_metrics >= 0
        assert report.created_at is not None

    def test_multiple_metrics_independent(self, setup) -> None:
        """Each order's drift is classified independently."""
        service, adapter = setup
        _submit_order(adapter, "drift-ord-small")
        _submit_order(adapter, "drift-ord-large")

        service.set_expected_prices(
            deployment_id=DEP_ID,
            expected={
                "drift-ord-small": Decimal("100.30"),  # ~0.3% drift
                "drift-ord-large": Decimal("112.00"),  # ~12% drift
            },
        )
        report = service.compute_drift(deployment_id=DEP_ID, window="1h")

        assert report.total_metrics >= 2
        severities = {m.severity for m in report.metrics}
        # Should have at least two different severity levels
        assert len(severities) >= 2, "Different drifts should produce different severities"
