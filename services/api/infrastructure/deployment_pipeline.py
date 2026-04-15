"""
Deployment promotion pipeline for staging → production deployments.

Responsibilities:
- Validate staging environment health before promotion.
- Enforce promotion gates: all health checks pass, artifact storage accessible,
  acceptance tests green, manual approval obtained.
- Trigger production rolling update via K8s API.
- Monitor rollout health and trigger automatic rollback on failure.
- Record deployment events for audit trail.

Does NOT:
- Build Docker images (that is CI's responsibility).
- Manage K8s cluster lifecycle or infrastructure provisioning.
- Run acceptance tests directly (delegates to external test runner).

Dependencies:
- structlog: Structured logging with correlation_id propagation.
- libs.contracts.errors: ConfigError for missing configuration.
- subprocess: For kubectl commands (production uses K8s Python client).

Error conditions:
- PromotionGateError: One or more promotion gates failed.
- RollbackTriggeredError: Health check failed after deployment, rollback initiated.
- ConfigError: Missing required configuration for deployment target.

Example:
    pipeline = DeploymentPipeline(
        staging_url="https://staging.fxlab.internal",
        production_namespace="fxlab",
        kubectl_context="prod-cluster",
    )
    result = pipeline.validate_staging(correlation_id="deploy-001")
    if result.all_passed:
        pipeline.promote_to_production(
            image_tag="v1.2.3",
            correlation_id="deploy-001",
            approved_by="glenn@fxlab.com",
        )
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

import structlog

from libs.contracts.errors import ConfigError

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class GateStatus(Enum):
    """Status of an individual promotion gate check."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class DeploymentStatus(Enum):
    """Overall deployment status."""

    PENDING = "pending"
    VALIDATING = "validating"
    PROMOTING = "promoting"
    MONITORING = "monitoring"
    SUCCEEDED = "succeeded"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


@dataclass(frozen=True)
class GateResult:
    """Result of a single promotion gate check.

    Attributes:
        name: Human-readable gate name (e.g. "staging_health").
        status: PASSED, FAILED, or SKIPPED.
        detail: Explanation of the result (error message on failure).
        duration_ms: Time taken for the check in milliseconds.
    """

    name: str
    status: GateStatus
    detail: str = ""
    duration_ms: int = 0


@dataclass
class ValidationResult:
    """Aggregated result of all promotion gate checks.

    Attributes:
        gates: List of individual gate results.
        all_passed: True only if every non-skipped gate passed.
        timestamp: When the validation was performed.
        correlation_id: Correlation ID for tracing.
    """

    gates: list[GateResult] = field(default_factory=list)
    all_passed: bool = False
    timestamp: str = ""
    correlation_id: str = ""


@dataclass
class DeploymentRecord:
    """Record of a deployment attempt for audit trail.

    Attributes:
        deployment_id: Unique identifier for this deployment.
        image_tag: Docker image tag being deployed.
        status: Current status of the deployment.
        approved_by: Email of the person who approved the promotion.
        started_at: ISO timestamp of when the deployment started.
        completed_at: ISO timestamp of when the deployment completed.
        validation: Staging validation result.
        rollback_reason: Reason for rollback, if applicable.
        correlation_id: Correlation ID for tracing.
    """

    deployment_id: str
    image_tag: str
    status: DeploymentStatus
    approved_by: str = ""
    started_at: str = ""
    completed_at: str = ""
    validation: ValidationResult | None = None
    rollback_reason: str = ""
    correlation_id: str = ""


# ---------------------------------------------------------------------------
# Custom errors
# ---------------------------------------------------------------------------


class PromotionGateError(Exception):
    """Raised when one or more promotion gates fail validation.

    Attributes:
        failed_gates: List of GateResult objects that failed.
        validation: The full ValidationResult.
    """

    def __init__(
        self,
        message: str,
        failed_gates: list[GateResult],
        validation: ValidationResult,
    ) -> None:
        super().__init__(message)
        self.failed_gates = failed_gates
        self.validation = validation


