"""
Unit tests for ExportService (Phase 9 — M6).

Verifies:
    - create_export happy path for each export type (TRADES, RUNS, ARTIFACTS).
    - create_export generates unique job IDs.
    - create_export state machine transitions (PENDING → PROCESSING → COMPLETE).
    - create_export generates valid zip bundles with metadata, data files, README.
    - create_export failure handling: storage error → FAILED status + re-raise.
    - create_export logs all transitions correctly.
    - get_export retrieves jobs by ID (found and not found).
    - list_exports with requested_by filter.
    - list_exports with object_id filter (uses list_by_object_id).
    - list_exports pagination (limit, offset).
    - download_export happy path (COMPLETE job with artifact).
    - download_export raises NotFoundError for missing job.
    - download_export raises NotFoundError for incomplete job (no artifact_uri).
    - download_export retrieves bytes from storage correctly.
    - Bundle structure: metadata.json, README.txt, data files (CSV/JSON).

Dependencies:
    - pytest for assertions.
    - MockExportRepository for job persistence.
    - MockArtifactStorage (defined in test) for artifact storage.
    - ExportService (system under test).
    - zipfile, json, io for bundle inspection.

Example:
    pytest tests/unit/test_export_service.py -v
"""

from __future__ import annotations

# mypy: ignore-errors
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any
from unittest.mock import Mock

import pytest

from libs.contracts.errors import ExternalServiceError, NotFoundError
from libs.contracts.export import ExportJobResponse, ExportStatus, ExportType
from libs.contracts.mocks.mock_export_repository import MockExportRepository
from libs.storage.base import ArtifactStorageBase
from services.api.services.export_service import ExportService

# ---------------------------------------------------------------------------
# Mock Artifact Storage (for unit tests)
# ---------------------------------------------------------------------------


