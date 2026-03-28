"""
Integration tests for M4 — Jobs + Queue Classes + Compute Policy.

These tests verify that the jobs and queue subsystem components work
together correctly as a complete system:

- MockJobRepository integrates with Job value objects across multiple operations.
- MockQueueService integrates with ContentionReport construction.
- GET /queues/contention endpoint returns the expected ContentionReport schema.
- GET /feed-health endpoint returns the expected feed list schema.
- Job lifecycle transitions (PENDING → RUNNING → COMPLETED) round-trip correctly.

Integration scope:
    Job value object ←→ MockJobRepository ←→ list_by_status() queries
    MockQueueService ←→ ContentionReport assembly
    FastAPI routes ←→ ContentionReport/feed-health response schema
"""

import pytest
from fastapi.testclient import TestClient

from libs.jobs.interfaces.job import ComputePolicy, Job, JobStatus, JobType
from libs.jobs.interfaces.queue import ContentionReport, QueueDepthSnapshot
from libs.jobs.mocks.mock_job_repository import MockJobRepository
from libs.jobs.mocks.mock_queue_service import MockQueueService
from services.api.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def job_repo() -> MockJobRepository:
    """Return a fresh MockJobRepository for each test."""
    return MockJobRepository()


@pytest.fixture
def queue_svc() -> MockQueueService:
    """Return a fresh MockQueueService for each test."""
    return MockQueueService()


@pytest.fixture
def api_client() -> TestClient:
    """Return a FastAPI TestClient bound to the main app."""
    return TestClient(app, raise_server_exceptions=False)


def _make_job(
    job_id: str,
    job_type: JobType = JobType.OPTIMIZATION,
    status: JobStatus = JobStatus.PENDING,
    compute_policy: ComputePolicy = ComputePolicy.STANDARD,
) -> Job:
    """Factory for Job instances with sensible defaults."""
    return Job(
        id=job_id,
        type=job_type,
        status=status,
        compute_policy=compute_policy,
    )


# ---------------------------------------------------------------------------
# Job lifecycle integration
# ---------------------------------------------------------------------------


class TestJobLifecycleIntegration:
    """
    Verify that Job status transitions round-trip correctly through
    MockJobRepository, simulating a PENDING → RUNNING → COMPLETED flow.
    """

    def test_job_pending_to_running_transition(
        self, job_repo: MockJobRepository
    ) -> None:
        """Job can be saved in PENDING, then updated to RUNNING."""
        job = _make_job("01HQAAAAAAAAAAAAAAAAAAAAAA", status=JobStatus.PENDING)
        job_repo.save(job)

        # Simulate the runner picking it up
        running_job = Job(
            id="01HQAAAAAAAAAAAAAAAAAAAAAA",
            type=JobType.OPTIMIZATION,
            status=JobStatus.RUNNING,
            compute_policy=ComputePolicy.STANDARD,
        )
        job_repo.save(running_job)

        retrieved = job_repo.get("01HQAAAAAAAAAAAAAAAAAAAAAA")
        assert retrieved.status == JobStatus.RUNNING
        assert retrieved.is_active() is True

    def test_job_running_to_completed_transition(
        self, job_repo: MockJobRepository
    ) -> None:
        """Job can be updated from RUNNING to COMPLETED."""
        running = _make_job("01HQBBBBBBBBBBBBBBBBBBBBBB", status=JobStatus.RUNNING)
        job_repo.save(running)

        completed = Job(
            id="01HQBBBBBBBBBBBBBBBBBBBBBB",
            type=JobType.OPTIMIZATION,
            status=JobStatus.COMPLETED,
            compute_policy=ComputePolicy.STANDARD,
        )
        job_repo.save(completed)

        retrieved = job_repo.get("01HQBBBBBBBBBBBBBBBBBBBBBB")
        assert retrieved.status == JobStatus.COMPLETED
        assert retrieved.is_terminal() is True

    def test_multiple_jobs_different_statuses(
        self, job_repo: MockJobRepository
    ) -> None:
        """Repository correctly segregates jobs by status."""
        pending_ids = [
            "01HQAAAAAAAAAAAAAAAAAAAAAA",
            "01HQBBBBBBBBBBBBBBBBBBBBBB",
        ]
        completed_id = "01HQCCCCCCCCCCCCCCCCCCCCCC"

        for jid in pending_ids:
            job_repo.save(_make_job(jid, status=JobStatus.PENDING))
        job_repo.save(_make_job(completed_id, status=JobStatus.COMPLETED))

        pending = job_repo.list_by_status(JobStatus.PENDING)
        completed = job_repo.list_by_status(JobStatus.COMPLETED)

        assert len(pending) == 2
        assert len(completed) == 1
        assert completed[0].id == completed_id

    def test_different_job_types_stored_and_retrieved(
        self, job_repo: MockJobRepository
    ) -> None:
        """Jobs of different types coexist in the repository."""
        for i, jtype in enumerate(JobType):
            uid = f"01HQAAAAAAAAAAAAAAAAAAAAAA"[: -1] + str(i)
            uid = "01HQAAAAAAAAAAAAAAAAAAAAAA"[:25] + str(i)
            job_repo.save(
                Job(
                    id=uid,
                    type=jtype,
                    status=JobStatus.PENDING,
                    compute_policy=ComputePolicy.STANDARD,
                )
            )

        assert job_repo.count() == len(JobType)

    def test_compute_policy_preserved_on_round_trip(
        self, job_repo: MockJobRepository
    ) -> None:
        """ComputePolicy is preserved when saving and retrieving a job."""
        job = _make_job(
            "01HQDDDDDDDDDDDDDDDDDDDDDD",
            compute_policy=ComputePolicy.EXCLUSIVE,
        )
        job_repo.save(job)
        retrieved = job_repo.get("01HQDDDDDDDDDDDDDDDDDDDDDD")
        assert retrieved.compute_policy == ComputePolicy.EXCLUSIVE


