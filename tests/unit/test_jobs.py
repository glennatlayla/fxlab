"""
RED unit tests for M4 — Jobs + Queue Classes + Compute Policy.

Tests verify:
- Job value object has correct fields and computed properties.
- JobStatus, JobType, ComputePolicy enums have expected values.
- MockJobRepository correctly implements JobRepositoryInterface.
- QueueDepthSnapshot and ContentionReport have correct fields.
- MockQueueService correctly implements QueueServiceInterface.
- GET /queues/contention endpoint returns correct response schema.
- GET /feed-health endpoint returns correct response schema.

RED markers (tests that FAIL until GREEN implementation):
- test_queues_contention_endpoint_returns_200_with_report
  → Fails because GET /queues/contention returns only a stub {} response,
    not the ContentionReport schema the test expects.
- test_feed_health_endpoint_returns_200_with_feeds_key
  → Fails because GET /feed-health returns 404 (no route registered).
"""

import pytest
from fastapi.testclient import TestClient

from libs.contracts.errors import NotFoundError
from libs.jobs.interfaces.job import ComputePolicy, Job, JobStatus, JobType
from libs.jobs.interfaces.queue import ContentionReport, QueueDepthSnapshot
from libs.jobs.mocks.mock_job_repository import MockJobRepository
from libs.jobs.mocks.mock_queue_service import MockQueueService

AUTH_HEADERS = {"Authorization": "Bearer TEST_TOKEN"}

# ---------------------------------------------------------------------------
# Job value object tests
# ---------------------------------------------------------------------------


class TestJobValueObject:
    """Verify the Job Pydantic model has correct fields and behaviour."""

    _VALID_JOB_KWARGS = {
        "id": "01HQAAAAAAAAAAAAAAAAAAAAAA",
        "type": JobType.OPTIMIZATION,
        "status": JobStatus.PENDING,
        "compute_policy": ComputePolicy.STANDARD,
    }

    def test_job_id_field_required(self) -> None:
        """Job.id is required."""
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            Job(
                type=JobType.BACKTEST,
                status=JobStatus.PENDING,
                compute_policy=ComputePolicy.STANDARD,
            )

    def test_job_type_field_required(self) -> None:
        """Job.type is required."""
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            Job(
                id="01HQAAAAAAAAAAAAAAAAAAAAAA",
                status=JobStatus.PENDING,
                compute_policy=ComputePolicy.STANDARD,
            )

    def test_job_status_field_required(self) -> None:
        """Job.status is required."""
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            Job(
                id="01HQAAAAAAAAAAAAAAAAAAAAAA",
                type=JobType.BACKTEST,
                compute_policy=ComputePolicy.STANDARD,
            )

    def test_job_compute_policy_defaults_to_standard(self) -> None:
        """compute_policy defaults to STANDARD when omitted."""
        job = Job(
            id="01HQAAAAAAAAAAAAAAAAAAAAAA",
            type=JobType.BACKTEST,
            status=JobStatus.PENDING,
        )
        assert job.compute_policy == ComputePolicy.STANDARD

    def test_job_is_terminal_for_completed(self) -> None:
        """Job.is_terminal() returns True for COMPLETED status."""
        job = Job(**{**self._VALID_JOB_KWARGS, "status": JobStatus.COMPLETED})
        assert job.is_terminal() is True

    def test_job_is_terminal_for_failed(self) -> None:
        """Job.is_terminal() returns True for FAILED status."""
        job = Job(**{**self._VALID_JOB_KWARGS, "status": JobStatus.FAILED})
        assert job.is_terminal() is True

    def test_job_is_terminal_for_cancelled(self) -> None:
        """Job.is_terminal() returns True for CANCELLED status."""
        job = Job(**{**self._VALID_JOB_KWARGS, "status": JobStatus.CANCELLED})
        assert job.is_terminal() is True

    def test_job_is_not_terminal_for_pending(self) -> None:
        """Job.is_terminal() returns False for PENDING status."""
        job = Job(**self._VALID_JOB_KWARGS)
        assert job.is_terminal() is False

    def test_job_is_not_terminal_for_running(self) -> None:
        """Job.is_terminal() returns False for RUNNING status."""
        job = Job(**{**self._VALID_JOB_KWARGS, "status": JobStatus.RUNNING})
        assert job.is_terminal() is False

    def test_job_is_active_for_pending(self) -> None:
        """Job.is_active() returns True for PENDING status."""
        job = Job(**self._VALID_JOB_KWARGS)
        assert job.is_active() is True

    def test_job_is_active_for_running(self) -> None:
        """Job.is_active() returns True for RUNNING status."""
        job = Job(**{**self._VALID_JOB_KWARGS, "status": JobStatus.RUNNING})
        assert job.is_active() is True

    def test_job_is_not_active_for_terminal(self) -> None:
        """Job.is_active() returns False for terminal statuses."""
        for terminal_status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
            job = Job(**{**self._VALID_JOB_KWARGS, "status": terminal_status})
            assert job.is_active() is False, f"Expected not active for {terminal_status}"

    def test_job_is_frozen(self) -> None:
        """Job is immutable (frozen Pydantic model)."""
        job = Job(**self._VALID_JOB_KWARGS)
        with pytest.raises(Exception):  # ValidationError or TypeError depending on Pydantic version
            job.status = JobStatus.COMPLETED  # type: ignore[misc]

    def test_job_metadata_defaults_to_empty_dict(self) -> None:
        """Job.metadata defaults to an empty dict."""
        job = Job(**self._VALID_JOB_KWARGS)
        assert job.metadata == {}


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestJobStatusEnum:
    """Verify JobStatus enum values."""

    def test_pending_exists(self) -> None:
        assert JobStatus.PENDING == "pending"

    def test_running_exists(self) -> None:
        assert JobStatus.RUNNING == "running"

    def test_completed_exists(self) -> None:
        assert JobStatus.COMPLETED == "completed"

    def test_failed_exists(self) -> None:
        assert JobStatus.FAILED == "failed"

    def test_cancelled_exists(self) -> None:
        assert JobStatus.CANCELLED == "cancelled"

    def test_five_statuses_defined(self) -> None:
        assert len(JobStatus) == 5


