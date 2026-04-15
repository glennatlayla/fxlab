"""
Notification configuration and alert rule definitions (Phase 6 — M13).

Purpose:
    Define the default alert routing rules and escalation policies for
    the FXLab incident automation system.  Provides factory functions
    for constructing the IncidentManager with production configuration.

Responsibilities:
    - DEFAULT_ALERT_RULES: Maps critical events to severity and channels.
    - DEFAULT_ESCALATION_POLICIES: Defines SLA timing for auto-escalation.
    - create_incident_manager: Factory that wires providers, rules, and repo.

Does NOT:
    - Deliver notifications (provider responsibility).
    - Persist incidents (repository responsibility).
    - Manage provider credentials (environment / secret manager responsibility).

Dependencies:
    - AlertRule, EscalationPolicy, NotificationChannel, IncidentSeverity contracts.
    - IncidentManager: Orchestration target.
    - NotificationProviderInterface: Provider implementations.
    - IncidentRepositoryInterface: Persistence layer.

Alert routing rules:
    - Kill switch activated  → P1 → PagerDuty + Slack #incidents
    - Kill switch deactivated → P4 → Slack #incidents (informational)
    - Circuit breaker OPEN   → P2 → PagerDuty + Slack #alerts
    - Circuit breaker CLOSED → P4 → Slack #alerts (informational)
    - SLO breach            → P2 → Slack #alerts
    - Secret expiring       → P4 → Slack #ops
    - Reconciliation discrepancy → P3 → Slack #alerts
    - VaR threshold breach      → P2 → PagerDuty + Slack #risk-alerts
    - Concentration breach      → P3 → Slack #risk-alerts
    - Correlation spike         → P3 → Slack #risk-alerts

Escalation policies:
    - P1: Auto-escalate after 15 minutes (900s) → PagerDuty + Slack
    - P2: Auto-escalate after 1 hour (3600s) → escalate to P1 → PagerDuty + Slack

Example:
    from services.api.infrastructure.notification_config import (
        DEFAULT_ALERT_RULES,
        DEFAULT_ESCALATION_POLICIES,
        create_incident_manager,
    )
    manager = create_incident_manager(
        incident_repo=repo,
        slack_webhook_url="https://hooks.slack.com/services/...",
        pagerduty_routing_key="R0KEY...",
    )
"""

from __future__ import annotations

import os

import structlog

