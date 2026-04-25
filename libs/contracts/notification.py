"""
Notification and incident automation contracts (Phase 6 — M13).

Purpose:
    Define the data structures for incident notification, alert routing,
    and escalation policy enforcement.  Used by the notification dispatch
    pipeline (Slack, PagerDuty) and the incident lifecycle manager.

Responsibilities:
    - IncidentSeverity: P1–P4 severity classification.
    - NotificationChannel: Delivery targets (Slack, PagerDuty).
    - AlertTriggerType: Events that can fire alerts.
    - AlertRule: Maps a trigger type to severity, channels, and message template.
    - IncidentRecord: Tracks an incident through create → ack → resolve lifecycle.
    - NotificationResult: Result of a single notification dispatch attempt.
    - EscalationPolicy: Timing rules for auto-escalation on unacknowledged incidents.

Does NOT:
    - Contain dispatch logic (service responsibility).
    - Access external APIs (adapter responsibility).

Dependencies:
    - pydantic: Validation and serialization.

Example:
    from libs.contracts.notification import IncidentSeverity, AlertRule
    rule = AlertRule(
        trigger_type=AlertTriggerType.KILL_SWITCH_ACTIVATED,
        severity=IncidentSeverity.P1,
        channels=[NotificationChannel.PAGERDUTY, NotificationChannel.SLACK],
        slack_channel="#incidents",
    )
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class IncidentSeverity(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """
    Incident severity classification aligned with PagerDuty urgency levels.

    P1 — Critical: immediate operator response required (kill switch, system down).
    P2 — High: prompt response needed (circuit breaker, SLO breach).
    P3 — Medium: investigate within business hours (reconciliation discrepancy).
    P4 — Low: informational (secret expiring, maintenance reminder).
    """

    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class NotificationChannel(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """
    Notification delivery channels.

    SLACK — Webhook-based Slack message to a named channel.
    PAGERDUTY — PagerDuty Events API v2 alert creation.
    """

    SLACK = "slack"
    PAGERDUTY = "pagerduty"


class AlertTriggerType(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """
    Events that can trigger automated incident notifications.

    Each trigger type maps to one or more AlertRules that determine
    severity, delivery channels, and message content.
    """

    KILL_SWITCH_ACTIVATED = "kill_switch_activated"
    KILL_SWITCH_DEACTIVATED = "kill_switch_deactivated"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"
    CIRCUIT_BREAKER_CLOSED = "circuit_breaker_closed"
    SLO_BREACH = "slo_breach"
    SECRET_EXPIRING = "secret_expiring"
    RECONCILIATION_DISCREPANCY = "reconciliation_discrepancy"
    # Phase 7 M11 — Risk Dashboard & Alerting triggers
    VAR_THRESHOLD_BREACH = "var_threshold_breach"
    CONCENTRATION_THRESHOLD_BREACH = "concentration_threshold_breach"
    CORRELATION_SPIKE = "correlation_spike"


class IncidentStatus(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """
    Incident lifecycle states.

    TRIGGERED — Initial state: alert fired, awaiting acknowledgment.
    ACKNOWLEDGED — Operator confirmed receipt and is investigating.
    RESOLVED — Incident closed (either manually or automatically).
    ESCALATED — Auto-escalated due to SLA timeout on acknowledgment.
    """

    TRIGGERED = "triggered"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class AlertRule(BaseModel):
    """
    Maps a trigger type to notification parameters.

    Each AlertRule defines what happens when a specific event fires:
    which severity to assign, which channels to notify, and what
    Slack channel name to use.

    Attributes:
        trigger_type: The event that activates this rule.
        severity: Incident severity for this trigger.
        channels: List of notification channels to send to.
        slack_channel: Slack channel name (e.g., "#incidents").
        description: Human-readable description of the rule.

    Example:
        rule = AlertRule(
            trigger_type=AlertTriggerType.KILL_SWITCH_ACTIVATED,
            severity=IncidentSeverity.P1,
            channels=[NotificationChannel.PAGERDUTY, NotificationChannel.SLACK],
            slack_channel="#incidents",
            description="Kill switch activated — all trading halted",
        )
    """

    trigger_type: AlertTriggerType
    severity: IncidentSeverity
    channels: list[NotificationChannel]
    slack_channel: str = Field(default="#alerts")
    description: str = Field(default="")

    model_config = {"frozen": True}


class EscalationPolicy(BaseModel):
    """
    Defines auto-escalation timing for unacknowledged incidents.

    If an incident is not acknowledged within ``ack_timeout_seconds``,
    it is automatically escalated to a higher severity or broader channel.

    Attributes:
        severity: Severity level this policy applies to.
        ack_timeout_seconds: Seconds before auto-escalation.
        escalate_to_severity: Target severity after escalation.
        notify_channels: Additional channels to notify on escalation.

    Example:
        policy = EscalationPolicy(
            severity=IncidentSeverity.P1,
            ack_timeout_seconds=900,  # 15 minutes
            escalate_to_severity=IncidentSeverity.P1,
            notify_channels=[NotificationChannel.PAGERDUTY, NotificationChannel.SLACK],
        )
    """

    severity: IncidentSeverity
    ack_timeout_seconds: int = Field(ge=60)
    escalate_to_severity: IncidentSeverity
    notify_channels: list[NotificationChannel]

    model_config = {"frozen": True}


class IncidentRecord(BaseModel):
    """
    Tracks an incident through its lifecycle.

    Immutable once resolved; mutable through acknowledge/escalate/resolve
    operations only via the IncidentManager service.

    Attributes:
        incident_id: ULID primary key.
        trigger_type: The event that caused this incident.
        severity: Current severity (may change on escalation).
        status: Current lifecycle state.
        title: Short human-readable summary.
        details: Structured details about the triggering event.
        affected_services: List of service names affected.
        created_at: When the incident was triggered.
        acknowledged_at: When an operator acknowledged (None if not yet).
        resolved_at: When the incident was resolved (None if not yet).
        escalated_at: When auto-escalation fired (None if not escalated).
        pagerduty_incident_id: PagerDuty incident key (None if not sent).

    Example:
        incident = IncidentRecord(
            incident_id="01HQINCIDENT0000000000000",
            trigger_type=AlertTriggerType.KILL_SWITCH_ACTIVATED,
            severity=IncidentSeverity.P1,
            status=IncidentStatus.TRIGGERED,
            title="Kill switch activated: all symbols",
            details={"symbols": ["*"], "activated_by": "system"},
            affected_services=["live-execution"],
        )
    """

    incident_id: str
    trigger_type: AlertTriggerType
    severity: IncidentSeverity
    status: IncidentStatus = Field(default=IncidentStatus.TRIGGERED)
    title: str
    details: dict = Field(default_factory=dict)
    affected_services: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    acknowledged_at: datetime | None = Field(default=None)
    resolved_at: datetime | None = Field(default=None)
    escalated_at: datetime | None = Field(default=None)
    pagerduty_incident_id: str | None = Field(default=None)

    model_config = {"from_attributes": True}


class NotificationResult(BaseModel):
    """
    Result of a single notification dispatch attempt.

    Attributes:
        channel: The channel the notification was sent to.
        success: Whether the dispatch succeeded.
        error_message: Error details if dispatch failed.
        response_id: External ID returned by the provider (e.g., PagerDuty dedup_key).

    Example:
        result = NotificationResult(
            channel=NotificationChannel.SLACK,
            success=True,
        )
    """

    channel: NotificationChannel
    success: bool
    error_message: str = Field(default="")
    response_id: str = Field(default="")
