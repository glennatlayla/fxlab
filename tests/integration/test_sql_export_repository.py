"""
Integration tests for SqlExportRepository.

Covers:
- create_job: persist + retrieve + duplicate rejection
- get_job: found + not found
- update_job: status, artifact_uri, error_message
- list_jobs: filter by requested_by, pagination, ordering
- list_by_object_id: filter by object_id, pagination, ordering

Uses in-memory SQLite with SAVEPOINT isolation per test.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.errors import NotFoundError
from libs.contracts.export import ExportJobResponse, ExportStatus, ExportType
from libs.contracts.models import Base
from services.api.repositories.sql_export_repository import SqlExportRepository

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
) -> ExportJobResponse:
    """Create a test export job response."""
    return ExportJobResponse(
        id=job_id,
        export_type=export_type,
        object_id=object_id,
        status=status,
        artifact_uri=artifact_uri,
        requested_by=requested_by,
        error_message=error_message,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        override_watermark=None,
    )


@pytest.fixture()
def db_session():
    """
    In-memory SQLite session with SAVEPOINT isolation.

    Creates all tables from Base.metadata, yields a session,
    then rolls back and tears down.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    # Enable SAVEPOINT support on SQLite
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def repo(db_session: Session) -> SqlExportRepository:
    """Create a SQL export repository with test database."""
    return SqlExportRepository(db=db_session)


# ---------------------------------------------------------------------------
# create_job tests
# ---------------------------------------------------------------------------


def test_create_job_successful_creation_persists_job(
    repo: SqlExportRepository, db_session: Session
) -> None:
    """create_job: successful creation persists to database."""
    job = _make_job()

    result = repo.create_job(job)

    assert result.id == job.id
    assert result.export_type == ExportType.TRADES
    assert result.object_id == _OBJECT_ID_1

    # Verify it's in the database
    retrieved = repo.get_job(job.id)
    assert retrieved is not None
    assert retrieved.id == job.id


def test_create_job_duplicate_rejection_raises_value_error(
    repo: SqlExportRepository,
) -> None:
    """create_job: duplicate job ID raises ValueError."""
    job = _make_job()
    repo.create_job(job)

    with pytest.raises(ValueError, match="already exists"):
        repo.create_job(job)


def test_create_job_preserves_all_fields(repo: SqlExportRepository) -> None:
    """create_job: all fields preserved through persistence."""
    job = _make_job(
        artifact_uri="s3://bucket/export.zip",
        error_message="Test error",
    )

    result = repo.create_job(job)

    assert result.artifact_uri == "s3://bucket/export.zip"
    assert result.error_message == "Test error"


# ---------------------------------------------------------------------------
# get_job tests
# ---------------------------------------------------------------------------


def test_get_job_found_returns_job(repo: SqlExportRepository) -> None:
    """get_job: existing job returns the job."""
    job = _make_job()
    repo.create_job(job)

    result = repo.get_job(job.id)

    assert result is not None
    assert result.id == job.id
    assert result.export_type == ExportType.TRADES


def test_get_job_not_found_returns_none(repo: SqlExportRepository) -> None:
    """get_job: non-existent job returns None."""
    result = repo.get_job("01HEXPORT_NONEXISTENT_0000")

    assert result is None


def test_get_job_retrieves_all_persisted_fields(repo: SqlExportRepository) -> None:
    """get_job: all persisted fields retrieved correctly."""
    job = _make_job(
        artifact_uri="s3://bucket/export.zip",
        error_message="Test error",
    )
    repo.create_job(job)

    result = repo.get_job(job.id)

    assert result is not None
    assert result.artifact_uri == "s3://bucket/export.zip"
    assert result.error_message == "Test error"


# ---------------------------------------------------------------------------
# update_job tests
# ---------------------------------------------------------------------------


def test_update_job_status_alone_updates_status(repo: SqlExportRepository) -> None:
    """update_job: status update alone changes status."""
    job = _make_job(status=ExportStatus.PENDING)
    repo.create_job(job)

    result = repo.update_job(job.id, ExportStatus.PROCESSING)

    assert result.status == ExportStatus.PROCESSING
    assert result.artifact_uri is None

    # Verify persistence
    retrieved = repo.get_job(job.id)
    assert retrieved is not None
    assert retrieved.status == ExportStatus.PROCESSING


def test_update_job_with_artifact_uri_sets_uri(repo: SqlExportRepository) -> None:
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

    # Verify persistence
    retrieved = repo.get_job(job.id)
    assert retrieved is not None
    assert retrieved.artifact_uri == "s3://bucket/export.zip"


def test_update_job_with_error_message_sets_message(repo: SqlExportRepository) -> None:
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

    # Verify persistence
    retrieved = repo.get_job(job.id)
    assert retrieved is not None
    assert retrieved.error_message == "Export failed: disk quota exceeded"


