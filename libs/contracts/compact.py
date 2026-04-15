"""
Compact View Contracts — mobile-optimized response shapes.

Purpose:
    Define lightweight Pydantic models for mobile API responses that omit
    large nested objects, long arrays, and detailed metadata. Reduces bandwidth
    and parsing time for card/list views on resource-constrained clients.

Responsibilities:
    - ViewMode enum: FULL vs COMPACT response detail levels.
    - Compact model definitions: ResearchRunCompact, ApprovalCompact, AuditEventCompact.
    - Conversion methods: from_full() to transform full records to compact form.

Does NOT:
    - Contain business logic or validation beyond schema definition.
    - Perform I/O or database access.

Dependencies:
    - pydantic v2 for BaseModel, Field, ConfigDict.
    - Python standard library datetime.

Used by:
    - Mobile clients sending ?view=compact to API endpoints.
    - API route handlers to conditionally return compact vs full responses.

Example:
    from libs.contracts.compact import ViewMode, ResearchRunCompact
    from libs.contracts.research_run import ResearchRunRecord

    record: ResearchRunRecord = ...
    if view_mode == ViewMode.COMPACT:
        compact = ResearchRunCompact.from_full(record)
        return compact
    return record
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# View Mode Enum
# ---------------------------------------------------------------------------


class ViewMode(str, Enum):
    """
    API response view mode.

    Values:
        FULL: Complete response with all nested objects and metadata.
        COMPACT: Lightweight response optimized for mobile clients, omitting
                 large nested structures, parameter grids, and detailed metadata.

    Example:
        ?view=full    — returns complete ResearchRunRecord with full config
        ?view=compact — returns ResearchRunCompact with only essential fields
    """

    FULL = "full"
    COMPACT = "compact"


# ---------------------------------------------------------------------------
# Compact Models
# ---------------------------------------------------------------------------


class ResearchRunCompact(BaseModel):
    """
    Compact representation of a research run for mobile list/card views.

    Omits:
    - Full config object (only run_type, strategy_id included)
    - Backtest/walk-forward/monte-carlo engine-specific config details
    - Result object (only summary_metrics included)
    - Large parameter grids
    - Full error stack traces

    Includes:
    - ID, status, timestamps for state tracking
    - Run type for visual distinction
    - Strategy and symbols for identification
    - Trial counters and summary metrics for at-a-glance info
    - Essential timestamps

    Attributes:
        id: ULID of the research run.
        status: Current lifecycle status (string for simplicity).
        run_type: Type of research run (backtest, walk_forward, etc.).
        strategy_id: ULID of the strategy being researched.
        symbols: Ticker symbols included in the research.
        created_at: RFC 3339 timestamp when submitted.
        created_by: User ID who submitted the run.
        started_at: RFC 3339 timestamp when execution began (optional).
        completed_at: RFC 3339 timestamp when execution finished (optional).
        summary_metrics: Key result metrics for at-a-glance view (optional).
        completed_trials: Number of successfully completed trials (optional).
        trial_count: Total number of trials to execute (optional).

    Example:
        compact = ResearchRunCompact(
            id="01HRUN00000000000000000001",
            status="completed",
            run_type="backtest",
            strategy_id="01HSTRAT000000000000000001",
            symbols=["AAPL", "MSFT"],
            created_at="2025-04-13T14:30:00Z",
            created_by="01HUSER000000000000000001",
            completed_at="2025-04-13T15:45:00Z",
            summary_metrics={"total_return": 0.15, "sharpe_ratio": 1.2},
        )
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="ULID primary key")
    status: str = Field(
        ..., description="Lifecycle status (pending, queued, running, completed, failed, cancelled)"
    )
    run_type: str = Field(
        ..., description="Type of research run (backtest, walk_forward, monte_carlo, composite)"
    )
    strategy_id: str = Field(..., description="ULID of the strategy being researched")
    symbols: list[str] = Field(..., description="Ticker symbols in the research")
    created_at: str = Field(..., description="RFC 3339 creation timestamp")
    created_by: str = Field(..., description="User ID who submitted the run")
    started_at: str | None = Field(None, description="RFC 3339 execution start timestamp")
    completed_at: str | None = Field(None, description="RFC 3339 execution completion timestamp")
    summary_metrics: dict | None = Field(None, description="Key result metrics for quick display")
    completed_trials: int | None = Field(
        None, description="Number of successfully completed trials"
    )
    trial_count: int | None = Field(None, description="Total number of trials to execute")

    @classmethod
    def from_full(cls, record: Any) -> ResearchRunCompact:
        """
        Convert a full ResearchRunRecord to a compact representation.

        Extracts only the essential fields from the full record, omitting
        nested config objects and large result arrays.

        Args:
            record: ResearchRunRecord instance.

        Returns:
            ResearchRunCompact instance with essential fields only.

        Example:
            full_record = service.get_run(run_id)
            compact = ResearchRunCompact.from_full(full_record)
        """
        return cls(
            id=record.id,
            status=record.status.value,
            run_type=record.config.run_type.value,
            strategy_id=record.config.strategy_id,
            symbols=record.config.symbols,
            created_at=record.created_at.isoformat()
            if isinstance(record.created_at, datetime)
            else record.created_at,
            created_by=record.created_by,
            started_at=record.started_at.isoformat()
            if isinstance(record.started_at, datetime) and record.started_at
            else None,
            completed_at=record.completed_at.isoformat()
            if isinstance(record.completed_at, datetime) and record.completed_at
            else None,
            summary_metrics=record.result.summary_metrics if record.result else None,
            completed_trials=None,  # TODO: Populate from result if available
            trial_count=None,  # TODO: Populate from config if available
        )


