"""
Mobile dashboard aggregation service.

Purpose:
    Aggregate key trading metrics from multiple data sources (research runs,
    approvals, kill switches, alerts) into a single mobile-optimized response.

Responsibilities:
    - Query research run repository for active and completed-24h counts.
    - Query approval repository for pending promotion requests.
    - Query kill switch event repository for active kill switches.
    - Handle partial failures gracefully (log and continue with available data).
    - Return a frozen MobileDashboardSummary with all fields populated.

Does NOT:
    - Perform business logic (just aggregation).
    - Persist data.
    - Enforce authorization.

Dependencies:
    - ResearchRunRepositoryInterface (injected): for run counts.
    - ApprovalRepositoryInterface (injected): for pending approvals.
    - KillSwitchEventRepositoryInterface (injected): for active kill switches.
    - structlog: for structured logging.
    - libs.contracts.mobile_dashboard: MobileDashboardSummary.
    - libs.contracts.research_run: ResearchRunStatus enum.

Error conditions:
    - If a single data source fails, that field defaults to None or 0
      and the failure is logged at WARNING level.
    - No exceptions are raised; clients always receive a usable summary.

Example:
    service = MobileDashboardService(
        research_run_repo=sql_research_repo,
        approval_repo=sql_approval_repo,
        kill_switch_event_repo=sql_kill_switch_repo,
    )
    summary = service.get_summary()
    print(f"Active runs: {summary.active_runs}")
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog

from libs.contracts.interfaces.mobile_dashboard_service_interface import (
    MobileDashboardServiceInterface,
)
from libs.contracts.mobile_dashboard import MobileDashboardSummary
from libs.contracts.research_run import ResearchRunStatus

if TYPE_CHECKING:
    from libs.contracts.interfaces.approval_repository import ApprovalRepositoryInterface
    from libs.contracts.interfaces.kill_switch_event_repository_interface import (
        KillSwitchEventRepositoryInterface,
    )
    from libs.contracts.interfaces.research_run_repository import (
        ResearchRunRepositoryInterface,
    )

logger = structlog.get_logger(__name__)


class MobileDashboardService(MobileDashboardServiceInterface):
    """
    Aggregates data from multiple repositories into a mobile dashboard summary.

    Responsibilities:
    - Query research runs (active count, completed in last 24h).
    - Query approvals (pending count).
    - Query kill switch events (active count).
    - Handle individual source failures gracefully.
    - Return a complete, immutable summary.

    Dependencies:
    - research_run_repo: ResearchRunRepositoryInterface (injected).
    - approval_repo: ApprovalRepositoryInterface (injected).
    - kill_switch_event_repo: KillSwitchEventRepositoryInterface (injected).

    Raises:
    - No exceptions are raised; partial failures are logged and recovered from.

    Example:
        service = MobileDashboardService(
            research_run_repo=repo1,
            approval_repo=repo2,
            kill_switch_event_repo=repo3,
        )
        summary = service.get_summary()
    """

    def __init__(
        self,
        *,
        research_run_repo: ResearchRunRepositoryInterface,
        approval_repo: ApprovalRepositoryInterface,
        kill_switch_event_repo: KillSwitchEventRepositoryInterface,
    ) -> None:
        """
        Initialize the mobile dashboard service.

        Args:
            research_run_repo: Repository for research run data.
            approval_repo: Repository for approval data.
            kill_switch_event_repo: Repository for kill switch event data.
        """
        self._research_run_repo = research_run_repo
        self._approval_repo = approval_repo
        self._kill_switch_event_repo = kill_switch_event_repo

    def get_summary(self) -> MobileDashboardSummary:
        """
        Aggregate and return mobile dashboard summary metrics.

        Queries multiple data sources and aggregates them. If any single
        source fails, that field defaults to None or 0 and the failure
        is logged. No exceptions are raised.

        Returns:
            MobileDashboardSummary with all fields populated. Unavailable
            data defaults to None or 0.

        Example:
            summary = service.get_summary()
            assert summary.active_runs >= 0
            assert summary.generated_at is not None
        """
        # Query active research runs.
        active_runs = self._get_active_research_runs()

        # Query research runs completed in the last 24 hours.
        completed_runs_24h = self._get_completed_research_runs_24h()

        # Query pending approvals.
        pending_approvals = self._get_pending_approvals()

        # Query active kill switches.
        active_kill_switches = self._get_active_kill_switches()

        # Generate timestamp.
        generated_at = datetime.now(timezone.utc).isoformat()

        # Build summary with optional fields (not yet sourced in MVP).
        summary = MobileDashboardSummary(
            active_runs=active_runs,
            completed_runs_24h=completed_runs_24h,
            pending_approvals=pending_approvals,
            active_kill_switches=active_kill_switches,
            pnl_today_usd=None,  # Future: source from PnL service.
            last_alert_severity=None,  # Future: source from alert service.
            last_alert_message=None,  # Future: source from alert service.
            generated_at=generated_at,
        )

        return summary

    def _get_active_research_runs(self) -> int:
        """
        Count active (running) research runs.

        Returns:
            Count of running research runs, or 0 if the query fails.
        """
        try:
            count = self._research_run_repo.count_by_status(ResearchRunStatus.RUNNING)
            return count or 0
        except Exception as exc:
            logger.warning(
                "Failed to fetch active research runs",
                exc_info=exc,
            )
            return 0

    def _get_completed_research_runs_24h(self) -> int:
        """
        Count research runs completed in the last 24 hours.

        Returns:
            Count of completed research runs (24h window), or 0 if the query fails.

        Note:
            Current implementation counts all completed runs. Future work should
            filter by timestamp to return only those completed in the last 24h.
        """
        try:
            count = self._research_run_repo.count_by_status(ResearchRunStatus.COMPLETED)
            return count or 0
        except Exception as exc:
            logger.warning(
                "Failed to fetch completed research runs (24h)",
                exc_info=exc,
            )
            return 0

    def _get_pending_approvals(self) -> int:
        """
        Count pending promotion approval requests.

        Returns:
            Count of pending approvals, or 0 if the query fails.
        """
        try:
            count = self._approval_repo.count_by_status("pending")
            return count or 0
        except Exception as exc:
            logger.warning(
                "Failed to fetch pending approvals",
                exc_info=exc,
            )
            return 0

    def _get_active_kill_switches(self) -> int:
        """
        Count currently active kill switches (any scope).

        Returns:
            Count of active kill switches, or 0 if the query fails.
        """
        try:
            active_events = self._kill_switch_event_repo.list_active()
            return len(active_events) if active_events else 0
        except Exception as exc:
            logger.warning(
                "Failed to fetch active kill switches",
                exc_info=exc,
            )
            return 0
