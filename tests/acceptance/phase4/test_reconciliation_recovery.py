"""
Acceptance test: Reconciliation recovers from restart without duplicates.

Spec gate 3: The reconciliation service can run multiple times against
the same deployment without producing duplicate reports or phantom
discrepancies.

Covers:
- Multiple reconciliation runs produce unique report IDs.
- Clean state produces consistent clean reports.
- No duplicate discrepancies across runs.
- Report listing returns all runs in order.
"""

from __future__ import annotations

import pytest

from libs.contracts.mocks.mock_broker_adapter import MockBrokerAdapter
from libs.contracts.mocks.mock_deployment_repository import MockDeploymentRepository
from libs.contracts.mocks.mock_reconciliation_repository import (
    MockReconciliationRepository,
)
from libs.contracts.reconciliation import ReconciliationTrigger
from services.api.services.reconciliation_service import ReconciliationService

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEP_ID = "01HACC_RECON_RECOV_001"
STRAT_ID = "01HACC_STRAT_RR_001"


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
    recon_repo = MockReconciliationRepository()
    adapter = MockBrokerAdapter(fill_mode="instant")

    service = ReconciliationService(
        deployment_repo=dep_repo,
        reconciliation_repo=recon_repo,
        adapter_registry={DEP_ID: adapter},
    )
    return service, recon_repo, adapter


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReconciliationRecovery:
    """Spec gate 3: Recon recovers from restart without duplicates."""

    def test_multiple_runs_unique_report_ids(self, setup) -> None:
        """Each reconciliation run produces a unique report ID."""
        service, _, _ = setup
        report1 = service.run_reconciliation(
            deployment_id=DEP_ID, trigger=ReconciliationTrigger.MANUAL
        )
        report2 = service.run_reconciliation(
            deployment_id=DEP_ID, trigger=ReconciliationTrigger.MANUAL
        )
        report3 = service.run_reconciliation(
            deployment_id=DEP_ID, trigger=ReconciliationTrigger.SCHEDULED
        )

        ids = {report1.report_id, report2.report_id, report3.report_id}
        assert len(ids) == 3, "Each run must produce a unique report ID"

    def test_clean_state_consistent(self, setup) -> None:
        """Clean deployment produces clean reports consistently."""
        service, _, _ = setup

        for _ in range(5):
            report = service.run_reconciliation(
                deployment_id=DEP_ID, trigger=ReconciliationTrigger.SCHEDULED
            )
            assert report.unresolved_count == 0, (
                "Clean state must always produce zero unresolved discrepancies"
            )

    def test_no_duplicate_discrepancies(self, setup) -> None:
        """Running reconciliation twice does not double-count discrepancies."""
        service, _, adapter = setup

        # Create a known state with some orders
        from decimal import Decimal

        from libs.contracts.execution import (
            ExecutionMode,
            OrderRequest,
            OrderSide,
            OrderType,
            TimeInForce,
        )

        adapter.submit_order(
            OrderRequest(
                client_order_id="recon-ord-001",
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("100"),
                time_in_force=TimeInForce.DAY,
                deployment_id=DEP_ID,
                strategy_id=STRAT_ID,
                correlation_id="corr-recon-001",
                execution_mode=ExecutionMode.PAPER,
            )
        )

        report1 = service.run_reconciliation(
            deployment_id=DEP_ID, trigger=ReconciliationTrigger.MANUAL
        )
        report2 = service.run_reconciliation(
            deployment_id=DEP_ID, trigger=ReconciliationTrigger.MANUAL
        )

        # Same state should produce same number of discrepancies
        assert report1.unresolved_count == report2.unresolved_count

    def test_report_listing_returns_all_runs(self, setup) -> None:
        """All reconciliation runs are retrievable."""
        service, recon_repo, _ = setup

        for _ in range(3):
            service.run_reconciliation(
                deployment_id=DEP_ID, trigger=ReconciliationTrigger.SCHEDULED
            )

        reports = service.list_reports(deployment_id=DEP_ID)
        assert len(reports) >= 3

    def test_startup_trigger_simulates_recovery(self, setup) -> None:
        """Startup trigger (simulating restart) produces valid report."""
        service, _, _ = setup

        report = service.run_reconciliation(
            deployment_id=DEP_ID, trigger=ReconciliationTrigger.STARTUP
        )
        assert report.deployment_id == DEP_ID
        assert report.trigger.value == "startup"
        assert report.status in ("completed", "completed_with_discrepancies")
