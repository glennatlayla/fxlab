"""
Contracts for Alertmanager webhook ingestion.

Purpose:
    Parse and validate the Prometheus Alertmanager v4 webhook payload that
    FXLab's Alertmanager POSTs to ``/observability/alert-webhook``.
    Provide a stable domain model (``AlertNotification``) so downstream
    persistence and business logic never see raw HTTP JSON.

Responsibilities:
    - Define ``AlertmanagerAlert`` and ``AlertmanagerWebhookPayload``
      Pydantic models matching the Alertmanager v4 JSON schema exactly
      (field names are mixedCase where upstream uses mixedCase).
    - Define the internal ``AlertNotification`` domain record used by the
      service and repository layers.
    - Provide ``AlertIngestResult`` — the value returned by the ingest
      service so route handlers have a small, serialisable summary.

Does NOT:
    - Persist data (that is the repository layer).
    - Evaluate alert semantics or route notifications (service layer).
    - Include framework-specific concerns (FastAPI lives in routes/).

Dependencies:
    - Pydantic v2.

Schema reference:
    https://prometheus.io/docs/alerting/latest/configuration/#webhook_config

Example:
    payload = AlertmanagerWebhookPayload.model_validate(body_json)
    notifications = [
        AlertNotification.from_payload(payload, alert)
        for alert in payload.alerts
    ]
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Alertmanager sends this sentinel in ``endsAt`` when the alert is still
#: firing (i.e. no resolution time yet). We normalise it to ``None``.
_UNRESOLVED_END_AT = "0001-01-01T00:00:00Z"

#: Valid Alertmanager alert statuses. The spec is closed — other values
#: indicate a protocol mismatch worth rejecting at the boundary.
_VALID_STATUSES: frozenset[str] = frozenset({"firing", "resolved"})

#: Maximum label/annotation count per alert. A single alert with >1000
#: labels is almost certainly an attack or a misconfigured exporter.
_MAX_LABELS_PER_ALERT = 1000

#: Maximum alerts per webhook body. Alertmanager batches per group; an
#: outlandishly large batch should be rejected rather than OOM the API.
_MAX_ALERTS_PER_BATCH = 512


# ---------------------------------------------------------------------------
# Inbound payload models (mirror Alertmanager's JSON exactly)
# ---------------------------------------------------------------------------


class AlertmanagerAlert(BaseModel):
    """
    One alert entry inside an Alertmanager webhook payload.

    Responsibilities:
        Carry exactly the fields Alertmanager v4 emits for a single alert.
        This model is a boundary adapter — it does not add semantics.

    Field name rationale:
        Alertmanager uses mixedCase (``startsAt``, ``endsAt``,
        ``generatorURL``). We keep that so model_validate() handles the
        raw payload without custom aliases, and downstream code maps it
        into our snake_case domain model.

    Raises:
        pydantic.ValidationError: If required fields are missing, types
            are wrong, or limits are exceeded.

    Example:
        AlertmanagerAlert(
            status="firing",
            labels={"alertname": "APIHighLatency", "severity": "warning"},
            annotations={"summary": "p99 > 1s"},
            startsAt="2026-04-15T12:00:00Z",
            endsAt="0001-01-01T00:00:00Z",
            generatorURL="http://prometheus:9090/...",
            fingerprint="abcdef1234567890",
        )
    """

    model_config = ConfigDict(
        extra="ignore",  # Tolerate forward-compatible extra fields.
        frozen=True,
    )

    status: str = Field(..., min_length=1, max_length=32)
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime
    endsAt: datetime | None = None
    generatorURL: str = Field(default="", max_length=2048)
    fingerprint: str = Field(..., min_length=1, max_length=128)

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        """Reject statuses outside the Alertmanager spec."""
        lowered = value.lower()
        if lowered not in _VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(_VALID_STATUSES)}, got {value!r}")
        return lowered

    @field_validator("endsAt", mode="before")
    @classmethod
    def _normalise_unresolved_end_at(cls, value: Any) -> Any:
        """
        Map Alertmanager's unresolved sentinel to ``None``.

        Alertmanager emits ``0001-01-01T00:00:00Z`` when an alert is
        firing without an ``ends_at`` yet. Treating that as a real
        datetime downstream would create garbage rows.
        """
        if value is None:
            return None
        if isinstance(value, str) and value.strip() == _UNRESOLVED_END_AT:
            return None
        return value

    @field_validator("labels", "annotations")
    @classmethod
    def _enforce_label_limits(cls, value: dict[str, str]) -> dict[str, str]:
        """Guard against pathological/exploited payloads."""
        if len(value) > _MAX_LABELS_PER_ALERT:
            raise ValueError(
                f"too many labels/annotations ({len(value)} > {_MAX_LABELS_PER_ALERT})"
            )
        return value


class AlertmanagerWebhookPayload(BaseModel):
    """
    Top-level Alertmanager webhook payload (v4).

    Responsibilities:
        Validate the envelope fields Alertmanager sends once per batch.

    Field name rationale:
        Same as AlertmanagerAlert — mixedCase preserved.

    Raises:
        pydantic.ValidationError: On any invalid/missing required field
            or when ``alerts`` exceeds the batch size limit.

    Example:
        payload = AlertmanagerWebhookPayload.model_validate({
            "version": "4",
            "groupKey": "{}:{alertname=...}",
            "status": "firing",
            "receiver": "default_webhook",
            "groupLabels": {...},
            "commonLabels": {...},
            "commonAnnotations": {...},
            "externalURL": "http://alertmanager:9093",
            "alerts": [...],
        })
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    version: str = Field(..., min_length=1, max_length=16)
    groupKey: str = Field(..., min_length=1, max_length=4096)
    truncatedAlerts: int = Field(default=0, ge=0, le=1_000_000)
    status: str = Field(..., min_length=1, max_length=32)
    receiver: str = Field(..., min_length=1, max_length=256)
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    externalURL: str = Field(default="", max_length=2048)
    alerts: list[AlertmanagerAlert] = Field(default_factory=list)

    @field_validator("status")
    @classmethod
    def _validate_top_status(cls, value: str) -> str:
        """Same allowed set as individual alerts."""
        lowered = value.lower()
        if lowered not in _VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(_VALID_STATUSES)}, got {value!r}")
        return lowered

    @field_validator("alerts")
    @classmethod
    def _enforce_batch_limit(cls, value: list[AlertmanagerAlert]) -> list[AlertmanagerAlert]:
        """Reject unreasonably large batches at the boundary."""
        if len(value) > _MAX_ALERTS_PER_BATCH:
            raise ValueError(
                f"too many alerts in one batch ({len(value)} > {_MAX_ALERTS_PER_BATCH})"
            )
        return value