# ---------------------------------------------------------------------------
# Queue service integration
# ---------------------------------------------------------------------------


class TestQueueServiceIntegration:
    """
    Verify that MockQueueService correctly assembles ContentionReport from
    multiple snapshots and that the overall_score is preserved.
    """

    def test_empty_service_returns_zero_score(
        self, queue_svc: MockQueueService
    ) -> None:
        """A fresh service with no snapshots returns overall_score=0.0."""
        report = queue_svc.get_contention_report()
        assert report.overall_score == 0.0
        assert report.queues == []

    def test_report_includes_all_registered_snapshots(
        self, queue_svc: MockQueueService
    ) -> None:
        """All snapshots added to the service appear in the report."""
        queue_svc.set_overall_score(45.0)
        queue_svc.add_snapshot(
            QueueDepthSnapshot(queue_name="optimization", depth=8, contention_score=45.0)
        )
        queue_svc.add_snapshot(
            QueueDepthSnapshot(queue_name="backtest", depth=2, contention_score=20.0)
        )

        report = queue_svc.get_contention_report()

        assert len(report.queues) == 2
        names = {s.queue_name for s in report.queues}
        assert names == {"optimization", "backtest"}
        assert report.overall_score == 45.0

    def test_contention_report_is_immutable(
        self, queue_svc: MockQueueService
    ) -> None:
        """ContentionReport returned by the service is a frozen model."""
        queue_svc.set_overall_score(10.0)
        report = queue_svc.get_contention_report()
        with pytest.raises(Exception):  # ValidationError or TypeError (frozen model)
            report.overall_score = 99.0  # type: ignore[misc]

    def test_clear_produces_empty_report_on_next_call(
        self, queue_svc: MockQueueService
    ) -> None:
        """After clear(), the next report has no queues and score 0."""
        queue_svc.add_snapshot(
            QueueDepthSnapshot(queue_name="q", depth=5, contention_score=60.0)
        )
        queue_svc.set_overall_score(60.0)
        queue_svc.clear()

        report = queue_svc.get_contention_report()
        assert report.queues == []
        assert report.overall_score == 0.0

    def test_multiple_calls_all_tracked(
        self, queue_svc: MockQueueService
    ) -> None:
        """call_count correctly counts multiple get_contention_report() calls."""
        for _ in range(5):
            queue_svc.get_contention_report()
        assert queue_svc.call_count == 5


# ---------------------------------------------------------------------------
# API endpoint integration
# ---------------------------------------------------------------------------


class TestQueuesContentionEndpointIntegration:
    """
    Integration tests for the M7 queue contention endpoints.

    M7 replaced the aggregate GET /queues/contention endpoint with
    per-class routing: GET /queues/{queue_class}/contention.
    These tests verify the M7 API shape.
    """

    def test_queues_list_returns_200(self, api_client: TestClient) -> None:
        """
        GET /queues/ returns HTTP 200 with the queue list shape.

        RATIONALE: M7 removed the aggregate /queues/contention endpoint.
        The canonical queue list endpoint is GET /queues/.
        """
        response = api_client.get("/queues/")
        assert response.status_code == 200

    def test_queues_list_has_queues_key(self, api_client: TestClient) -> None:
        """GET /queues/ response body contains a 'queues' key."""
        response = api_client.get("/queues/")
        body = response.json()
        assert "queues" in body

    def test_per_class_contention_unknown_class_returns_404(
        self, api_client: TestClient
    ) -> None:
        """
        GET /queues/{unknown_class}/contention returns 404.

        RATIONALE: M7 routes contention per queue_class; an unknown class
        raises NotFoundError which the handler maps to HTTP 404.
        """
        response = api_client.get("/queues/NONEXISTENT_CLASS/contention")
        assert response.status_code == 404

    def test_queues_field_is_list(self, api_client: TestClient) -> None:
        """GET /queues/ response 'queues' field is a JSON array."""
        response = api_client.get("/queues/")
        body = response.json()
        assert isinstance(body["queues"], list)


class TestFeedHealthEndpointIntegration:
    """
    Integration tests for GET /feed-health.

    Verifies the full request path returns a correctly shaped response.
    """

    def test_endpoint_returns_200(self, api_client: TestClient) -> None:
        """GET /feed-health returns HTTP 200."""
        response = api_client.get("/feed-health")
        assert response.status_code == 200

    def test_response_has_feeds_and_generated_at(
        self, api_client: TestClient
    ) -> None:
        """Response body contains 'feeds' list and 'generated_at' timestamp."""
        response = api_client.get("/feed-health")
        body = response.json()
        assert "feeds" in body
        assert "generated_at" in body

    def test_feeds_field_is_list(self, api_client: TestClient) -> None:
        """Response 'feeds' field is a JSON array."""
        response = api_client.get("/feed-health")
        body = response.json()
        assert isinstance(body["feeds"], list)

    def test_stub_returns_empty_feeds_list(self, api_client: TestClient) -> None:
        """Stub phase returns an empty feeds list."""
        response = api_client.get("/feed-health")
        assert response.json()["feeds"] == []
