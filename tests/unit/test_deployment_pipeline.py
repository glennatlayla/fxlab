"""
Tests for the deployment promotion pipeline.

Covers:
- Pipeline construction validation (missing config → ConfigError)
- Staging validation: all gates pass, some gates fail
- Promotion: successful end-to-end, gate failure blocks promotion
- Rollout monitoring and automatic rollback on failure
- Post-deployment health check: pass and fail scenarios
- Manual rollback
- DeploymentRecord audit trail correctness

Example:
    pytest tests/unit/test_deployment_pipeline.py -v
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from libs.contracts.errors import ConfigError
from services.api.infrastructure.deployment_pipeline import (
    DeploymentPipeline,
    DeploymentStatus,
    GateResult,
    GateStatus,
    PromotionGateError,
    RollbackTriggeredError,
    ValidationResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def pipeline() -> DeploymentPipeline:
    """Return a pipeline configured for testing."""
    return DeploymentPipeline(
        staging_url="https://staging.fxlab.test",
        production_namespace="fxlab",
        kubectl_context="test-cluster",
        deployment_name="fxlab-api",
        rollout_timeout_s=10,
        health_check_retries=2,
        health_check_interval_s=0,  # No sleep in tests
    )


def _mock_curl_success(*args, **kwargs) -> subprocess.CompletedProcess:
    """Simulate a successful curl invocation returning HTTP 200."""
    return subprocess.CompletedProcess(args=args, returncode=0, stdout="200", stderr="")


def _mock_curl_failure(*args, **kwargs) -> subprocess.CompletedProcess:
    """Simulate a failed curl invocation returning HTTP 503."""
    return subprocess.CompletedProcess(args=args, returncode=22, stdout="503", stderr="")


def _mock_kubectl_success(*args, **kwargs) -> subprocess.CompletedProcess:
    """Simulate a successful kubectl invocation."""
    cmd = args[0] if args else kwargs.get("args", [])
    # If asking for readyReplicas, return "2"
    if "jsonpath" in str(cmd):
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="2", stderr="")
    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


# ---------------------------------------------------------------------------
# Construction validation
# ---------------------------------------------------------------------------


class TestPipelineConstruction:
    """Tests for pipeline initialization and config validation."""

    def test_missing_staging_url_raises_config_error(self):
        """Empty staging_url raises ConfigError."""
        with pytest.raises(ConfigError, match="staging_url"):
            DeploymentPipeline(
                staging_url="",
                production_namespace="fxlab",
                kubectl_context="prod",
            )

    def test_missing_namespace_raises_config_error(self):
        """Empty production_namespace raises ConfigError."""
        with pytest.raises(ConfigError, match="production_namespace"):
            DeploymentPipeline(
                staging_url="https://staging.test",
                production_namespace="",
                kubectl_context="prod",
            )

    def test_missing_kubectl_context_raises_config_error(self):
        """Empty kubectl_context raises ConfigError."""
        with pytest.raises(ConfigError, match="kubectl_context"):
            DeploymentPipeline(
                staging_url="https://staging.test",
                production_namespace="fxlab",
                kubectl_context="",
            )

    def test_valid_construction(self, pipeline):
        """Pipeline constructs successfully with valid config."""
        assert pipeline._staging_url == "https://staging.fxlab.test"
        assert pipeline._production_namespace == "fxlab"


# ---------------------------------------------------------------------------
# Staging validation
# ---------------------------------------------------------------------------


class TestStagingValidation:
    """Tests for staging environment validation gates."""

    @patch("subprocess.run")
    def test_all_gates_pass(self, mock_run, pipeline):
        """When all HTTP checks return 200, all gates pass."""
        mock_run.side_effect = _mock_curl_success

        result = pipeline.validate_staging(correlation_id="test-001")

        assert result.all_passed is True
        assert len(result.gates) == 4
        assert all(g.status == GateStatus.PASSED for g in result.gates)
        assert result.correlation_id == "test-001"

    @patch("subprocess.run")
    def test_health_gate_failure(self, mock_run, pipeline):
        """When /health returns non-200, staging_health gate fails."""
        # First call (health) fails, rest succeed
        mock_run.side_effect = [
            _mock_curl_failure(),  # staging_health
            _mock_curl_success(),  # staging_ready
            _mock_curl_success(),  # artifact_storage_health
            _mock_curl_success(),  # database_connectivity
        ]

        result = pipeline.validate_staging(correlation_id="test-002")

        assert result.all_passed is False
        assert result.gates[0].name == "staging_health"
        assert result.gates[0].status == GateStatus.FAILED

    @patch("subprocess.run")
    def test_all_gates_fail(self, mock_run, pipeline):
        """When all endpoints fail, all gates fail."""
        mock_run.side_effect = _mock_curl_failure

        result = pipeline.validate_staging(correlation_id="test-003")

        assert result.all_passed is False
        assert all(g.status == GateStatus.FAILED for g in result.gates)

    @patch("subprocess.run")
    def test_curl_timeout_is_gate_failure(self, mock_run, pipeline):
        """When curl times out, the gate is marked FAILED."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="curl", timeout=10)

        result = pipeline.validate_staging(correlation_id="test-004")

        assert result.all_passed is False
        assert result.gates[0].status == GateStatus.FAILED
        assert (
            "timed out" in result.gates[0].detail.lower()
            or "TimeoutExpired" in result.gates[0].detail
        )

    @patch("subprocess.run")
    def test_validation_result_has_timestamp(self, mock_run, pipeline):
        """ValidationResult includes an ISO timestamp."""
        mock_run.side_effect = _mock_curl_success

        result = pipeline.validate_staging(correlation_id="test-005")

        assert result.timestamp != ""
        # Should be a valid ISO timestamp
        assert "T" in result.timestamp

    @patch("subprocess.run")
    def test_gate_results_have_duration(self, mock_run, pipeline):
        """Each gate result includes a duration_ms field."""
        mock_run.side_effect = _mock_curl_success

        result = pipeline.validate_staging(correlation_id="test-006")

        for gate in result.gates:
            assert isinstance(gate.duration_ms, int)
            assert gate.duration_ms >= 0