class ApprovalCompact(BaseModel):
    """
    Compact representation of an approval for list views.

    Omits:
    - Full approval decision history
    - Complete evidence links and attachments
    - Full rationale text (truncated for display)

    Includes:
    - ID and status for state tracking
    - Object type for visual grouping
    - Submitter and reviewer IDs
    - Brief display text

    Attributes:
        id: ULID of the approval request.
        status: Current approval status (pending, approved, rejected).
        object_type: Type of object being approved.
        submitter_id: User ID who submitted the request.
        reviewer_id: User ID assigned to review (if assigned).
        created_at: RFC 3339 creation timestamp.
        summary: Brief summary of the approval request.

    Example:
        compact = ApprovalCompact(
            id="01HAPPROVAL000000000000001",
            status="pending",
            object_type="promotion_request",
            submitter_id="01HUSER000000000000000001",
            reviewer_id=None,
            created_at="2025-04-13T10:00:00Z",
            summary="Promote strategy STRAT-001 to live environment",
        )
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="ULID primary key")
    status: str = Field(..., description="Approval status (pending, approved, rejected)")
    object_type: str = Field(..., description="Type of object being approved")
    submitter_id: str = Field(..., description="User ID who submitted the request")
    reviewer_id: str | None = Field(None, description="User ID assigned to review")
    created_at: str = Field(..., description="RFC 3339 creation timestamp")
    summary: str | None = Field(None, description="Brief summary for display")


class AuditEventCompact(BaseModel):
    """
    Compact representation of an audit event for explorer views.

    Omits:
    - Full request/response payloads
    - Detailed error context
    - Deep nested change tracking

    Includes:
    - ID and timestamp for chronology
    - Actor information for accountability
    - High-level operation summary
    - Outcome status

    Attributes:
        id: ULID of the audit event.
        actor: User or system ID who performed the action.
        operation: High-level operation name (e.g., "research_run_created").
        object_type: Type of object affected.
        object_id: ULID of the affected object.
        outcome: Success/failure/partial outcome.
        created_at: RFC 3339 event timestamp.
        summary: Brief human-readable summary.

    Example:
        compact = AuditEventCompact(
            id="01HQAUDIT00000000000000001",
            actor="analyst@fxlab.io",
            operation="research_run_submitted",
            object_type="research_run",
            object_id="01HRUN000000000000000001",
            outcome="success",
            created_at="2025-04-13T14:30:00Z",
            summary="Submitted backtest research run",
        )
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="ULID primary key")
    actor: str = Field(..., description="User or system ID who performed the action")
    operation: str = Field(..., description="High-level operation name")
    object_type: str = Field(..., description="Type of object affected")
    object_id: str = Field(..., description="ULID of the affected object")
    outcome: str = Field(..., description="Outcome status (success, failure, partial)")
    created_at: str = Field(..., description="RFC 3339 event timestamp")
    summary: str | None = Field(None, description="Brief human-readable summary")
