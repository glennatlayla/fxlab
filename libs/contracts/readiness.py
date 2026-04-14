"""
Readiness assessment contracts.

Readiness reports score a backtest run's production-readiness across
data quality, strategy clarity, risk management, and operational checks.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from libs.contracts.base import FXLabBaseModel
from libs.contracts.enums import ReadinessGrade


class ReadinessBlocker(FXLabBaseModel):
    """
    A single blocker preventing production promotion.

    v1.1 adds blocker_owner and next_step for actionability.
    """

    code: str = Field(..., description="Machine-readable blocker code")
    message: str = Field(..., description="Human-readable blocker description")
    blocker_owner: str = Field(..., description="Team or role responsible for resolution")
    next_step: str = Field(..., description="Concrete action to resolve this blocker")
    severity: Literal["critical", "high", "medium", "low"] = Field(
        default="high", description="Blocker severity level"
    )


class ScoringEvidence(FXLabBaseModel):
    """
    Evidence supporting readiness scoring decisions.

    Provides transparency into how readiness grade was computed.
    """

    dimension: str = Field(..., description="Scoring dimension (e.g., 'data_quality')")
    score: float = Field(..., ge=0.0, le=1.0, description="Normalized score [0,1]")
    weight: float = Field(..., ge=0.0, le=1.0, description="Weight in overall grade")
    details: str | None = Field(None, description="Supporting details")


class ReadinessReport(FXLabBaseModel):
    """
    Complete readiness assessment for a backtest run.

    Aggregates all checks, blockers, and evidence into a single grade.
    """

    run_id: str = Field(..., description="ULID of the assessed run")
    readiness_grade: ReadinessGrade = Field(..., description="Overall readiness grade")
    blockers: list[ReadinessBlocker] = Field(
        default_factory=list, description="List of blockers preventing promotion"
    )
    scoring_evidence: list[ScoringEvidence] = Field(
        default_factory=list, description="Detailed scoring breakdown"
    )
    assessed_at: str | None = Field(None, description="ISO8601 timestamp of assessment")
    assessor: str | None = Field(None, description="Service or user who performed assessment")
