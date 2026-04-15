"""
Unit tests for libs.contracts.alertmanager_webhook.

Scope:
    Contract-level verification that the Pydantic models correctly parse
    real Alertmanager v4 payloads, reject protocol violations, normalise
    the unresolved ``endsAt`` sentinel, and build a clean domain record
    via ``AlertNotification.from_payload``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from libs.contracts.alertmanager_webhook import (
    AlertIngestResult,
    AlertmanagerAlert,
    AlertmanagerWebhookPayload,
    AlertNotification,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _sample_alert(**overrides) -> dict:
    """Return a minimally-valid Alertmanager alert payload."""
    base = {
        "status": "firing",
        "labels": {"alertname": "APIHighLatency", "severity": "warning"},
        "annotations": {"summary": "p99 latency > 1s"},
        "startsAt": "2026-04-15T12:00:00Z",
        "endsAt": "0001-01-01T00:00:00Z",
        "generatorURL": "http://prometheus:9090/graph?g0.expr=...",
        "fingerprint": "abcdef1234567890",
    }
    base.update(overrides)
    return base


def _sample_payload(**overrides) -> dict:
    """Return a minimally-valid Alertmanager webhook payload."""
    base = {
        "version": "4",
        "groupKey": '{}:{alertname="APIHighLatency"}',
        "truncatedAlerts": 0,
        "status": "firing",
        "receiver": "default_webhook",
        "groupLabels": {"alertname": "APIHighLatency"},
        "commonLabels": {"severity": "warning"},
        "commonAnnotations": {"runbook_url": "https://runbooks.example/latency"},
        "externalURL": "http://alertmanager:9093",
        "alerts": [_sample_alert()],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# AlertmanagerAlert
# ---------------------------------------------------------------------------


def test_alert_parses_valid_firing_alert() -> None:
    """A well-formed firing alert parses cleanly with no surprises."""
    alert = AlertmanagerAlert.model_validate(_sample_alert())
    assert alert.status == "firing"
    assert alert.fingerprint == "abcdef1234567890"
    assert alert.endsAt is None  # unresolved sentinel normalised to None


def test_alert_normalises_unresolved_end_at_to_none() -> None:
    alert = AlertmanagerAlert.model_validate(_sample_alert(endsAt="0001-01-01T00:00:00Z"))
    assert alert.endsAt is None


def test_alert_preserves_real_end_at() -> None:
    alert = AlertmanagerAlert.model_validate(
        _sample_alert(status="resolved", endsAt="2026-04-15T12:05:00Z")
    )
    assert alert.endsAt is not None
    assert alert.endsAt.year == 2026


def test_alert_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        AlertmanagerAlert.model_validate(_sample_alert(status="pending"))


def test_alert_rejects_empty_fingerprint() -> None:
    with pytest.raises(ValidationError):
        AlertmanagerAlert.model_validate(_sample_alert(fingerprint=""))


def test_alert_ignores_extra_fields_for_forward_compatibility() -> None:
    """Upstream may add fields — we should not reject them."""
    alert = AlertmanagerAlert.model_validate(_sample_alert(brandNewFieldFromAlertmanagerV5="x"))
    assert alert.status == "firing"


def test_alert_rejects_too_many_labels() -> None:
    huge_labels = {f"k{i}": "v" for i in range(1001)}
    with pytest.raises(ValidationError):
        AlertmanagerAlert.model_validate(_sample_alert(labels=huge_labels))


# ---------------------------------------------------------------------------
# AlertmanagerWebhookPayload
# ---------------------------------------------------------------------------


def test_payload_parses_happy_path() -> None:
    payload = AlertmanagerWebhookPayload.model_validate(_sample_payload())
    assert payload.version == "4"
    assert payload.receiver == "default_webhook"
    assert len(payload.alerts) == 1


def test_payload_rejects_missing_required_field() -> None:
    body = _sample_payload()
    del body["groupKey"]
    with pytest.raises(ValidationError):
        AlertmanagerWebhookPayload.model_validate(body)


def test_payload_accepts_empty_alerts_list() -> None:
    """Alertmanager can send an empty batch; don't reject it here."""
    payload = AlertmanagerWebhookPayload.model_validate(_sample_payload(alerts=[]))
    assert payload.alerts == []


