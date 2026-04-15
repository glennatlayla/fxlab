"""
Unit tests for IncidentManager (Phase 6 — M13).

Verifies:
    - create_incident persists and dispatches to correct channels.
    - acknowledge_incident transitions status and records timestamp.
    - resolve_incident transitions status and sends resolution notifications.
    - check_escalations auto-escalates unacknowledged incidents past SLA.
    - Notification failures do not block incident creation.
    - Notification dispatches to all configured channels for a rule.

Dependencies:
    - pytest, unittest.mock.
    - MockIncidentRepository for persistence.
    - MagicMock for notification providers.

Example:
    pytest tests/unit/test_incident_manager.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from libs.contracts.mocks.mock_incident_repository import MockIncidentRepository
from libs.contracts.notification import (
    AlertRule,
    AlertTriggerType,
    EscalationPolicy,
    IncidentSeverity,
    IncidentStatus,
    NotificationChannel,
    NotificationResult,
)

if TYPE_CHECKING:
    from services.api.infrastructure.incident_manager import IncidentManager

_NOW = datetime(2026, 4, 12, 14, 0, 0, tzinfo=timezone.utc)


def _make_alert_rules() -> list[AlertRule]:
    """Build default alert rules for testing."""
    return [
        AlertRule(
            trigger_type=AlertTriggerType.KILL_SWITCH_ACTIVATED,
            severity=IncidentSeverity.P1,
            channels=[NotificationChannel.PAGERDUTY, NotificationChannel.SLACK],
            slack_channel="#incidents",
            description="Kill switch activated",
        ),
        AlertRule(
            trigger_type=AlertTriggerType.CIRCUIT_BREAKER_OPEN,
            severity=IncidentSeverity.P2,
            channels=[NotificationChannel.PAGERDUTY, NotificationChannel.SLACK],
            slack_channel="#alerts",
            description="Circuit breaker tripped",
        ),
        AlertRule(
            trigger_type=AlertTriggerType.SLO_BREACH,
            severity=IncidentSeverity.P2,
            channels=[NotificationChannel.SLACK],
            slack_channel="#alerts",
            description="SLO breach detected",
        ),
        AlertRule(
            trigger_type=AlertTriggerType.SECRET_EXPIRING,
            severity=IncidentSeverity.P4,
            channels=[NotificationChannel.SLACK],
            slack_channel="#ops",
            description="Secret expiring within 14 days",
        ),
        AlertRule(
            trigger_type=AlertTriggerType.RECONCILIATION_DISCREPANCY,
            severity=IncidentSeverity.P3,
            channels=[NotificationChannel.SLACK],
            slack_channel="#alerts",
            description="Reconciliation discrepancy detected",
        ),
    ]


def _make_escalation_policies() -> list[EscalationPolicy]:
    """Build default escalation policies for testing."""
    return [
        EscalationPolicy(
            severity=IncidentSeverity.P1,
            ack_timeout_seconds=900,  # 15 minutes
            escalate_to_severity=IncidentSeverity.P1,
            notify_channels=[NotificationChannel.PAGERDUTY, NotificationChannel.SLACK],
        ),
        EscalationPolicy(
            severity=IncidentSeverity.P2,
            ack_timeout_seconds=3600,  # 1 hour
            escalate_to_severity=IncidentSeverity.P1,
            notify_channels=[NotificationChannel.PAGERDUTY, NotificationChannel.SLACK],
        ),
    ]


@pytest.fixture()
def repo() -> MockIncidentRepository:
    """Provide a fresh MockIncidentRepository."""
    return MockIncidentRepository()


@pytest.fixture()
def mock_slack() -> MagicMock:
    """Provide a mock Slack notification provider."""
    provider = MagicMock()
    provider.send_alert.return_value = NotificationResult(
        channel=NotificationChannel.SLACK, success=True
    )
    provider.send_resolution.return_value = NotificationResult(
        channel=NotificationChannel.SLACK, success=True
    )
    return provider


@pytest.fixture()
def mock_pagerduty() -> MagicMock:
    """Provide a mock PagerDuty notification provider."""
    provider = MagicMock()
    provider.send_alert.return_value = NotificationResult(
        channel=NotificationChannel.PAGERDUTY,
        success=True,
        response_id="dedup-123",
    )
    provider.send_resolution.return_value = NotificationResult(
        channel=NotificationChannel.PAGERDUTY, success=True
    )
    return provider


@pytest.fixture()
def manager(
    repo: MockIncidentRepository,
    mock_slack: MagicMock,
    mock_pagerduty: MagicMock,
) -> IncidentManager:
    """Provide an IncidentManager wired with mocks."""
    from services.api.infrastructure.incident_manager import IncidentManager

    return IncidentManager(
        incident_repo=repo,
        providers={
            NotificationChannel.SLACK: mock_slack,
            NotificationChannel.PAGERDUTY: mock_pagerduty,
        },
        alert_rules=_make_alert_rules(),
        escalation_policies=_make_escalation_policies(),
        now_fn=lambda: _NOW,
    )


# ---------------------------------------------------------------------------
# Tests: create_incident
# ---------------------------------------------------------------------------


class TestCreateIncident:
    """Tests for IncidentManager.create_incident."""

    def test_creates_incident_and_persists(
        self,
        manager: IncidentManager,
        repo: MockIncidentRepository,
    ) -> None:
        """create_incident saves the incident to the repository."""
        incident = manager.create_incident(
            trigger_type=AlertTriggerType.KILL_SWITCH_ACTIVATED,
            title="Kill switch activated: all symbols",
            details={"symbols": ["*"]},
            affected_services=["live-execution"],
        )

        assert repo.count() == 1
        stored = repo.find_by_id(incident.incident_id)
        assert stored.trigger_type == AlertTriggerType.KILL_SWITCH_ACTIVATED
        assert stored.severity == IncidentSeverity.P1
        assert stored.status == IncidentStatus.TRIGGERED

    def test_dispatches_to_pagerduty_and_slack(
        self,
        manager: IncidentManager,
        mock_slack: MagicMock,
        mock_pagerduty: MagicMock,
    ) -> None:
        """P1 kill switch triggers both PagerDuty and Slack notifications."""
        manager.create_incident(
            trigger_type=AlertTriggerType.KILL_SWITCH_ACTIVATED,
            title="Kill switch activated",
            details={},
            affected_services=["live-execution"],
        )

        mock_pagerduty.send_alert.assert_called_once()
        mock_slack.send_alert.assert_called_once()

    def test_dispatches_slack_only_for_slo_breach(
        self,
        manager: IncidentManager,
        mock_slack: MagicMock,
        mock_pagerduty: MagicMock,
    ) -> None:
        """SLO breach triggers only Slack, not PagerDuty."""
        manager.create_incident(
            trigger_type=AlertTriggerType.SLO_BREACH,
            title="SLO breach: p99 latency",
            details={},
            affected_services=["api"],
        )

        mock_slack.send_alert.assert_called_once()
        mock_pagerduty.send_alert.assert_not_called()

    def test_notification_failure_does_not_block_creation(
        self,
        manager: IncidentManager,
        mock_slack: MagicMock,
        mock_pagerduty: MagicMock,
        repo: MockIncidentRepository,
    ) -> None:
        """If Slack fails, the incident is still created."""
        mock_slack.send_alert.return_value = NotificationResult(
            channel=NotificationChannel.SLACK,
            success=False,
            error_message="webhook error",
        )

        incident = manager.create_incident(
            trigger_type=AlertTriggerType.KILL_SWITCH_ACTIVATED,
            title="Kill switch activated",
            details={},
            affected_services=["live-execution"],
        )

        assert repo.count() == 1
        assert incident.status == IncidentStatus.TRIGGERED

    def test_stores_pagerduty_dedup_key(
        self,
        manager: IncidentManager,
        mock_pagerduty: MagicMock,
        repo: MockIncidentRepository,
    ) -> None:
        """PagerDuty response_id is stored as pagerduty_incident_id."""
        incident = manager.create_incident(
            trigger_type=AlertTriggerType.KILL_SWITCH_ACTIVATED,
            title="Kill switch activated",
            details={},
            affected_services=["live-execution"],
        )

        stored = repo.find_by_id(incident.incident_id)
        assert stored.pagerduty_incident_id == "dedup-123"

    def test_sets_correct_severity_from_rule(
        self,
        manager: IncidentManager,
        repo: MockIncidentRepository,
    ) -> None:
        """Secret expiring should create a P4 incident."""
        incident = manager.create_incident(
            trigger_type=AlertTriggerType.SECRET_EXPIRING,
            title="API key expiring in 7 days",
            details={"secret_name": "ALPACA_API_KEY"},
            affected_services=["live-execution"],
        )

        assert incident.severity == IncidentSeverity.P4


# ---------------------------------------------------------------------------
# Tests: acknowledge_incident
# ---------------------------------------------------------------------------


class TestAcknowledgeIncident:
    """Tests for IncidentManager.acknowledge_incident."""

    def test_acknowledges_triggered_incident(
        self,
        manager: IncidentManager,
        repo: MockIncidentRepository,
    ) -> None:
        """acknowledge_incident transitions status to ACKNOWLEDGED."""
        incident = manager.create_incident(
            trigger_type=AlertTriggerType.KILL_SWITCH_ACTIVATED,
            title="Kill switch activated",
            details={},
            affected_services=["live-execution"],
        )

        acked = manager.acknowledge_incident(incident.incident_id)

        assert acked.status == IncidentStatus.ACKNOWLEDGED
        assert acked.acknowledged_at is not None

    def test_acknowledge_not_found_raises(
        self,
        manager: IncidentManager,
    ) -> None:
        """Acknowledging a nonexistent incident raises NotFoundError."""
        from libs.contracts.errors import NotFoundError

        with pytest.raises(NotFoundError):
            manager.acknowledge_incident("01HQNONEXISTENT00000000000")


# ---------------------------------------------------------------------------
# Tests: resolve_incident
# ---------------------------------------------------------------------------


class TestResolveIncident:
    """Tests for IncidentManager.resolve_incident."""

    def test_resolves_incident(
        self,
        manager: IncidentManager,
        repo: MockIncidentRepository,
    ) -> None:
        """resolve_incident transitions status to RESOLVED."""
        incident = manager.create_incident(
            trigger_type=AlertTriggerType.KILL_SWITCH_ACTIVATED,
            title="Kill switch activated",
            details={},
            affected_services=["live-execution"],
        )

        resolved = manager.resolve_incident(incident.incident_id)

        assert resolved.status == IncidentStatus.RESOLVED
        assert resolved.resolved_at is not None

    def test_resolve_sends_resolution_notifications(
        self,
        manager: IncidentManager,
        mock_slack: MagicMock,
        mock_pagerduty: MagicMock,
    ) -> None:
        """Resolution sends resolution notifications to providers."""
        incident = manager.create_incident(
            trigger_type=AlertTriggerType.KILL_SWITCH_ACTIVATED,
            title="Kill switch activated",
            details={},
            affected_services=["live-execution"],
        )

        manager.resolve_incident(incident.incident_id)

        mock_slack.send_resolution.assert_called_once()
        mock_pagerduty.send_resolution.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: check_escalations
# ---------------------------------------------------------------------------


class TestCheckEscalations:
    """Tests for IncidentManager.check_escalations."""

    def test_escalates_p1_after_15_minutes(
        self,
        repo: MockIncidentRepository,
        mock_slack: MagicMock,
        mock_pagerduty: MagicMock,
    ) -> None:
        """P1 incident unacknowledged for 16 minutes gets escalated."""
        from services.api.infrastructure.incident_manager import IncidentManager

        # Create at T=0
        create_time = _NOW
        manager_create = IncidentManager(
            incident_repo=repo,
            providers={
                NotificationChannel.SLACK: mock_slack,
                NotificationChannel.PAGERDUTY: mock_pagerduty,
            },
            alert_rules=_make_alert_rules(),
            escalation_policies=_make_escalation_policies(),
            now_fn=lambda: create_time,
        )
        manager_create.create_incident(
            trigger_type=AlertTriggerType.KILL_SWITCH_ACTIVATED,
            title="Kill switch activated",
            details={},
            affected_services=["live-execution"],
        )

        # Fast-forward to T=16min
        escalation_time = _NOW + timedelta(minutes=16)
        manager_escalate = IncidentManager(
            incident_repo=repo,
            providers={
                NotificationChannel.SLACK: mock_slack,
                NotificationChannel.PAGERDUTY: mock_pagerduty,
            },
            alert_rules=_make_alert_rules(),
            escalation_policies=_make_escalation_policies(),
            now_fn=lambda: escalation_time,
        )

        mock_slack.send_alert.reset_mock()
        mock_pagerduty.send_alert.reset_mock()

        escalated = manager_escalate.check_escalations()

        assert len(escalated) == 1
        assert escalated[0].status == IncidentStatus.ESCALATED
        assert escalated[0].escalated_at is not None
        # Should re-notify on escalation
        mock_slack.send_alert.assert_called_once()
        mock_pagerduty.send_alert.assert_called_once()

    def test_does_not_escalate_acknowledged_incident(
        self,
        repo: MockIncidentRepository,
        mock_slack: MagicMock,
        mock_pagerduty: MagicMock,
    ) -> None:
        """Acknowledged incidents are not escalated even past SLA."""
        from services.api.infrastructure.incident_manager import IncidentManager

        manager = IncidentManager(
            incident_repo=repo,
            providers={
                NotificationChannel.SLACK: mock_slack,
                NotificationChannel.PAGERDUTY: mock_pagerduty,
            },
            alert_rules=_make_alert_rules(),
            escalation_policies=_make_escalation_policies(),
            now_fn=lambda: _NOW,
        )
        incident = manager.create_incident(
            trigger_type=AlertTriggerType.KILL_SWITCH_ACTIVATED,
            title="Kill switch activated",
            details={},
            affected_services=["live-execution"],
        )
        manager.acknowledge_incident(incident.incident_id)

        # Fast forward past SLA
        escalation_time = _NOW + timedelta(minutes=30)
        manager_later = IncidentManager(
            incident_repo=repo,
            providers={
                NotificationChannel.SLACK: mock_slack,
                NotificationChannel.PAGERDUTY: mock_pagerduty,
            },
            alert_rules=_make_alert_rules(),
            escalation_policies=_make_escalation_policies(),
            now_fn=lambda: escalation_time,
        )

        mock_slack.send_alert.reset_mock()
        mock_pagerduty.send_alert.reset_mock()

        escalated = manager_later.check_escalations()

        assert len(escalated) == 0

    def test_does_not_escalate_within_sla(
        self,
        repo: MockIncidentRepository,
        mock_slack: MagicMock,
        mock_pagerduty: MagicMock,
    ) -> None:
        """P1 incident within 15 minutes is not escalated."""
        from services.api.infrastructure.incident_manager import IncidentManager

        manager = IncidentManager(
            incident_repo=repo,
            providers={
                NotificationChannel.SLACK: mock_slack,
                NotificationChannel.PAGERDUTY: mock_pagerduty,
            },
            alert_rules=_make_alert_rules(),
            escalation_policies=_make_escalation_policies(),
            now_fn=lambda: _NOW,
        )
        manager.create_incident(
            trigger_type=AlertTriggerType.KILL_SWITCH_ACTIVATED,
            title="Kill switch activated",
            details={},
            affected_services=["live-execution"],
        )

        # Only 5 minutes later
        manager_5min = IncidentManager(
            incident_repo=repo,
            providers={
                NotificationChannel.SLACK: mock_slack,
                NotificationChannel.PAGERDUTY: mock_pagerduty,
            },
            alert_rules=_make_alert_rules(),
            escalation_policies=_make_escalation_policies(),
            now_fn=lambda: _NOW + timedelta(minutes=5),
        )

        escalated = manager_5min.check_escalations()

        assert len(escalated) == 0
