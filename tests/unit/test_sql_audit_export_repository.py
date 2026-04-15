"""
Unit tests for SqlAuditExportRepository with durable storage backend.

Verifies:
    - save_export_job persists metadata to the database.
    - get_export_job retrieves metadata by job_id.
    - get_export_job raises NotFoundError for unknown job_id.
    - save_export_content writes bytes to artifact storage (not memory).
    - get_export_content reads bytes from artifact storage.
    - get_export_content raises NotFoundError when storage key is missing.
    - Storage backend is invoked with correct bucket and key prefix.

Dependencies:
    - SQLAlchemy in-memory SQLite.
    - Mock ArtifactStorageBase for verifying storage interactions.
    - libs.contracts.models: AuditExportJob ORM model.

Example:
    pytest tests/unit/test_sql_audit_export_repository.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.audit_export import AuditExportFormat, AuditExportResult
from libs.contracts.errors import NotFoundError
from libs.contracts.models import Base
from libs.storage.base import ArtifactStorageBase

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_db() -> Session:
    """Create an in-memory SQLite database with all tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    yield session  # type: ignore[misc]
    session.close()


@pytest.fixture
def mock_storage() -> MagicMock:
    """Return a MagicMock implementing ArtifactStorageBase."""
    storage = MagicMock(spec=ArtifactStorageBase)
    # Default: put() returns the key, get() returns sample bytes
    storage.put.return_value = "exports/test-job-id"
    storage.get.return_value = b"exported-content"
    return storage


def _make_repo(
    db: Session,
    storage: MagicMock,
) -> Any:
    """Create SqlAuditExportRepository with injected dependencies."""
    from services.api.repositories.sql_audit_export_repository import (
        SqlAuditExportRepository,
    )

    return SqlAuditExportRepository(db=db, storage=storage)


