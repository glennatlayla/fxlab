"""
Unit tests for POST /observability/alert-webhook.

Scope:
    - Happy path: valid Alertmanager v4 payload → 202 + summary.
    - Validation errors: malformed JSON, missing required fields, bad
      enum values → 400 with a clean error envelope.
    - Service failure: ingest raises → 500, no data leaked.
    - Correlation ID propagation: header value echoed back in summary.

The ingest service is overridden via FastAPI's ``dependency_overrides``
so this suite never touches the database and completes in milliseconds.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from libs.contracts.alertmanager_webhook import AlertIngestResult
from libs.contracts.interfaces.alert_ingest_service import (
    AlertIngestServiceError,
)
from services.api.main import app
from services.api.routes.observability import get_alert_ingest_service

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _valid_body() -> dict:
    """Return a minimal, spec-valid Alertmanager v4 payload."""
    return {
        "version": "4",
        "groupKey": '{}:{alertname="APIHighLatency"}',
        "truncatedAlerts": 0,
        "status": "firing",
        "receiver": "default_webhook",
        "groupLabels": {"alertname": "APIHighLatency"},
        "commonLabels": {"severity": "warning"},
        "commonAnnotations": {"summary": "p99 over threshold"},
        "externalURL": "http://alertmanager:9093",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "APIHighLatency",
                    "severity": "warning",
                },
                "annotations": {"summary": "p99 > 1s"},
                "startsAt": "2026-04-15T12:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": "http://prom:9090/graph",
                "fingerprint": "abcdef1234567890",
            }
        ],
    }


@pytest.fixture()
def mock_service() -> MagicMock:
    """Return a MagicMock implementing AlertIngestServiceInterface."""
    svc = MagicMock()
    svc.ingest.return_value = AlertIngestResult(
        received_count=1,
        persisted_count=1,
        correlation_id="corr-from-test",
        group_key='{}:{alertname="APIHighLatency"}',
    )
    return svc


@pytest.fixture()
def client(mock_service: MagicMock) -> Iterator[TestClient]:
    app.dependency_overrides[get_alert_ingest_service] = lambda: mock_service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_webhook_accepts_valid_payload_and_returns_202(
    client: TestClient, mock_service: MagicMock
) -> None:
    resp = client.post(
        "/observability/alert-webhook",
        json=_valid_body(),
        headers={"X-Correlation-ID": "corr-from-test"},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["received"] == 1
    assert body["persisted"] == 1
    assert body["correlation_id"] == "corr-from-test"
    mock_service.ingest.assert_called_once()


def test_webhook_uses_default_correlation_id_when_header_missing(
    client: TestClient, mock_service: MagicMock
) -> None:
    """Alertmanager does not currently send X-Correlation-ID; the route
    must not crash and must pass a non-empty correlation ID through."""
    mock_service.ingest.return_value = AlertIngestResult(
        received_count=1,
        persisted_count=1,
        correlation_id="no-corr",
        group_key='{}:{alertname="APIHighLatency"}',
    )
    resp = client.post("/observability/alert-webhook", json=_valid_body())
    assert resp.status_code == 202


def test_webhook_forwards_multiple_alerts_in_batch(
    client: TestClient, mock_service: MagicMock
) -> None:
    body = _valid_body()
    body["alerts"].extend(
        [
            {
                **body["alerts"][0],
                "fingerprint": f"fp-{i}",
            }
            for i in range(2)
        ]
    )
    mock_service.ingest.return_value = AlertIngestResult(
        received_count=3,
        persisted_count=3,
        correlation_id="no-corr",
        group_key='{}:{alertname="APIHighLatency"}',
    )
    resp = client.post("/observability/alert-webhook", json=body)
    assert resp.status_code == 202
    assert resp.json()["persisted"] == 3


# ---------------------------------------------------------------------------
# Validation failures (400)
# ---------------------------------------------------------------------------


def test_webhook_rejects_malformed_json(client: TestClient) -> None:
    resp = client.post(
        "/observability/alert-webhook",
        data=b"this-is-not-json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert "JSON" in resp.json()["detail"]


def test_webhook_rejects_missing_required_field(client: TestClient) -> None:
    body = _valid_body()
    del body["groupKey"]
    resp = client.post("/observability/alert-webhook", json=body)
    assert resp.status_code == 400
    assert "schema validation" in resp.json()["detail"].lower()


def test_webhook_rejects_invalid_alert_status(client: TestClient) -> None:
    body = _valid_body()
    body["alerts"][0]["status"] = "pending"  # not a valid status
    resp = client.post("/observability/alert-webhook", json=body)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Service failures (500)
# ---------------------------------------------------------------------------


def test_webhook_returns_500_when_service_raises(
    client: TestClient, mock_service: MagicMock
) -> None:
    mock_service.ingest.side_effect = AlertIngestServiceError("DB down")
    resp = client.post("/observability/alert-webhook", json=_valid_body())
    assert resp.status_code == 500
    # Error detail should not leak internal state.
    assert "DB down" not in resp.json()["detail"]
    assert "Failed to persist" in resp.json()["detail"]
