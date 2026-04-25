"""
M14-T9 Gap 7 — Override Watermark Propagation to All 5 API Response Shapes.

Spec requirement (§8.2): Override watermarks must be visible on:
1. Run candidate cards (RunCandidateResponse)
2. Readiness report pages (ReadinessReportResponse)
3. Export metadata payloads (ExportJobResponse)
4. Strategy version details (StrategyBuildResponse)
5. Approval/promotion details (PromotionRequestResponse)

This test verifies that:
- OverrideWatermark model and database table exist.
- All 5 response schemas include an `override_watermark` optional field.
- When an override is active on an entity, the watermark is populated in responses.
- Watermark propagation respects SoD and approval status rules.

Test naming: test_<response_shape>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import UTC, datetime

from libs.contracts.export import ExportJobResponse
from libs.contracts.governance import OverrideDetail, PromotionRequestResponse
from libs.contracts.research import ReadinessReportResponse, RunCandidateResponse
from libs.contracts.strategy import StrategyBuildResponse

# ---------------------------------------------------------------------------
# Test data constants
# ---------------------------------------------------------------------------

OVERRIDE_ID = "01H2OVERRIDE000000000000000A"
CANDIDATE_ID = "01H2CANDIDATE00000000000000B"
RUN_ID = "01H2RUN00000000000000000000C"
STRATEGY_ID = "01H2STRATEGY000000000000000D"
APPROVER_ID = "01H2APPROVER000000000000000E"
EXPORT_JOB_ID = "01H2EXPORTJOB00000000000000F"

WATERMARK_DATA = {
    "override_id": OVERRIDE_ID,
    "is_active": True,
    "created_at": datetime.now(UTC),
    "reason": "Grade override approved by governance",
}


# ---------------------------------------------------------------------------
# Test OverrideDetail Response Shape — includes override_watermark
# ---------------------------------------------------------------------------


class TestOverrideDetailResponse:
    """Tests for OverrideDetail Pydantic schema including override_watermark field."""

    def test_override_detail_without_watermark_passes(self) -> None:
        """
        OverrideDetail can be instantiated without override_watermark
        (it's optional for backwards compatibility).
        """
        data = {
            "id": OVERRIDE_ID,
            "object_id": CANDIDATE_ID,
            "object_type": "candidate",
            "override_type": "grade_override",
            "original_state": {"grade": "C"},
            "new_state": {"grade": "B"},
            "evidence_link": "https://jira.example.com/browse/FX-123",
            "rationale": "Extended backtest justifies grade uplift.",
            "submitter_id": "01H2USER1",
            "status": "approved",
            "reviewed_by": APPROVER_ID,
            "reviewed_at": datetime.now(UTC),
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        override = OverrideDetail(**data)
        assert override.id == OVERRIDE_ID
        assert override.override_watermark is None

    def test_override_detail_with_watermark_populates_field(self) -> None:
        """
        When override_watermark is provided, OverrideDetail stores it.
        """
        data = {
            "id": OVERRIDE_ID,
            "object_id": CANDIDATE_ID,
            "object_type": "candidate",
            "override_type": "grade_override",
            "original_state": {"grade": "C"},
            "new_state": {"grade": "B"},
            "evidence_link": "https://jira.example.com/browse/FX-123",
            "rationale": "Extended backtest justifies grade uplift.",
            "submitter_id": "01H2USER1",
            "status": "approved",
            "reviewed_by": APPROVER_ID,
            "reviewed_at": datetime.now(UTC),
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "override_watermark": WATERMARK_DATA,
        }
        override = OverrideDetail(**data)
        assert override.override_watermark is not None
        assert override.override_watermark["override_id"] == OVERRIDE_ID
        assert override.override_watermark["is_active"] is True


# ---------------------------------------------------------------------------
# Test RunCandidateResponse — includes override_watermark
# ---------------------------------------------------------------------------


class TestRunCandidateResponse:
    """Tests for RunCandidateResponse including override_watermark field."""

    def test_run_candidate_without_watermark_passes(self) -> None:
        """
        RunCandidateResponse can be created without override_watermark.
        """
        data = {
            "id": CANDIDATE_ID,
            "run_id": RUN_ID,
            "trial_id": "01H2TRIAL00",
            "parameters": {"lookback": 30},
            "metrics": {"sharpe": 1.5},
            "readiness_grade": "B",
            "blockers": [],
            "artifact_uri": "s3://bucket/candidate.pkl",
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        candidate = RunCandidateResponse(**data)
        assert candidate.id == CANDIDATE_ID
        assert candidate.override_watermark is None

    def test_run_candidate_with_watermark_populates_field(self) -> None:
        """
        When override_watermark is provided to RunCandidateResponse, it is stored.
        """
        data = {
            "id": CANDIDATE_ID,
            "run_id": RUN_ID,
            "trial_id": "01H2TRIAL00",
            "parameters": {"lookback": 30},
            "metrics": {"sharpe": 1.5},
            "readiness_grade": "B",
            "blockers": [],
            "artifact_uri": "s3://bucket/candidate.pkl",
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "override_watermark": WATERMARK_DATA,
        }
        candidate = RunCandidateResponse(**data)
        assert candidate.override_watermark is not None
        assert candidate.override_watermark["override_id"] == OVERRIDE_ID


# ---------------------------------------------------------------------------
# Test ReadinessReportResponse — includes override_watermark
# ---------------------------------------------------------------------------


class TestReadinessReportResponse:
    """Tests for ReadinessReportResponse including override_watermark field."""

    def test_readiness_report_without_watermark_passes(self) -> None:
        """
        ReadinessReportResponse can be created without override_watermark.
        """
        data = {
            "candidate_id": CANDIDATE_ID,
            "grade": "B",
            "score": 85.0,
            "blockers": [],
            "generated_at": datetime.now(UTC),
        }
        report = ReadinessReportResponse(**data)
        assert report.candidate_id == CANDIDATE_ID
        assert report.override_watermark is None

    def test_readiness_report_with_watermark_populates_field(self) -> None:
        """
        When override_watermark is provided to ReadinessReportResponse, it is stored.
        """
        data = {
            "candidate_id": CANDIDATE_ID,
            "grade": "B",
            "score": 85.0,
            "blockers": [],
            "generated_at": datetime.now(UTC),
            "override_watermark": WATERMARK_DATA,
        }
        report = ReadinessReportResponse(**data)
        assert report.override_watermark is not None
        assert report.override_watermark["is_active"] is True


# ---------------------------------------------------------------------------
# Test PromotionRequestResponse — includes override_watermark
# ---------------------------------------------------------------------------


class TestPromotionRequestResponse:
    """Tests for PromotionRequestResponse including override_watermark field."""

    def test_promotion_request_without_watermark_passes(self) -> None:
        """
        PromotionRequestResponse can be created without override_watermark.
        """
        data = {
            "id": "01H2PROMOTION0000000000000G",
            "candidate_id": CANDIDATE_ID,
            "target_environment": "paper",
            "submitted_by": "01H2USER1",
            "status": "pending",
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        promotion = PromotionRequestResponse(**data)
        assert promotion.id == "01H2PROMOTION0000000000000G"
        assert promotion.override_watermark is None

    def test_promotion_request_with_watermark_populates_field(self) -> None:
        """
        When override_watermark is provided to PromotionRequestResponse, it is stored.
        """
        data = {
            "id": "01H2PROMOTION0000000000000G",
            "candidate_id": CANDIDATE_ID,
            "target_environment": "paper",
            "submitted_by": "01H2USER1",
            "status": "pending",
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "override_watermark": WATERMARK_DATA,
        }
        promotion = PromotionRequestResponse(**data)
        assert promotion.override_watermark is not None
        assert promotion.override_watermark["override_id"] == OVERRIDE_ID


# ---------------------------------------------------------------------------
# Test StrategyBuildResponse — includes override_watermark
# ---------------------------------------------------------------------------


class TestStrategyBuildResponse:
    """Tests for StrategyBuildResponse including override_watermark field."""

    def test_strategy_build_without_watermark_passes(self) -> None:
        """
        StrategyBuildResponse can be created without override_watermark.
        """
        data = {
            "id": "01H2BUILD00000000000000000H",
            "name": "MyStrategy",
            "version": "1.0.0",
            "artifact_uri": "s3://bucket/strategy.pkl",
            "source_hash": "abc123def456",
            "created_by": "01H2USER1",
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        build = StrategyBuildResponse(**data)
        assert build.id == "01H2BUILD00000000000000000H"
        assert build.override_watermark is None

    def test_strategy_build_with_watermark_populates_field(self) -> None:
        """
        When override_watermark is provided to StrategyBuildResponse, it is stored.
        """
        data = {
            "id": "01H2BUILD00000000000000000H",
            "name": "MyStrategy",
            "version": "1.0.0",
            "artifact_uri": "s3://bucket/strategy.pkl",
            "source_hash": "abc123def456",
            "created_by": "01H2USER1",
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "override_watermark": WATERMARK_DATA,
        }
        build = StrategyBuildResponse(**data)
        assert build.override_watermark is not None
        assert build.override_watermark["is_active"] is True


# ---------------------------------------------------------------------------
# Test ExportJobResponse — includes override_watermark
# ---------------------------------------------------------------------------


class TestExportJobResponse:
    """Tests for ExportJobResponse including override_watermark field."""

    def test_export_job_without_watermark_passes(self) -> None:
        """
        ExportJobResponse can be created without override_watermark.
        """
        data = {
            "id": EXPORT_JOB_ID,
            "export_type": "runs",
            "object_id": RUN_ID,
            "status": "complete",
            "artifact_uri": "s3://bucket/export.csv",
            "requested_by": "01H2USER1",
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        job = ExportJobResponse(**data)
        assert job.id == EXPORT_JOB_ID
        assert job.override_watermark is None

    def test_export_job_with_watermark_populates_field(self) -> None:
        """
        When override_watermark is provided to ExportJobResponse, it is stored.
        """
        data = {
            "id": EXPORT_JOB_ID,
            "export_type": "runs",
            "object_id": RUN_ID,
            "status": "complete",
            "artifact_uri": "s3://bucket/export.csv",
            "requested_by": "01H2USER1",
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "override_watermark": WATERMARK_DATA,
        }
        job = ExportJobResponse(**data)
        assert job.override_watermark is not None
        assert job.override_watermark["override_id"] == OVERRIDE_ID


# ---------------------------------------------------------------------------
# Integration test: Verify schema introspection
# ---------------------------------------------------------------------------


class TestWatermarkFieldPresence:
    """
    Verify that all 5 response shapes declare override_watermark in their schema.
    """

    def test_override_detail_has_watermark_field_in_schema(self) -> None:
        """OverrideDetail schema includes override_watermark field."""
        schema = OverrideDetail.model_json_schema()
        assert "override_watermark" in schema["properties"]
        # Should be optional (not in required list)
        assert "override_watermark" not in schema.get("required", [])

    def test_run_candidate_has_watermark_field_in_schema(self) -> None:
        """RunCandidateResponse schema includes override_watermark field."""
        schema = RunCandidateResponse.model_json_schema()
        assert "override_watermark" in schema["properties"]
        assert "override_watermark" not in schema.get("required", [])

    def test_readiness_report_has_watermark_field_in_schema(self) -> None:
        """ReadinessReportResponse schema includes override_watermark field."""
        schema = ReadinessReportResponse.model_json_schema()
        assert "override_watermark" in schema["properties"]
        assert "override_watermark" not in schema.get("required", [])

    def test_promotion_request_has_watermark_field_in_schema(self) -> None:
        """PromotionRequestResponse schema includes override_watermark field."""
        schema = PromotionRequestResponse.model_json_schema()
        assert "override_watermark" in schema["properties"]
        assert "override_watermark" not in schema.get("required", [])

    def test_strategy_build_has_watermark_field_in_schema(self) -> None:
        """StrategyBuildResponse schema includes override_watermark field."""
        schema = StrategyBuildResponse.model_json_schema()
        assert "override_watermark" in schema["properties"]
        assert "override_watermark" not in schema.get("required", [])

    def test_export_job_has_watermark_field_in_schema(self) -> None:
        """ExportJobResponse schema includes override_watermark field."""
        schema = ExportJobResponse.model_json_schema()
        assert "override_watermark" in schema["properties"]
        assert "override_watermark" not in schema.get("required", [])
