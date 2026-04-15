"""
Reconciliation repository interface (port).

Responsibilities:
- Define the abstract contract for reconciliation report persistence.

Does NOT:
- Implement storage logic.

Dependencies:
- libs.contracts.reconciliation: ReconciliationReport.

Example:
    repo: ReconciliationRepositoryInterface = MockReconciliationRepository()
    repo.save(report)
    reports = repo.list_by_deployment(deployment_id="01HDEPLOY...")
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.reconciliation import ReconciliationReport


class ReconciliationRepositoryInterface(ABC):
    """Port interface for reconciliation report persistence."""

    @abstractmethod
    def save(self, report: ReconciliationReport) -> None:
        """Persist a reconciliation report."""
        ...

    @abstractmethod
    def get_by_id(self, report_id: str) -> ReconciliationReport | None:
        """Get a report by ID. Returns None if not found."""
        ...

    @abstractmethod
    def list_by_deployment(
        self,
        *,
        deployment_id: str,
        limit: int = 20,
    ) -> list[ReconciliationReport]:
        """List reports for a deployment, most recent first."""
        ...
