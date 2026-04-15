"""
Mobile dashboard summary contract.

Purpose:
    Define the frozen Pydantic model for mobile dashboard aggregated data.
    Provides a read-only snapshot of key trading metrics for mobile UX.

Responsibilities:
    - Define the MobileDashboardSummary contract with field descriptions.
    - Provide Pydantic v2 validation and JSON serialization.
    - Serve as the single source of truth for mobile dashboard response shape.

Does NOT:
    - Implement data aggregation logic (service responsibility).
    - Persist data (repository responsibility).
    - Contain business rules beyond validation.

Dependencies:
    - pydantic: BaseModel, Field, ConfigDict.
    - Standard library: datetime.

Example:
    summary = MobileDashboardSummary(
        active_runs=3,
        completed_runs_24h=5,
        pending_approvals=2,
        active_kill_switches=0,
        pnl_today_usd=1250.50,
        last_alert_severity="warning",
        last_alert_message="Position delta exceeds threshold",
        generated_at="2026-04-13T14:30:00+00:00",
    )
    json_str = summary.model_dump_json()
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MobileDashboardSummary(BaseModel):
    """
    Aggregated metrics for mobile dashboard display.

    Frozen model ensures immutability once constructed. All timestamp
    fields are ISO 8601 strings for mobile JSON compatibility.

    Attributes:
        active_runs: Count of currently executing research runs.
        completed_runs_24h: Count of research runs completed in the last 24 hours.
        pending_approvals: Count of promotion requests awaiting approval.
        active_kill_switches: Count of currently active kill switches (any scope).
        pnl_today_usd: Today's profit/loss in USD. None if unavailable.
        last_alert_severity: Severity of most recent alert ("info", "warning",
            "critical", or None if no alerts exist).
        last_alert_message: Human-readable message from the most recent alert
            (or None if no alerts exist).
        generated_at: ISO 8601 timestamp when this summary was generated.

    Example:
        summary = MobileDashboardSummary(
            active_runs=3,
            completed_runs_24h=5,
            pending_approvals=1,
            active_kill_switches=0,
            pnl_today_usd=1250.50,
            last_alert_severity="warning",
            last_alert_message="Position delta exceeds threshold",
            generated_at="2026-04-13T14:30:00+00:00",
        )
        assert summary.active_runs == 3
    """

    model_config = {"frozen": True}

    active_runs: int = Field(
        ...,
        ge=0,
        description="Count of currently active research runs.",
    )
    completed_runs_24h: int = Field(
        ...,
        ge=0,
        description="Count of research runs completed in the last 24 hours.",
    )
    pending_approvals: int = Field(
        ...,
        ge=0,
        description="Count of promotion requests awaiting approval.",
    )
    active_kill_switches: int = Field(
        ...,
        ge=0,
        description="Count of currently active kill switches (any scope).",
    )
    pnl_today_usd: float | None = Field(
        default=None,
        description="Today's profit/loss in USD, or None if unavailable.",
    )
    last_alert_severity: str | None = Field(
        default=None,
        description="Severity of most recent alert: 'info', 'warning', 'critical', or None.",
    )
    last_alert_message: str | None = Field(
        default=None,
        description="Human-readable message from most recent alert, or None.",
    )
    generated_at: str = Field(
        ...,
        description="ISO 8601 timestamp when this summary was generated.",
    )