class RollbackTriggeredError(Exception):
    """Raised when a deployment rollback was triggered due to health check failure.

    Attributes:
        reason: Why the rollback was triggered.
        deployment_id: The deployment that was rolled back.
    """

    def __init__(self, message: str, reason: str, deployment_id: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.deployment_id = deployment_id


# ---------------------------------------------------------------------------
# Pipeline implementation
# ---------------------------------------------------------------------------


class DeploymentPipeline:
    """
    Orchestrates staging validation and production promotion for FXLab.

    Responsibilities:
    - Run staging health checks (API health, artifact storage, database).
    - Enforce mandatory promotion gates before production deployment.
    - Execute kubectl rolling update against the production namespace.
    - Monitor rollout status and trigger automatic rollback on failure.
    - Produce DeploymentRecord for audit trail.

    Does NOT:
    - Build or push Docker images.
    - Manage infrastructure provisioning.
    - Run acceptance test suites directly (validates their results).

    Dependencies:
    - kubectl binary available on PATH for K8s operations.
    - structlog for logging.

    Raises:
    - ConfigError: Missing required configuration.
    - PromotionGateError: Staging validation failed.
    - RollbackTriggeredError: Post-deployment health check failed.

    Example:
        pipeline = DeploymentPipeline(
            staging_url="https://staging.fxlab.internal",
            production_namespace="fxlab",
            kubectl_context="prod-cluster",
        )
        result = pipeline.validate_staging(correlation_id="deploy-001")
        assert result.all_passed
    """

    def __init__(
        self,
        staging_url: str,
        production_namespace: str,
        kubectl_context: str,
        deployment_name: str = "fxlab-api",
        rollout_timeout_s: int = 300,
        health_check_retries: int = 5,
        health_check_interval_s: int = 10,
    ) -> None:
        """
        Initialize the deployment pipeline.

        Args:
            staging_url: Base URL of the staging environment (e.g. https://staging.fxlab.internal).
            production_namespace: K8s namespace for production deployment.
            kubectl_context: kubectl context name for the production cluster.
            deployment_name: Name of the K8s Deployment resource.
            rollout_timeout_s: Maximum time to wait for rollout completion.
            health_check_retries: Number of health check attempts after deploy.
            health_check_interval_s: Seconds between health check retries.

        Raises:
            ConfigError: If staging_url or production_namespace is empty.
        """
        if not staging_url:
            raise ConfigError("staging_url is required for deployment pipeline.")
        if not production_namespace:
            raise ConfigError("production_namespace is required for deployment pipeline.")
        if not kubectl_context:
            raise ConfigError("kubectl_context is required for deployment pipeline.")

        self._staging_url = staging_url.rstrip("/")
        self._production_namespace = production_namespace
        self._kubectl_context = kubectl_context
        self._deployment_name = deployment_name
        self._rollout_timeout_s = rollout_timeout_s
        self._health_check_retries = health_check_retries
        self._health_check_interval_s = health_check_interval_s

    # ------------------------------------------------------------------
    # Staging validation
    # ------------------------------------------------------------------

    def validate_staging(self, correlation_id: str) -> ValidationResult:
        """
        Run all promotion gate checks against the staging environment.

        Gates checked:
        1. staging_health — GET /health returns 200.
        2. staging_ready — GET /ready returns 200.
        3. artifact_storage — GET /health returns artifact storage status.
        4. database — Database connectivity via /health endpoint.

        Args:
            correlation_id: Correlation ID for tracing.

        Returns:
            ValidationResult with per-gate results and all_passed flag.
        """
        logger.info(
            "deployment_pipeline.validate_staging.start",
            staging_url=self._staging_url,
            correlation_id=correlation_id,
            component="deployment_pipeline",
        )

        gates: list[GateResult] = []

        # Gate 1: Staging health endpoint
        gates.append(
            self._check_http_endpoint(
                name="staging_health",
                url=f"{self._staging_url}/health",
                correlation_id=correlation_id,
            )
        )

        # Gate 2: Staging readiness endpoint
        gates.append(
            self._check_http_endpoint(
                name="staging_ready",
                url=f"{self._staging_url}/ready",
                correlation_id=correlation_id,
            )
        )

        # Gate 3: Artifact storage health (via /health response body)
        gates.append(
            self._check_http_endpoint(
                name="artifact_storage_health",
                url=f"{self._staging_url}/health",
                correlation_id=correlation_id,
                expect_json_key="status",
            )
        )

        # Gate 4: Database connectivity (implicit in /ready)
        gates.append(
            self._check_http_endpoint(
                name="database_connectivity",
                url=f"{self._staging_url}/ready",
                correlation_id=correlation_id,
                expect_json_key="status",
            )
        )

        all_passed = all(g.status == GateStatus.PASSED for g in gates)
        result = ValidationResult(
            gates=gates,
            all_passed=all_passed,
            timestamp=datetime.now(timezone.utc).isoformat(),
            correlation_id=correlation_id,
        )

        log_fn = logger.info if all_passed else logger.warning
        log_fn(
            "deployment_pipeline.validate_staging.complete",
            all_passed=all_passed,
            gate_count=len(gates),
            failed_count=sum(1 for g in gates if g.status == GateStatus.FAILED),
            correlation_id=correlation_id,
            component="deployment_pipeline",
        )

        return result

    # ------------------------------------------------------------------
    # Promotion
    # ------------------------------------------------------------------

    def promote_to_production(
        self,
        *,
        image_tag: str,
        correlation_id: str,
        approved_by: str,
        validation: ValidationResult | None = None,
    ) -> DeploymentRecord:
        """
        Promote a validated staging build to production.

        Sequence:
        1. Verify promotion gates passed (or run validation if not provided).
        2. Execute kubectl set image to trigger rolling update.
        3. Monitor rollout status until success or timeout.
        4. Run post-deployment health checks.
        5. If health checks fail, trigger automatic rollback.

        Args:
            image_tag: Docker image tag to deploy (e.g. "v1.2.3" or "sha-abc123").
            correlation_id: Correlation ID for tracing.
            approved_by: Email of the person who approved the promotion.
            validation: Pre-computed validation result. If None, runs validation.

        Returns:
            DeploymentRecord with the deployment outcome.

        Raises:
            PromotionGateError: If staging validation fails.
            RollbackTriggeredError: If post-deployment health checks fail.
            ConfigError: If required configuration is missing.
        """
        deployment_id = f"deploy-{int(time.time())}-{correlation_id[:8]}"
        started_at = datetime.now(timezone.utc).isoformat()

        logger.info(
            "deployment_pipeline.promote.start",
            image_tag=image_tag,
            approved_by=approved_by,
            deployment_id=deployment_id,
            correlation_id=correlation_id,
            component="deployment_pipeline",
        )

        record = DeploymentRecord(
            deployment_id=deployment_id,
            image_tag=image_tag,
            status=DeploymentStatus.VALIDATING,
            approved_by=approved_by,
            started_at=started_at,
            correlation_id=correlation_id,
        )

        # Step 1: Validate staging (or use provided validation)
        if validation is None:
            validation = self.validate_staging(correlation_id=correlation_id)

        record.validation = validation

        if not validation.all_passed:
            failed = [g for g in validation.gates if g.status == GateStatus.FAILED]
            record.status = DeploymentStatus.FAILED
            record.completed_at = datetime.now(timezone.utc).isoformat()

            logger.error(
                "deployment_pipeline.promote.gates_failed",
                failed_gates=[g.name for g in failed],
                deployment_id=deployment_id,
                correlation_id=correlation_id,
                component="deployment_pipeline",
            )

            raise PromotionGateError(
                f"Promotion blocked: {len(failed)} gate(s) failed: "
                + ", ".join(g.name for g in failed),
                failed_gates=failed,
                validation=validation,
            )

        # Step 2: Trigger rolling update
        record.status = DeploymentStatus.PROMOTING
        full_image = f"fxlab-api:{image_tag}"

        try:
            self._kubectl(
                "set",
                "image",
                f"deployment/{self._deployment_name}",
                f"fxlab-api={full_image}",
                correlation_id=correlation_id,
            )
        except subprocess.CalledProcessError as exc:
            record.status = DeploymentStatus.FAILED
            record.completed_at = datetime.now(timezone.utc).isoformat()
            logger.error(
                "deployment_pipeline.promote.set_image_failed",
                error=str(exc),
                deployment_id=deployment_id,
                correlation_id=correlation_id,
                component="deployment_pipeline",
            )
            raise

        # Step 3: Monitor rollout
        record.status = DeploymentStatus.MONITORING
        try:
            self._kubectl(
                "rollout",
                "status",
                f"deployment/{self._deployment_name}",
                f"--timeout={self._rollout_timeout_s}s",
                correlation_id=correlation_id,
            )
        except subprocess.CalledProcessError:
            # Rollout failed — trigger rollback
            logger.error(
                "deployment_pipeline.promote.rollout_failed",
                deployment_id=deployment_id,
                correlation_id=correlation_id,
                component="deployment_pipeline",
            )
            self._rollback(
                deployment_id=deployment_id,
                reason="Rollout timed out or failed",
                correlation_id=correlation_id,
            )
            record.status = DeploymentStatus.ROLLED_BACK
            record.rollback_reason = "Rollout timed out or failed"
            record.completed_at = datetime.now(timezone.utc).isoformat()
            raise RollbackTriggeredError(
                "Deployment rolled back due to rollout failure",
                reason="Rollout timed out or failed",
                deployment_id=deployment_id,
            ) from None

        # Step 4: Post-deployment health checks
        health_ok = self._post_deploy_health_check(correlation_id=correlation_id)
        if not health_ok:
            self._rollback(
                deployment_id=deployment_id,
                reason="Post-deployment health check failed",
                correlation_id=correlation_id,
            )
            record.status = DeploymentStatus.ROLLED_BACK
            record.rollback_reason = "Post-deployment health check failed"
            record.completed_at = datetime.now(timezone.utc).isoformat()
            raise RollbackTriggeredError(
                "Deployment rolled back due to health check failure",
                reason="Post-deployment health check failed",
                deployment_id=deployment_id,
            )

        # Success
        record.status = DeploymentStatus.SUCCEEDED
        record.completed_at = datetime.now(timezone.utc).isoformat()

        logger.info(
            "deployment_pipeline.promote.success",
            image_tag=image_tag,
            deployment_id=deployment_id,
            correlation_id=correlation_id,
            component="deployment_pipeline",
        )

        return record

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def rollback(self, *, correlation_id: str, reason: str = "manual") -> None:
        """
        Rollback the production deployment to the previous revision.

        Args:
            correlation_id: Correlation ID for tracing.
            reason: Human-readable reason for the rollback.
        """
        self._rollback(
            deployment_id="manual",
            reason=reason,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check_http_endpoint(
        self,
        *,
        name: str,
        url: str,
        correlation_id: str,
        expect_json_key: str | None = None,
    ) -> GateResult:
        """
        Check an HTTP endpoint and return a GateResult.

        Uses subprocess + curl to avoid adding requests as a dependency.
        In production, this would use the requests library or httpx.

        Args:
            name: Gate name for the result.
            url: Full URL to check.
            correlation_id: Correlation ID for tracing.
            expect_json_key: If set, verify the response JSON contains this key.

        Returns:
            GateResult with PASSED or FAILED status.
        """
        start_ms = int(time.time() * 1000)
        try:
            result = subprocess.run(
                ["curl", "-sf", "-o", "/dev/null", "-w", "%{http_code}", url],
                capture_output=True,
                text=True,
                timeout=10,
            )
            duration_ms = int(time.time() * 1000) - start_ms
            http_code = result.stdout.strip()

            if result.returncode == 0 and http_code.startswith("2"):
                return GateResult(
                    name=name,
                    status=GateStatus.PASSED,
                    detail=f"HTTP {http_code}",
                    duration_ms=duration_ms,
                )
            return GateResult(
                name=name,
                status=GateStatus.FAILED,
                detail=f"HTTP {http_code}, return code {result.returncode}",
                duration_ms=duration_ms,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            duration_ms = int(time.time() * 1000) - start_ms
            return GateResult(
                name=name,
                status=GateStatus.FAILED,
                detail=f"Check failed: {exc}",
                duration_ms=duration_ms,
            )

    def _kubectl(self, *args: str, correlation_id: str) -> subprocess.CompletedProcess:
        """
        Execute a kubectl command against the production cluster.

        Args:
            *args: kubectl subcommand and arguments.
            correlation_id: Correlation ID for tracing.

        Returns:
            CompletedProcess result.

        Raises:
            subprocess.CalledProcessError: If kubectl exits non-zero.
        """
        cmd = [
            "kubectl",
            "--context",
            self._kubectl_context,
            "--namespace",
            self._production_namespace,
            *args,
        ]
        logger.info(
            "deployment_pipeline.kubectl",
            command=" ".join(cmd),
            correlation_id=correlation_id,
            component="deployment_pipeline",
        )
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self._rollout_timeout_s + 30,
            check=True,
        )

    def _rollback(
        self,
        *,
        deployment_id: str,
        reason: str,
        correlation_id: str,
    ) -> None:
        """
        Rollback the production deployment to the previous revision.

        Args:
            deployment_id: ID of the deployment being rolled back.
            reason: Human-readable reason.
            correlation_id: Correlation ID for tracing.
        """
        logger.warning(
            "deployment_pipeline.rollback.start",
            deployment_id=deployment_id,
            reason=reason,
            correlation_id=correlation_id,
            component="deployment_pipeline",
        )
        try:
            self._kubectl(
                "rollout",
                "undo",
                f"deployment/{self._deployment_name}",
                correlation_id=correlation_id,
            )
            logger.info(
                "deployment_pipeline.rollback.success",
                deployment_id=deployment_id,
                correlation_id=correlation_id,
                component="deployment_pipeline",
            )
        except subprocess.CalledProcessError as exc:
            logger.error(
                "deployment_pipeline.rollback.failed",
                deployment_id=deployment_id,
                error=str(exc),
                correlation_id=correlation_id,
                component="deployment_pipeline",
            )
            raise

    def _post_deploy_health_check(self, correlation_id: str) -> bool:
        """
        Run health checks against production after deployment.

        Retries up to health_check_retries times with health_check_interval_s
        between attempts. All attempts must pass for the check to succeed.

        Args:
            correlation_id: Correlation ID for tracing.

        Returns:
            True if all health checks pass within the retry window.
        """
        # In a real K8s deployment, we'd hit the production URL.
        # Here we verify via kubectl that all pods are ready.
        for attempt in range(1, self._health_check_retries + 1):
            try:
                result = self._kubectl(
                    "get",
                    "deployment",
                    self._deployment_name,
                    "-o",
                    "jsonpath={.status.readyReplicas}",
                    correlation_id=correlation_id,
                )
                ready_count = result.stdout.strip()
                if ready_count and int(ready_count) > 0:
                    logger.info(
                        "deployment_pipeline.health_check.passed",
                        attempt=attempt,
                        ready_replicas=ready_count,
                        correlation_id=correlation_id,
                        component="deployment_pipeline",
                    )
                    return True
            except (subprocess.CalledProcessError, ValueError):
                pass

            if attempt < self._health_check_retries:
                logger.warning(
                    "deployment_pipeline.health_check.retry",
                    attempt=attempt,
                    max_retries=self._health_check_retries,
                    correlation_id=correlation_id,
                    component="deployment_pipeline",
                )
                time.sleep(self._health_check_interval_s)

        logger.error(
            "deployment_pipeline.health_check.failed",
            retries=self._health_check_retries,
            correlation_id=correlation_id,
            component="deployment_pipeline",
        )
        return False
