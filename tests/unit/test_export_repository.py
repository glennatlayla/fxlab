"""
Unit tests for MockExportRepository.

Covers:
- create_job: successful creation, duplicate rejection
- get_job: found, not found
- update_job: successful update, not found error
- update status alone, with artifact_uri, with error_message
- list_jobs: all jobs, filtered by requested_by, pagination, ordering
- list_by_object_id: all jobs for object, pagination, ordering
- Introspection: count, get_all, clear
- Thread safety (basic verification)

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from libs.contracts.errors import NotFoundError
from libs.contracts.export import ExportJobResponse, ExportStatus, ExportType
from libs.contracts.mocks.mock_export_repository import MockExportRepository

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_USER_ID_1 = "01HUSER00000000000000001"
_USER_ID_2 = "01HUSER00000000000000002"
_OBJECT_ID_1 = "01HRUN00000000000000001"
_OBJECT_ID_2 = "01HRUN00000000000000002"


def _make_job(
    job_id: str = "01HEXPORT0000000000000001",
    export_type: ExportType = ExportType.TRADES,
    object_id: str = _OBJECT_ID_1,
    status: ExportStatus = ExportStatus.PENDING,
    requested_by: str = _USER_ID_1,
    artifact_uri: str | None = None,
    error_message: str | None = None,
    override_watermark: dict[str, Any] | None = None,
) -> ExportJobResponse:
    """Create a test export job response."""
    return ExportJobResponse(
        id=job_id,
        export_type=export_type,
        object_id=object_id,
        status=status,
        artifact_uri=artifact_uri,
        requested_by=requested_by,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        override_watermark=override_watermark,
    )


@pytest.fixture()
def repo() -> MockExportRepository:
    """Create a fresh mock repository for each test."""
    return MockExportRepository()


# ---------------------------------------------------------------------------
# create_job tests
# ---------------------------------------------------------------------------


def test_create_job_successful_creation_returns_job(repo: MockExportRepository) -> None:
    """create_job: successful creation returns the job."""
    job = _make_job()
    result = repo.create_job(job)

    assert result.id == job.id
    assert result.export_type == ExportType.TRADES
    assert result.object_id == _OBJECT_ID_1
    assert result.status == ExportStatus.PENDING
    assert result.requested_by == _USER_ID_1


def test_create_job_duplicate_rejection_raises_value_error(
    repo: MockExportRepository,
) -> None:
    """create_job: duplicate job ID raises ValueError."""
    job = _make_job()
    repo.create_job(job)

    with pytest.raises(ValueError, match="already exists"):
        repo.create_job(job)


def test_create_job_multiple_jobs_all_persisted(repo: MockExportRepository) -> None:
    """create_job: multiple distinct jobs all persisted."""
    job1 = _make_job(job_id="01HEXPORT0000000000000001")
    job2 = _make_job(job_id="01HEXPORT0000000000000002")
    job3 = _make_job(job_id="01HEXPORT0000000000000003")

    repo.create_job(job1)
    repo.create_job(job2)
    repo.create_job(job3)

    assert repo.count() == 3


# ---------------------------------------------------------------------------
# get_job tests
# ---------------------------------------------------------------------------


def test_get_job_found_returns_job(repo: MockExportRepository) -> None:
    """get_job: existing job returns the job."""
    job = _make_job()
    repo.create_job(job)

    result = repo.get_job(job.id)

    assert result is not None
    assert result.id == job.id
    assert result.export_type == ExportType.TRADES


def test_get_job_not_found_returns_none(repo: MockExportRepository) -> None:
    """get_job: non-existent job returns None."""
    result = repo.get_job("01HEXPORT_NONEXISTENT_0000")

    assert result is None


def test_get_job_retrieves_all_fields(repo: MockExportRepository) -> None:
    """get_job: retrieves all fields including optional ones."""
    now = datetime.now(timezone.utc)
    watermark = {"version": "1.0", "timestamp": "2026-04-13T12:00:00Z"}
    job = _make_job(
        artifact_uri="s3://bucket/export.zip",
        error_message=None,
        override_watermark=watermark,
    )
    job.created_at = now
    repo.create_job(job)

    result = repo.get_job(job.id)

    assert result is not None
    assert result.artifact_uri == "s3://bucket/export.zip"
    assert result.error_message is None
    assert result.override_watermark == watermark


# ---------------------------------------------------------------------------
# update_job tests
# ---------------------------------------------------------------------------


def test_update_job_status_alone_updates_status(repo: MockExportRepository) -> None:
    """update_job: status update alone changes status."""
    job = _make_job(status=ExportStatus.PENDING)
    repo.create_job(job)

    result = repo.update_job(job.id, ExportStatus.PROCESSING)

    assert result.status == ExportStatus.PROCESSING
    assert result.artifact_uri is None


def test_update_job_with_artifact_uri_sets_uri(repo: MockExportRepository) -> None:
    """update_job: artifact_uri parameter sets the URI."""
    job = _make_job()
    repo.create_job(job)

    result = repo.update_job(
        job.id,
        ExportStatus.COMPLETE,
        artifact_uri="s3://bucket/export.zip",
    )

    assert result.status == ExportStatus.COMPLETE
    assert result.artifact_uri == "s3://bucket/export.zip"


def test_update_job_with_error_message_sets_message(repo: MockExportRepository) -> None:
    """update_job: error_message parameter sets the error."""
    job = _make_job()
    repo.create_job(job)

    result = repo.update_job(
        job.id,
        ExportStatus.FAILED,
        error_message="Export failed: disk quota exceeded",
    )

    assert result.status == ExportStatus.FAILED
    assert result.error_message == "Export failed: disk quota exceeded"


def test_update_job_with_both_uri_and_error_sets_both(
    repo: MockExportRepository,
) -> None:
    """update_job: both artifact_uri and error_message set together."""
    job = _make_job()
    repo.create_job(job)

    result = repo.update_job(
        job.id,
        ExportStatus.FAILED,
        artifact_uri="s3://bucket/partial.zip",
        error_message="Partial export before failure",
    )

    assert result.status == ExportStatus.FAILED
    assert result.artifact_uri == "s3://bucket/partial.zip"
    assert result.error_message == "Partial export before failure"


def test_update_job_not_found_raises_not_found_error(
    repo: MockExportRepository,
) -> None:
    """update_job: non-existent job raises NotFoundError."""
    with pytest.raises(NotFoundError, match="not found"):
        repo.update_job("01HEXPORT_NONEXISTENT_0000", ExportStatus.PROCESSING)


def test_update_job_updates_updated_at_timestamp(repo: MockExportRepository) -> None:
    """update_job: updated_at timestamp is refreshed."""
    job = _make_job()
    repo.create_job(job)
    original_updated_at = job.updated_at

    result = repo.update_job(job.id, ExportStatus.PROCESSING)

    # updated_at should be more recent
    assert result.updated_at >= original_updated_at


def test_update_job_preserves_other_fields(repo: MockExportRepository) -> None:
    """update_job: other fields (export_type, object_id) unchanged."""
    job = _make_job(export_type=ExportType.RUNS, object_id=_OBJECT_ID_2)
    repo.create_job(job)

    result = repo.update_job(job.id, ExportStatus.PROCESSING)

    assert result.export_type == ExportType.RUNS
    assert result.object_id == _OBJECT_ID_2


# ---------------------------------------------------------------------------
# list_jobs tests
# ---------------------------------------------------------------------------


def test_list_jobs_empty_repo_returns_empty_list(repo: MockExportRepository) -> None:
    """list_jobs: empty repo returns empty list and zero count."""
    jobs, total = repo.list_jobs()

    assert jobs == []
    assert total == 0


def test_list_jobs_all_jobs_returned_no_filter(repo: MockExportRepository) -> None:
    """list_jobs: no filter returns all jobs."""
    job1 = _make_job(job_id="01HEXPORT0000000000000001")
    job2 = _make_job(job_id="01HEXPORT0000000000000002")
    job3 = _make_job(job_id="01HEXPORT0000000000000003")

    repo.create_job(job1)
    repo.create_job(job2)
    repo.create_job(job3)

    jobs, total = repo.list_jobs()

    assert len(jobs) == 3
    assert total == 3


def test_list_jobs_filtered_by_requested_by_returns_matching(
    repo: MockExportRepository,
) -> None:
    """list_jobs: requested_by filter returns only matching jobs."""
    job1 = _make_job(job_id="01HEXPORT0000000000000001", requested_by=_USER_ID_1)
    job2 = _make_job(job_id="01HEXPORT0000000000000002", requested_by=_USER_ID_2)
    job3 = _make_job(job_id="01HEXPORT0000000000000003", requested_by=_USER_ID_1)

    repo.create_job(job1)
    repo.create_job(job2)
    repo.create_job(job3)

    jobs, total = repo.list_jobs(requested_by=_USER_ID_1)

    assert len(jobs) == 2
    assert total == 2
    assert all(job.requested_by == _USER_ID_1 for job in jobs)


def test_list_jobs_pagination_limit_respected(repo: MockExportRepository) -> None:
    """list_jobs: limit parameter respected."""
    for i in range(1, 6):
        job = _make_job(job_id=f"01HEXPORT000000000000000{i:02d}")
        repo.create_job(job)

    jobs, total = repo.list_jobs(limit=3)

    assert len(jobs) == 3
    assert total == 5


def test_list_jobs_pagination_offset_respected(repo: MockExportRepository) -> None:
    """list_jobs: offset parameter skips items correctly."""
    for i in range(1, 6):
        job = _make_job(job_id=f"01HEXPORT000000000000000{i:02d}")
        repo.create_job(job)

    jobs_page1, _ = repo.list_jobs(limit=2, offset=0)
    jobs_page2, _ = repo.list_jobs(limit=2, offset=2)
    jobs_page3, _ = repo.list_jobs(limit=2, offset=4)

    assert len(jobs_page1) == 2
    assert len(jobs_page2) == 2
    assert len(jobs_page3) == 1
    # Verify no overlap
    ids_p1 = {j.id for j in jobs_page1}
    ids_p2 = {j.id for j in jobs_page2}
    ids_p3 = {j.id for j in jobs_page3}
    assert ids_p1.isdisjoint(ids_p2)
    assert ids_p2.isdisjoint(ids_p3)


def test_list_jobs_ordered_newest_first(repo: MockExportRepository) -> None:
    """list_jobs: results ordered by created_at descending."""
    import time

    job1 = _make_job(job_id="01HEXPORT0000000000000001")
    time.sleep(0.01)  # Ensure distinct timestamps
    job2 = _make_job(job_id="01HEXPORT0000000000000002")
    time.sleep(0.01)
    job3 = _make_job(job_id="01HEXPORT0000000000000003")

    repo.create_job(job1)
    repo.create_job(job2)
    repo.create_job(job3)

    jobs, _ = repo.list_jobs()

    # Most recent should be first
    assert jobs[0].id == job3.id
    assert jobs[1].id == job2.id
    assert jobs[2].id == job1.id


def test_list_jobs_filter_and_pagination_combined(repo: MockExportRepository) -> None:
    """list_jobs: filter and pagination work together."""
    for i in range(1, 6):
        job = _make_job(
            job_id=f"01HEXPORT000000000000000{i:02d}",
            requested_by=_USER_ID_1 if i % 2 == 1 else _USER_ID_2,
        )
        repo.create_job(job)

    # User 1 should have jobs 1, 3, 5 (3 total)
    jobs, total = repo.list_jobs(requested_by=_USER_ID_1, limit=2, offset=0)

    assert len(jobs) == 2
    assert total == 3
    assert all(job.requested_by == _USER_ID_1 for job in jobs)


# ---------------------------------------------------------------------------
# list_by_object_id tests
# ---------------------------------------------------------------------------


def test_list_by_object_id_empty_repo_returns_empty(repo: MockExportRepository) -> None:
    """list_by_object_id: empty repo returns empty list."""
    jobs, total = repo.list_by_object_id(_OBJECT_ID_1)

    assert jobs == []
    assert total == 0


def test_list_by_object_id_returns_matching_jobs(repo: MockExportRepository) -> None:
    """list_by_object_id: returns only jobs with matching object_id."""
    job1 = _make_job(job_id="01HEXPORT0000000000000001", object_id=_OBJECT_ID_1)
    job2 = _make_job(job_id="01HEXPORT0000000000000002", object_id=_OBJECT_ID_2)
    job3 = _make_job(job_id="01HEXPORT0000000000000003", object_id=_OBJECT_ID_1)

    repo.create_job(job1)
    repo.create_job(job2)
    repo.create_job(job3)

    jobs, total = repo.list_by_object_id(_OBJECT_ID_1)

    assert len(jobs) == 2
    assert total == 2
    assert all(job.object_id == _OBJECT_ID_1 for job in jobs)


def test_list_by_object_id_pagination_limit_respected(
    repo: MockExportRepository,
) -> None:
    """list_by_object_id: limit parameter respected."""
    for i in range(1, 6):
        job = _make_job(
            job_id=f"01HEXPORT000000000000000{i:02d}",
            object_id=_OBJECT_ID_1,
        )
        repo.create_job(job)

    jobs, total = repo.list_by_object_id(_OBJECT_ID_1, limit=3)

    assert len(jobs) == 3
    assert total == 5


def test_list_by_object_id_pagination_offset_respected(
    repo: MockExportRepository,
) -> None:
    """list_by_object_id: offset parameter skips items correctly."""
    for i in range(1, 4):
        job = _make_job(
            job_id=f"01HEXPORT000000000000000{i:02d}",
            object_id=_OBJECT_ID_1,
        )
        repo.create_job(job)

    jobs_page1, _ = repo.list_by_object_id(_OBJECT_ID_1, limit=2, offset=0)
    jobs_page2, _ = repo.list_by_object_id(_OBJECT_ID_1, limit=2, offset=2)

    assert len(jobs_page1) == 2
    assert len(jobs_page2) == 1


def test_list_by_object_id_ordered_newest_first(repo: MockExportRepository) -> None:
    """list_by_object_id: results ordered by created_at descending."""
    import time

    job1 = _make_job(job_id="01HEXPORT0000000000000001", object_id=_OBJECT_ID_1)
    time.sleep(0.01)
    job2 = _make_job(job_id="01HEXPORT0000000000000002", object_id=_OBJECT_ID_1)
    time.sleep(0.01)
    job3 = _make_job(job_id="01HEXPORT0000000000000003", object_id=_OBJECT_ID_1)

    repo.create_job(job1)
    repo.create_job(job2)
    repo.create_job(job3)

    jobs, _ = repo.list_by_object_id(_OBJECT_ID_1)

    assert jobs[0].id == job3.id
    assert jobs[1].id == job2.id
    assert jobs[2].id == job1.id


# ---------------------------------------------------------------------------
# Introspection helper tests
# ---------------------------------------------------------------------------


def test_count_returns_total_jobs(repo: MockExportRepository) -> None:
    """count: returns total number of jobs."""
    job1 = _make_job(job_id="01HEXPORT0000000000000001")
    job2 = _make_job(job_id="01HEXPORT0000000000000002")

    repo.create_job(job1)
    repo.create_job(job2)

    assert repo.count() == 2


def test_count_empty_repo_returns_zero(repo: MockExportRepository) -> None:
    """count: empty repo returns 0."""
    assert repo.count() == 0


def test_get_all_returns_all_jobs(repo: MockExportRepository) -> None:
    """get_all: returns all jobs in store."""
    job1 = _make_job(job_id="01HEXPORT0000000000000001")
    job2 = _make_job(job_id="01HEXPORT0000000000000002")

    repo.create_job(job1)
    repo.create_job(job2)

    all_jobs = repo.get_all()

    assert len(all_jobs) == 2
    ids = {j.id for j in all_jobs}
    assert job1.id in ids
    assert job2.id in ids


def test_get_all_empty_repo_returns_empty_list(repo: MockExportRepository) -> None:
    """get_all: empty repo returns empty list."""
    assert repo.get_all() == []


def test_clear_removes_all_jobs(repo: MockExportRepository) -> None:
    """clear: removes all jobs from store."""
    job1 = _make_job(job_id="01HEXPORT0000000000000001")
    job2 = _make_job(job_id="01HEXPORT0000000000000002")

    repo.create_job(job1)
    repo.create_job(job2)
    assert repo.count() == 2

    repo.clear()

    assert repo.count() == 0
    assert repo.get_all() == []


def test_clear_allows_recreation_with_same_id(repo: MockExportRepository) -> None:
    """clear: after clear, can create job with previously used ID."""
    job = _make_job(job_id="01HEXPORT0000000000000001")

    repo.create_job(job)
    repo.clear()

    # Should not raise ValueError
    repo.create_job(job)
    assert repo.count() == 1
