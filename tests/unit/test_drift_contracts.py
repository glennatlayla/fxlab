"""
Unit tests for drift analysis contract schemas.

Covers:
- DriftSeverity enum stability.
- DriftMetric construction, frozen, serialization.
- DriftReport construction, defaults, frozen, serialization.
- ReplayTimelineEvent construction.
- ReplayTimeline construction, frozen, serialization.

Dependencies:
- libs.contracts.drift
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from libs.contracts.drift import (
    DriftMetric,
    DriftReport,
    DriftSeverity,
    ReplayTimeline,
    ReplayTimelineEvent,
)


class TestDriftSeverity:
    """Verify drift severity enum."""

    def test_severity_members(self) -> None:
        members = {m.value for m in DriftSeverity}
        assert members == {"negligible", "minor", "significant", "critical"}

    def test_severity_count(self) -> None:
        assert len(DriftSeverity) == 4


class TestDriftMetric:
    """Verify DriftMetric construction and behavior."""

    def test_construction_minimal(self) -> None:
        m = DriftMetric(
            metric_name="fill_price",
            expected_value=Decimal("175.00"),
            actual_value=Decimal("175.50"),
        )
        assert m.metric_name == "fill_price"
        assert m.drift_pct == Decimal("0")
        assert m.severity == DriftSeverity.NEGLIGIBLE

    def test_construction_full(self) -> None:
        m = DriftMetric(
            metric_name="slippage",
            expected_value=Decimal("0"),
            actual_value=Decimal("0.50"),
            drift_pct=Decimal("100"),
            severity=DriftSeverity.SIGNIFICANT,
            symbol="AAPL",
            order_id="ord-001",
            details="Slippage exceeded threshold",
        )
        assert m.severity == DriftSeverity.SIGNIFICANT
        assert m.symbol == "AAPL"

    def test_frozen(self) -> None:
        m = DriftMetric(
            metric_name="fill_price",
            expected_value=Decimal("100"),
            actual_value=Decimal("101"),
        )
        with pytest.raises(Exception):
            m.metric_name = "changed"  # type: ignore[misc]

    def test_serialization_roundtrip(self) -> None:
        m = DriftMetric(
            metric_name="timing",
            expected_value=Decimal("100"),
            actual_value=Decimal("150"),
            drift_pct=Decimal("50"),
            severity=DriftSeverity.MINOR,
        )
        data = m.model_dump()
        restored = DriftMetric.model_validate(data)
        assert restored == m


class TestDriftReport:
    """Verify DriftReport construction and behavior."""

    def test_construction_defaults(self) -> None:
        r = DriftReport(
            report_id="01HDRIFT001",
            deployment_id="01HDEPLOY001",
            window="1h",
        )
        assert r.metrics == []
        assert r.max_severity == DriftSeverity.NEGLIGIBLE
        assert r.total_metrics == 0
        assert r.critical_count == 0
        assert isinstance(r.created_at, datetime)

    def test_construction_with_metrics(self) -> None:
        metric = DriftMetric(
            metric_name="fill_price",
            expected_value=Decimal("175"),
            actual_value=Decimal("176"),
            severity=DriftSeverity.MINOR,
        )
        r = DriftReport(
            report_id="01HDRIFT002",
            deployment_id="01HDEPLOY001",
            window="24h",
            metrics=[metric],
            max_severity=DriftSeverity.MINOR,
            total_metrics=1,
            minor_count=1,
        )
        assert len(r.metrics) == 1
        assert r.max_severity == DriftSeverity.MINOR

    def test_frozen(self) -> None:
        r = DriftReport(
            report_id="01HDRIFT003",
            deployment_id="01HDEPLOY001",
            window="1h",
        )
        with pytest.raises(Exception):
            r.window = "24h"  # type: ignore[misc]

    def test_serialization_roundtrip(self) -> None:
        r = DriftReport(
            report_id="01HDRIFT004",
            deployment_id="01HDEPLOY001",
            window="7d",
            total_metrics=5,
            critical_count=1,
        )
        data = r.model_dump()
        restored = DriftReport.model_validate(data)
        assert restored.report_id == r.report_id
        assert restored.critical_count == 1


class TestReplayTimelineEvent:
    """Verify ReplayTimelineEvent construction."""

    def test_construction(self) -> None:
        now = datetime.now(timezone.utc)
        e = ReplayTimelineEvent(
            event_type="submitted",
            timestamp=now,
            details={"broker_order_id": "ALPACA-123"},
            source="paper_execution_service",
        )
        assert e.event_type == "submitted"
        assert e.source == "paper_execution_service"

    def test_frozen(self) -> None:
        e = ReplayTimelineEvent(
            event_type="filled",
            timestamp=datetime.now(timezone.utc),
        )
        with pytest.raises(Exception):
            e.event_type = "changed"  # type: ignore[misc]


class TestReplayTimeline:
    """Verify ReplayTimeline construction and behavior."""

    def test_construction_defaults(self) -> None:
        t = ReplayTimeline(
            order_id="ord-001",
            deployment_id="01HDEPLOY001",
            symbol="AAPL",
        )
        assert t.events == []
        assert t.correlation_id == ""

    def test_construction_with_events(self) -> None:
        now = datetime.now(timezone.utc)
        events = [
            ReplayTimelineEvent(
                event_type="signal",
                timestamp=now,
                source="strategy",
            ),
            ReplayTimelineEvent(
                event_type="submitted",
                timestamp=now,
                source="execution_service",
            ),
        ]
        t = ReplayTimeline(
            order_id="ord-001",
            deployment_id="01HDEPLOY001",
            symbol="AAPL",
            correlation_id="corr-001",
            events=events,
        )
        assert len(t.events) == 2
        assert t.correlation_id == "corr-001"

    def test_frozen(self) -> None:
        t = ReplayTimeline(
            order_id="ord-001",
            deployment_id="01HDEPLOY001",
            symbol="AAPL",
        )
        with pytest.raises(Exception):
            t.order_id = "changed"  # type: ignore[misc]

    def test_serialization_roundtrip(self) -> None:
        now = datetime.now(timezone.utc)
        t = ReplayTimeline(
            order_id="ord-001",
            deployment_id="01HDEPLOY001",
            symbol="AAPL",
            events=[
                ReplayTimelineEvent(event_type="submitted", timestamp=now),
            ],
        )
        data = t.model_dump()
        restored = ReplayTimeline.model_validate(data)
        assert restored.order_id == t.order_id
        assert len(restored.events) == 1
