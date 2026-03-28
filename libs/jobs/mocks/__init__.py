"""
Mocks package for jobs.

In-memory fakes for unit-testing the jobs subsystem.
Concrete implementations must never be imported here.
"""

from libs.jobs.mocks.mock_job_repository import MockJobRepository
from libs.jobs.mocks.mock_queue_service import MockQueueService

__all__ = ["MockJobRepository", "MockQueueService"]