# ---------------------------------------------------------------------------
# Domain record (what the repository and service layers speak)
# ---------------------------------------------------------------------------


class AlertNotification(BaseModel):
    """
    Canonical domain representation of one received alert notification.

    This is the value the service layer assembles and hands to the
    repository for persistence — it is distinct from the inbound
    Alertmanager JSON so that the rest of the system is insulated from
    upstream naming conventions.

    Fields:
        id: ULID assigned by the ingest service (primary key).
        fingerprint: Alertmanager's stable per-alert identifier.
        status: ``firing`` or ``resolved`` (already validated).
        alertname: Convenience copy of ``labels["alertname"]`` for
            indexing and cheap filtering.
        severity: Convenience copy of ``labels["severity"]`` (``""`` if
            the label is absent — per LL-007 we use empty string, not
            ``None``, for optional short strings on the boundary).
        starts_at: When the alert started firing.
        ends_at: When the alert resolved (``None`` if still firing).
        labels: Full Alertmanager ``labels`` map.
        annotations: Full Alertmanager ``annotations`` map.
        generator_url: Prometheus URL that generated the alert.
        receiver: Alertmanager receiver name that routed this alert.
        external_url: Alertmanager external URL at time of delivery.
        group_key: Alertmanager group key (stable per group).
        received_at: Timestamp we received the webhook (UTC).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., min_length=1, max_length=40)
    fingerprint: str = Field(..., min_length=1, max_length=128)
    status: str = Field(..., min_length=1, max_length=32)
    alertname: str = Field(default="", max_length=256)
    severity: str = Field(default="", max_length=32)
    starts_at: datetime
    ends_at: datetime | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    generator_url: str = Field(default="", max_length=2048)
    receiver: str = Field(..., min_length=1, max_length=256)
    external_url: str = Field(default="", max_length=2048)
    group_key: str = Field(..., min_length=1, max_length=4096)
    received_at: datetime

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        if value not in _VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(_VALID_STATUSES)}, got {value!r}")
        return value

    @classmethod
    def from_payload(
        cls,
        *,
        id: str,
        payload: AlertmanagerWebhookPayload,
        alert: AlertmanagerAlert,
        received_at: datetime,
    ) -> AlertNotification:
        """
        Build an ``AlertNotification`` from a parsed inbound payload.

        Args:
            id: Pre-generated ULID for this notification row.
            payload: Parsed envelope — used for receiver, externalURL,
                and groupKey (common to every alert in the batch).
            alert: One inbound alert entry.
            received_at: Timestamp at which the API received the POST,
                normalised to UTC.

        Returns:
            Immutable ``AlertNotification`` ready for persistence.

        Raises:
            pydantic.ValidationError: If any field violates the domain
                constraints (length, status enum, etc.).
        """
        return cls(
            id=id,
            fingerprint=alert.fingerprint,
            status=alert.status,
            alertname=alert.labels.get("alertname", ""),
            severity=alert.labels.get("severity", ""),
            starts_at=_to_utc(alert.startsAt),
            ends_at=_to_utc(alert.endsAt) if alert.endsAt is not None else None,
            labels=dict(alert.labels),
            annotations=dict(alert.annotations),
            generator_url=alert.generatorURL,
            receiver=payload.receiver,
            external_url=payload.externalURL,
            group_key=payload.groupKey,
            received_at=_to_utc(received_at),
        )


class AlertIngestResult(BaseModel):
    """
    Summary of an alert-webhook ingest operation.

    Returned by the ingest service to the route layer so the HTTP response
    can report how many alerts were persisted without leaking internal
    structures.

    Fields:
        received_count: Total alerts in the inbound batch.
        persisted_count: Number of alert rows written.
        correlation_id: Request-scoped correlation ID (echoed back).
        group_key: Alertmanager group key for log stitching.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    received_count: int = Field(..., ge=0)
    persisted_count: int = Field(..., ge=0)
    correlation_id: str = Field(..., min_length=1, max_length=256)
    group_key: str = Field(..., min_length=1, max_length=4096)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_utc(value: datetime) -> datetime:
    """
    Coerce a datetime to an aware UTC datetime.

    Naive inputs are assumed UTC (Alertmanager emits RFC3339 with a Z
    suffix, but tests and callers may pass naive UTC datetimes). Aware
    datetimes are converted to UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
