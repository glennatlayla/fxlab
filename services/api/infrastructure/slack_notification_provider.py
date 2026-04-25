"""
Slack notification provider (Phase 6 — M13).

Purpose:
    Deliver incident alert and resolution messages to Slack channels via
    incoming webhooks.  Formats messages with severity-coded attachments
    for operator readability.

Responsibilities:
    - send_alert: Post a structured incident alert to Slack.
    - send_resolution: Post a resolution confirmation to Slack.

Does NOT:
    - Decide when to send (notification service / incident manager responsibility).
    - Retry on failure (caller or resilient adapter responsibility).
    - Manage Slack app configuration or OAuth tokens.

Dependencies:
    - requests.Session (injected): HTTP client for webhook calls.
    - IncidentRecord, NotificationResult contracts.
    - structlog: Structured logging.

Error conditions:
    - HTTP errors and connection failures are caught and returned as
      NotificationResult(success=False) — never raised to the caller.

Example:
    provider = SlackNotificationProvider(
        webhook_url="https://hooks.slack.com/services/T00/B00/xxx",
        channel="#incidents",
    )
    result = provider.send_alert(incident)
"""

from __future__ import annotations

import json

import structlog
from requests import Session as HttpSession

from libs.contracts.notification import (
    IncidentRecord,
    IncidentSeverity,
    NotificationChannel,
    NotificationResult,
)
from services.api.infrastructure.interfaces.notification_provider_interface import (
    NotificationProviderInterface,
)

logger = structlog.get_logger(__name__)

# Slack attachment color codes by severity
_SEVERITY_COLORS: dict[IncidentSeverity, str] = {
    IncidentSeverity.P1: "#FF0000",  # Red — critical
    IncidentSeverity.P2: "#FF8C00",  # Orange — high
    IncidentSeverity.P3: "#FFD700",  # Gold — medium
    IncidentSeverity.P4: "#4169E1",  # Blue — informational
}

_WEBHOOK_TIMEOUT_S = 10


class SlackNotificationProvider(NotificationProviderInterface):
    """
    Slack webhook-based notification provider.

    Sends structured messages to a configured Slack channel via an incoming
    webhook URL.  Messages include severity-coded attachments with incident
    details for operator triage.

    Responsibilities:
        - Format incident data into Slack-compatible JSON payloads.
        - POST payloads to the configured webhook URL.
        - Return success/failure results without raising exceptions.

    Does NOT:
        - Manage webhook URL rotation or Slack app lifecycle.
        - Retry on failure (caller responsibility).

    Dependencies:
        - requests.Session (injected or default): HTTP client.

    Example:
        provider = SlackNotificationProvider(
            webhook_url="https://hooks.slack.com/services/T00/B00/xxx",
            channel="#incidents",
        )
        result = provider.send_alert(incident)
    """

    def __init__(
        self,
        *,
        webhook_url: str,
        channel: str = "#alerts",
        http_session: HttpSession | None = None,
    ) -> None:
        """
        Initialize the Slack notification provider.

        Args:
            webhook_url: Slack incoming webhook URL.
            channel: Default Slack channel to post to.
            http_session: Optional HTTP session for connection pooling and testing.
        """
        self._webhook_url = webhook_url
        self._channel = channel
        self._http = http_session or HttpSession()

    def send_alert(self, incident: IncidentRecord) -> NotificationResult:
        """
        Send an incident alert to Slack.

        Formats the incident as a color-coded attachment with severity,
        affected services, trigger details, and timestamps.

        Args:
            incident: The incident to alert on.

        Returns:
            NotificationResult indicating delivery success or failure.

        Example:
            result = provider.send_alert(incident)
            assert result.success
        """
        color = _SEVERITY_COLORS.get(incident.severity, "#808080")
        fields = [
            {"title": "Severity", "value": incident.severity.value, "short": True},
            {"title": "Trigger", "value": incident.trigger_type.value, "short": True},
            {
                "title": "Affected Services",
                "value": ", ".join(incident.affected_services) or "N/A",
                "short": True,
            },
            {
                "title": "Incident ID",
                "value": incident.incident_id,
                "short": True,
            },
        ]

        if incident.details:
            details_str = ", ".join(f"{k}: {v}" for k, v in incident.details.items())
            fields.append({"title": "Details", "value": details_str, "short": False})

        payload = {
            "channel": self._channel,
            "text": f":rotating_light: *Incident Alert — {incident.severity.value}*: {incident.title}",
            "attachments": [
                {
                    "color": color,
                    "text": f"Severity: {incident.severity.value} | Status: {incident.status.value}",
                    "fields": fields,
                    "ts": str(int(incident.created_at.timestamp())),
                }
            ],
        }

        return self._post(payload, incident, "alert")

    def send_resolution(self, incident: IncidentRecord) -> NotificationResult:
        """
        Send an incident resolution message to Slack.

        Args:
            incident: The resolved incident.

        Returns:
            NotificationResult indicating delivery success or failure.

        Example:
            result = provider.send_resolution(resolved_incident)
        """
        payload = {
            "channel": self._channel,
            "text": (
                f":white_check_mark: *Incident Resolved — {incident.severity.value}*: "
                f"{incident.title}"
            ),
            "attachments": [
                {
                    "color": "#36A64F",  # Green for resolved
                    "text": (f"Incident {incident.incident_id} has been resolved."),
                    "fields": [
                        {
                            "title": "Severity",
                            "value": incident.severity.value,
                            "short": True,
                        },
                        {
                            "title": "Status",
                            "value": "resolved",
                            "short": True,
                        },
                    ],
                }
            ],
        }

        return self._post(payload, incident, "resolution")

    def _post(
        self,
        payload: dict,
        incident: IncidentRecord,
        action: str,
    ) -> NotificationResult:
        """
        POST a JSON payload to the Slack webhook.

        Args:
            payload: JSON-serializable Slack message payload.
            incident: The incident being notified (for logging context).
            action: Human-readable action name ("alert" or "resolution").

        Returns:
            NotificationResult with success/failure.
        """
        try:
            response = self._http.post(
                self._webhook_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=_WEBHOOK_TIMEOUT_S,
            )
        except Exception as exc:
            error_msg = f"Slack {action} failed: {exc}"
            logger.warning(
                "notification.slack.send_failed",
                operation=f"send_{action}",
                component="SlackNotificationProvider",
                incident_id=incident.incident_id,
                error=str(exc),
            )
            return NotificationResult(
                channel=NotificationChannel.SLACK,
                success=False,
                error_message=error_msg,
            )

        if response.status_code != 200:
            error_msg = f"Slack {action} returned HTTP {response.status_code}: {response.text}"
            logger.warning(
                "notification.slack.non_200",
                operation=f"send_{action}",
                component="SlackNotificationProvider",
                incident_id=incident.incident_id,
                status_code=response.status_code,
                response_text=response.text,
            )
            return NotificationResult(
                channel=NotificationChannel.SLACK,
                success=False,
                error_message=error_msg,
            )

        logger.info(
            f"notification.slack.{action}_sent",
            operation=f"send_{action}",
            component="SlackNotificationProvider",
            incident_id=incident.incident_id,
            channel=self._channel,
            result="success",
        )

        return NotificationResult(
            channel=NotificationChannel.SLACK,
            success=True,
        )
