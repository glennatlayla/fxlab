"""
Drift analysis and replay schemas.

Responsibilities:
- Define drift metric comparison and severity classification.
- Define drift report summary with categorized entries.
- Define replay timeline for order context reconstruction.

Does NOT:
- Implement drift computation logic (service responsibility).
- Persist reports (repository/service responsibility).

Dependencies:
- pydantic: BaseModel, Field.
- Standard library: datetime, decimal, enum.

Example:
    metric = DriftMetric(
        metric_name="fill_price",
        expected_value=Decimal("175.00"),
        actual_value=Decimal("175.50"),
        drift_pct=Decimal("0.29"),
        severity=DriftSeverity.MINOR,
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DriftSeverity(str, Enum):
    """Severity classification for execution drift."""

    NEGLIGIBLE = "negligible"
    MINOR = "minor"
    SIGNIFICANT = "significant"
    CRITICAL = "critical"


class DriftMetric(BaseModel):
    """
    Individual drift metric comparison.

    Compares an expected value (from shadow/backtest) against actual
    execution value and classifies the severity of the difference.

    Example:
        metric = DriftMetric(
            metric_name="fill_price",
            expected_value=Decimal("175.00"),
            actual_value=Decimal("175.50"),
            drift_pct=Decimal("0.29"),
            severity=DriftSeverity.MINOR,
            symbol="AAPL",
            order_id="ord-001",
        )
    """

    model_config = {"frozen": True}

    metric_name: str = Field(
        ..., description="Name of the metric (fill_price, timing, slippage, fill_rate)."
    )
    expected_value: Decimal = Field(..., description="Expected value from shadow/backtest.")
    actual_value: Decimal = Field(..., description="Actual execution value.")
    drift_pct: Decimal = Field(
        default=Decimal("0"),
        description="Drift as a percentage of expected value.",
    )
    severity: DriftSeverity = Field(
        default=DriftSeverity.NEGLIGIBLE,
        description="Severity classification of the drift.",
    )
    symbol: str | None = Field(default=None, description="Instrument symbol if applicable.")
    order_id: str | None = Field(default=None, description="Order ID if applicable.")
    details: str | None = Field(default=None, description="Human-readable explanation.")


class DriftReport(BaseModel):
    """
    Summary of drift analysis for a deployment over a time window.

    Contains all individual drift metrics and aggregate statistics.

    Example:
        report = DriftReport(
            report_id="01HDRIFT001",
            deployment_id="01HDEPLOY001",
            window="1h",
            metrics=[...],
            max_severity=DriftSeverity.MINOR,
            total_metrics=5,
            critical_count=0,
            significant_count=0,
        )
    """

    model_config = {"frozen": True}

    report_id: str = Field(..., description="ULID of the drift report.")
    deployment_id: str = Field(..., description="ULID of the deployment.")
    window: str = Field(..., description="Time window for analysis (e.g., '1h', '24h', '7d').")
    metrics: list[DriftMetric] = Field(default_factory=list, description="All drift metrics.")
    max_severity: DriftSeverity = Field(
        default=DriftSeverity.NEGLIGIBLE,
        description="Highest severity across all metrics.",
    )
    total_metrics: int = Field(default=0, description="Total number of metrics computed.")
    critical_count: int = Field(default=0, description="Number of critical severity metrics.")
    significant_count: int = Field(default=0, description="Number of significant severity metrics.")
    minor_count: int = Field(default=0, description="Number of minor severity metrics.")
    negligible_count: int = Field(default=0, description="Number of negligible severity metrics.")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the report was generated.",
    )


class ReplayTimelineEvent(BaseModel):
    """
    Single event in an order replay timeline.

    Example:
        event = ReplayTimelineEvent(
            event_type="submitted",
            timestamp=datetime(2026, 4, 11, 10, 0, 0),
            details={"broker_order_id": "ALPACA-12345"},
        )
    """

    model_config = {"frozen": True}

    event_type: str = Field(
        ..., description="Event type (signal, risk_check, submitted, filled, etc.)."
    )
    timestamp: datetime = Field(..., description="When the event occurred.")
    details: dict[str, Any] = Field(default_factory=dict, description="Event-specific context.")
    source: str = Field(default="", description="System component that produced this event.")


class ReplayTimeline(BaseModel):
    """
    Ordered event sequence for an order, from strategy decision
    through broker response.

    Used to reconstruct the full context of an order for debugging,
    compliance, and drift analysis.

    Example:
        timeline = ReplayTimeline(
            order_id="ord-001",
            deployment_id="01HDEPLOY001",
            symbol="AAPL",
            events=[...],
        )
    """

    model_config = {"frozen": True}

    order_id: str = Field(..., description="Client order ID.")
    deployment_id: str = Field(..., description="ULID of the deployment.")
    symbol: str = Field(..., description="Instrument symbol.")
    correlation_id: str = Field(default="", description="Distributed tracing ID.")
    events: list[ReplayTimelineEvent] = Field(
        default_factory=list, description="Ordered event sequence."
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the timeline was reconstructed.",
    )