class TestJobTypeEnum:
    """Verify JobType enum values."""

    def test_optimization_exists(self) -> None:
        assert JobType.OPTIMIZATION == "optimization"

    def test_backtest_exists(self) -> None:
        assert JobType.BACKTEST == "backtest"

    def test_promotion_validation_exists(self) -> None:
        assert JobType.PROMOTION_VALIDATION == "promotion_validation"

    def test_feed_verification_exists(self) -> None:
        assert JobType.FEED_VERIFICATION == "feed_verification"

    def test_parity_check_exists(self) -> None:
        assert JobType.PARITY_CHECK == "parity_check"


class TestComputePolicyEnum:
    """Verify ComputePolicy enum values."""

    def test_standard_exists(self) -> None:
        assert ComputePolicy.STANDARD == "standard"

    def test_high_priority_exists(self) -> None:
        assert ComputePolicy.HIGH_PRIORITY == "high_priority"

    def test_exclusive_exists(self) -> None:
        assert ComputePolicy.EXCLUSIVE == "exclusive"

    def test_three_policies_defined(self) -> None:
        assert len(ComputePolicy) == 3


# ---------------------------------------------------------------------------
# MockJobRepository tests
# ---------------------------------------------------------------------------


class TestMockJobRepository:
    """Verify MockJobRepository implements JobRepositoryInterface correctly."""

    _JOB = Job(
        id="01HQAAAAAAAAAAAAAAAAAAAAAA",
        type=JobType.OPTIMIZATION,
        status=JobStatus.PENDING,
        compute_policy=ComputePolicy.STANDARD,
    )

    def test_save_and_retrieve_job(self) -> None:
        """save() and get() round-trip correctly."""
        repo = MockJobRepository()
        repo.save(self._JOB)
        retrieved = repo.get("01HQAAAAAAAAAAAAAAAAAAAAAA")
        # Compare via model_dump: pydantic-core stub in this sandbox may not
        # support direct frozen-model equality (ISS-006 / LL-007).
        assert retrieved.model_dump() == self._JOB.model_dump()

    def test_get_raises_not_found_for_unknown_id(self) -> None:
        """get() raises NotFoundError for an unregistered job ID."""
        repo = MockJobRepository()
        with pytest.raises(NotFoundError):
            repo.get("01HQBBBBBBBBBBBBBBBBBBBBBB")

    def test_save_overwrites_existing(self) -> None:
        """save() with the same ID replaces the existing record."""
        repo = MockJobRepository()
        repo.save(self._JOB)
        updated = Job(
            id="01HQAAAAAAAAAAAAAAAAAAAAAA",
            type=JobType.OPTIMIZATION,
            status=JobStatus.RUNNING,
            compute_policy=ComputePolicy.STANDARD,
        )
        repo.save(updated)
        assert repo.get("01HQAAAAAAAAAAAAAAAAAAAAAA").status == JobStatus.RUNNING

    def test_list_by_status_returns_matching(self) -> None:
        """list_by_status() returns only jobs in the requested state."""
        repo = MockJobRepository()
        pending = Job(
            id="01HQAAAAAAAAAAAAAAAAAAAAAA",
            type=JobType.BACKTEST,
            status=JobStatus.PENDING,
            compute_policy=ComputePolicy.STANDARD,
        )
        completed = Job(
            id="01HQBBBBBBBBBBBBBBBBBBBBBB",
            type=JobType.BACKTEST,
            status=JobStatus.COMPLETED,
            compute_policy=ComputePolicy.STANDARD,
        )
        repo.save(pending)
        repo.save(completed)
        pending_list = repo.list_by_status(JobStatus.PENDING)
        assert len(pending_list) == 1
        assert pending_list[0].id == "01HQAAAAAAAAAAAAAAAAAAAAAA"

    def test_list_by_status_returns_empty_when_none_match(self) -> None:
        """list_by_status() returns [] when no jobs match."""
        repo = MockJobRepository()
        repo.save(self._JOB)
        assert repo.list_by_status(JobStatus.RUNNING) == []

    def test_save_call_count_increments(self) -> None:
        """save_call_count tracks the number of save() calls."""
        repo = MockJobRepository()
        repo.save(self._JOB)
        repo.save(self._JOB)
        assert repo.save_call_count == 2

    def test_count_reflects_stored_jobs(self) -> None:
        """count() returns the number of stored jobs."""
        repo = MockJobRepository()
        assert repo.count() == 0
        repo.save(self._JOB)
        assert repo.count() == 1

    def test_get_all_returns_all_jobs(self) -> None:
        """get_all() returns all stored jobs."""
        repo = MockJobRepository()
        repo.save(self._JOB)
        all_jobs = repo.get_all()
        assert len(all_jobs) == 1
        assert all_jobs[0].id == self._JOB.id
        assert all_jobs[0].status == self._JOB.status

    def test_clear_resets_store_and_counters(self) -> None:
        """clear() removes all jobs and resets call counts."""
        repo = MockJobRepository()
        repo.save(self._JOB)
        repo.clear()
        assert repo.count() == 0
        assert repo.save_call_count == 0
        with pytest.raises(NotFoundError):
            repo.get("01HQAAAAAAAAAAAAAAAAAAAAAA")