def _sample_result(job_id: str = "01HQEXPORT0AAAAAAAAAAAAAAA") -> AuditExportResult:
    """Create a sample AuditExportResult for testing."""
    return AuditExportResult(
        job_id=job_id,
        status="completed",
        record_count=42,
        content_hash="sha256:abc123",
        byte_size=1024,
        format=AuditExportFormat.JSON,
        compressed=False,
        created_at=datetime(2026, 4, 12, 10, 0, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 4, 12, 10, 0, 5, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Tests: Job metadata persistence
# ---------------------------------------------------------------------------


class TestSaveExportJob:
    """Tests for save_export_job()."""

    def test_save_export_job_persists_metadata(
        self,
        test_db: Session,
        mock_storage: MagicMock,
    ) -> None:
        """Job metadata is persisted to the database."""
        repo = _make_repo(test_db, mock_storage)
        result = _sample_result()
        repo.save_export_job(result)

        # Verify we can retrieve it
        retrieved = repo.get_export_job(result.job_id)
        assert retrieved.job_id == result.job_id
        assert retrieved.status == "completed"
        assert retrieved.record_count == 42
        assert retrieved.content_hash == "sha256:abc123"

    def test_save_export_job_stores_all_fields(
        self,
        test_db: Session,
        mock_storage: MagicMock,
    ) -> None:
        """All metadata fields are correctly round-tripped."""
        repo = _make_repo(test_db, mock_storage)
        result = _sample_result()
        repo.save_export_job(result)

        retrieved = repo.get_export_job(result.job_id)
        assert retrieved.byte_size == 1024
        assert retrieved.format == AuditExportFormat.JSON
        assert retrieved.compressed is False
        assert retrieved.created_at is not None
        assert retrieved.completed_at is not None


class TestGetExportJob:
    """Tests for get_export_job()."""

    def test_get_export_job_returns_result(
        self,
        test_db: Session,
        mock_storage: MagicMock,
    ) -> None:
        """Retrieves the correct job metadata by ID."""
        repo = _make_repo(test_db, mock_storage)
        repo.save_export_job(_sample_result("01HQEXPORT0BBBBBBBBBBBBBBB"))

        result = repo.get_export_job("01HQEXPORT0BBBBBBBBBBBBBBB")
        assert result.job_id == "01HQEXPORT0BBBBBBBBBBBBBBB"

    def test_get_export_job_raises_not_found(
        self,
        test_db: Session,
        mock_storage: MagicMock,
    ) -> None:
        """Unknown job_id raises NotFoundError."""
        repo = _make_repo(test_db, mock_storage)
        with pytest.raises(NotFoundError):
            repo.get_export_job("01HQNON_EXISTENT_JOB_IDAAA")


# ---------------------------------------------------------------------------
# Tests: Content storage (durable, NOT in-memory)
# ---------------------------------------------------------------------------


class TestSaveExportContent:
    """Tests for save_export_content() — writes to ArtifactStorageBase."""

    def test_save_export_content_delegates_to_storage(
        self,
        test_db: Session,
        mock_storage: MagicMock,
    ) -> None:
        """Content bytes are written to the artifact storage backend."""
        repo = _make_repo(test_db, mock_storage)
        content = b"exported-audit-data-csv"

        repo.save_export_content("01HQEXPORT0CCCCCCCCCCCCCCC", content)

        mock_storage.put.assert_called_once()
        call_kwargs = mock_storage.put.call_args
        assert call_kwargs.kwargs["data"] == content
        assert call_kwargs.kwargs["bucket"] == "fxlab-audit-exports"
        assert "01HQEXPORT0CCCCCCCCCCCCCCC" in call_kwargs.kwargs["key"]

    def test_save_export_content_uses_correct_key_prefix(
        self,
        test_db: Session,
        mock_storage: MagicMock,
    ) -> None:
        """Storage key follows the exports/{job_id} pattern."""
        repo = _make_repo(test_db, mock_storage)
        repo.save_export_content("01HQEXPORT0DDDDDDDDDDDDDDD", b"data")

        call_kwargs = mock_storage.put.call_args
        assert call_kwargs.kwargs["key"] == "exports/01HQEXPORT0DDDDDDDDDDDDDDD"

    def test_save_export_content_includes_metadata(
        self,
        test_db: Session,
        mock_storage: MagicMock,
    ) -> None:
        """Storage put call includes job_id in metadata for traceability."""
        repo = _make_repo(test_db, mock_storage)
        repo.save_export_content("01HQEXPORT0EEEEEEEEEEEEEEE", b"data")

        call_kwargs = mock_storage.put.call_args
        assert call_kwargs.kwargs["metadata"]["job_id"] == "01HQEXPORT0EEEEEEEEEEEEEEE"


class TestGetExportContent:
    """Tests for get_export_content() — reads from ArtifactStorageBase."""

    def test_get_export_content_returns_bytes(
        self,
        test_db: Session,
        mock_storage: MagicMock,
    ) -> None:
        """Content bytes are read from the artifact storage backend."""
        mock_storage.get.return_value = b"retrieved-audit-data"
        repo = _make_repo(test_db, mock_storage)

        content = repo.get_export_content("01HQEXPORT0FFFFFFFFFFF0000")

        assert content == b"retrieved-audit-data"
        mock_storage.get.assert_called_once_with(
            bucket="fxlab-audit-exports",
            key="exports/01HQEXPORT0FFFFFFFFFFF0000",
            correlation_id="export-01HQEXPORT0FFFFFFFFFFF0000",
        )

    def test_get_export_content_raises_not_found_when_missing(
        self,
        test_db: Session,
        mock_storage: MagicMock,
    ) -> None:
        """FileNotFoundError from storage is translated to NotFoundError."""
        mock_storage.get.side_effect = FileNotFoundError("no such key")
        repo = _make_repo(test_db, mock_storage)

        with pytest.raises(NotFoundError, match="not found"):
            repo.get_export_content("01HQEXPORT0GGGGGGGGGGGGGGG")


class TestNoInMemoryContentStore:
    """Verify the §0 ABSOLUTE LAW fix: no in-memory dict for content."""

    def test_repository_has_no_content_store_dict(
        self,
        test_db: Session,
        mock_storage: MagicMock,
    ) -> None:
        """SqlAuditExportRepository must NOT have a _content_store dict attribute."""
        repo = _make_repo(test_db, mock_storage)
        assert not hasattr(repo, "_content_store"), (
            "§0 violation: SqlAuditExportRepository must not use an in-memory "
            "dict for content storage. Content must be persisted to durable "
            "artifact storage (MinIO/local filesystem)."
        )

    def test_content_survives_repo_recreation(
        self,
        test_db: Session,
        mock_storage: MagicMock,
    ) -> None:
        """Content persisted by one repo instance is retrievable by another."""
        repo1 = _make_repo(test_db, mock_storage)
        repo1.save_export_content("01HQEXPORT0HHHHHHHHHHHHHHH", b"persistent-data")

        # Simulate a new request / process restart — new repo, same storage
        repo2 = _make_repo(test_db, mock_storage)
        mock_storage.get.return_value = b"persistent-data"
        content = repo2.get_export_content("01HQEXPORT0HHHHHHHHHHHHHHH")
        assert content == b"persistent-data"
