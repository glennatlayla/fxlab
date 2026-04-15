"""
Risk alerting contracts and value objects (Phase 7 — M11).

Responsibilities:
- Define risk alert threshold configuration.
- Define risk alert evaluation results.
- Define risk alert rule types for VaR, concentration, and correlation.
- Provide frozen Pydantic models for immutable value objects.

Does NOT:
- Evaluate alert rules (service responsibility).
- Dispatch notifications (IncidentManager responsibility).
- Persist alert state (repository responsibility).

Dependencies:
- pydantic: BaseModel, Field.
- Standard library: Decimal, enum, datetime.

Error conditions:
- ValidationError: invalid field values (Pydantic enforcement).

Example:
    config = RiskAlertConfig(
        deployment_id="01HTESTDEPLOY000000000000",
        var_threshold_pct=Decimal("5.0"),
        concentration_threshold_pct=Decimal("30.0"),
        correlation_threshold=Decimal("0.90"),
    )
    result = RiskAlertEvaluation(
        deployment_id="01HTESTDEPLOY000000000000",
        alerts_triggered=[
            RiskAlert(
                alert_type=RiskAlertType.VAR_BREACH,
                message="VaR 95% (6.2%) exceeds threshold (5.0%)",
                current_value=Decimal("6.2"),
                threshold_value=Decimal("5.0"),
            ),
        ],
        evaluated_at=datetime.now(timezone.utc),
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class RiskAlertType(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """
    Types of risk alerts that can be triggered.

    VAR_BREACH — Portfolio VaR exceeds configured percentage threshold.
    CONCENTRATION_BREACH — Single position exceeds portfolio percentage threshold.
    CORRELATION_SPIKE — Pairwise correlation exceeds configured threshold.
    """

    VAR_BREACH = "var_breach"
    CONCENTRATION_BREACH = "concentration_breach"
    CORRELATION_SPIKE = "correlation_spike"


class RiskAlertConfig(BaseModel):
    """
    Configuration for risk alert thresholds per deployment.

    Defines the threshold values that trigger risk alerts. When any
    metric exceeds its threshold, the alert service creates an incident
    via the IncidentManager.

    Attributes:
        deployment_id: Target deployment for monitoring.
        var_threshold_pct: VaR 95% threshold as percentage of equity (0-100).
            Alert fires when portfolio VaR exceeds this percentage.
        concentration_threshold_pct: Single position concentration threshold (0-100).
            Alert fires when any position exceeds this percentage of portfolio.
        correlation_threshold: Pairwise correlation threshold (-1 to 1).
            Alert fires when any pair exceeds this threshold.
        lookback_days: Number of days for VaR and correlation lookback.
        enabled: Whether this alert configuration is active.

    Example:
        config = RiskAlertConfig(
            deployment_id="01HTESTDEPLOY000000000000",
            var_threshold_pct=Decimal("5.0"),
            concentration_threshold_pct=Decimal("30.0"),
            correlation_threshold=Decimal("0.90"),
        )
    """

    model_config = {"frozen": True}

    deployment_id: str = Field(..., min_length=1, description="Target deployment ID.")
    var_threshold_pct: Decimal = Field(
        default=Decimal("5.0"),
        gt=0.0,
        le=100.0,
        description="VaR 95% threshold as percentage of equity (0-100).",
    )
    concentration_threshold_pct: Decimal = Field(
        default=Decimal("30.0"),
        gt=0.0,
        le=100.0,
        description="Single position concentration threshold (0-100).",
    )
    correlation_threshold: Decimal = Field(
        default=Decimal("0.90"),
        gt=-1.0,
        le=1.0,
        description="Pairwise correlation alert threshold.",
    )
    lookback_days: int = Field(
        default=252,
        ge=30,
        le=1260,
        description="Lookback period for VaR and correlation (trading days).",
    )
    enabled: bool = Field(
        default=True,
        description="Whether this alert configuration is active.",
    )


class RiskAlert(BaseModel):
    """
    A single risk alert that was triggered during evaluation.

    Attributes:
        alert_type: The type of risk alert.
        message: Human-readable description of the breach.
        current_value: Current metric value that triggered the alert.
        threshold_value: Configured threshold that was exceeded.
        symbol: Relevant symbol (for concentration/correlation alerts).
        symbol_b: Second symbol (for correlation alerts only).

    Example:
        alert = RiskAlert(
            alert_type=RiskAlertType.VAR_BREACH,
            message="VaR 95% (6.2%) exceeds threshold (5.0%)",
            current_value=Decimal("6.2"),
            threshold_value=Decimal("5.0"),
        )
    """

    model_config = {"frozen": True}

    alert_type: RiskAlertType = Field(..., description="Type of risk alert.")
    message: str = Field(..., min_length=1, description="Human-readable alert description.")
    current_value: Decimal = Field(..., description="Current metric value.")
    threshold_value: Decimal = Field(..., description="Threshold that was breached.")
    symbol: str | None = Field(default=None, description="Relevant symbol.")
    symbol_b: str | None = Field(default=None, description="Second symbol (correlation).")


class RiskAlertEvaluation(BaseModel):
    """
    Result of evaluating all risk alert rules for a deployment.

    Contains the list of triggered alerts and metadata about the
    evaluation run.

    Attributes:
        deployment_id: Deployment that was evaluated.
        alerts_triggered: List of alerts that fired.
        total_rules_checked: Number of rules evaluated.
        evaluated_at: Timestamp of the evaluation.

    Example:
        result = RiskAlertEvaluation(
            deployment_id="01HTESTDEPLOY000000000000",
            alerts_triggered=[...],
            total_rules_checked=3,
            evaluated_at=datetime.now(timezone.utc),
        )
    """

    model_config = {"frozen": True}

    deployment_id: str = Field(..., description="Deployment that was evaluated.")
    alerts_triggered: list[RiskAlert] = Field(
        default_factory=list, description="Alerts that fired."
    )
    total_rules_checked: int = Field(default=0, ge=0, description="Number of rules evaluated.")
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Evaluation timestamp.",
    )
