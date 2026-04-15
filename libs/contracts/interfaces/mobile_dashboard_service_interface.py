"""
Mobile dashboard service interface (port).

Purpose:
    Define the abstract contract for mobile dashboard data aggregation.
    Allows multiple implementations (real, test, fallback) without coupling
    the controller to a concrete service.

Responsibilities:
    - Define the get_summary() method contract.
    - Document error conditions and fallback behavior.

Does NOT:
    - Implement aggregation logic.
    - Perform I/O (service implementation responsibility).
    - Contain business rules.

Dependencies:
    - libs.contracts.mobile_dashboard: MobileDashboardSummary.

Error conditions:
    - Partial failures are handled gracefully — missing data fields are
      populated with None or 0 (see service implementation).
    - No exceptions are raised from get_summary(); all errors are logged
      and partial results returned.

Example:
    service: MobileDashboardServiceInterface = MobileDashboardService(...)
    summary = service.get_summary()
    assert summary.active_runs >= 0
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.mobile_dashboard import MobileDashboardSummary


class MobileDashboardServiceInterface(ABC):
    """
    Abstract port for mobile dashboard data aggregation.

    Implementations:
    - MobileDashboardService — real aggregation from multiple repositories.
    - MockMobileDashboardService — in-memory, for unit tests.
    """

    @abstractmethod
    def get_summary(self) -> MobileDashboardSummary:
        """
        Aggregate and return mobile dashboard summary metrics.

        Queries multiple data sources (research runs, approvals, kill switches,
        alerts) and aggregates them into a single summary suitable for mobile
        display.

        Returns:
            MobileDashboardSummary with all fields populated. Fields that
            cannot be sourced are set to None or 0 as appropriate.

        Notes:
            - This method gracefully degrades on partial failures.
            - If a single data source fails, the summary is populated with
              what data is available, and the failure is logged.
            - No exceptions are raised; clients always receive a usable response.

        Example:
            summary = service.get_summary()
            print(f"Active runs: {summary.active_runs}")
            print(f"PnL: ${summary.pnl_today_usd or 'N/A'}")
        """
        ...
