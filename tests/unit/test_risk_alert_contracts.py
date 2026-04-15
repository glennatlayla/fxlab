"""
Unit tests for risk alert contracts.

Validates RiskAlertConfig, RiskAlert, RiskAlertEvaluation, and
RiskAlertType enum behaviour including Pydantic validation rules.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from libs.contracts.risk_alert import (
    RiskAlert,
    RiskAlertConfig,
    RiskAlertEvaluation,
    RiskAlertType,
)

# ---------------------------------------------------------------------------
# RiskAlertType enum
# ---------------------------------------------------------------------------


class TestRiskAlertType:
    """Tests for RiskAlertType enumeration."""

    def test_has_three_types(self) -> None:
        assert len(RiskAlertType) == 3

    def test_values(self) -> None:
        assert RiskAlertType.VAR_BREACH.value == "var_breach"
        assert RiskAlertType.CONCENTRATION_BREACH.value == "concentration_breach"
        assert RiskAlertType.CORRELATION_SPIKE.value == "correlation_spike"


# ---------------------------------------------------------------------------
# RiskAlertConfig
# ---------------------------------------------------------------------------


class TestRiskAlertConfig:
    """Tests for RiskAlertConfig contract."""

    def test_default_values(self) -> None:
        config = RiskAlertConfig(deployment_id="01HTEST")
        assert config.var_threshold_pct == Decimal("5.0")
        assert config.concentration_threshold_pct == Decimal("30.0")
        assert config.correlation_threshold == Decimal("0.90")
        assert config.lookback_days == 252
        assert config.enabled is True

    def test_custom_values(self) -> None:
        config = RiskAlertConfig(
            deployment_id="01HTEST",
            var_threshold_pct=Decimal("3.0"),
            concentration_threshold_pct=Decimal("25.0"),
            correlation_threshold=Decimal("0.85"),
            lookback_days=126,
            enabled=False,
        )
        assert config.var_threshold_pct == Decimal("3.0")
        assert config.concentration_threshold_pct == Decimal("25.0")
        assert config.correlation_threshold == Decimal("0.85")
        assert config.lookback_days == 126
        assert config.enabled is False

    def test_frozen(self) -> None:
        config = RiskAlertConfig(deployment_id="01HTEST")
        with pytest.raises(ValidationError):
            config.var_threshold_pct = Decimal("10.0")  # type: ignore[misc]

    def test_rejects_zero_var_threshold(self) -> None:
        with pytest.raises(ValidationError, match="var_threshold_pct"):
            RiskAlertConfig(
                deployment_id="01HTEST",
                var_threshold_pct=Decimal("0"),
            )

    def test_rejects_negative_concentration(self) -> None:
        with pytest.raises(ValidationError, match="concentration_threshold_pct"):
            RiskAlertConfig(
                deployment_id="01HTEST",
                concentration_threshold_pct=Decimal("-1"),
            )

    def test_rejects_lookback_too_small(self) -> None:
        with pytest.raises(ValidationError, match="lookback_days"):
            RiskAlertConfig(
                deployment_id="01HTEST",
                lookback_days=10,
            )

    def test_rejects_empty_deployment_id(self) -> None:
        with pytest.raises(ValidationError, match="deployment_id"):
            RiskAlertConfig(deployment_id="")

    def test_serialization_roundtrip(self) -> None:
        config = RiskAlertConfig(
            deployment_id="01HTEST",
            var_threshold_pct=Decimal("4.5"),
        )
        data = config.model_dump()
        restored = RiskAlertConfig(**data)
        assert restored.deployment_id == config.deployment_id
        assert restored.var_threshold_pct == config.var_threshold_pct


# ---------------------------------------------------------------------------
# RiskAlert
# ---------------------------------------------------------------------------


class TestRiskAlert:
    """Tests for RiskAlert value object."""

    def test_basic_construction(self) -> None:
        alert = RiskAlert(
            alert_type=RiskAlertType.VAR_BREACH,
            message="VaR 95% (6.2%) exceeds threshold (5.0%)",
            current_value=Decimal("6.2"),
            threshold_value=Decimal("5.0"),
        )
        assert alert.alert_type == RiskAlertType.VAR_BREACH
        assert alert.symbol is None
        assert alert.symbol_b is None

    def test_concentration_alert_with_symbol(self) -> None:
        alert = RiskAlert(
            alert_type=RiskAlertType.CONCENTRATION_BREACH,
            message="AAPL at 45%",
            current_value=Decimal("45"),
            threshold_value=Decimal("30"),
            symbol="AAPL",
        )
        assert alert.symbol == "AAPL"

    def test_correlation_alert_with_pair(self) -> None:
        alert = RiskAlert(
            alert_type=RiskAlertType.CORRELATION_SPIKE,
            message="AAPL/MSFT at 0.95",
            current_value=Decimal("0.95"),
            threshold_value=Decimal("0.90"),
            symbol="AAPL",
            symbol_b="MSFT",
        )
        assert alert.symbol == "AAPL"
        assert alert.symbol_b == "MSFT"

    def test_frozen(self) -> None:
        alert = RiskAlert(
            alert_type=RiskAlertType.VAR_BREACH,
            message="test",
            current_value=Decimal("1"),
            threshold_value=Decimal("0.5"),
        )
        with pytest.raises(ValidationError):
            alert.current_value = Decimal("2")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RiskAlertEvaluation
# ---------------------------------------------------------------------------


class TestRiskAlertEvaluation:
    """Tests for RiskAlertEvaluation result object."""

    def test_empty_evaluation(self) -> None:
        result = RiskAlertEvaluation(
            deployment_id="01HTEST",
            total_rules_checked=3,
        )
        assert result.alerts_triggered == []
        assert result.total_rules_checked == 3

    def test_with_alerts(self) -> None:
        alerts = [
            RiskAlert(
                alert_type=RiskAlertType.VAR_BREACH,
                message="VaR breach",
                current_value=Decimal("6"),
                threshold_value=Decimal("5"),
            ),
            RiskAlert(
                alert_type=RiskAlertType.CONCENTRATION_BREACH,
                message="Concentration breach",
                current_value=Decimal("40"),
                threshold_value=Decimal("30"),
                symbol="AAPL",
            ),
        ]
        result = RiskAlertEvaluation(
            deployment_id="01HTEST",
            alerts_triggered=alerts,
            total_rules_checked=3,
        )
        assert len(result.alerts_triggered) == 2

    def test_frozen(self) -> None:
        result = RiskAlertEvaluation(
            deployment_id="01HTEST",
            total_rules_checked=3,
        )
        with pytest.raises(ValidationError):
            result.deployment_id = "other"  # type: ignore[misc]

    def test_evaluated_at_auto_set(self) -> None:
        result = RiskAlertEvaluation(
            deployment_id="01HTEST",
        )
        assert result.evaluated_at is not None
        assert result.evaluated_at.tzinfo is not None

    def test_serialization_roundtrip(self) -> None:
        now = datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc)
        result = RiskAlertEvaluation(
            deployment_id="01HTEST",
            alerts_triggered=[
                RiskAlert(
                    alert_type=RiskAlertType.VAR_BREACH,
                    message="test",
                    current_value=Decimal("6"),
                    threshold_value=Decimal("5"),
                ),
            ],
            total_rules_checked=3,
            evaluated_at=now,
        )
        data = result.model_dump(mode="json")
        assert len(data["alerts_triggered"]) == 1
        assert data["total_rules_checked"] == 3
