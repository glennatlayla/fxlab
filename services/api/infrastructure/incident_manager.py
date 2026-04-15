"""
Incident lifecycle manager (Phase 6 — M13).

Purpose:
    Orchestrate the full incident lifecycle: creation, notification dispatch,
    acknowledgment, escalation, and resolution.  Acts as the central hub
    that connects alert rules, notification providers, and incident persistence.

Responsibilities:
    - create_incident: Create an incident, match alert rules, dispatch notifications.
    - acknowledge_incident: Mark an incident as acknowledged.
    - resolve_incident: Mark an incident as resolved, send resolution notifications.
    - check_escalations: Find unacknowledged incidents past SLA and auto-escalate.

Does NOT:
    - Deliver notifications directly (delegates to NotificationProviderInterface).
    - Persist incidents directly (delegates to IncidentRepositoryInterface).
    - Schedule escalation checks (caller / job scheduler responsibility).

Dependencies:
    - IncidentRepositoryInterface (injected): Incident persistence.
    - NotificationProviderInterface dict (injected): Channel→provider mapping.
    - AlertRule list (injected): Trigger→severity/channel routing configuration.
    - EscalationPolicy list (injected): SLA timing for auto-escalation.
    - now_fn callable (injected): Clock abstraction for deterministic testing.

Error conditions:
    - NotFoundError: If an incident_id is unknown for ack/resolve operations.
    - Notification failures are logged but never block incident operations.

Example:
    manager = IncidentManager(
        incident_repo=repo,
        providers={NotificationChannel.SLACK: slack, NotificationChannel.PAGERDUTY: pd},
        alert_rules=rules,
        escalation_policies=policies,
    )
    incident = manager.create_incident(
        trigger_type=AlertTriggerType.KILL_SWITCH_ACTIVATED,
        title="Kill switch activated: all symbols",
        details={"symbols": ["*"]},
        affected_services=["live-execution"],
    )
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import structlog
import ulid as _ulid

from libs.contracts.interfaces.incident_repository_interface import (
    IncidentRepositoryInterface,
)
from libs.contracts.notification import (
    AlertRule,
    AlertTriggerType,
    EscalationPolicy,
    IncidentRecord,
    IncidentSeverity,
    IncidentStatus,
    NotificationChannel,
    NotificationResult,
)
from services.api.infrastructure.interfaces.notification_provider_interface import (
    NotificationProviderInterface,
)

logger = structlog.get_logger(__name__)


class IncidentManager:
    """
    Central orchestrator for incident lifecycle management.

    Connects alert rules, notification providers, and incident persistence
    to handle the full incident flow: trigger → dispatch → ack → resolve,
    with automatic escalation on SLA timeout.

    Responsibilities:
        - Create incidents with correct severity from alert rules.
        - Dispatch notifications to all channels configured for the trigger.
        - Track PagerDuty dedup keys for resolution matching.
        - Auto-escalate unacknowledged incidents past their SLA.

    Does NOT:
        - Schedule escalation checks (caller / background job responsibility).
        - Modify alert rules or escalation policies at runtime.
        - Handle notification retries (provider/adapter responsibility).

    Dependencies:
        - IncidentRepositoryInterface (injected): Persistence layer.
        - dict[NotificationChannel, NotificationProviderInterface] (injected):
          Provider implementations keyed by channel type.
        - list[AlertRule] (injected): Alert routing configuration.
        - list[EscalationPolicy] (injected): Escalation timing rules.
        - Callable[[], datetime] now_fn (injected): Clock for testability.

    Raises:
        - NotFoundError: On ack/resolve of unknown incident_id.

    Example:
        manager = IncidentManager(
            incident_repo=repo,
            providers={...},
            alert_rules=rules,
            escalation_policies=policies,
        )
        incident = manager.create_incident(
            trigger_type=AlertTriggerType.KILL_SWITCH_ACTIVATED,
            title="Kill switch activated",
            details={},
            affected_services=["live-execution"],
        )
    """

    def __init__(
        self,
        *,
        incident_repo: IncidentRepositoryInterface,
        providers: dict[NotificationChannel, NotificationProviderInterface],
        alert_rules: list[AlertRule],
        escalation_policies: list[EscalationPolicy],
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        """
        Initialize the incident manager.

        Args:
            incident_repo: Repository for incident persistence.
            providers: Notification providers keyed by channel type.
            alert_rules: Alert rules mapping triggers to severity/channels.
            escalation_policies: Escalation timing rules by severity.
            now_fn: Optional clock function for deterministic testing.
                    Defaults to ``datetime.now(timezone.utc)``.
        """
        self._repo = incident_repo
        self._providers = providers
        self._rules: dict[AlertTriggerType, AlertRule] = {
            rule.trigger_type: rule for rule in alert_rules
        }
        self._escalation: dict[IncidentSeverity, EscalationPolicy] = {
            policy.severity: policy for policy in escalation_policies
        }
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_incident(
        self,
        *,
        trigger_type: AlertTriggerType,
        title: str,
        details: dict[str, Any],
        affected_services: list[str],
    ) -> IncidentRecord:
        """
        Create a new incident, persist it, and dispatch notifications.

        Looks up the AlertRule for the given trigger_type to determine
        severity and notification channels.  If no rule exists, defaults
        to P3 severity with Slack-only notification.

        Notification failures are logged but do NOT block incident creation.
        The incident is persisted regardless of notification success.

        Args:
            trigger_type: The event that triggered this incident.
            title: Short human-readable summary.
            details: Structured details about the triggering event.
            affected_services: List of affected service names.

        Returns:
            The created IncidentRecord with incident_id and status=TRIGGERED.

        Example:
            incident = manager.create_incident(
                trigger_type=AlertTriggerType.KILL_SWITCH_ACTIVATED,
                title="Kill switch activated: all symbols",
                details={"symbols": ["*"]},
                affected_services=["live-execution"],
            )
        """
        now = self._now_fn()
        rule = self._rules.get(trigger_type)

        severity = rule.severity if rule else IncidentSeverity.P3
        channels = rule.channels if rule else [NotificationChannel.SLACK]

        incident = IncidentRecord(
            incident_id=str(_ulid.ULID()),
            trigger_type=trigger_type,
            severity=severity,
            status=IncidentStatus.TRIGGERED,
            title=title,
            details=details,
            affected_services=affected_services,
            created_at=now,
        )

        # Persist first — incident exists regardless of notification outcome
        self._repo.save(incident)

        logger.info(
            "incident.created",
            operation="create_incident",
            component="IncidentManager",
            incident_id=incident.incident_id,
            trigger_type=trigger_type.value,
            severity=severity.value,
            channels=[c.value for c in channels],
        )

        # Dispatch notifications to configured channels
        results = self._dispatch_notifications(incident, channels)

        # Store PagerDuty dedup key if available
        pd_result = next(
            (r for r in results if r.channel == NotificationChannel.PAGERDUTY and r.success),
            None,
        )
        if pd_result and pd_result.response_id:
            incident = incident.model_copy(update={"pagerduty_incident_id": pd_result.response_id})
            self._repo.save(incident)

        return incident

    def acknowledge_incident(self, incident_id: str) -> IncidentRecord:
        """
        Mark an incident as acknowledged.

        Transitions the incident from TRIGGERED/ESCALATED to ACKNOWLEDGED
        and records the acknowledgment timestamp.

        Args:
            incident_id: ULID of the incident to acknowledge.

        Returns:
            The updated IncidentRecord with status=ACKNOWLEDGED.

        Raises:
            NotFoundError: If the incident does not exist.

        Example:
            acked = manager.acknowledge_incident("01HQINCIDENT...")
        """
        now = self._now_fn()
        incident = self._repo.find_by_id(incident_id)

        updated = incident.model_copy(
            update={
                "status": IncidentStatus.ACKNOWLEDGED,
                "acknowledged_at": now,
            }
        )
        self._repo.save(updated)

        logger.info(
            "incident.acknowledged",
            operation="acknowledge_incident",
            component="IncidentManager",
            incident_id=incident_id,
            severity=updated.severity.value,
        )

        return updated

    def resolve_incident(self, incident_id: str) -> IncidentRecord:
        """
        Mark an incident as resolved and send resolution notifications.

        Transitions the incident to RESOLVED, records the resolution
        timestamp, and dispatches resolution notifications to all
        channels configured for the incident's trigger type.

        Args:
            incident_id: ULID of the incident to resolve.

        Returns:
            The updated IncidentRecord with status=RESOLVED.

        Raises:
            NotFoundError: If the incident does not exist.

        Example:
            resolved = manager.resolve_incident("01HQINCIDENT...")
        """
        now = self._now_fn()
        incident = self._repo.find_by_id(incident_id)

        updated = incident.model_copy(
            update={
                "status": IncidentStatus.RESOLVED,
                "resolved_at": now,
            }
        )
        self._repo.save(updated)

        logger.info(
            "incident.resolved",
            operation="resolve_incident",
            component="IncidentManager",
            incident_id=incident_id,
            severity=updated.severity.value,
        )

        # Send resolution notifications
        rule = self._rules.get(updated.trigger_type)
        channels = rule.channels if rule else [NotificationChannel.SLACK]
        self._dispatch_resolutions(updated, channels)

        return updated

    def check_escalations(self) -> list[IncidentRecord]:
        """
        Find and auto-escalate unacknowledged incidents past their SLA.

        Queries the incident repository for triggered incidents whose
        creation time exceeds the acknowledgment SLA defined in the
        escalation policy.  Escalated incidents are marked as ESCALATED
        and re-notified to the escalation channels.

        Returns:
            List of IncidentRecord objects that were escalated.

        Example:
            escalated = manager.check_escalations()
            for inc in escalated:
                print(f"Escalated: {inc.incident_id}")
        """
        now = self._now_fn()
        severity_sla_map = {
            sev.value: policy.ack_timeout_seconds for sev, policy in self._escalation.items()
        }

        past_sla = self._repo.find_unacknowledged_past_sla(severity_sla_map, now)
        escalated: list[IncidentRecord] = []

        for incident in past_sla:
            policy = self._escalation.get(incident.severity)
            if policy is None:
                continue

            updated = incident.model_copy(
                update={
                    "status": IncidentStatus.ESCALATED,
                    "escalated_at": now,
                    "severity": policy.escalate_to_severity,
                }
            )
            self._repo.save(updated)

            logger.warning(
                "incident.escalated",
                operation="check_escalations",
                component="IncidentManager",
                incident_id=incident.incident_id,
                original_severity=incident.severity.value,
                escalated_severity=policy.escalate_to_severity.value,
                ack_timeout_seconds=policy.ack_timeout_seconds,
            )

            # Re-notify on escalation channels
            self._dispatch_notifications(updated, policy.notify_channels)
            escalated.append(updated)

        return escalated

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _dispatch_notifications(
        self,
        incident: IncidentRecord,
        channels: list[NotificationChannel],
    ) -> list[NotificationResult]:
        """
        Dispatch alert notifications to all specified channels.

        Failures are logged but never raised — notifications must not
        block the calling operation.

        Args:
            incident: The incident to notify about.
            channels: List of channels to send to.

        Returns:
            List of NotificationResult from each channel.
        """
        results: list[NotificationResult] = []
        for channel in channels:
            provider = self._providers.get(channel)
            if provider is None:
                logger.warning(
                    "notification.provider_not_found",
                    operation="dispatch_notifications",
                    component="IncidentManager",
                    channel=channel.value,
                    incident_id=incident.incident_id,
                )
                continue

            try:
                result = provider.send_alert(incident)
                results.append(result)
                if not result.success:
                    logger.warning(
                        "notification.dispatch_failed",
                        operation="dispatch_notifications",
                        component="IncidentManager",
                        channel=channel.value,
                        incident_id=incident.incident_id,
                        error=result.error_message,
                    )
            except Exception as exc:
                logger.error(
                    "notification.dispatch_exception",
                    operation="dispatch_notifications",
                    component="IncidentManager",
                    channel=channel.value,
                    incident_id=incident.incident_id,
                    error=str(exc),
                    exc_info=True,
                )
                results.append(
                    NotificationResult(
                        channel=channel,
                        success=False,
                        error_message=str(exc),
                    )
                )

        return results

    def _dispatch_resolutions(
        self,
        incident: IncidentRecord,
        channels: list[NotificationChannel],
    ) -> list[NotificationResult]:
        """
        Dispatch resolution notifications to all specified channels.

        Args:
            incident: The resolved incident.
            channels: List of channels to send to.

        Returns:
            List of NotificationResult from each channel.
        """
        results: list[NotificationResult] = []
        for channel in channels:
            provider = self._providers.get(channel)
            if provider is None:
                continue

            try:
                result = provider.send_resolution(incident)
                results.append(result)
            except Exception as exc:
                logger.error(
                    "notification.resolution_exception",
                    operation="dispatch_resolutions",
                    component="IncidentManager",
                    channel=channel.value,
                    incident_id=incident.incident_id,
                    error=str(exc),
                    exc_info=True,
                )

        return results
