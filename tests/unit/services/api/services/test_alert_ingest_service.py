"""
Unit tests for services.api.services.alert_ingest_service.AlertIngestService.

Scope:
    Verify that the service correctly transforms a validated payload,
    hands the domain records to the repository, returns an accurate
    summary, and surfaces persistence errors as AlertIngestServiceError.
    All I/O is faked — the tests complete in milliseconds.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from libs.contracts.alertmanager_webhook import (
    AlertmanagerWebhookPayload,
    AlertNotification,
)
from libs.contracts.interfaces.alert_ingest_service import (
    AlertIngestServiceError,
)
from libs.contracts.interfaces.alert_notification_repository import (
    AlertNotificationRepositoryError,
    AlertNotificationRepositoryInterface,
)
from services.api.services.alert_ingest_service import AlertIngestService

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class _FakeAlertRepository(AlertNotificationRepositoryInterface):
    """Captures batches so tests can assert what the service persisted."""

    saved_batches: list[list[AlertNotification]] = field(default_factory=list)
    raise_on_save: Exception | None = None
    raise_on_count: Exception | None = None

    def save_batch(self, notifications: list[AlertNotification]) -> int:
        if self.raise_on_save is not None:
            raise self.raise_on_save
        self.saved_batches.append(list(notifications))
        return len(notifications)

    def count_by_fingerprint(self, fingerprint: str) -> int:
        if self.raise_on_count is not None:
            raise self.raise_on_count
        return sum(1 for batch in self.saved_batches for n in batch if n.fingerprint == fingerprint)


def _deterministic_id_factory() -> callable:
    counter = itertools.count(1)
    return lambda: f"01HTEST{next(counter):020d}"


def _fixed_clock(ts: datetime) -> callable:
    return lambda: ts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_payload(alert_count: int = 1) -> AlertmanagerWebhookPayload:
    """Build a valid payload with the requested number of alerts."""
    alerts = [
        {
            "status": "firing",
            "labels": {
                "alertname": "APIHighLatency",
                "severity": "warning",
                "idx": str(i),
            },
            "annotations": {"summary": f"alert {i}"},
            "startsAt": "2026-04-15T12:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "generatorURL": "http://prom:9090/graph",
            "fingerprint": f"fp-{i:04d}",
        }
        for i in range(alert_count)
    ]
    return AlertmanagerWebhookPayload.model_validate(
        {
            "version": "4",
            "groupKey": '{}:{alertname="APIHighLatency"}',
            "status": "firing",
            "receiver": "default_webhook",
            "groupLabels": {"alertname": "APIHighLatency"},
            "commonLabels": {"severity": "warning"},
            "commonAnnotations": {},
            "externalURL": "http://alertmanager:9093",
            "alerts": alerts,
        }
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_ingest_persists_all_alerts_in_batch() -> None:
    repo = _FakeAlertRepository()
    clock_ts = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
    service = AlertIngestService(
        repository=repo,
        id_factory=_deterministic_id_factory(),
        clock=_fixed_clock(clock_ts),
    )
    payload = _make_payload(alert_count=3)

    result = service.ingest(payload, correlation_id="corr-abc")

    assert result.received_count == 3
    assert result.persisted_count == 3
    assert result.correlation_id == "corr-abc"
    assert result.group_key == payload.groupKey

    assert len(repo.saved_batches) == 1
    persisted = repo.saved_batches[0]
    assert [n.fingerprint for n in persisted] == [
        "fp-0000",
        "fp-0001",
        "fp-0002",
    ]
    # All notifications in the batch share one received_at.
    assert {n.received_at for n in persisted} == {clock_ts}


def test_ingest_handles_empty_batch() -> None:
    """An empty payload persists nothing but still returns a summary."""
    repo = _FakeAlertRepository()
    service = AlertIngestService(
        repository=repo,
        id_factory=_deterministic_id_factory(),
        clock=_fixed_clock(datetime(2026, 4, 15, tzinfo=timezone.utc)),
    )
    payload = _make_payload(alert_count=0)

    result = service.ingest(payload, correlation_id="corr-empty")

    assert result.received_count == 0
    assert result.persisted_count == 0
    # Empty batch still goes to the repo (which is a no-op in that case).
    assert repo.saved_batches == [[]]


def test_ingest_assigns_unique_ids() -> None:
    repo = _FakeAlertRepository()
    service = AlertIngestService(
        repository=repo,
        id_factory=_deterministic_id_factory(),
        clock=_fixed_clock(datetime(2026, 4, 15, tzinfo=timezone.utc)),
    )
    payload = _make_payload(alert_count=5)

    service.ingest(payload, correlation_id="corr-ids")

    ids = [n.id for n in repo.saved_batches[0]]
    assert len(set(ids)) == 5  # all unique


# ---------------------------------------------------------------------------
# Error path
# ---------------------------------------------------------------------------


def test_ingest_wraps_repository_error_as_service_error() -> None:
    repo = _FakeAlertRepository(raise_on_save=AlertNotificationRepositoryError("DB down"))
    service = AlertIngestService(
        repository=repo,
        id_factory=_deterministic_id_factory(),
        clock=_fixed_clock(datetime(2026, 4, 15, tzinfo=timezone.utc)),
    )
    payload = _make_payload(alert_count=2)

    with pytest.raises(AlertIngestServiceError) as excinfo:
        service.ingest(payload, correlation_id="corr-err")

    assert isinstance(excinfo.value.__cause__, AlertNotificationRepositoryError)
    # No batch was successfully persisted.
    assert repo.saved_batches == []


def test_ingest_default_id_factory_produces_unique_strings() -> None:
    """The default ULID factory must not produce collisions."""
    repo = _FakeAlertRepository()
    service = AlertIngestService(repository=repo)
    payload = _make_payload(alert_count=10)

    service.ingest(payload, correlation_id="corr-ulid")

    ids = [n.id for n in repo.saved_batches[0]]
    assert len(set(ids)) == 10
    # ULID strings are 26 chars — defensive check that we're not getting
    # back the empty string or a random stub.
    assert all(len(i) == 26 for i in ids)


def test_ingest_default_clock_returns_utc_aware() -> None:
    """The injected clock default must produce a UTC-aware datetime so
    downstream storage stays consistent."""
    repo = _FakeAlertRepository()
    service = AlertIngestService(repository=repo)
    payload = _make_payload(alert_count=1)

    service.ingest(payload, correlation_id="corr-clock")

    received = repo.saved_batches[0][0].received_at
    assert received.tzinfo is not None
    assert received.utcoffset().total_seconds() == 0
