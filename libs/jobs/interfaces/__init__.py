"""
Interfaces package for jobs.

Abstract ports (ABCs / Protocols) for the jobs subsystem.
Concrete implementations must never be imported here.
"""

from libs.jobs.interfaces.job import (
    ComputePolicy,
    Job,
    JobRepositoryInterface,
    JobStatus,
    JobType,
)
from libs.jobs.interfaces.queue import (
    ContentionReport,
    QueueDepthSnapshot,
    QueueServiceInterface,
)

__all__ = [
    "ComputePolicy",
    "ContentionReport",
    "Job",
    "JobRepositoryInterface",
    "JobStatus",
    "JobType",
    "QueueDepthSnapshot",
    "QueueServiceInterface",
]
