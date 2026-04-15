"""
Unit tests for compact view contracts (BE-02 — Compact View Parameter).

Purpose:
    Verify that compact view enum and model definitions work correctly,
    and that full-to-compact conversion preserves essential fields
    while omitting large nested structures.

Verifies:
    - ViewMode enum values (FULL, COMPACT).
    - ResearchRunCompact model creation and validation.
    - ResearchRunCompact.from_full() conversion from full records.
    - ApprovalCompact and AuditEventCompact model creation.
    - Compact models omit large nested fields.

Dependencies:
    - libs.contracts.compact: ViewMode, ResearchRunCompact, ApprovalCompact, AuditEventCompact.
    - libs.contracts.research_run: ResearchRunRecord, ResearchRunConfig, ResearchRunStatus, ResearchRunType.
    - pydantic.ValidationError: Expected on invalid inputs.

Example:
    pytest tests/unit/test_compact_view_contracts.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from libs.contracts.backtest import BacktestConfig
from libs.contracts.compact import (
    ApprovalCompact,
    AuditEventCompact,
    ResearchRunCompact,
    ViewMode,
)
from libs.contracts.research_run import (
    ResearchRunConfig,
    ResearchRunRecord,
    ResearchRunStatus,
    ResearchRunType,
)

# ---------------------------------------------------------------------------
# ViewMode Enum Tests
# ---------------------------------------------------------------------------


class TestViewMode:
    """Tests for ViewMode enum."""

    def test_view_mode_full_value(self) -> None:
        """ViewMode.FULL has value 'full'."""
        assert ViewMode.FULL.value == "full"

    def test_view_mode_compact_value(self) -> None:
        """ViewMode.COMPACT has value 'compact'."""
        assert ViewMode.COMPACT.value == "compact"

    def test_view_mode_count(self) -> None:
        """Exactly 2 view modes are defined."""
        assert len(ViewMode) == 2

    def test_view_mode_string_comparison(self) -> None:
        """ViewMode can be compared with strings."""
        assert ViewMode.FULL == "full"
        assert ViewMode.COMPACT == "compact"

    def test_view_mode_from_string(self) -> None:
        """ViewMode can be instantiated from string."""
        assert ViewMode("full") == ViewMode.FULL
        assert ViewMode("compact") == ViewMode.COMPACT

    def test_view_mode_invalid_value_raises(self) -> None:
        """ViewMode raises on invalid value."""
        with pytest.raises(ValueError):
            ViewMode("invalid")


# ---------------------------------------------------------------------------
# ResearchRunCompact Tests
# ---------------------------------------------------------------------------


class TestResearchRunCompact:
    """Tests for ResearchRunCompact model."""

    def test_compact_model_requires_essential_fields(self) -> None:
        """Compact model creation requires id, status, run_type, etc."""
        compact = ResearchRunCompact(
            id="01HRUN00000000000000000001",
            status="completed",
            run_type="backtest",
            strategy_id="01HSTRAT000000000000000001",
            symbols=["AAPL"],
            created_at="2025-04-13T14:30:00Z",
            created_by="01HUSER000000000000000001",
        )

        assert compact.id == "01HRUN00000000000000000001"
        assert compact.status == "completed"
        assert compact.run_type == "backtest"
        assert compact.strategy_id == "01HSTRAT000000000000000001"
        assert compact.symbols == ["AAPL"]

    def test_compact_model_optional_fields(self) -> None:
        """Compact model optional fields (started_at, summary_metrics) are truly optional."""
        compact = ResearchRunCompact(
            id="01HRUN00000000000000000001",
            status="queued",
            run_type="backtest",
            strategy_id="01HSTRAT000000000000000001",
            symbols=["AAPL"],
            created_at="2025-04-13T14:30:00Z",
            created_by="01HUSER000000000000000001",
        )

        assert compact.started_at is None
        assert compact.completed_at is None
        assert compact.summary_metrics is None
        assert compact.completed_trials is None
        assert compact.trial_count is None

    def test_compact_model_with_optional_fields(self) -> None:
        """Compact model accepts optional fields when provided."""
        compact = ResearchRunCompact(
            id="01HRUN00000000000000000001",
            status="completed",
            run_type="backtest",
            strategy_id="01HSTRAT000000000000000001",
            symbols=["AAPL", "MSFT"],
            created_at="2025-04-13T14:30:00Z",
            created_by="01HUSER000000000000000001",
            started_at="2025-04-13T14:35:00Z",
            completed_at="2025-04-13T15:00:00Z",
            summary_metrics={"total_return": 0.15, "sharpe_ratio": 1.2},
            completed_trials=10,
            trial_count=10,
        )

        assert compact.started_at == "2025-04-13T14:35:00Z"
        assert compact.completed_at == "2025-04-13T15:00:00Z"
        assert compact.summary_metrics == {"total_return": 0.15, "sharpe_ratio": 1.2}
        assert compact.completed_trials == 10
        assert compact.trial_count == 10

    def test_compact_model_frozen(self) -> None:
        """Compact model is frozen (immutable)."""
        compact = ResearchRunCompact(
            id="01HRUN00000000000000000001",
            status="completed",
            run_type="backtest",
            strategy_id="01HSTRAT000000000000000001",
            symbols=["AAPL"],
            created_at="2025-04-13T14:30:00Z",
            created_by="01HUSER000000000000000001",
        )

        with pytest.raises(Exception):  # Pydantic frozen models raise ValidationError on assignment
            compact.status = "failed"

    def test_from_full_with_minimal_record(self) -> None:
        """from_full() converts minimal ResearchRunRecord to compact form."""
        config = ResearchRunConfig(
            run_type=ResearchRunType.BACKTEST,
            strategy_id="01HSTRAT000000000000000001",
            symbols=["AAPL"],
            initial_equity=Decimal("100000"),
            backtest_config=BacktestConfig(
                strategy_id="01HSTRAT000000000000000001",
                symbols=["AAPL"],
                start_date="2025-01-01",
                end_date="2025-12-31",
            ),
        )

        record = ResearchRunRecord(
            id="01HRUN00000000000000000001",
            config=config,
            status=ResearchRunStatus.PENDING,
            created_by="01HUSER000000000000000001",
        )

        compact = ResearchRunCompact.from_full(record)

        assert compact.id == record.id
        assert compact.status == "pending"
        assert compact.run_type == "backtest"
        assert compact.strategy_id == config.strategy_id
        assert compact.symbols == config.symbols
        assert compact.created_by == record.created_by
        assert compact.started_at is None
        assert compact.summary_metrics is None

    def test_from_full_with_completed_record(self) -> None:
        """from_full() extracts summary_metrics from completed run."""
        from libs.contracts.research_run import ResearchRunResult

        config = ResearchRunConfig(
            run_type=ResearchRunType.BACKTEST,
            strategy_id="01HSTRAT000000000000000001",
            symbols=["AAPL"],
            initial_equity=Decimal("100000"),
            backtest_config=BacktestConfig(
                strategy_id="01HSTRAT000000000000000001",
                symbols=["AAPL"],
                start_date="2025-01-01",
                end_date="2025-12-31",
            ),
        )

        result = ResearchRunResult(
            summary_metrics={"total_return": 0.15, "sharpe_ratio": 1.2},
        )

        now = datetime.now(timezone.utc)
        record = ResearchRunRecord(
            id="01HRUN00000000000000000001",
            config=config,
            status=ResearchRunStatus.COMPLETED,
            created_by="01HUSER000000000000000001",
            result=result,
            started_at=now,
            completed_at=now,
        )

        compact = ResearchRunCompact.from_full(record)

        assert compact.status == "completed"
        assert compact.summary_metrics == {"total_return": 0.15, "sharpe_ratio": 1.2}
        assert compact.started_at is not None
        assert compact.completed_at is not None

    def test_from_full_datetime_iso_format(self) -> None:
        """from_full() converts datetime fields to ISO 8601 strings."""
        config = ResearchRunConfig(
            run_type=ResearchRunType.BACKTEST,
            strategy_id="01HSTRAT000000000000000001",
            symbols=["AAPL"],
            initial_equity=Decimal("100000"),
            backtest_config=BacktestConfig(
                strategy_id="01HSTRAT000000000000000001",
                symbols=["AAPL"],
                start_date="2025-01-01",
                end_date="2025-12-31",
            ),
        )

        record = ResearchRunRecord(
            id="01HRUN00000000000000000001",
            config=config,
            status=ResearchRunStatus.RUNNING,
            created_by="01HUSER000000000000000001",
        )

        compact = ResearchRunCompact.from_full(record)

        # created_at should be a string in ISO 8601 format
        assert isinstance(compact.created_at, str)
        assert "T" in compact.created_at
        assert "Z" in compact.created_at or "+" in compact.created_at


# ---------------------------------------------------------------------------
# ApprovalCompact Tests
# ---------------------------------------------------------------------------


class TestApprovalCompact:
    """Tests for ApprovalCompact model."""

    def test_approval_compact_creation(self) -> None:
        """ApprovalCompact model creation with essential fields."""
        compact = ApprovalCompact(
            id="01HAPPROVAL000000000000001",
            status="pending",
            object_type="promotion_request",
            submitter_id="01HUSER000000000000000001",
            created_at="2025-04-13T10:00:00Z",
        )

        assert compact.id == "01HAPPROVAL000000000000001"
        assert compact.status == "pending"
        assert compact.object_type == "promotion_request"
        assert compact.submitter_id == "01HUSER000000000000000001"
        assert compact.reviewer_id is None

    def test_approval_compact_with_reviewer(self) -> None:
        """ApprovalCompact accepts optional reviewer_id."""
        compact = ApprovalCompact(
            id="01HAPPROVAL000000000000001",
            status="pending",
            object_type="promotion_request",
            submitter_id="01HUSER000000000000000001",
            reviewer_id="01HUSER000000000000000002",
            created_at="2025-04-13T10:00:00Z",
            summary="Promote strategy to live",
        )

        assert compact.reviewer_id == "01HUSER000000000000000002"
        assert compact.summary == "Promote strategy to live"

    def test_approval_compact_frozen(self) -> None:
        """ApprovalCompact model is frozen."""
        compact = ApprovalCompact(
            id="01HAPPROVAL000000000000001",
            status="pending",
            object_type="promotion_request",
            submitter_id="01HUSER000000000000000001",
            created_at="2025-04-13T10:00:00Z",
        )

        with pytest.raises(Exception):
            compact.status = "approved"


# ---------------------------------------------------------------------------
# AuditEventCompact Tests
# ---------------------------------------------------------------------------


class TestAuditEventCompact:
    """Tests for AuditEventCompact model."""

    def test_audit_event_compact_creation(self) -> None:
        """AuditEventCompact model creation with essential fields."""
        compact = AuditEventCompact(
            id="01HQAUDIT00000000000000001",
            actor="analyst@fxlab.io",
            operation="research_run_submitted",
            object_type="research_run",
            object_id="01HRUN000000000000000001",
            outcome="success",
            created_at="2025-04-13T14:30:00Z",
        )

        assert compact.id == "01HQAUDIT00000000000000001"
        assert compact.actor == "analyst@fxlab.io"
        assert compact.operation == "research_run_submitted"
        assert compact.outcome == "success"

    def test_audit_event_compact_with_summary(self) -> None:
        """AuditEventCompact accepts optional summary field."""
        compact = AuditEventCompact(
            id="01HQAUDIT00000000000000001",
            actor="analyst@fxlab.io",
            operation="research_run_submitted",
            object_type="research_run",
            object_id="01HRUN000000000000000001",
            outcome="success",
            created_at="2025-04-13T14:30:00Z",
            summary="Submitted backtest research run for STRAT-001",
        )

        assert compact.summary == "Submitted backtest research run for STRAT-001"

    def test_audit_event_compact_frozen(self) -> None:
        """AuditEventCompact model is frozen."""
        compact = AuditEventCompact(
            id="01HQAUDIT00000000000000001",
            actor="analyst@fxlab.io",
            operation="research_run_submitted",
            object_type="research_run",
            object_id="01HRUN000000000000000001",
            outcome="success",
            created_at="2025-04-13T14:30:00Z",
        )

        with pytest.raises(Exception):
            compact.outcome = "failure"
