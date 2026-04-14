"""
In-memory mock implementation of JobRepositoryInterface.

Responsibilities:
- Store Job objects in memory for unit and integration tests.
- Implement all JobRepositoryInterface methods.
- Provide introspection helpers for test assertions.

Does NOT:
- Connect to a database or queue backend.
- Contain business logic.

Example:
    repo = MockJobRepository()
    job = Job(id="01HQAAAAAAAAAAAAAAAAAAAAAA", type=JobType.BACKTEST,
              status=JobStatus.PENDING, compute_policy=ComputePolicy.STANDARD)
    repo.save(job)
    retrieved = repo.get("01HQAAAAAAAAAAAAAAAAAAAAAA")
    assert retrieved.status == JobStatus.PENDING
"""

from libs.contracts.errors import NotFoundError
from libs.jobs.interfaces.job import Job, JobRepositoryInterface, JobStatus


class MockJobRepository(JobRepositoryInterface):
    """
    In-memory job store for unit testing.

    Responsibilities:
    - Accept save() and return the stored job.
    - Raise NotFoundError on get() for unknown IDs.
    - Support list_by_status() filtering.

    Does NOT:
    - Persist between test runs.
    - Validate ULID format (assumes callers provide valid IDs).

    Example:
        repo = MockJobRepository()
        repo.save(job)
        assert repo.count() == 1
        assert repo.get(job.id) == job
    """

    def __init__(self) -> None:
        """Initialise an empty in-memory store."""
        self._store: dict[str, Job] = {}
        self.save_call_count: int = 0

    def save(self, job: Job) -> Job:
        """
        Persist (insert or overwrite) the given job.

        Args:
            job: Job value object to store.

        Returns:
            The same job (no server-side mutations in mock).
        """
        self._store[job.id] = job
        self.save_call_count += 1
        return job

    def get(self, job_id: str) -> Job:
        """
        Retrieve a job by ULID.

        Args:
            job_id: ULID of the job.

        Returns:
            The stored Job.

        Raises:
            NotFoundError: If no job with that id has been saved.
        """
        if job_id not in self._store:
            raise NotFoundError(f"Job {job_id!r} not found in MockJobRepository")
        return self._store[job_id]

    def list_by_status(self, status: JobStatus) -> list[Job]:
        """
        Return all jobs in the given status.

        Args:
            status: Filter to this JobStatus.

        Returns:
            List of matching jobs (may be empty).
        """
        return [j for j in self._store.values() if j.status == status]

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return total number of stored jobs."""
        return len(self._store)

    def get_all(self) -> list[Job]:
        """Return all stored jobs as a list."""
        return list(self._store.values())

    def clear(self) -> None:
        """Reset the store and call counters."""
        self._store.clear()
        self.save_call_count = 0


__all__ = ["MockJobRepository"]
