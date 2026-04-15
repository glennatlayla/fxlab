"""
PagerDuty notification provider (Phase 6 — M13).

Purpose:
    Deliver incident alerts and resolutions to PagerDuty via the Events
    API v2.  Maps FXLab incident severity to PagerDuty urgency levels
    and uses incident_id as the dedup_key for idempotent event handling.

Responsibilities:
    - send_alert: Create a trigger event in PagerDuty.
    - send_resolution: Create a resolve event in PagerDuty.

Does NOT:
    - Manage PagerDuty service or escalation policy configuration.
    - Retry on failure (caller or resilient adapter responsibility).
    - Handle PagerDuty REST API (uses Events API v2 only).

Dependencies:
    - requests.Session (injected): HTTP client for API calls.
    - IncidentRecord, NotificationResult contracts.
    - structlog: Structured logging.

Error conditions:
    - HTTP errors and connection failures are caught and returned as
      NotificationResult(success=False) — never raised to the caller.

Example:
    provider = PagerDutyNotificationProvider(
        routing_key="R0KEY...",
    )
    result = provider.send_alert(incident)
"""

from __future__ import annotations

import structlog
from requests import Session as HttpSession  # type: ignore[import-untyped]

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

_EVENTS_API_URL = "https://events.pagerduty.com/v2/enqueue"

# PagerDuty Events API v2 severity mapping
_SEVERITY_MAP: dict[IncidentSeverity, str] = {
    IncidentSeverity.P1: "critical",
    IncidentSeverity.P2: "error",
    IncidentSeverity.P3: "warning",
    IncidentSeverity.P4: "info",
}

_API_TIMEOUT_S = 10


class PagerDutyNotificationProvider(NotificationProviderInterface):
    """
    PagerDuty Events API v2 notification provider.

    Sends trigger and resolve events to PagerDuty using the Events API v2.
    Uses the incident_id as the dedup_key for idempotent event handling,
    preventing duplicate alerts for the same incident.

    Responsibilities:
        - Map FXLab incident severity to PagerDuty severity.
        - Format Events API v2 payloads with incident metadata.
        - POST events to the PagerDuty enqueue endpoint.
        - Return success/failure results without raising exceptions.

    Does NOT:
        - Manage PagerDuty routing keys or service configuration.
        - Retry on failure (caller responsibility).

    Dependencies:
        - requests.Session (injected or default): HTTP client.

    Example:
        provider = PagerDutyNotificationProvider(routing_key="R0KEY...")
        result = provider.send_alert(incident)
    """

    def __init__(
        self,
        *,
        routing_key: str,
        http_session: HttpSession | None = None,
        events_api_url: str = _EVENTS_API_URL,
    ) -> None:
        """
        Initialize the PagerDuty notification provider.

        Args:
            routing_key: PagerDuty Events API v2 integration/routing key.
            http_session: Optional HTTP session for connection pooling and testing.
            events_api_url: PagerDuty Events API endpoint URL (overridable for testing).
        """
        self._routing_key = routing_key
        self._http = http_session or HttpSession()
        self._events_api_url = events_api_url

    def send_alert(self, incident: IncidentRecord) -> NotificationResult:
        """
        Send a trigger event to PagerDuty for the given incident.

        Creates an Events API v2 trigger event with the incident's severity
        mapped to PagerDuty severity, and uses incident_id as the dedup_key.

        Args:
            incident: The incident to alert on.

        Returns:
            NotificationResult with success/failure and dedup_key as response_id.

        Example:
            result = provider.send_alert(incident)
            assert result.success
            assert result.response_id  # PagerDuty dedup_key
        """
        pd_severity = _SEVERITY_MAP.get(incident.severity, "warning")

        payload = {
            "routing_key": self._routing_key,
            "event_action": "trigger",
            "dedup_key": incident.incident_id,
            "payload": {
                "summary": f"[{incident.severity.value}] {incident.title}",
                "source": "fxlab-trading-platform",
                "severity": pd_severity,
                "component": ", ".join(incident.affected_services) or "unknown",
                "custom_details": {
                    "incident_id": incident.incident_id,
                    "trigger_type": incident.trigger_type.value,
                    "details": incident.details,
                    "affected_services": incident.affected_services,
                    "created_at": incident.created_at.isoformat(),
                },
            },
        }

        return self._post(payload, incident, "trigger")

    def send_resolution(self, incident: IncidentRecord) -> NotificationResult:
        """
        Send a resolve event to PagerDuty for the given incident.

        Uses the pagerduty_incident_id (if available) or incident_id as
        the dedup_key to match the original trigger event.

        Args:
            incident: The resolved incident.

        Returns:
            NotificationResult indicating delivery success or failure.

        Example:
            result = provider.send_resolution(resolved_incident)
        """
        dedup_key = incident.pagerduty_incident_id or incident.incident_id

        payload = {
            "routing_key": self._routing_key,
            "event_action": "resolve",
            "dedup_key": dedup_key,
        }

        return self._post(payload, incident, "resolve")

    def _post(
        self,
        payload: dict,
        incident: IncidentRecord,
        action: str,
    ) -> NotificationResult:
        """
        POST a JSON payload to the PagerDuty Events API.

        Args:
            payload: Events API v2 JSON payload.
            incident: The incident being notified (for logging context).
            action: Event action name ("trigger" or "resolve").

        Returns:
            NotificationResult with success/failure.
        """
        try:
            response = self._http.post(
                self._events_api_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=_API_TIMEOUT_S,
            )
        except Exception as exc:
            error_msg = f"PagerDuty {action} failed: {exc}"
            logger.warning(
                "notification.pagerduty.send_failed",
                operation=f"send_{action}",
                component="PagerDutyNotificationProvider",
                incident_id=incident.incident_id,
                error=str(exc),
            )
            return NotificationResult(
                channel=NotificationChannel.PAGERDUTY,
                success=False,
                error_message=error_msg,
            )

        if response.status_code != 202:
            error_msg = f"PagerDuty {action} returned HTTP {response.status_code}"
            logger.warning(
                "notification.pagerduty.non_202",
                operation=f"send_{action}",
                component="PagerDutyNotificationProvider",
                incident_id=incident.incident_id,
                status_code=response.status_code,
            )
            return NotificationResult(
                channel=NotificationChannel.PAGERDUTY,
                success=False,
                error_message=error_msg,
            )

        # Extract dedup_key from response
        dedup_key = ""
        try:
            resp_data = response.json()
            dedup_key = resp_data.get("dedup_key", "")
        except (ValueError, AttributeError):
            pass

        logger.info(
            f"notification.pagerduty.{action}_sent",
            operation=f"send_{action}",
            component="PagerDutyNotificationProvider",
            incident_id=incident.incident_id,
            dedup_key=dedup_key,
            result="success",
        )

        return NotificationResult(
            channel=NotificationChannel.PAGERDUTY,
            success=True,
            response_id=dedup_key,
        )