# ---------------------------------------------------------------------------
# Promotion — happy path
# ---------------------------------------------------------------------------


class TestPromotionHappyPath:
    """Tests for successful staging → production promotion."""

    @patch("subprocess.run")
    def test_promote_succeeds_with_passing_gates(self, mock_run, pipeline):
        """Promotion succeeds when all gates pass and rollout completes."""
        mock_run.side_effect = _mock_kubectl_success

        # Pre-validated result with all gates passing
        validation = ValidationResult(
            gates=[
                GateResult(name="staging_health", status=GateStatus.PASSED),
                GateResult(name="staging_ready", status=GateStatus.PASSED),
                GateResult(name="artifact_storage_health", status=GateStatus.PASSED),
                GateResult(name="database_connectivity", status=GateStatus.PASSED),
            ],
            all_passed=True,
            correlation_id="test-010",
        )

        record = pipeline.promote_to_production(
            image_tag="v1.2.3",
            correlation_id="test-010",
            approved_by="glenn@fxlab.test",
            validation=validation,
        )

        assert record.status == DeploymentStatus.SUCCEEDED
        assert record.image_tag == "v1.2.3"
        assert record.approved_by == "glenn@fxlab.test"
        assert record.started_at != ""
        assert record.completed_at != ""

    @patch("subprocess.run")
    def test_promote_records_deployment_id(self, mock_run, pipeline):
        """Promotion record includes a unique deployment_id."""
        mock_run.side_effect = _mock_kubectl_success

        validation = ValidationResult(
            gates=[GateResult(name="g", status=GateStatus.PASSED)],
            all_passed=True,
            correlation_id="test-011",
        )

        record = pipeline.promote_to_production(
            image_tag="v1.2.3",
            correlation_id="test-011",
            approved_by="admin@fxlab.test",
            validation=validation,
        )

        assert record.deployment_id.startswith("deploy-")
        assert record.correlation_id == "test-011"


# ---------------------------------------------------------------------------
# Promotion — gate failures
# ---------------------------------------------------------------------------


class TestPromotionGateFailure:
    """Tests for promotion blocked by failed gates."""

    def test_failed_validation_blocks_promotion(self, pipeline):
        """Promotion raises PromotionGateError when gates fail."""
        validation = ValidationResult(
            gates=[
                GateResult(name="staging_health", status=GateStatus.FAILED, detail="503"),
                GateResult(name="staging_ready", status=GateStatus.PASSED),
            ],
            all_passed=False,
            correlation_id="test-020",
        )

        with pytest.raises(PromotionGateError) as exc_info:
            pipeline.promote_to_production(
                image_tag="v1.2.3",
                correlation_id="test-020",
                approved_by="admin@fxlab.test",
                validation=validation,
            )

        assert len(exc_info.value.failed_gates) == 1
        assert exc_info.value.failed_gates[0].name == "staging_health"

    @patch("subprocess.run")
    def test_auto_validation_blocks_on_failure(self, mock_run, pipeline):
        """When no validation provided, pipeline runs it — and blocks on failure."""
        mock_run.side_effect = _mock_curl_failure

        with pytest.raises(PromotionGateError):
            pipeline.promote_to_production(
                image_tag="v1.2.3",
                correlation_id="test-021",
                approved_by="admin@fxlab.test",
            )