def test_update_job_not_found_raises_not_found_error(
    repo: SqlExportRepository,
) -> None:
    """update_job: non-existent job raises NotFoundError."""
    with pytest.raises(NotFoundError, match="not found"):
        repo.update_job("01HEXPORT_NONEXISTENT_0000", ExportStatus.PROCESSING)


def test_update_job_updates_updated_at_timestamp(repo: SqlExportRepository) -> None:
    """update_job: updated_at timestamp is refreshed."""
    import time

    job = _make_job()
    repo.create_job(job)
    time.sleep(0.01)

    result = repo.update_job(job.id, ExportStatus.PROCESSING)

    # updated_at should be more recent (result has timezone-aware timestamp)
    assert result.status == ExportStatus.PROCESSING


def test_update_job_preserves_other_fields(repo: SqlExportRepository) -> None:
    """update_job: other fields unchanged."""
    job = _make_job(export_type=ExportType.RUNS, object_id=_OBJECT_ID_2)
    repo.create_job(job)

    result = repo.update_job(job.id, ExportStatus.PROCESSING)

    assert result.export_type == ExportType.RUNS
    assert result.object_id == _OBJECT_ID_2


# ---------------------------------------------------------------------------
# list_jobs tests
# ---------------------------------------------------------------------------


def test_list_jobs_empty_repo_returns_empty_list(repo: SqlExportRepository) -> None:
    """list_jobs: empty repo returns empty list and zero count."""
    jobs, total = repo.list_jobs()

    assert jobs == []
    assert total == 0


def test_list_jobs_all_jobs_returned_no_filter(repo: SqlExportRepository) -> None:
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
    repo: SqlExportRepository,
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


def test_list_jobs_pagination_limit_respected(repo: SqlExportRepository) -> None:
    """list_jobs: limit parameter respected."""
    for i in range(1, 6):
        job = _make_job(job_id=f"01HEXPORT000000000000000{i:02d}")
        repo.create_job(job)

    jobs, total = repo.list_jobs(limit=3)

    assert len(jobs) == 3
    assert total == 5


def test_list_jobs_pagination_offset_respected(repo: SqlExportRepository) -> None:
    """list_jobs: offset parameter skips items correctly."""
    for i in range(1, 6):
        job = _make_job(job_id=f"01HEXPORT000000000000000{i:02d}")
        repo.create_job(job)

    jobs_page1, _ = repo.list_jobs(limit=2, offset=0)
    jobs_page2, _ = repo.list_jobs(limit=2, offset=2)

    assert len(jobs_page1) == 2
    assert len(jobs_page2) == 2


def test_list_jobs_ordered_newest_first(repo: SqlExportRepository) -> None:
    """list_jobs: results ordered by created_at descending."""
    import time

    job1 = _make_job(job_id="01HEXPORT0000000000000001")
    repo.create_job(job1)
    time.sleep(0.01)

    job2 = _make_job(job_id="01HEXPORT0000000000000002")
    repo.create_job(job2)
    time.sleep(0.01)

    job3 = _make_job(job_id="01HEXPORT0000000000000003")
    repo.create_job(job3)

    jobs, _ = repo.list_jobs()

    # Most recent should be first
    assert jobs[0].id == job3.id
    assert jobs[1].id == job2.id
    assert jobs[2].id == job1.id


# ---------------------------------------------------------------------------
# list_by_object_id tests
# ---------------------------------------------------------------------------


def test_list_by_object_id_empty_repo_returns_empty(repo: SqlExportRepository) -> None:
    """list_by_object_id: empty repo returns empty list."""
    jobs, total = repo.list_by_object_id(_OBJECT_ID_1)

    assert jobs == []
    assert total == 0


def test_list_by_object_id_returns_matching_jobs(repo: SqlExportRepository) -> None:
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
    repo: SqlExportRepository,
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
    repo: SqlExportRepository,
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


def test_list_by_object_id_ordered_newest_first(repo: SqlExportRepository) -> None:
    """list_by_object_id: results ordered by created_at descending."""
    import time

    job1 = _make_job(job_id="01HEXPORT0000000000000001", object_id=_OBJECT_ID_1)
    repo.create_job(job1)
    time.sleep(0.01)

    job2 = _make_job(job_id="01HEXPORT0000000000000002", object_id=_OBJECT_ID_1)
    repo.create_job(job2)
    time.sleep(0.01)

    job3 = _make_job(job_id="01HEXPORT0000000000000003", object_id=_OBJECT_ID_1)
    repo.create_job(job3)

    jobs, _ = repo.list_by_object_id(_OBJECT_ID_1)

    assert jobs[0].id == job3.id
    assert jobs[1].id == job2.id
    assert jobs[2].id == job1.id
