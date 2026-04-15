"""
Reconciliation service interface (port).

Responsibilities:
- Define the abstract contract for reconciliation operations.
- Compare internal state vs broker state and detect discrepancies.

Does NOT:
- Implement reconciliation logic (service responsibility).
- Persist reports (delegates to repository).

Dependencies:
- libs.contracts.reconciliation: ReconciliationReport, ReconciliationTrigger.

Error conditions:
- NotFoundError: report_id or deployment_id not found.

Example:
    service: ReconciliationServiceInterface = ReconciliationService(...)
    report = service.run_reconciliation(
        deployment_id="01HDEPLOY...",
        trigger=ReconciliationTrigger.STARTUP,
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.reconciliation import ReconciliationReport, ReconciliationTrigger


class ReconciliationServiceInterface(ABC):
    """
    Port interface for reconciliation service.

    Implementations:
    - ReconciliationService — production implementation (M6)
    """

    @abstractmethod
    def run_reconciliation(
        self,
        *,
        deployment_id: str,
        trigger: ReconciliationTrigger,
    ) -> ReconciliationReport:
        """
        Run reconciliation for a deployment.

        Args:
            deployment_id: ULID of the deployment.
            trigger: What triggered this run.

        Returns:
            ReconciliationReport with all discrepancies.

        Raises:
            NotFoundError: deployment has no active adapter.
        """
        ...

    @abstractmethod
    def get_report(
        self,
        *,
        report_id: str,
    ) -> ReconciliationReport:
        """
        Get a specific reconciliation report.

        Args:
            report_id: ULID of the report.

        Returns:
            ReconciliationReport.

        Raises:
            NotFoundError: report not found.
        """
        ...

    @abstractmethod
    def list_reports(
        self,
        *,
        deployment_id: str,
        limit: int = 20,
    ) -> list[ReconciliationReport]:
        """
        List reconciliation reports for a deployment.

        Args:
            deployment_id: ULID of the deployment.
            limit: Maximum number of reports to return.

        Returns:
            List of ReconciliationReport objects, most recent first.
        """
        ...
