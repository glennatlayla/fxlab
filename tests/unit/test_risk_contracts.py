"""
Unit tests for risk gate contracts and schemas.

Covers:
- RiskEventSeverity enum stability
- RiskCheckResult construction and frozen model
- RiskEvent construction and defaults
- PreTradeRiskLimits construction and defaults
- Serialization roundtrip
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from libs.contracts.risk import (
    PreTradeRiskLimits,
    RiskCheckResult,
    RiskEvent,
    RiskEventSeverity,
)


class TestRiskEventSeverity:
    """Tests for RiskEventSeverity enum."""

    def test_values(self) -> None:
        assert RiskEventSeverity.INFO.value == "info"
        assert RiskEventSeverity.WARNING.value == "warning"
        assert RiskEventSeverity.CRITICAL.value == "critical"
        assert RiskEventSeverity.HALT.value == "halt"

    def test_member_count(self) -> None:
        assert len(RiskEventSeverity) == 4


class TestRiskCheckResult:
    """Tests for RiskCheckResult schema."""

    def test_passing_result(self) -> None:
        result = RiskCheckResult(passed=True, check_name="position_limit")
        assert result.passed is True
        assert result.check_name == "position_limit"
        assert result.reason is None
        assert result.severity == RiskEventSeverity.INFO

    def test_failing_result(self) -> None:
        result = RiskCheckResult(
            passed=False,
            check_name="daily_loss",
            reason="Daily loss $6000 exceeds limit $5000",
            severity=RiskEventSeverity.CRITICAL,
            current_value="6000",
            limit_value="5000",
        )
        assert result.passed is False
        assert result.reason == "Daily loss $6000 exceeds limit $5000"
        assert result.severity == RiskEventSeverity.CRITICAL

    def test_frozen(self) -> None:
        result = RiskCheckResult(passed=True, check_name="test")
        with pytest.raises(Exception):
            result.passed = False  # type: ignore[misc]

    def test_json_roundtrip(self) -> None:
        result = RiskCheckResult(
            passed=False,
            check_name="position_limit",
            reason="Exceeded",
            severity=RiskEventSeverity.CRITICAL,
            current_value="15000",
            limit_value="10000",
        )
        data = result.model_dump()
        rebuilt = RiskCheckResult(**data)
        assert rebuilt == result


class TestRiskEvent:
    """Tests for RiskEvent schema."""

    def test_construction(self) -> None:
        event = RiskEvent(
            event_id="01HRISK0000000000000000001",
            deployment_id="01HDEPLOY0000000000000001",
            check_name="position_limit",
            severity=RiskEventSeverity.CRITICAL,
            passed=False,
            reason="Position exceeded",
            order_client_id="ord-001",
            correlation_id="corr-001",
        )
        assert event.event_id == "01HRISK0000000000000000001"
        assert event.passed is False
        assert isinstance(event.created_at, datetime)

    def test_defaults(self) -> None:
        event = RiskEvent(
            event_id="01HRISK0000000000000000002",
            deployment_id="01HDEPLOY0000000000000001",
            check_name="order_value",
            severity=RiskEventSeverity.INFO,
            passed=True,
        )
        assert event.reason is None
        assert event.order_client_id is None
        assert event.symbol is None
        assert event.correlation_id is None


class TestPreTradeRiskLimits:
    """Tests for PreTradeRiskLimits schema."""

    def test_defaults(self) -> None:
        limits = PreTradeRiskLimits()
        assert limits.max_position_size == Decimal("0")
        assert limits.max_daily_loss == Decimal("0")
        assert limits.max_order_value == Decimal("0")
        assert limits.max_concentration_pct == Decimal("0")
        assert limits.max_open_orders == 0

    def test_custom_values(self) -> None:
        limits = PreTradeRiskLimits(
            max_position_size=Decimal("10000"),
            max_daily_loss=Decimal("5000"),
            max_order_value=Decimal("50000"),
            max_concentration_pct=Decimal("25"),
            max_open_orders=100,
        )
        assert limits.max_position_size == Decimal("10000")
        assert limits.max_daily_loss == Decimal("5000")
        assert limits.max_order_value == Decimal("50000")
        assert limits.max_concentration_pct == Decimal("25")
        assert limits.max_open_orders == 100

    def test_frozen(self) -> None:
        limits = PreTradeRiskLimits()
        with pytest.raises(Exception):
            limits.max_position_size = Decimal("999")  # type: ignore[misc]

    def test_json_roundtrip(self) -> None:
        limits = PreTradeRiskLimits(
            max_position_size=Decimal("10000"),
            max_daily_loss=Decimal("5000"),
        )
        data = limits.model_dump()
        rebuilt = PreTradeRiskLimits(**data)
        assert rebuilt == limits
