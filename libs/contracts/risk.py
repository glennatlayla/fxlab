"""
Risk gate schemas and value objects.

Responsibilities:
- Define risk check result, risk event, and severity contracts.
- Define extended risk limits for pre-trade checks.
- Provide frozen Pydantic models for type safety and serialization.

Does NOT:
- Implement risk check logic (service responsibility).
- Persist risk events (repository responsibility).

Dependencies:
- pydantic: BaseModel, Field.
- Standard library: Decimal, datetime, enum.

Error conditions:
- ValidationError: invalid field values (Pydantic enforcement).

Example:
    result = RiskCheckResult(passed=False, reason="Position limit exceeded")
    event = RiskEvent(
        deployment_id="01HDEPLOY...",
        check_name="position_limit",
        severity=RiskEventSeverity.CRITICAL,
        passed=False,
        reason="Position size 15000 exceeds limit 10000",
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class RiskEventSeverity(str, Enum):
    """
    Severity levels for risk events.

    Values:
    - INFO: informational, no action needed.
    - WARNING: approaching limits, monitor closely.
    - CRITICAL: limit breached, order rejected.
    - HALT: catastrophic breach, kill switch triggered.
    """

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    HALT = "halt"


class RiskCheckResult(BaseModel):
    """
    Result of a single pre-trade risk check.

    Responsibilities:
    - Indicate pass/fail status of a risk check.
    - Provide human-readable reason for failures.
    - Identify which check was performed.

    Does NOT:
    - Persist the result (service/repository concern).

    Example:
        result = RiskCheckResult(
            passed=False,
            check_name="position_limit",
            reason="Position size 15000 exceeds max 10000",
            severity=RiskEventSeverity.CRITICAL,
        )
    """

    model_config = {"frozen": True}

    passed: bool = Field(..., description="Whether the risk check passed.")
    check_name: str = Field(..., description="Name of the risk check performed.")
    reason: str | None = Field(
        default=None,
        description="Human-readable reason for failure (None if passed).",
    )
    severity: RiskEventSeverity = Field(
        default=RiskEventSeverity.INFO,
        description="Severity level of the check result.",
    )
    current_value: str | None = Field(
        default=None,
        description="Current value that was checked (as decimal string).",
    )
    limit_value: str | None = Field(
        default=None,
        description="Limit value that was compared against (as decimal string).",
    )


class RiskEvent(BaseModel):
    """
    Recorded risk check event (append-only audit trail).

    Responsibilities:
    - Capture the full context of a risk check for audit and analysis.
    - Support filtering by deployment, severity, and time range.

    Does NOT:
    - Make risk decisions (gate service responsibility).

    Example:
        event = RiskEvent(
            event_id="01HRISK...",
            deployment_id="01HDEPLOY...",
            check_name="daily_loss",
            severity=RiskEventSeverity.CRITICAL,
            passed=False,
            reason="Daily loss $6000 exceeds limit $5000",
            order_client_id="ord-001",
            correlation_id="corr-001",
        )
    """

    model_config = {"frozen": True}

    event_id: str = Field(..., description="ULID of the risk event.")
    deployment_id: str = Field(..., description="ULID of the deployment.")
    check_name: str = Field(..., description="Name of the risk check performed.")
    severity: RiskEventSeverity = Field(..., description="Severity level.")
    passed: bool = Field(..., description="Whether the check passed.")
    reason: str | None = Field(default=None, description="Human-readable reason for failure.")
    current_value: str | None = Field(default=None, description="Current value that was checked.")
    limit_value: str | None = Field(default=None, description="Limit value compared against.")
    order_client_id: str | None = Field(
        default=None, description="Client order ID that triggered the check."
    )
    symbol: str | None = Field(default=None, description="Symbol involved in the check.")
    correlation_id: str | None = Field(
        default=None, description="Distributed tracing correlation ID."
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the event was recorded.",
    )


class PreTradeRiskLimits(BaseModel):
    """
    Extended risk limits for pre-trade checks.

    These limits are applied per-deployment and checked by the RiskGateService
    before any order reaches a broker adapter.

    Responsibilities:
    - Define all configurable risk parameters for pre-trade checking.
    - Provide safe defaults for paper-mode deployments.

    Does NOT:
    - Enforce limits (service responsibility).

    Example:
        limits = PreTradeRiskLimits(
            max_position_size=Decimal("10000"),
            max_daily_loss=Decimal("5000"),
            max_order_value=Decimal("50000"),
            max_concentration_pct=Decimal("25"),
            max_open_orders=100,
        )
    """

    model_config = {"frozen": True}

    max_position_size: Decimal = Field(
        default=Decimal("0"),
        description="Maximum position size per symbol in shares/contracts. 0 = unlimited.",
    )
    max_daily_loss: Decimal = Field(
        default=Decimal("0"),
        description="Maximum daily loss before orders are rejected. 0 = unlimited.",
    )
    max_order_value: Decimal = Field(
        default=Decimal("0"),
        description="Maximum notional value per single order. 0 = unlimited.",
    )
    max_concentration_pct: Decimal = Field(
        default=Decimal("0"),
        description="Maximum portfolio concentration in a single symbol (0-100). 0 = unlimited.",
    )
    max_open_orders: int = Field(
        default=0,
        description="Maximum open orders per deployment. 0 = unlimited.",
        ge=0,
    )
