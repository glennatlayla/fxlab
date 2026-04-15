"""
Unit tests for MobileDashboardService.

Validates service layer logic: aggregating data from multiple repositories,
handling partial failures gracefully, and returning well-formed summaries.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from libs.contracts.mobile_dashboard import MobileDashboardSummary
from libs.contracts.research_run import ResearchRunStatus
from services.api.services.mobile_dashboard_service import MobileDashboardService

# ---------------------------------------------------------------------------
# Mock repositories
# ---------------------------------------------------------------------------


class _MockResearchRunRepository:
    """In-memory mock research run repository for service tests."""

    def __init__(
        self,
        active_count: int = 0,
        completed_24h_count: int = 0,
    ) -> None:
        self._active_count = active_count
        self._completed_24h_count = completed_24h_count
        self._should_fail = False

    def count_by_status(self, status: Any = None) -> int:
        """Count runs by status."""
        if self._should_fail:
            raise Exception("Repository error")
        if status == ResearchRunStatus.RUNNING:
            return self._active_count
        if status == ResearchRunStatus.COMPLETED:
            return self._completed_24h_count
        return 0

    def set_should_fail(self, fail: bool) -> None:
        """Make the repo fail on next call (for testing error handling)."""
        self._should_fail = fail


class _MockApprovalRepository:
    """In-memory mock approval repository for service tests."""

    def __init__(self, pending_count: int = 0) -> None:
        self._pending_count = pending_count
        self._should_fail = False

    def count_by_status(self, status: str) -> int:
        """Count approvals by status."""
        if self._should_fail:
            raise Exception("Repository error")
        if status == "pending":
            return self._pending_count
        return 0

    def set_should_fail(self, fail: bool) -> None:
        """Make the repo fail on next call (for testing error handling)."""
        self._should_fail = fail


class _MockKillSwitchEventRepository:
    """In-memory mock kill switch event repository for service tests."""

    def __init__(self, active_count: int = 0) -> None:
        self._active_count = active_count
        self._should_fail = False

    def list_active(self) -> list[dict[str, Any]]:
        """List active kill switch events."""
        if self._should_fail:
            raise Exception("Repository error")
        return [{"id": f"event_{i}"} for i in range(self._active_count)]

    def set_should_fail(self, fail: bool) -> None:
        """Make the repo fail on next call (for testing error handling)."""
        self._should_fail = fail


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMobileDashboardService:
    """Tests for MobileDashboardService.get_summary()."""

    def test_get_summary_returns_all_fields_when_all_sources_available(self) -> None:
        """All data sources available => all fields populated correctly."""
        research_repo = _MockResearchRunRepository(active_count=3, completed_24h_count=5)
        approval_repo = _MockApprovalRepository(pending_count=2)
        kill_switch_repo = _MockKillSwitchEventRepository(active_count=1)

        service = MobileDashboardService(
            research_run_repo=research_repo,
            approval_repo=approval_repo,
            kill_switch_event_repo=kill_switch_repo,
        )

        summary = service.get_summary()

        assert isinstance(summary, MobileDashboardSummary)
        assert summary.active_runs == 3
        assert summary.completed_runs_24h == 5
        assert summary.pending_approvals == 2
        assert summary.active_kill_switches == 1
        # pnl_today_usd, alerts are not sourced in MVP, so None
        assert summary.pnl_today_usd is None
        assert summary.last_alert_severity is None
        assert summary.last_alert_message is None
        # generated_at is always present
        assert summary.generated_at is not None

    def test_get_summary_handles_partial_failure_gracefully(self) -> None:
        """One data source fails => other sources still populated."""
        research_repo = _MockResearchRunRepository(active_count=3, completed_24h_count=5)
        approval_repo = _MockApprovalRepository(pending_count=2)
        approval_repo.set_should_fail(True)  # This one will fail
        kill_switch_repo = _MockKillSwitchEventRepository(active_count=1)

        service = MobileDashboardService(
            research_run_repo=research_repo,
            approval_repo=approval_repo,
            kill_switch_event_repo=kill_switch_repo,
        )

        # Should not raise, but return partial summary
        summary = service.get_summary()

        assert isinstance(summary, MobileDashboardSummary)
        # Research data is available
        assert summary.active_runs == 3
        assert summary.completed_runs_24h == 5
        # Approval data failed, so default to 0
        assert summary.pending_approvals == 0
        # Kill switch data is available
        assert summary.active_kill_switches == 1
        # Summary is still valid
        assert summary.generated_at is not None

    def test_get_summary_returns_zero_counts_when_no_data(self) -> None:
        """All repos return zero => summary reflects zero counts."""
        research_repo = _MockResearchRunRepository(active_count=0, completed_24h_count=0)
        approval_repo = _MockApprovalRepository(pending_count=0)
        kill_switch_repo = _MockKillSwitchEventRepository(active_count=0)

        service = MobileDashboardService(
            research_run_repo=research_repo,
            approval_repo=approval_repo,
            kill_switch_event_repo=kill_switch_repo,
        )

        summary = service.get_summary()

        assert isinstance(summary, MobileDashboardSummary)
        assert summary.active_runs == 0
        assert summary.completed_runs_24h == 0
        assert summary.pending_approvals == 0
        assert summary.active_kill_switches == 0
        assert summary.generated_at is not None

    def test_get_summary_generated_at_is_valid_iso_8601(self) -> None:
        """generated_at is a valid ISO 8601 timestamp."""
        research_repo = _MockResearchRunRepository(active_count=1)
        approval_repo = _MockApprovalRepository(pending_count=0)
        kill_switch_repo = _MockKillSwitchEventRepository(active_count=0)

        service = MobileDashboardService(
            research_run_repo=research_repo,
            approval_repo=approval_repo,
            kill_switch_event_repo=kill_switch_repo,
        )

        summary = service.get_summary()

        # Should be parseable as an ISO 8601 string
        ts = datetime.fromisoformat(summary.generated_at.replace("Z", "+00:00"))
        assert ts.tzinfo is not None  # Must have timezone info