# ---------------------------------------------------------------------------
# Queue value objects and MockQueueService tests
# ---------------------------------------------------------------------------


class TestQueueValueObjects:
    """Verify QueueDepthSnapshot and ContentionReport schemas.

    Note: pydantic-core may use a stub implementation in this sandbox that
    silently skips runtime constraint enforcement (ISS-006/LL-007).  Tests
    verify field constraint declarations via model_fields inspection rather
    than expecting ValidationError at construction time.
    """

    def test_snapshot_contention_score_has_lower_bound_declared(self) -> None:
        """contention_score field declares ge=0.0 constraint."""

        field = QueueDepthSnapshot.model_fields["contention_score"]
        ge_constraints = [m for m in field.metadata if hasattr(m, "ge")]
        assert ge_constraints, "contention_score must declare ge=0.0 constraint"
        assert ge_constraints[0].ge == 0.0

    def test_snapshot_contention_score_has_upper_bound_declared(self) -> None:
        """contention_score field declares le=100.0 constraint."""
        field = QueueDepthSnapshot.model_fields["contention_score"]
        le_constraints = [m for m in field.metadata if hasattr(m, "le")]
        assert le_constraints, "contention_score must declare le=100.0 constraint"
        assert le_constraints[0].le == 100.0

    def test_snapshot_depth_has_non_negative_bound_declared(self) -> None:
        """depth field declares ge=0 constraint."""
        field = QueueDepthSnapshot.model_fields["depth"]
        ge_constraints = [m for m in field.metadata if hasattr(m, "ge")]
        assert ge_constraints, "depth must declare ge=0 constraint"
        assert ge_constraints[0].ge == 0

    def test_contention_report_overall_score_has_bounds_declared(self) -> None:
        """ContentionReport.overall_score declares ge=0.0 and le=100.0."""
        field = ContentionReport.model_fields["overall_score"]
        ge_constraints = [m for m in field.metadata if hasattr(m, "ge")]
        le_constraints = [m for m in field.metadata if hasattr(m, "le")]
        assert ge_constraints, "overall_score must declare ge=0.0"
        assert le_constraints, "overall_score must declare le=100.0"

    def test_contention_report_queues_defaults_to_empty(self) -> None:
        """ContentionReport.queues defaults to an empty list."""
        report = ContentionReport(overall_score=0.0)
        assert report.queues == []