from libs.contracts.interfaces.incident_repository_interface import (
    IncidentRepositoryInterface,
)
from libs.contracts.notification import (
    AlertRule,
    AlertTriggerType,
    EscalationPolicy,
    IncidentSeverity,
    NotificationChannel,
)
from services.api.infrastructure.incident_manager import IncidentManager
from services.api.infrastructure.interfaces.notification_provider_interface import (
    NotificationProviderInterface,
)
from services.api.infrastructure.pagerduty_notification_provider import (
    PagerDutyNotificationProvider,
)
from services.api.infrastructure.slack_notification_provider import (
    SlackNotificationProvider,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Default alert routing rules
# ---------------------------------------------------------------------------


DEFAULT_ALERT_RULES: list[AlertRule] = [
    # Kill switch — highest priority, immediate operator response
    AlertRule(
        trigger_type=AlertTriggerType.KILL_SWITCH_ACTIVATED,
        severity=IncidentSeverity.P1,
        channels=[NotificationChannel.PAGERDUTY, NotificationChannel.SLACK],
        slack_channel="#incidents",
        description="Kill switch activated — all trading halted",
    ),
    AlertRule(
        trigger_type=AlertTriggerType.KILL_SWITCH_DEACTIVATED,
        severity=IncidentSeverity.P4,
        channels=[NotificationChannel.SLACK],
        slack_channel="#incidents",
        description="Kill switch deactivated — trading resumed",
    ),
    # Circuit breaker — high priority, prompt investigation
    AlertRule(
        trigger_type=AlertTriggerType.CIRCUIT_BREAKER_OPEN,
        severity=IncidentSeverity.P2,
        channels=[NotificationChannel.PAGERDUTY, NotificationChannel.SLACK],
        slack_channel="#alerts",
        description="Circuit breaker tripped — external service degraded",
    ),
    AlertRule(
        trigger_type=AlertTriggerType.CIRCUIT_BREAKER_CLOSED,
        severity=IncidentSeverity.P4,
        channels=[NotificationChannel.SLACK],
        slack_channel="#alerts",
        description="Circuit breaker recovered — service restored",
    ),
    # SLO breach — high priority, investigate within business hours
    AlertRule(
        trigger_type=AlertTriggerType.SLO_BREACH,
        severity=IncidentSeverity.P2,
        channels=[NotificationChannel.SLACK],
        slack_channel="#alerts",
        description="SLO breach detected — performance target missed",
    ),
    # Secret expiring — low priority, ops team notification
    AlertRule(
        trigger_type=AlertTriggerType.SECRET_EXPIRING,
        severity=IncidentSeverity.P4,
        channels=[NotificationChannel.SLACK],
        slack_channel="#ops",
        description="Secret expiring within 14 days — rotation required",
    ),
    # Reconciliation discrepancy — medium priority
    AlertRule(
        trigger_type=AlertTriggerType.RECONCILIATION_DISCREPANCY,
        severity=IncidentSeverity.P3,
        channels=[NotificationChannel.SLACK],
        slack_channel="#alerts",
        description="Reconciliation discrepancy detected — manual review required",
    ),
    # Phase 7 M11 — Risk alerting triggers
    AlertRule(
        trigger_type=AlertTriggerType.VAR_THRESHOLD_BREACH,
        severity=IncidentSeverity.P2,
        channels=[NotificationChannel.PAGERDUTY, NotificationChannel.SLACK],
        slack_channel="#risk-alerts",
        description="Portfolio VaR exceeds configured threshold — risk exposure too high",
    ),
    AlertRule(
        trigger_type=AlertTriggerType.CONCENTRATION_THRESHOLD_BREACH,
        severity=IncidentSeverity.P3,
        channels=[NotificationChannel.SLACK],
        slack_channel="#risk-alerts",
        description="Single position concentration exceeds threshold — portfolio undiversified",
    ),
    AlertRule(
        trigger_type=AlertTriggerType.CORRELATION_SPIKE,
        severity=IncidentSeverity.P3,
        channels=[NotificationChannel.SLACK],
        slack_channel="#risk-alerts",
        description="Pairwise correlation spike detected — diversification benefit reduced",
    ),
]


# ---------------------------------------------------------------------------
# Default escalation policies
# ---------------------------------------------------------------------------


DEFAULT_ESCALATION_POLICIES: list[EscalationPolicy] = [
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


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------


def create_incident_manager(
    *,
    incident_repo: IncidentRepositoryInterface,
    slack_webhook_url: str | None = None,
    pagerduty_routing_key: str | None = None,
    alert_rules: list[AlertRule] | None = None,
    escalation_policies: list[EscalationPolicy] | None = None,
) -> IncidentManager:
    """
    Factory function to create a fully wired IncidentManager.

    Reads notification credentials from environment variables if not
    provided explicitly.  Falls back gracefully — if a provider's
    credentials are missing, that channel is simply omitted.

    Args:
        incident_repo: Repository for incident persistence.
        slack_webhook_url: Slack incoming webhook URL (env: SLACK_WEBHOOK_URL).
        pagerduty_routing_key: PagerDuty Events API routing key
            (env: PAGERDUTY_ROUTING_KEY).
        alert_rules: Custom alert rules (defaults to DEFAULT_ALERT_RULES).
        escalation_policies: Custom escalation policies
            (defaults to DEFAULT_ESCALATION_POLICIES).

    Returns:
        Configured IncidentManager ready for use.

    Example:
        manager = create_incident_manager(incident_repo=repo)
    """
    providers: dict[NotificationChannel, NotificationProviderInterface] = {}

    # Wire Slack provider
    slack_url = slack_webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")
    if slack_url:
        providers[NotificationChannel.SLACK] = SlackNotificationProvider(
            webhook_url=slack_url,
        )
        logger.info(
            "notification_config.slack_configured",
            operation="create_incident_manager",
            component="notification_config",
        )
    else:
        logger.warning(
            "notification_config.slack_not_configured",
            operation="create_incident_manager",
            component="notification_config",
            reason="SLACK_WEBHOOK_URL not set",
        )

    # Wire PagerDuty provider
    pd_key = pagerduty_routing_key or os.environ.get("PAGERDUTY_ROUTING_KEY", "")
    if pd_key:
        providers[NotificationChannel.PAGERDUTY] = PagerDutyNotificationProvider(
            routing_key=pd_key,
        )
        logger.info(
            "notification_config.pagerduty_configured",
            operation="create_incident_manager",
            component="notification_config",
        )
    else:
        logger.warning(
            "notification_config.pagerduty_not_configured",
            operation="create_incident_manager",
            component="notification_config",
            reason="PAGERDUTY_ROUTING_KEY not set",
        )

    return IncidentManager(
        incident_repo=incident_repo,
        providers=providers,
        alert_rules=alert_rules or DEFAULT_ALERT_RULES,
        escalation_policies=escalation_policies or DEFAULT_ESCALATION_POLICIES,
    )