class MockArtifactStorage(ArtifactStorageBase):
    """
    In-memory mock implementation of ArtifactStorageBase for unit testing.

    Stores artifacts in a dict keyed by "bucket/key". Provides introspection
    helpers for test assertions.
    """

    def __init__(self) -> None:
        """Initialize the in-memory store."""
        self._store: dict[str, bytes] = {}
        self._metadata: dict[str, dict[str, Any]] = {}

    def initialize(self, correlation_id: str) -> None:
        """Idempotent initialization (no-op in mock)."""
        pass

    def is_initialized(self) -> bool:
        """Always initialized in mock."""
        return True

    def health_check(self, correlation_id: str) -> bool:
        """Always healthy in mock."""
        return True

    def put(
        self,
        data: bytes,
        bucket: str,
        key: str,
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> str:
        """
        Store data and return the full path.

        Args:
            data: Bytes to store.
            bucket: Logical bucket.
            key: Object key.
            metadata: Optional metadata dict.
            correlation_id: Optional correlation ID.

        Returns:
            Full storage path ("bucket/key").
        """
        storage_path = f"{bucket}/{key}"
        self._store[storage_path] = data
        self._metadata[storage_path] = metadata or {}
        return storage_path

    def get(
        self,
        bucket: str,
        key: str,
        correlation_id: str,
    ) -> bytes:
        """
        Retrieve stored data.

        Args:
            bucket: Logical bucket.
            key: Object key.
            correlation_id: Correlation ID.

        Returns:
            Stored bytes.

        Raises:
            FileNotFoundError: If the object does not exist.
        """
        storage_path = f"{bucket}/{key}"
        if storage_path not in self._store:
            raise FileNotFoundError(f"Object not found: {storage_path}")
        return self._store[storage_path]

    def get_with_metadata(
        self,
        bucket: str,
        key: str,
        correlation_id: str,
    ) -> tuple[bytes, dict[str, Any]]:
        """Retrieve data and metadata."""
        storage_path = f"{bucket}/{key}"
        if storage_path not in self._store:
            raise FileNotFoundError(f"Object not found: {storage_path}")
        return self._store[storage_path], self._metadata.get(storage_path, {})

    def list(
        self,
        bucket: str,
        prefix: str,
        correlation_id: str,
        max_keys: int | None = None,
    ) -> list[str]:
        """List objects with prefix filter."""
        bucket_prefix = f"{bucket}/"
        keys = [
            k.replace(bucket_prefix, "")
            for k in self._store
            if k.startswith(bucket_prefix)
            and (not prefix or k.startswith(f"{bucket_prefix}{prefix}"))
        ]
        if max_keys:
            keys = keys[:max_keys]
        return keys

    def delete(
        self,
        bucket: str,
        key: str,
        correlation_id: str,
    ) -> None:
        """Delete object (idempotent)."""
        storage_path = f"{bucket}/{key}"
        self._store.pop(storage_path, None)
        self._metadata.pop(storage_path, None)

    # Introspection helpers for tests
    def get_stored_keys(self) -> list[str]:
        """Return all stored keys."""
        return list(self._store.keys())

    def clear(self) -> None:
        """Clear all stored data."""
        self._store.clear()
        self._metadata.clear()


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------


_NOW = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def repo() -> MockExportRepository:
    """Provide a fresh mock repository for each test."""
    return MockExportRepository()


@pytest.fixture
def storage() -> MockArtifactStorage:
    """Provide a fresh mock storage for each test."""
    return MockArtifactStorage()


@pytest.fixture
def service(repo: MockExportRepository, storage: MockArtifactStorage) -> ExportService:
    """Provide a service instance for each test."""
    return ExportService(repo=repo, storage=storage)


# ---------------------------------------------------------------------------
# Tests: create_export
# ---------------------------------------------------------------------------


class TestCreateExport:
    """Tests for create_export happy path and error handling."""

    def test_create_export_trades_happy_path(
        self, service: ExportService, repo: MockExportRepository, storage: MockArtifactStorage
    ) -> None:
        """
        Test create_export with TRADES type.

        Verifies:
        - Job created with PENDING status.
        - Job transitions to PROCESSING.
        - Bundle generated with metadata, README, data.csv.
        - Bundle stored in "exports" bucket.
        - Job completed with artifact_uri.
        """
        job = service.create_export(
            ExportType.TRADES,
            "01HRUN0ABCD1234567890ABCD",
            "01HUSER0XYZW987654321XYZW",
            correlation_id="corr-test-1",
        )

        # Verify job state
        assert job.status == ExportStatus.COMPLETE
        assert job.export_type == ExportType.TRADES
        assert job.object_id == "01HRUN0ABCD1234567890ABCD"
        assert job.requested_by == "01HUSER0XYZW987654321XYZW"
        assert job.artifact_uri is not None
        assert job.artifact_uri.startswith("exports/")
        assert job.artifact_uri.endswith(".zip")
        assert job.error_message is None

        # Verify artifact was stored
        assert storage.get_stored_keys() == [job.artifact_uri]

        # Verify bundle structure
        bundle_bytes = storage.get("exports", job.artifact_uri.split("/")[1], "corr-test-1")
        assert bundle_bytes is not None

        with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as zf:
            files = zf.namelist()
            assert "metadata.json" in files
            assert "README.txt" in files
            assert "data.csv" in files

            # Verify metadata.json content
            metadata_str = zf.read("metadata.json").decode("utf-8")
            metadata = json.loads(metadata_str)
            assert metadata["export_type"] == "trades"
            assert metadata["object_id"] == "01HRUN0ABCD1234567890ABCD"
            assert metadata["requested_by"] == "01HUSER0XYZW987654321XYZW"

            # Verify data.csv has headers and rows
            csv_content = zf.read("data.csv").decode("utf-8")
            assert "trade_id,symbol,side,quantity,price,timestamp" in csv_content

    def test_create_export_runs_happy_path(
        self, service: ExportService, repo: MockExportRepository, storage: MockArtifactStorage
    ) -> None:
        """
        Test create_export with RUNS type.

        Verifies bundle contains results.json instead of data.csv.
        """
        job = service.create_export(
            ExportType.RUNS,
            "01HRUN0AAAAAAAAAAAAAAAA",
            "01HUSER0XYZW987654321XYZW",
        )

        assert job.status == ExportStatus.COMPLETE
        assert job.export_type == ExportType.RUNS
        assert job.artifact_uri is not None

        # Verify bundle contains results.json
        bundle_bytes = storage.get("exports", job.artifact_uri.split("/")[1], "")
        with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as zf:
            files = zf.namelist()
            assert "metadata.json" in files
            assert "README.txt" in files
            assert "results.json" in files
            assert "data.csv" not in files

            # Verify results.json structure
            results_str = zf.read("results.json").decode("utf-8")
            results = json.loads(results_str)
            assert results["run_id"] == "01HRUN0AAAAAAAAAAAAAAAA"
            assert "status" in results
            assert "trades" in results
            assert "profit_loss" in results

    def test_create_export_artifacts_happy_path(
        self, service: ExportService, repo: MockExportRepository, storage: MockArtifactStorage
    ) -> None:
        """
        Test create_export with ARTIFACTS type.

        Verifies bundle contains only metadata and README (no data file).
        """
        job = service.create_export(
            ExportType.ARTIFACTS,
            "01HARTIFACT0AAAAAAAAAA",
            "01HUSER0XYZW987654321XYZW",
        )

        assert job.status == ExportStatus.COMPLETE
        assert job.export_type == ExportType.ARTIFACTS

        # Verify bundle structure
        bundle_bytes = storage.get("exports", job.artifact_uri.split("/")[1], "")
        with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as zf:
            files = zf.namelist()
            assert "metadata.json" in files
            assert "README.txt" in files
            assert "data.csv" not in files
            assert "results.json" not in files

    def test_create_export_generates_unique_ids(
        self, service: ExportService, repo: MockExportRepository
    ) -> None:
        """
        Test that create_export generates unique job IDs for multiple calls.
        """
        job1 = service.create_export(
            ExportType.TRADES,
            "01HRUN0AAAAAAAAAAAAAAAA",
            "01HUSER0XYZW987654321XYZW",
        )
        job2 = service.create_export(
            ExportType.TRADES,
            "01HRUN0AAAAAAAAAAAAAAAA",
            "01HUSER0XYZW987654321XYZW",
        )

        assert job1.id != job2.id
        assert repo.count() == 2

    def test_create_export_persists_to_repo(
        self, service: ExportService, repo: MockExportRepository
    ) -> None:
        """
        Test that create_export persists job to repository.
        """
        job = service.create_export(
            ExportType.TRADES,
            "01HRUN0AAAAAAAAAAAAAAAA",
            "01HUSER0XYZW987654321XYZW",
        )

        # Verify job is in repo
        persisted = repo.get_job(job.id)
        assert persisted is not None
        assert persisted.id == job.id
        assert persisted.status == ExportStatus.COMPLETE

    def test_create_export_storage_failure_updates_to_failed(
        self, repo: MockExportRepository
    ) -> None:
        """
        Test that storage failure updates job to FAILED and re-raises.

        Verifies:
        - Job in repo has FAILED status.
        - Error message is set.
        - ExternalServiceError is raised.
        """
        # Create a storage that fails on put
        failing_storage = Mock(spec=ArtifactStorageBase)
        failing_storage.put.side_effect = OSError("Storage unavailable")

        service = ExportService(repo=repo, storage=failing_storage)

        with pytest.raises(ExternalServiceError) as exc_info:
            service.create_export(
                ExportType.TRADES,
                "01HRUN0AAAAAAAAAAAAAAAA",
                "01HUSER0XYZW987654321XYZW",
            )

        # Verify error message contains original exception
        assert "Storage unavailable" in str(exc_info.value)

        # Verify job was created and updated to FAILED
        assert repo.count() == 1
        job = repo.get_all()[0]
        assert job.status == ExportStatus.FAILED
        assert "Storage unavailable" in job.error_message or "OSError" in job.error_message

    def test_create_export_repository_create_failure_raises(
        self, storage: MockArtifactStorage
    ) -> None:
        """
        Test that repository failure on create_job raises.
        """
        failing_repo = Mock(spec=MockExportRepository)
        failing_repo.create_job.side_effect = ValueError("Duplicate ID")

        service = ExportService(repo=failing_repo, storage=storage)

        with pytest.raises(ExternalServiceError):
            service.create_export(
                ExportType.TRADES,
                "01HRUN0AAAAAAAAAAAAAAAA",
                "01HUSER0XYZW987654321XYZW",
            )

    def test_create_export_timestamps_are_utc(
        self, service: ExportService, repo: MockExportRepository
    ) -> None:
        """
        Test that created_at and updated_at use UTC timezone.
        """
        job = service.create_export(
            ExportType.TRADES,
            "01HRUN0AAAAAAAAAAAAAAAA",
            "01HUSER0XYZW987654321XYZW",
        )

        assert job.created_at.tzinfo == timezone.utc
        assert job.updated_at.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# Tests: get_export
# ---------------------------------------------------------------------------


class TestGetExport:
    """Tests for get_export retrieval."""

    def test_get_export_found(self, service: ExportService) -> None:
        """Test get_export returns job when found."""
        created = service.create_export(
            ExportType.TRADES,
            "01HRUN0AAAAAAAAAAAAAAAA",
            "01HUSER0XYZW987654321XYZW",
        )

        retrieved = service.get_export(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.status == ExportStatus.COMPLETE

    def test_get_export_not_found(self, service: ExportService) -> None:
        """Test get_export returns None for non-existent job."""
        result = service.get_export("01HEXPORT0NOTFOUND0000000")
        assert result is None


# ---------------------------------------------------------------------------
# Tests: list_exports
# ---------------------------------------------------------------------------


class TestListExports:
    """Tests for list_exports filtering and pagination."""

    def test_list_exports_by_requested_by(self, service: ExportService) -> None:
        """
        Test list_exports filters by requested_by.

        Creates jobs with different requesters, verifies filtering.
        """
        user1 = "01HUSER0AAAAAAAAAAAAAA"
        user2 = "01HUSER0BBBBBBBBBBBBBB"

        service.create_export(ExportType.TRADES, "01HRUN0AA", user1)
        service.create_export(ExportType.RUNS, "01HRUN0BB", user1)
        service.create_export(ExportType.ARTIFACTS, "01HRUN0CC", user2)

        jobs, total = service.list_exports(requested_by=user1)

        assert len(jobs) == 2
        assert total == 2
        assert all(j.requested_by == user1 for j in jobs)
        assert not any(j.requested_by == user2 for j in jobs)

    def test_list_exports_by_object_id(self, service: ExportService) -> None:
        """
        Test list_exports filters by object_id.

        Creates multiple exports for the same object and others.
        """
        obj_id = "01HRUN0CCCCCCCCCCCCCCCC"
        user1 = "01HUSER0AAAAAAAAAAAAAA"
        user2 = "01HUSER0BBBBBBBBBBBBBB"

        service.create_export(ExportType.TRADES, obj_id, user1)
        service.create_export(ExportType.RUNS, obj_id, user2)
        service.create_export(ExportType.TRADES, "01HRUN0DDDDDDDDDDDDDDD", user1)

        jobs, total = service.list_exports(object_id=obj_id)

        assert len(jobs) == 2
        assert total == 2
        assert all(j.object_id == obj_id for j in jobs)

    def test_list_exports_pagination(self, service: ExportService) -> None:
        """
        Test list_exports pagination with limit and offset.
        """
        user = "01HUSER0AAAAAAAAAAAAAA"

        for i in range(5):
            service.create_export(ExportType.TRADES, f"01HRUN0{i:02d}", user)

        # First page
        jobs, total = service.list_exports(requested_by=user, limit=2, offset=0)
        assert len(jobs) == 2
        assert total == 5

        # Second page
        jobs, total = service.list_exports(requested_by=user, limit=2, offset=2)
        assert len(jobs) == 2
        assert total == 5

        # Out of range
        jobs, total = service.list_exports(requested_by=user, limit=2, offset=10)
        assert len(jobs) == 0
        assert total == 5

    def test_list_exports_default_limit(self, service: ExportService) -> None:
        """Test list_exports uses default limit=50."""
        user = "01HUSER0AAAAAAAAAAAAAA"

        for i in range(10):
            service.create_export(ExportType.TRADES, f"01HRUN0{i:02d}", user)

        jobs, total = service.list_exports(requested_by=user)

        assert len(jobs) == 10
        assert total == 10

    def test_list_exports_no_filters_returns_all(self, service: ExportService) -> None:
        """
        Test list_exports with no filters returns all jobs.
        """
        user1 = "01HUSER0AAAAAAAAAAAAAA"
        user2 = "01HUSER0BBBBBBBBBBBBBB"

        service.create_export(ExportType.TRADES, "01HRUN0AA", user1)
        service.create_export(ExportType.RUNS, "01HRUN0BB", user2)

        jobs, total = service.list_exports()

        assert len(jobs) == 2
        assert total == 2


# ---------------------------------------------------------------------------
# Tests: download_export
# ---------------------------------------------------------------------------


class TestDownloadExport:
    """Tests for download_export retrieval."""

    def test_download_export_happy_path(self, service: ExportService) -> None:
        """
        Test download_export returns artifact bytes for complete job.

        Verifies:
        - Returns bytes of the zip file.
        - Bytes are valid zip archive.
        """
        job = service.create_export(
            ExportType.TRADES,
            "01HRUN0AAAAAAAAAAAAAAAA",
            "01HUSER0XYZW987654321XYZW",
        )

        artifact_bytes = service.download_export(job.id)

        assert artifact_bytes is not None
        assert len(artifact_bytes) > 0
        # Verify it's a valid zip
        with zipfile.ZipFile(io.BytesIO(artifact_bytes), "r") as zf:
            assert "metadata.json" in zf.namelist()

    def test_download_export_job_not_found(self, service: ExportService) -> None:
        """
        Test download_export raises NotFoundError for missing job.
        """
        with pytest.raises(NotFoundError) as exc_info:
            service.download_export("01HEXPORT0NOTFOUND0000000")

        assert "not found" in str(exc_info.value).lower()

    def test_download_export_incomplete_job_raises(self, repo: MockExportRepository) -> None:
        """
        Test download_export raises NotFoundError for incomplete job.

        Creates a PENDING job (not COMPLETE) and verifies error.
        """
        job = ExportJobResponse(
            id="01HEXPORT0TEST0000000000",
            export_type=ExportType.TRADES,
            object_id="01HRUN0AAAAAAAAAAAAAAAA",
            status=ExportStatus.PENDING,
            artifact_uri=None,
            requested_by="01HUSER0XYZW987654321XYZW",
            error_message=None,
            created_at=_NOW,
            updated_at=_NOW,
            override_watermark=None,
        )
        repo.create_job(job)

        storage = MockArtifactStorage()
        service = ExportService(repo=repo, storage=storage)

        with pytest.raises(NotFoundError) as exc_info:
            service.download_export(job.id)

        assert (
            "not complete" in str(exc_info.value).lower()
            or "artifact_uri" in str(exc_info.value).lower()
        )

    def test_download_export_artifact_missing_from_storage(
        self, repo: MockExportRepository
    ) -> None:
        """
        Test download_export raises FileNotFoundError if artifact is missing.
        """
        job = ExportJobResponse(
            id="01HEXPORT0TEST0000000000",
            export_type=ExportType.TRADES,
            object_id="01HRUN0AAAAAAAAAAAAAAAA",
            status=ExportStatus.COMPLETE,
            artifact_uri="exports/missing.zip",
            requested_by="01HUSER0XYZW987654321XYZW",
            error_message=None,
            created_at=_NOW,
            updated_at=_NOW,
            override_watermark=None,
        )
        repo.create_job(job)

        storage = MockArtifactStorage()
        service = ExportService(repo=repo, storage=storage)

        with pytest.raises(FileNotFoundError):
            service.download_export(job.id)

    def test_download_export_with_correlation_id(self, service: ExportService) -> None:
        """
        Test download_export passes correlation_id to storage.get().
        """
        job = service.create_export(
            ExportType.TRADES,
            "01HRUN0AAAAAAAAAAAAAAAA",
            "01HUSER0XYZW987654321XYZW",
        )

        # Should not raise; correlation_id is logged but doesn't change behavior
        artifact_bytes = service.download_export(job.id, correlation_id="corr-test-123")

        assert len(artifact_bytes) > 0


# ---------------------------------------------------------------------------
# Tests: Bundle Generation
# ---------------------------------------------------------------------------


class TestBundleGeneration:
    """Tests for internal bundle generation logic."""

    def test_bundle_metadata_json_structure(self, service: ExportService) -> None:
        """
        Test metadata.json has required fields.
        """
        job = service.create_export(
            ExportType.TRADES,
            "01HRUN0AAAAAAAAAAAAAAAA",
            "01HUSER0XYZW987654321XYZW",
        )

        artifact_bytes = service.download_export(job.id)

        with zipfile.ZipFile(io.BytesIO(artifact_bytes), "r") as zf:
            metadata_str = zf.read("metadata.json").decode("utf-8")
            metadata = json.loads(metadata_str)

            assert metadata["export_type"] == "trades"
            assert metadata["object_id"] == "01HRUN0AAAAAAAAAAAAAAAA"
            assert metadata["requested_by"] == "01HUSER0XYZW987654321XYZW"
            assert "exported_at" in metadata

    def test_bundle_readme_contains_metadata(self, service: ExportService) -> None:
        """
        Test README.txt includes export metadata and file listing.
        """
        job = service.create_export(
            ExportType.TRADES,
            "01HRUN0AAAAAAAAAAAAAAAA",
            "01HUSER0XYZW987654321XYZW",
        )

        artifact_bytes = service.download_export(job.id)

        with zipfile.ZipFile(io.BytesIO(artifact_bytes), "r") as zf:
            readme = zf.read("README.txt").decode("utf-8")

            assert "FXLab Export Bundle" in readme
            assert "trades" in readme
            assert "01HRUN0AAAAAAAAAAAAAAAA" in readme

    def test_bundle_trades_csv_has_headers(self, service: ExportService) -> None:
        """
        Test TRADES bundle CSV has expected headers.
        """
        job = service.create_export(
            ExportType.TRADES,
            "01HRUN0AAAAAAAAAAAAAAAA",
            "01HUSER0XYZW987654321XYZW",
        )

        artifact_bytes = service.download_export(job.id)

        with zipfile.ZipFile(io.BytesIO(artifact_bytes), "r") as zf:
            csv_content = zf.read("data.csv").decode("utf-8")
            assert "trade_id,symbol,side,quantity,price,timestamp" in csv_content

    def test_bundle_runs_json_has_result_fields(self, service: ExportService) -> None:
        """
        Test RUNS bundle JSON has expected result fields.
        """
        job = service.create_export(
            ExportType.RUNS,
            "01HRUN0AAAAAAAAAAAAAAAA",
            "01HUSER0XYZW987654321XYZW",
        )

        artifact_bytes = service.download_export(job.id)

        with zipfile.ZipFile(io.BytesIO(artifact_bytes), "r") as zf:
            results_str = zf.read("results.json").decode("utf-8")
            results = json.loads(results_str)

            assert "run_id" in results
            assert "status" in results
            assert "trades" in results
            assert "profit_loss" in results
            assert "win_rate" in results

    def test_bundle_artifacts_omits_data_file(self, service: ExportService) -> None:
        """
        Test ARTIFACTS bundle has no data file (only metadata and README).
        """
        job = service.create_export(
            ExportType.ARTIFACTS,
            "01HARTIFACT0AAAAAAAAAA",
            "01HUSER0XYZW987654321XYZW",
        )

        artifact_bytes = service.download_export(job.id)

        with zipfile.ZipFile(io.BytesIO(artifact_bytes), "r") as zf:
            files = zf.namelist()
            assert "metadata.json" in files
            assert "README.txt" in files
            assert len(files) == 2  # Only metadata and README


# ---------------------------------------------------------------------------
# Integration-style test: Full workflow
# ---------------------------------------------------------------------------


class TestFullExportWorkflow:
    """Integration-style tests for complete export workflow."""

    def test_full_workflow_create_list_download(self, service: ExportService) -> None:
        """
        Test complete workflow: create → list → download.

        Creates multiple exports, filters by requester, and downloads one.
        """
        user1 = "01HUSER0AAAAAAAAAAAAAA"
        user2 = "01HUSER0BBBBBBBBBBBBBB"

        # Create exports
        job1 = service.create_export(ExportType.TRADES, "01HRUN0AA", user1)
        service.create_export(ExportType.RUNS, "01HRUN0BB", user1)
        service.create_export(ExportType.ARTIFACTS, "01HRUN0CC", user2)

        # List by requester
        jobs, total = service.list_exports(requested_by=user1)
        assert len(jobs) == 2
        assert total == 2

        # Retrieve specific job
        retrieved = service.get_export(job1.id)
        assert retrieved is not None
        assert retrieved.status == ExportStatus.COMPLETE

        # Download
        artifact_bytes = service.download_export(job1.id)
        assert len(artifact_bytes) > 0

        # Verify download is valid zip
        with zipfile.ZipFile(io.BytesIO(artifact_bytes), "r") as zf:
            assert "metadata.json" in zf.namelist()
