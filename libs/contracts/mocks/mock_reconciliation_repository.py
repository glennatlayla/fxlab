"""
In-memory mock implementation of ReconciliationRepositoryInterface.

Responsibilities:
- Provide a test double for reconciliation report persistence.
- Support introspection helpers for test assertions.

Does NOT:
- Persist data beyond the lifetime of the instance.
- Contain reconciliation logic.

Dependencies:
- libs.contracts.interfaces.reconciliation_repository_interface.
- libs.contracts.reconciliation: ReconciliationReport.

Example:
    repo = MockReconciliationRepository()
    repo.save(report)
    assert repo.count() == 1
    retrieved = repo.get_by_id(report.report_id)
"""

from __future__ import annotations

from libs.contracts.interfaces.reconciliation_repository_interface import (
    ReconciliationRepositoryInterface,
)
from libs.contracts.reconciliation import ReconciliationReport


class MockReconciliationRepository(ReconciliationRepositoryInterface):
    """
    In-memory implementation of ReconciliationRepositoryInterface.

    Responsibilities:
    - Store reconciliation reports in memory for testing.
    - Support retrieval by ID and deployment_id.
    - Provide introspection helpers (count, get_all, clear).

    Does NOT:
    - Persist data to any external store.

    Example:
        repo = MockReconciliationRepository()
        repo.save(report)
        reports = repo.list_by_deployment(deployment_id="dep-001")
    """

    def __init__(self) -> None:
        self._store: dict[str, ReconciliationReport] = {}

    def save(self, report: ReconciliationReport) -> None:
        """
        Persist a reconciliation report in memory.

        Args:
            report: ReconciliationReport to store.
        """
        self._store[report.report_id] = report

    def get_by_id(self, report_id: str) -> ReconciliationReport | None:
        """
        Get a report by ID.

        Args:
            report_id: ULID of the report.

        Returns:
            ReconciliationReport or None if not found.
        """
        return self._store.get(report_id)

    def list_by_deployment(
        self,
        *,
        deployment_id: str,
        limit: int = 20,
    ) -> list[ReconciliationReport]:
        """
        List reports for a deployment, most recent first.

        Args:
            deployment_id: ULID of the deployment.
            limit: Maximum number of reports to return.

        Returns:
            List of ReconciliationReport objects, most recent first.
        """
        filtered = [r for r in self._store.values() if r.deployment_id == deployment_id]
        # Most recent first by created_at
        filtered.sort(key=lambda r: r.created_at, reverse=True)
        return filtered[:limit]

    # ------------------------------------------------------------------
    # Introspection helpers for tests
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return total number of stored reports."""
        return len(self._store)

    def get_all(self) -> list[ReconciliationReport]:
        """Return all stored reports."""
        return list(self._store.values())

    def clear(self) -> None:
        """Remove all stored reports."""
        self._store.clear()
