"""
Unit tests for notification configuration and alert rules (Phase 6 — M13).

Verifies:
    - DEFAULT_ALERT_RULES covers all required trigger types.
    - Kill switch activation maps to P1 with PagerDuty + Slack.
    - Circuit breaker OPEN maps to P2 with PagerDuty + Slack.
    - SLO breach maps to P2 with Slack only.
    - Secret expiring maps to P4 with Slack only.
    - DEFAULT_ESCALATION_POLICIES covers P1 (15 min) and P2 (1 hour).
    - create_incident_manager wires providers from explicit credentials.
    - create_incident_manager omits providers when credentials are missing.

Dependencies:
    - pytest.
    - notification_config module.
    - MockIncidentRepository.

Example:
    pytest tests/unit/test_notification_config.py -v
"""

from __future__ import annotations

import os
from unittest.mock import patch

from libs.contracts.mocks.mock_incident_repository import MockIncidentRepository
from libs.contracts.notification import (
    AlertTriggerType,
    IncidentSeverity,
    NotificationChannel,
)
from services.api.infrastructure.notification_config import (
    DEFAULT_ALERT_RULES,
    DEFAULT_ESCALATION_POLICIES,
    create_incident_manager,
)

# ---------------------------------------------------------------------------
# Tests: DEFAULT_ALERT_RULES
# ---------------------------------------------------------------------------


class TestDefaultAlertRules:
    """Tests for DEFAULT_ALERT_RULES configuration."""

    def test_covers_kill_switch_activated(self) -> None:
        """Kill switch activation has a P1 rule with PagerDuty and Slack."""
        rule = next(
            r
            for r in DEFAULT_ALERT_RULES
            if r.trigger_type == AlertTriggerType.KILL_SWITCH_ACTIVATED
        )
        assert rule.severity == IncidentSeverity.P1
        assert NotificationChannel.PAGERDUTY in rule.channels
        assert NotificationChannel.SLACK in rule.channels
        assert rule.slack_channel == "#incidents"

    def test_covers_circuit_breaker_open(self) -> None:
        """Circuit breaker OPEN has a P2 rule with PagerDuty and Slack."""
        rule = next(
            r
            for r in DEFAULT_ALERT_RULES
            if r.trigger_type == AlertTriggerType.CIRCUIT_BREAKER_OPEN
        )
        assert rule.severity == IncidentSeverity.P2
        assert NotificationChannel.PAGERDUTY in rule.channels
        assert NotificationChannel.SLACK in rule.channels

    def test_covers_slo_breach(self) -> None:
        """SLO breach has a P2 rule with Slack only."""
        rule = next(r for r in DEFAULT_ALERT_RULES if r.trigger_type == AlertTriggerType.SLO_BREACH)
        assert rule.severity == IncidentSeverity.P2
        assert NotificationChannel.SLACK in rule.channels
        assert NotificationChannel.PAGERDUTY not in rule.channels

    def test_covers_secret_expiring(self) -> None:
        """Secret expiring has a P4 rule with Slack #ops."""
        rule = next(
            r for r in DEFAULT_ALERT_RULES if r.trigger_type == AlertTriggerType.SECRET_EXPIRING
        )
        assert rule.severity == IncidentSeverity.P4
        assert rule.slack_channel == "#ops"

    def test_covers_reconciliation_discrepancy(self) -> None:
        """Reconciliation discrepancy has a P3 rule."""
        rule = next(
            r
            for r in DEFAULT_ALERT_RULES
            if r.trigger_type == AlertTriggerType.RECONCILIATION_DISCREPANCY
        )
        assert rule.severity == IncidentSeverity.P3

    def test_all_trigger_types_have_rules(self) -> None:
        """Every AlertTriggerType has at least one matching rule."""
        covered_triggers = {r.trigger_type for r in DEFAULT_ALERT_RULES}
        for trigger in AlertTriggerType:
            assert trigger in covered_triggers, f"Missing alert rule for {trigger.value}"


# ---------------------------------------------------------------------------
# Tests: DEFAULT_ESCALATION_POLICIES
# ---------------------------------------------------------------------------


class TestDefaultEscalationPolicies:
    """Tests for DEFAULT_ESCALATION_POLICIES configuration."""

    def test_p1_escalation_15_minutes(self) -> None:
        """P1 incidents escalate after 15 minutes (900 seconds)."""
        policy = next(p for p in DEFAULT_ESCALATION_POLICIES if p.severity == IncidentSeverity.P1)
        assert policy.ack_timeout_seconds == 900

    def test_p2_escalation_1_hour(self) -> None:
        """P2 incidents escalate after 1 hour (3600 seconds)."""
        policy = next(p for p in DEFAULT_ESCALATION_POLICIES if p.severity == IncidentSeverity.P2)
        assert policy.ack_timeout_seconds == 3600

    def test_p2_escalates_to_p1(self) -> None:
        """P2 escalation upgrades severity to P1."""
        policy = next(p for p in DEFAULT_ESCALATION_POLICIES if p.severity == IncidentSeverity.P2)
        assert policy.escalate_to_severity == IncidentSeverity.P1


# ---------------------------------------------------------------------------
# Tests: create_incident_manager factory
# ---------------------------------------------------------------------------


class TestCreateIncidentManager:
    """Tests for create_incident_manager factory function."""

    def test_wires_providers_with_explicit_credentials(self) -> None:
        """Explicit credentials create both Slack and PagerDuty providers."""
        repo = MockIncidentRepository()
        manager = create_incident_manager(
            incident_repo=repo,
            slack_webhook_url="https://hooks.slack.com/services/T00/B00/xxx",
            pagerduty_routing_key="R0KEY000000000000000000000000000",
        )

        assert NotificationChannel.SLACK in manager._providers
        assert NotificationChannel.PAGERDUTY in manager._providers

    def test_omits_slack_when_url_missing(self) -> None:
        """No Slack URL → Slack provider omitted (not an error)."""
        repo = MockIncidentRepository()
        with patch.dict(os.environ, {}, clear=True):
            manager = create_incident_manager(
                incident_repo=repo,
                pagerduty_routing_key="R0KEY000000000000000000000000000",
            )

        assert NotificationChannel.SLACK not in manager._providers
        assert NotificationChannel.PAGERDUTY in manager._providers

    def test_omits_pagerduty_when_key_missing(self) -> None:
        """No PagerDuty key → PagerDuty provider omitted."""
        repo = MockIncidentRepository()
        with patch.dict(os.environ, {}, clear=True):
            manager = create_incident_manager(
                incident_repo=repo,
                slack_webhook_url="https://hooks.slack.com/services/T00/B00/xxx",
            )

        assert NotificationChannel.SLACK in manager._providers
        assert NotificationChannel.PAGERDUTY not in manager._providers

    def test_uses_default_rules_and_policies(self) -> None:
        """Factory uses DEFAULT_ALERT_RULES and DEFAULT_ESCALATION_POLICIES."""
        repo = MockIncidentRepository()
        manager = create_incident_manager(
            incident_repo=repo,
            slack_webhook_url="https://hooks.slack.com/services/T00/B00/xxx",
        )

        assert len(manager._rules) == len(DEFAULT_ALERT_RULES)
        assert len(manager._escalation) == len(DEFAULT_ESCALATION_POLICIES)
