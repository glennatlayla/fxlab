"""
Unit tests for Slack and PagerDuty notification providers (Phase 6 — M13).

Verifies:
    - SlackNotificationProvider sends well-formed webhook payloads.
    - PagerDutyNotificationProvider sends Events API v2 payloads.
    - Both providers handle HTTP errors gracefully (no exceptions leak).
    - Both providers return correct NotificationResult on success/failure.
    - Resolution notifications include correct event actions.

Dependencies:
    - pytest, unittest.mock for HTTP mocking.
    - IncidentRecord, NotificationResult contracts.

Example:
    pytest tests/unit/test_notification_providers.py -v
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from libs.contracts.notification import (
    AlertTriggerType,
    IncidentRecord,
    IncidentSeverity,
    IncidentStatus,
    NotificationChannel,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 12, 14, 0, 0, tzinfo=timezone.utc)


def _make_incident(
    *,
    severity: IncidentSeverity = IncidentSeverity.P1,
    status: IncidentStatus = IncidentStatus.TRIGGERED,
    trigger: AlertTriggerType = AlertTriggerType.KILL_SWITCH_ACTIVATED,
    pagerduty_id: str | None = None,
) -> IncidentRecord:
    """Build a test incident with sensible defaults."""
    return IncidentRecord(
        incident_id="01HQINCIDENT0000000000000A",
        trigger_type=trigger,
        severity=severity,
        status=status,
        title="Kill switch activated: all symbols",
        details={"symbols": ["*"], "activated_by": "operator@fxlab.test"},
        affected_services=["live-execution"],
        created_at=_NOW,
        pagerduty_incident_id=pagerduty_id,
    )


# ---------------------------------------------------------------------------
# Slack provider tests
# ---------------------------------------------------------------------------


class TestSlackNotificationProvider:
    """Tests for SlackNotificationProvider."""

    def test_send_alert_posts_to_webhook_url(self) -> None:
        """send_alert calls the webhook URL with a JSON payload."""
        from services.api.infrastructure.slack_notification_provider import (
            SlackNotificationProvider,
        )

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"
        mock_session.post.return_value = mock_response

        provider = SlackNotificationProvider(
            webhook_url="https://hooks.slack.com/services/T00/B00/xxx",
            channel="#incidents",
            http_session=mock_session,
        )
        incident = _make_incident()
        result = provider.send_alert(incident)

        assert result.success is True
        assert result.channel == NotificationChannel.SLACK
        mock_session.post.assert_called_once()
        call_kwargs = mock_session.post.call_args
        payload = json.loads(call_kwargs[1]["data"])
        assert payload["channel"] == "#incidents"
        assert "Kill switch" in payload["text"]

    def test_send_alert_includes_severity_and_details(self) -> None:
        """Slack payload contains severity, affected services, and details."""
        from services.api.infrastructure.slack_notification_provider import (
            SlackNotificationProvider,
        )

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"
        mock_session.post.return_value = mock_response

        provider = SlackNotificationProvider(
            webhook_url="https://hooks.slack.com/services/T00/B00/xxx",
            channel="#incidents",
            http_session=mock_session,
        )
        incident = _make_incident()
        provider.send_alert(incident)

        call_kwargs = mock_session.post.call_args
        payload = json.loads(call_kwargs[1]["data"])
        # Attachments should contain severity color-coded block
        assert len(payload.get("attachments", [])) > 0
        attachment = payload["attachments"][0]
        assert "P1" in attachment.get("text", "") or "P1" in str(attachment.get("fields", ""))

    def test_send_alert_returns_failure_on_http_error(self) -> None:
        """HTTP 500 from Slack webhook returns success=False, no exception."""
        from services.api.infrastructure.slack_notification_provider import (
            SlackNotificationProvider,
        )

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "internal_error"
        mock_session.post.return_value = mock_response

        provider = SlackNotificationProvider(
            webhook_url="https://hooks.slack.com/services/T00/B00/xxx",
            channel="#incidents",
            http_session=mock_session,
        )
        result = provider.send_alert(_make_incident())

        assert result.success is False
        assert "500" in result.error_message or "internal_error" in result.error_message

    def test_send_alert_returns_failure_on_connection_error(self) -> None:
        """Network error returns success=False, no exception leak."""
        from services.api.infrastructure.slack_notification_provider import (
            SlackNotificationProvider,
        )

        mock_session = MagicMock()
        mock_session.post.side_effect = ConnectionError("DNS resolution failed")

        provider = SlackNotificationProvider(
            webhook_url="https://hooks.slack.com/services/T00/B00/xxx",
            channel="#incidents",
            http_session=mock_session,
        )
        result = provider.send_alert(_make_incident())

        assert result.success is False
        assert "DNS" in result.error_message or "connection" in result.error_message.lower()

    def test_send_resolution_posts_resolution_message(self) -> None:
        """send_resolution sends a resolution message to Slack."""
        from services.api.infrastructure.slack_notification_provider import (
            SlackNotificationProvider,
        )

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"
        mock_session.post.return_value = mock_response

        provider = SlackNotificationProvider(
            webhook_url="https://hooks.slack.com/services/T00/B00/xxx",
            channel="#incidents",
            http_session=mock_session,
        )
        incident = _make_incident(status=IncidentStatus.RESOLVED)
        result = provider.send_resolution(incident)

        assert result.success is True
        call_kwargs = mock_session.post.call_args
        payload = json.loads(call_kwargs[1]["data"])
        assert "resolved" in payload["text"].lower() or "resolved" in str(payload).lower()


# ---------------------------------------------------------------------------
# PagerDuty provider tests
# ---------------------------------------------------------------------------


class TestPagerDutyNotificationProvider:
    """Tests for PagerDutyNotificationProvider."""

    def test_send_alert_posts_trigger_event(self) -> None:
        """send_alert sends a trigger event to PagerDuty Events API v2."""
        from services.api.infrastructure.pagerduty_notification_provider import (
            PagerDutyNotificationProvider,
        )

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {
            "status": "success",
            "dedup_key": "dedup-123",
        }
        mock_session.post.return_value = mock_response

        provider = PagerDutyNotificationProvider(
            routing_key="R0TESTKEY000000000000000000000000",
            http_session=mock_session,
        )
        result = provider.send_alert(_make_incident())

        assert result.success is True
        assert result.channel == NotificationChannel.PAGERDUTY
        assert result.response_id == "dedup-123"
        mock_session.post.assert_called_once()

        call_kwargs = mock_session.post.call_args
        payload = call_kwargs[1]["json"]
        assert payload["event_action"] == "trigger"
        assert payload["routing_key"] == "R0TESTKEY000000000000000000000000"
        assert payload["payload"]["severity"] == "critical"

    def test_send_alert_maps_severity_correctly(self) -> None:
        """P1→critical, P2→error, P3→warning, P4→info."""
        from services.api.infrastructure.pagerduty_notification_provider import (
            PagerDutyNotificationProvider,
        )

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {"status": "success", "dedup_key": "dk"}
        mock_session.post.return_value = mock_response

        provider = PagerDutyNotificationProvider(
            routing_key="R0TESTKEY000000000000000000000000",
            http_session=mock_session,
        )

        for severity, expected in [
            (IncidentSeverity.P1, "critical"),
            (IncidentSeverity.P2, "error"),
            (IncidentSeverity.P3, "warning"),
            (IncidentSeverity.P4, "info"),
        ]:
            mock_session.reset_mock()
            provider.send_alert(_make_incident(severity=severity))
            call_kwargs = mock_session.post.call_args
            payload = call_kwargs[1]["json"]
            assert payload["payload"]["severity"] == expected, (
                f"{severity.value} should map to {expected}"
            )

    def test_send_alert_returns_failure_on_http_error(self) -> None:
        """Non-202 from PagerDuty returns success=False."""
        from services.api.infrastructure.pagerduty_notification_provider import (
            PagerDutyNotificationProvider,
        )

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"
        mock_response.json.side_effect = ValueError("not json")
        mock_session.post.return_value = mock_response

        provider = PagerDutyNotificationProvider(
            routing_key="R0TESTKEY000000000000000000000000",
            http_session=mock_session,
        )
        result = provider.send_alert(_make_incident())

        assert result.success is False
        assert "400" in result.error_message

    def test_send_alert_returns_failure_on_connection_error(self) -> None:
        """Network error returns success=False."""
        from services.api.infrastructure.pagerduty_notification_provider import (
            PagerDutyNotificationProvider,
        )

        mock_session = MagicMock()
        mock_session.post.side_effect = ConnectionError("timeout")

        provider = PagerDutyNotificationProvider(
            routing_key="R0TESTKEY000000000000000000000000",
            http_session=mock_session,
        )
        result = provider.send_alert(_make_incident())

        assert result.success is False

    def test_send_resolution_posts_resolve_event(self) -> None:
        """send_resolution sends a resolve event with dedup_key."""
        from services.api.infrastructure.pagerduty_notification_provider import (
            PagerDutyNotificationProvider,
        )

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {"status": "success", "dedup_key": "dk"}
        mock_session.post.return_value = mock_response

        provider = PagerDutyNotificationProvider(
            routing_key="R0TESTKEY000000000000000000000000",
            http_session=mock_session,
        )
        incident = _make_incident(status=IncidentStatus.RESOLVED, pagerduty_id="dedup-orig")
        result = provider.send_resolution(incident)

        assert result.success is True
        call_kwargs = mock_session.post.call_args
        payload = call_kwargs[1]["json"]
        assert payload["event_action"] == "resolve"
        assert payload["dedup_key"] == "dedup-orig"

    def test_send_alert_uses_incident_id_as_dedup_key(self) -> None:
        """PagerDuty dedup_key is set to the incident_id for idempotency."""
        from services.api.infrastructure.pagerduty_notification_provider import (
            PagerDutyNotificationProvider,
        )

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {"status": "success", "dedup_key": "dk"}
        mock_session.post.return_value = mock_response

        provider = PagerDutyNotificationProvider(
            routing_key="R0TESTKEY000000000000000000000000",
            http_session=mock_session,
        )
        incident = _make_incident()
        provider.send_alert(incident)

        call_kwargs = mock_session.post.call_args
        payload = call_kwargs[1]["json"]
        assert payload["dedup_key"] == incident.incident_id