def test_payload_rejects_oversized_batch() -> None:
    huge_batch = [_sample_alert(fingerprint=f"fp{i}") for i in range(513)]
    with pytest.raises(ValidationError):
        AlertmanagerWebhookPayload.model_validate(_sample_payload(alerts=huge_batch))


# ---------------------------------------------------------------------------
# AlertNotification.from_payload
# ---------------------------------------------------------------------------


def test_from_payload_flattens_common_fields() -> None:
    payload = AlertmanagerWebhookPayload.model_validate(_sample_payload())
    alert = payload.alerts[0]
    received_at = datetime(2026, 4, 15, 12, 0, 30, tzinfo=timezone.utc)

    notification = AlertNotification.from_payload(
        id="01HWEBHOOK000000000000000001",
        payload=payload,
        alert=alert,
        received_at=received_at,
    )

    assert notification.id == "01HWEBHOOK000000000000000001"
    assert notification.alertname == "APIHighLatency"
    assert notification.severity == "warning"
    assert notification.receiver == "default_webhook"
    assert notification.group_key == payload.groupKey
    assert notification.ends_at is None  # was unresolved sentinel
    # starts_at and received_at must be timezone-aware UTC
    assert notification.starts_at.tzinfo is not None
    assert notification.received_at.tzinfo is not None


def test_from_payload_leaves_missing_label_as_empty_string() -> None:
    alert_data = _sample_alert(labels={"alertname": "Foo"})  # no severity
    payload = AlertmanagerWebhookPayload.model_validate(_sample_payload(alerts=[alert_data]))
    notification = AlertNotification.from_payload(
        id="01HNOTIF",
        payload=payload,
        alert=payload.alerts[0],
        received_at=datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc),
    )
    assert notification.severity == ""  # LL-007: "" not None


def test_from_payload_coerces_naive_datetimes_to_utc() -> None:
    """Naive datetimes (e.g. from tests) must be treated as UTC."""
    alert = AlertmanagerAlert.model_validate(_sample_alert(startsAt="2026-04-15T12:00:00Z"))
    payload = AlertmanagerWebhookPayload.model_validate(_sample_payload())
    naive = datetime(2026, 4, 15, 12, 0, 30)  # no tzinfo
    notification = AlertNotification.from_payload(
        id="01H", payload=payload, alert=alert, received_at=naive
    )
    assert notification.received_at.tzinfo is timezone.utc


def test_notification_rejects_bad_status() -> None:
    with pytest.raises(ValidationError):
        AlertNotification(
            id="01H",
            fingerprint="fp",
            status="unknown",
            alertname="",
            severity="",
            starts_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
            receiver="r",
            group_key="g",
            received_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
        )


def test_notification_is_frozen() -> None:
    notification = AlertNotification(
        id="01H",
        fingerprint="fp",
        status="firing",
        alertname="",
        severity="",
        starts_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
        receiver="r",
        group_key="g",
        received_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
    )
    with pytest.raises(ValidationError):
        notification.id = "something-else"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AlertIngestResult
# ---------------------------------------------------------------------------


def test_ingest_result_rejects_negative_counts() -> None:
    with pytest.raises(ValidationError):
        AlertIngestResult(
            received_count=-1,
            persisted_count=0,
            correlation_id="c",
            group_key="g",
        )


def test_ingest_result_is_frozen() -> None:
    result = AlertIngestResult(
        received_count=1,
        persisted_count=1,
        correlation_id="c",
        group_key="g",
    )
    with pytest.raises(ValidationError):
        result.persisted_count = 99  # type: ignore[misc]