class TestMockQueueService:
    """Verify MockQueueService implements QueueServiceInterface correctly."""

    def test_get_contention_report_returns_report(self) -> None:
        """get_contention_report() returns a ContentionReport."""
        svc = MockQueueService(overall_score=25.0)
        report = svc.get_contention_report()
        assert isinstance(report, ContentionReport)
        assert report.overall_score == 25.0

    def test_add_snapshot_appears_in_report(self) -> None:
        """Snapshots added via add_snapshot() appear in the next report."""
        svc = MockQueueService(overall_score=50.0)
        snap = QueueDepthSnapshot(queue_name="opt", depth=7, contention_score=50.0)
        svc.add_snapshot(snap)
        report = svc.get_contention_report()
        assert len(report.queues) == 1
        assert report.queues[0].queue_name == "opt"

    def test_multiple_snapshots_all_included(self) -> None:
        """Multiple snapshots all appear in the report."""
        svc = MockQueueService(overall_score=60.0)
        svc.add_snapshot(QueueDepthSnapshot(queue_name="a", depth=1, contention_score=30.0))
        svc.add_snapshot(QueueDepthSnapshot(queue_name="b", depth=4, contention_score=60.0))
        report = svc.get_contention_report()
        assert len(report.queues) == 2

    def test_call_count_increments(self) -> None:
        """call_count tracks how many times get_contention_report() was called."""
        svc = MockQueueService()
        svc.get_contention_report()
        svc.get_contention_report()
        assert svc.call_count == 2

    def test_set_overall_score_changes_report(self) -> None:
        """set_overall_score() changes the score in the next report."""
        svc = MockQueueService(overall_score=10.0)
        svc.set_overall_score(75.0)
        report = svc.get_contention_report()
        assert report.overall_score == 75.0

    def test_clear_resets_snapshots_and_counters(self) -> None:
        """clear() removes snapshots and resets call_count."""
        svc = MockQueueService(overall_score=50.0)
        svc.add_snapshot(QueueDepthSnapshot(queue_name="q", depth=2, contention_score=50.0))
        svc.get_contention_report()
        svc.clear()
        report = svc.get_contention_report()
        assert svc.call_count == 1  # the call above, not the cleared one
        assert len(report.queues) == 0
        assert report.overall_score == 0.0


# ---------------------------------------------------------------------------
# API endpoint RED tests
# ---------------------------------------------------------------------------


class TestQueuesContentionEndpoint:
    """
    GREEN (M7): Queue contention endpoint tests updated to the M7 API shape.

    M7 replaced the aggregate GET /queues/contention (ContentionReport) with
    per-class GET /queues/{queue_class}/contention (QueueContentionResponse).
    These tests were rewritten to match the new spec.

    Pre-M7 tests expected overall_score + queues aggregate — see
    test_m7_charts_and_queues.py::TestQueueContentionEndpoint for comprehensive
    per-class coverage.
    """

    def test_queues_contention_unknown_class_returns_404(self) -> None:
        """
        GET /queues/{queue_class}/contention returns 404 for an unknown queue class.

        M7: The aggregate /queues/contention endpoint no longer exists.
        Per-class routing means /queues/contention treats 'contention' as
        the queue_class name, which is unknown → 404.

        GREEN: This verifies the new M7 per-class 404 behaviour.
        """
        from services.api.main import app

        client = TestClient(app, raise_server_exceptions=False)
        # 'contention' is not a registered queue class → 404
        response = client.get("/queues/contention/contention", headers=AUTH_HEADERS)
        assert response.status_code == 404

    def test_queues_list_endpoint_returns_200_with_queues_key(self) -> None:
        """
        GET /queues/ returns 200 with a 'queues' list key.

        M7: The aggregate endpoint shape was replaced by GET /queues/ which
        returns {queues: [...], generated_at: "..."}.
        """
        from services.api.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/queues/", headers=AUTH_HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert "queues" in body, f"Response must include 'queues' list key: {body}"
        assert isinstance(body["queues"], list), "queues must be a list"


class TestFeedHealthEndpoint:
    """
    RED: GET /feed-health must return a response with a 'feeds' list.

    This test FAILS until the feed-health route is wired to return data.
    """

    def test_feed_health_endpoint_returns_200(self) -> None:
        """
        GET /feed-health must return 200.

        RED: Currently returns 404 because the router stub has no GET route.
        Will FAIL until the route is implemented in GREEN.
        """
        from services.api.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/feed-health", headers=AUTH_HEADERS)
        assert response.status_code == 200

    def test_feed_health_response_has_feeds_key(self) -> None:
        """GET /feed-health response must contain a 'feeds' key."""
        from services.api.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/feed-health", headers=AUTH_HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert "feeds" in body, "Response must include 'feeds' list field."