# ---------------------------------------------------------------------------
# Rollout failure and rollback
# ---------------------------------------------------------------------------


class TestRolloutFailureAndRollback:
    """Tests for automatic rollback on rollout or health check failure."""

    @patch("subprocess.run")
    def test_rollout_timeout_triggers_rollback(self, mock_run, pipeline):
        """When rollout status times out, automatic rollback is triggered."""
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            cmd = args[0] if args else kwargs.get("args", [])
            cmd_str = " ".join(cmd)

            if "set image" in cmd_str:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if "rollout status" in cmd_str:
                raise subprocess.CalledProcessError(1, cmd, output="", stderr="timed out")
            if "rollout undo" in cmd_str:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        validation = ValidationResult(
            gates=[GateResult(name="g", status=GateStatus.PASSED)],
            all_passed=True,
            correlation_id="test-030",
        )

        with pytest.raises(RollbackTriggeredError) as exc_info:
            pipeline.promote_to_production(
                image_tag="v1.2.3",
                correlation_id="test-030",
                approved_by="admin@fxlab.test",
                validation=validation,
            )

        assert (
            "rollout failure" in exc_info.value.reason.lower() or "Rollout" in exc_info.value.reason
        )

    @patch("subprocess.run")
    def test_health_check_failure_triggers_rollback(self, mock_run, pipeline):
        """When post-deploy health check fails, automatic rollback is triggered."""

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            cmd_str = " ".join(cmd)

            if "set image" in cmd_str:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if "rollout status" in cmd_str:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if "jsonpath" in cmd_str:
                # Return 0 ready replicas — health check fails
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="0", stderr="")
            if "rollout undo" in cmd_str:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        validation = ValidationResult(
            gates=[GateResult(name="g", status=GateStatus.PASSED)],
            all_passed=True,
            correlation_id="test-031",
        )

        with pytest.raises(RollbackTriggeredError) as exc_info:
            pipeline.promote_to_production(
                image_tag="v1.2.3",
                correlation_id="test-031",
                approved_by="admin@fxlab.test",
                validation=validation,
            )

        assert "health check" in exc_info.value.reason.lower()


# ---------------------------------------------------------------------------
# Manual rollback
# ---------------------------------------------------------------------------


class TestManualRollback:
    """Tests for manual rollback functionality."""

    @patch("subprocess.run")
    def test_manual_rollback_calls_kubectl_undo(self, mock_run, pipeline):
        """Manual rollback executes kubectl rollout undo."""
        mock_run.side_effect = _mock_kubectl_success

        pipeline.rollback(correlation_id="test-040", reason="bad deploy")

        # Verify kubectl rollout undo was called
        calls = mock_run.call_args_list
        assert any("rollout" in str(c) and "undo" in str(c) for c in calls)


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class TestValueObjects:
    """Tests for pipeline value objects and enums."""

    def test_gate_result_frozen(self):
        """GateResult is immutable (frozen dataclass)."""
        gate = GateResult(name="test", status=GateStatus.PASSED)
        with pytest.raises(AttributeError):
            gate.name = "changed"

    def test_gate_status_values(self):
        """GateStatus enum has expected values."""
        assert GateStatus.PASSED.value == "passed"
        assert GateStatus.FAILED.value == "failed"
        assert GateStatus.SKIPPED.value == "skipped"

    def test_deployment_status_values(self):
        """DeploymentStatus enum has all expected states."""
        expected = {
            "pending",
            "validating",
            "promoting",
            "monitoring",
            "succeeded",
            "rolled_back",
            "failed",
        }
        actual = {s.value for s in DeploymentStatus}
        assert actual == expected

    def test_promotion_gate_error_attributes(self):
        """PromotionGateError carries failed gates and validation."""
        failed = [GateResult(name="g1", status=GateStatus.FAILED)]
        validation = ValidationResult(gates=failed, all_passed=False)
        error = PromotionGateError("blocked", failed_gates=failed, validation=validation)
        assert error.failed_gates == failed
        assert error.validation == validation

    def test_rollback_triggered_error_attributes(self):
        """RollbackTriggeredError carries reason and deployment_id."""
        error = RollbackTriggeredError(
            "rolled back", reason="health check failed", deployment_id="deploy-123"
        )
        assert error.reason == "health check failed"
        assert error.deployment_id == "deploy-123"
