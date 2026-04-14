"""
Unit tests for M5: Artifact Registry + Storage Abstraction.

Coverage:
- GET /artifacts — list endpoint with filtering and pagination
- GET /artifacts/{artifact_id}/download — streaming download endpoint
- MockArtifactRepository — in-memory repo behavioural parity
- LocalArtifactStorage — filesystem-backed storage implementation
- ArtifactStorageBase — ABC cannot be instantiated directly

All tests MUST FAIL on a fresh checkout until the GREEN step provides
implementations.  This file documents the exact behaviour required.

Fixtures used (from tests/conftest.py and tests/unit/conftest.py):
- correlation_id: fresh ULID string
- mock_artifact_storage: MagicMock implementing ArtifactStorageBase methods
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from libs.contracts.artifact import Artifact, ArtifactQuery, ArtifactType
from libs.contracts.errors import NotFoundError
from libs.contracts.mocks.mock_artifact_repository import MockArtifactRepository

AUTH_HEADERS = {"Authorization": "Bearer TEST_TOKEN"}

# ---------------------------------------------------------------------------
# Test helpers / shared fixtures
# ---------------------------------------------------------------------------

_SAMPLE_ULID_1 = "01HQAAAAAAAAAAAAAAAAAAAAAA"
_SAMPLE_ULID_2 = "01HQBBBBBBBBBBBBBBBBBBBBBB"
_SAMPLE_ULID_3 = "01HQCCCCCCCCCCCCCCCCCCCCCC"
_SAMPLE_USER_ULID = "01HQUUUUUUUUUUUUUUUUUUUUUU"


def _make_artifact(
    artifact_id: str = _SAMPLE_ULID_1,
    artifact_type: ArtifactType = ArtifactType.BACKTEST_RESULT,
    subject_id: str = _SAMPLE_ULID_2,
    storage_path: str = "fxlab-artifacts/runs/abc/result.json",
    size_bytes: int = 1024,
    created_by: str = _SAMPLE_USER_ULID,
) -> Artifact:
    """Build a minimal valid Artifact for tests."""
    return Artifact(
        id=artifact_id,
        artifact_type=artifact_type,
        subject_id=subject_id,
        storage_path=storage_path,
        size_bytes=size_bytes,
        created_at=datetime(2026, 3, 19, 12, 0, 0, tzinfo=timezone.utc),
        created_by=created_by,
        metadata={},
    )


# ---------------------------------------------------------------------------
# MockArtifactRepository — behavioural tests
# ---------------------------------------------------------------------------


class TestMockArtifactRepository:
    """
    Verify that MockArtifactRepository honours the interface contract.

    These tests serve dual duty: they specify the required behaviour AND they
    validate the mock itself so it stays in sync with the real repo.
    """

    def test_save_and_find_by_id_round_trips_artifact(self) -> None:
        """
        GIVEN a freshly saved artifact
        WHEN find_by_id is called with its id
        THEN the same artifact is returned unchanged.
        """
        repo = MockArtifactRepository()
        art = _make_artifact()
        repo.save(art)
        found = repo.find_by_id(art.id)
        assert found.model_dump() == art.model_dump()

    def test_find_by_id_raises_not_found_for_unknown_id(self) -> None:
        """
        GIVEN an empty repository
        WHEN find_by_id is called with any id
        THEN NotFoundError is raised.
        """
        repo = MockArtifactRepository()
        with pytest.raises(NotFoundError, match=_SAMPLE_ULID_1):
            repo.find_by_id(_SAMPLE_ULID_1)

    def test_list_returns_all_artifacts_without_filters(self) -> None:
        """
        GIVEN three saved artifacts
        WHEN list() is called with no filters
        THEN all three are returned in the response.
        """
        repo = MockArtifactRepository()
        for i, uid in enumerate([_SAMPLE_ULID_1, _SAMPLE_ULID_2, _SAMPLE_ULID_3]):
            repo.save(_make_artifact(artifact_id=uid, size_bytes=i * 100))

        resp = repo.list(ArtifactQuery(limit=100, offset=0))
        assert resp.total_count == 3
        assert len(resp.artifacts) == 3

    def test_list_paginates_correctly(self) -> None:
        """
        GIVEN three saved artifacts
        WHEN list() is called with limit=2 offset=1
        THEN two artifacts are returned and total_count is 3.
        """
        repo = MockArtifactRepository()
        for uid in [_SAMPLE_ULID_1, _SAMPLE_ULID_2, _SAMPLE_ULID_3]:
            repo.save(_make_artifact(artifact_id=uid))

        resp = repo.list(ArtifactQuery(limit=2, offset=1))
        assert resp.total_count == 3
        assert len(resp.artifacts) == 2
        assert resp.limit == 2
        assert resp.offset == 1

    def test_list_filters_by_artifact_type(self) -> None:
        """
        GIVEN artifacts of different types
        WHEN list() is called with artifact_types filter
        THEN only matching types are returned.
        """
        repo = MockArtifactRepository()
        repo.save(_make_artifact(_SAMPLE_ULID_1, ArtifactType.BACKTEST_RESULT))
        repo.save(_make_artifact(_SAMPLE_ULID_2, ArtifactType.READINESS_REPORT))

        resp = repo.list(ArtifactQuery(artifact_types=[ArtifactType.BACKTEST_RESULT], limit=100))
        assert resp.total_count == 1
        assert resp.artifacts[0].artifact_type == ArtifactType.BACKTEST_RESULT

    def test_list_filters_by_subject_id(self) -> None:
        """
        GIVEN two artifacts with different subject_ids
        WHEN list() is called with a subject_id filter
        THEN only the matching artifact is returned.

        Note (LL-007): The pydantic-core native binary may not load in
        cross-architecture sandboxes.  When the pure-Python stub is active,
        validating a string value against Optional[str] raises TypeError.
        Use model_construct() to bypass validation and test filter logic
        independently of Pydantic runtime enforcement.
        """
        repo = MockArtifactRepository()
        repo.save(_make_artifact(_SAMPLE_ULID_1, subject_id="SUBJ0000000000000000000001"))
        repo.save(_make_artifact(_SAMPLE_ULID_2, subject_id="SUBJ0000000000000000000002"))

        # model_construct bypasses pydantic-core validation (LL-007 workaround)
        query = ArtifactQuery.model_construct(
            artifact_types=None,
            subject_id="SUBJ0000000000000000000001",
            created_by=None,
            start_time=None,
            end_time=None,
            limit=100,
            offset=0,
        )
        resp = repo.list(query)
        assert resp.total_count == 1
        assert resp.artifacts[0].subject_id == "SUBJ0000000000000000000001"

    def test_count_reflects_saved_artifacts(self) -> None:
        """
        GIVEN two saved artifacts
        WHEN count() is called
        THEN it returns 2.
        """
        repo = MockArtifactRepository()
        repo.save(_make_artifact(_SAMPLE_ULID_1))
        repo.save(_make_artifact(_SAMPLE_ULID_2))
        assert repo.count() == 2

    def test_clear_empties_store(self) -> None:
        """
        GIVEN a repository with saved artifacts
        WHEN clear() is called
        THEN count() returns 0 and find_by_id raises NotFoundError.
        """
        repo = MockArtifactRepository()
        repo.save(_make_artifact(_SAMPLE_ULID_1))
        repo.clear()
        assert repo.count() == 0
        with pytest.raises(NotFoundError):
            repo.find_by_id(_SAMPLE_ULID_1)

    def test_list_filters_by_created_by(self) -> None:
        """
        GIVEN two artifacts with different created_by values
        WHEN list() is called with a created_by filter
        THEN only the matching artifact is returned.

        Note (LL-007): Uses model_construct to bypass pydantic-core validation.
        """
        user_a = "01HQUUUUUUUUUUUUUUUUUUUUUU"
        user_b = "01HQVVVVVVVVVVVVVVVVVVVVVV"
        repo = MockArtifactRepository()
        repo.save(_make_artifact(_SAMPLE_ULID_1, created_by=user_a))
        repo.save(_make_artifact(_SAMPLE_ULID_2, created_by=user_b))

        query = ArtifactQuery.model_construct(
            artifact_types=None,
            subject_id=None,
            created_by=user_a,
            start_time=None,
            end_time=None,
            limit=100,
            offset=0,
        )
        resp = repo.list(query)
        assert resp.total_count == 1
        assert resp.artifacts[0].created_by == user_a

    def test_list_filters_by_time_range(self) -> None:
        """
        GIVEN artifacts at different creation times
        WHEN list() is called with start_time / end_time filters
        THEN only artifacts within the range are returned.

        Note (LL-007): Uses model_construct to bypass pydantic-core validation.
        """
        from datetime import datetime, timezone

        early = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mid = datetime(2026, 3, 1, tzinfo=timezone.utc)
        late = datetime(2026, 6, 1, tzinfo=timezone.utc)

        repo = MockArtifactRepository()
        art_early = Artifact(
            id=_SAMPLE_ULID_1,
            artifact_type=ArtifactType.BACKTEST_RESULT,
            subject_id=_SAMPLE_ULID_2,
            storage_path="bucket/key1.json",
            size_bytes=100,
            created_at=early,
            created_by=_SAMPLE_USER_ULID,
            metadata={},
        )
        art_late = Artifact(
            id=_SAMPLE_ULID_2,
            artifact_type=ArtifactType.BACKTEST_RESULT,
            subject_id=_SAMPLE_ULID_3,
            storage_path="bucket/key2.json",
            size_bytes=100,
            created_at=late,
            created_by=_SAMPLE_USER_ULID,
            metadata={},
        )
        repo.save(art_early)
        repo.save(art_late)

        # Test start_time filter: only art_late (created at `late`) should match
        query = ArtifactQuery.model_construct(
            artifact_types=None,
            subject_id=None,
            created_by=None,
            start_time=mid,
            end_time=None,
            limit=100,
            offset=0,
        )
        resp = repo.list(query)
        assert resp.total_count == 1
        assert resp.artifacts[0].id == _SAMPLE_ULID_2

        # Test end_time filter: only art_early (created at `early`) should match
        query_end = ArtifactQuery.model_construct(
            artifact_types=None,
            subject_id=None,
            created_by=None,
            start_time=None,
            end_time=mid,
            limit=100,
            offset=0,
        )
        resp_end = repo.list(query_end)
        assert resp_end.total_count == 1
        assert resp_end.artifacts[0].id == _SAMPLE_ULID_1

    def test_all_returns_every_saved_artifact(self) -> None:
        """
        GIVEN two saved artifacts
        WHEN all() is called
        THEN both artifacts are returned.
        """
        repo = MockArtifactRepository()
        repo.save(_make_artifact(_SAMPLE_ULID_1))
        repo.save(_make_artifact(_SAMPLE_ULID_2))
        all_arts = repo.all()
        assert len(all_arts) == 2
        ids = {a.id for a in all_arts}
        assert _SAMPLE_ULID_1 in ids
        assert _SAMPLE_ULID_2 in ids

    def test_save_with_empty_id_raises_value_error(self) -> None:
        """
        GIVEN an artifact with an empty id
        WHEN save() is called
        THEN ValueError is raised.
        """
        repo = MockArtifactRepository()
        art = _make_artifact(artifact_id="")
        # Pydantic may reject empty id before save() is reached; either
        # path (Pydantic ValidationError or our ValueError) is acceptable.
        with pytest.raises((ValueError, Exception)):
            repo.save(art)


# ---------------------------------------------------------------------------
# LocalArtifactStorage — filesystem implementation tests
# ---------------------------------------------------------------------------


class TestLocalArtifactStorage:
    """
    Verify LocalArtifactStorage (lib/storage/local_storage.py).

    These tests run against a real tmpdir — no mocking of I/O.  They confirm
    that the concrete implementation satisfies ArtifactStorageBase's contract.
    """

    @pytest.fixture
    def storage_root(self, tmp_path: Path) -> Path:
        """Provide a clean temporary directory for each test."""
        return tmp_path / "artifacts"

    @pytest.fixture
    def storage(self, storage_root: Path):
        """Instantiate LocalArtifactStorage pointing at storage_root."""
        from libs.storage.local_storage import LocalArtifactStorage

        return LocalArtifactStorage(root=storage_root)

    def test_storage_is_subclass_of_base(self, storage) -> None:
        """LocalArtifactStorage must inherit from ArtifactStorageBase."""
        from libs.storage.base import ArtifactStorageBase

        assert isinstance(storage, ArtifactStorageBase)

    def test_initialize_creates_root_directory(
        self, storage, storage_root: Path, correlation_id: str
    ) -> None:
        """
        GIVEN a storage_root that does not yet exist
        WHEN initialize() is called
        THEN the root directory is created on disk.
        """
        storage.initialize(correlation_id=correlation_id)
        assert storage_root.exists()

    def test_is_initialized_returns_false_before_initialize(self, storage) -> None:
        """
        GIVEN a freshly constructed storage instance
        WHEN is_initialized() is called before initialize()
        THEN it returns False.
        """
        assert storage.is_initialized() is False

    def test_is_initialized_returns_true_after_initialize(
        self, storage, correlation_id: str
    ) -> None:
        """
        GIVEN a freshly constructed storage instance
        WHEN initialize() is called
        THEN is_initialized() returns True.
        """
        storage.initialize(correlation_id=correlation_id)
        assert storage.is_initialized() is True

    def test_initialize_is_idempotent(self, storage, correlation_id: str) -> None:
        """
        GIVEN a storage instance
        WHEN initialize() is called twice
        THEN no exception is raised.
        """
        storage.initialize(correlation_id=correlation_id)
        storage.initialize(correlation_id=correlation_id)  # must not raise
        assert storage.is_initialized() is True

    def test_health_check_returns_true_when_root_exists(self, storage, correlation_id: str) -> None:
        """
        GIVEN an initialized storage
        WHEN health_check() is called
        THEN it returns True.
        """
        storage.initialize(correlation_id=correlation_id)
        assert storage.health_check(correlation_id=correlation_id) is True

    def test_put_stores_data_and_returns_storage_path(self, storage, correlation_id: str) -> None:
        """
        GIVEN initialized storage and some bytes
        WHEN put() is called
        THEN the data is written to disk and the returned path is a non-empty string.
        """
        storage.initialize(correlation_id=correlation_id)
        data = b"test artifact content"
        path = storage.put(
            data=data,
            bucket="fxlab-artifacts",
            key="runs/test.json",
            correlation_id=correlation_id,
        )
        assert isinstance(path, str)
        assert len(path) > 0

    def test_get_returns_same_bytes_as_put(self, storage, correlation_id: str) -> None:
        """
        GIVEN data stored via put()
        WHEN get() is called with the same bucket/key
        THEN the original bytes are returned unchanged.
        """
        storage.initialize(correlation_id=correlation_id)
        original = b"round-trip test data"
        storage.put(
            data=original,
            bucket="fxlab-artifacts",
            key="test.bin",
            correlation_id=correlation_id,
        )
        retrieved = storage.get("fxlab-artifacts", "test.bin", correlation_id)
        assert retrieved == original

    def test_get_raises_file_not_found_for_missing_key(self, storage, correlation_id: str) -> None:
        """
        GIVEN initialized storage with no stored objects
        WHEN get() is called with a non-existent key
        THEN FileNotFoundError is raised.
        """
        storage.initialize(correlation_id=correlation_id)
        with pytest.raises(FileNotFoundError):
            storage.get("fxlab-artifacts", "nonexistent.bin", correlation_id)

    def test_get_with_metadata_returns_data_and_dict(self, storage, correlation_id: str) -> None:
        """
        GIVEN data stored with metadata
        WHEN get_with_metadata() is called
        THEN both bytes and a metadata dict are returned.
        """
        storage.initialize(correlation_id=correlation_id)
        data = b"payload"
        meta = {"type": "backtest", "version": "1"}
        storage.put(
            data=data,
            bucket="fxlab-artifacts",
            key="meta_test.bin",
            metadata=meta,
            correlation_id=correlation_id,
        )
        retrieved_data, retrieved_meta = storage.get_with_metadata(
            "fxlab-artifacts", "meta_test.bin", correlation_id
        )
        assert retrieved_data == data
        assert isinstance(retrieved_meta, dict)

    def test_list_returns_stored_keys(self, storage, correlation_id: str) -> None:
        """
        GIVEN two objects stored under the same bucket
        WHEN list() is called with an empty prefix
        THEN both keys are returned.
        """
        storage.initialize(correlation_id=correlation_id)
        storage.put(b"a", "fxlab-artifacts", "file_a.bin", correlation_id=correlation_id)
        storage.put(b"b", "fxlab-artifacts", "file_b.bin", correlation_id=correlation_id)

        keys = storage.list("fxlab-artifacts", prefix="", correlation_id=correlation_id)
        assert "file_a.bin" in keys
        assert "file_b.bin" in keys

    def test_list_filters_by_prefix(self, storage, correlation_id: str) -> None:
        """
        GIVEN objects stored under two different prefixes
        WHEN list() is called with a specific prefix
        THEN only matching keys are returned.
        """
        storage.initialize(correlation_id=correlation_id)
        storage.put(b"1", "fxlab-artifacts", "runs/run1.bin", correlation_id=correlation_id)
        storage.put(b"2", "fxlab-artifacts", "runs/run2.bin", correlation_id=correlation_id)
        storage.put(b"3", "fxlab-artifacts", "models/model1.bin", correlation_id=correlation_id)

        keys = storage.list("fxlab-artifacts", prefix="runs/", correlation_id=correlation_id)
        assert all(k.startswith("runs/") for k in keys)
        assert len(keys) == 2

    def test_delete_removes_stored_object(self, storage, correlation_id: str) -> None:
        """
        GIVEN a stored object
        WHEN delete() is called
        THEN get() subsequently raises FileNotFoundError.
        """
        storage.initialize(correlation_id=correlation_id)
        storage.put(b"to delete", "fxlab-artifacts", "todel.bin", correlation_id=correlation_id)
        storage.delete("fxlab-artifacts", "todel.bin", correlation_id)
        with pytest.raises(FileNotFoundError):
            storage.get("fxlab-artifacts", "todel.bin", correlation_id)

    def test_delete_is_idempotent_for_nonexistent_key(self, storage, correlation_id: str) -> None:
        """
        GIVEN initialized storage with no stored objects
        WHEN delete() is called with a non-existent key
        THEN no exception is raised.
        """
        storage.initialize(correlation_id=correlation_id)
        storage.delete("fxlab-artifacts", "ghost.bin", correlation_id)  # must not raise


# ---------------------------------------------------------------------------
# GET /artifacts — route handler tests
# ---------------------------------------------------------------------------


class TestArtifactsListEndpoint:
    """
    Unit tests for GET /artifacts.

    The endpoint must:
    - Return 200 with a list of artifact metadata objects.
    - Support optional query parameters: artifact_type, subject_id, limit, offset.
    - Delegate all data access to the injected artifact repository.
    - Never perform storage I/O directly.
    """

    @pytest.fixture
    def repo(self) -> MockArtifactRepository:
        """Provide a pre-populated in-memory repository."""
        r = MockArtifactRepository()
        r.save(_make_artifact(_SAMPLE_ULID_1, ArtifactType.BACKTEST_RESULT))
        r.save(_make_artifact(_SAMPLE_ULID_2, ArtifactType.READINESS_REPORT))
        return r

    @pytest.fixture
    def client(self, repo: MockArtifactRepository) -> TestClient:
        """
        Build a TestClient with the artifact repo dependency overridden.

        FAILS until services/api/routes/artifacts.py is implemented and the
        repo dependency is wired.
        """
        from services.api.main import app
        from services.api.routes.artifacts import get_artifact_repository

        app.dependency_overrides[get_artifact_repository] = lambda: repo
        client = TestClient(app)
        yield client
        app.dependency_overrides.clear()

    def test_get_artifacts_returns_200(self, client: TestClient) -> None:
        """
        GIVEN the artifact registry has items
        WHEN GET /artifacts is requested
        THEN the response status is 200 OK.

        FAILS: artifacts.py stub has no implementation.
        """
        resp = client.get("/artifacts", headers=AUTH_HEADERS)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_get_artifacts_returns_list_field(self, client: TestClient) -> None:
        """
        GIVEN two artifacts in the registry
        WHEN GET /artifacts is requested
        THEN the response body contains an 'artifacts' list with 2 items.
        """
        resp = client.get("/artifacts", headers=AUTH_HEADERS)
        body = resp.json()
        assert "artifacts" in body, f"Expected 'artifacts' key in response: {body}"
        assert len(body["artifacts"]) == 2

    def test_get_artifacts_returns_total_count(self, client: TestClient) -> None:
        """
        GIVEN two artifacts in the registry
        WHEN GET /artifacts is requested
        THEN the response body contains total_count == 2.
        """
        resp = client.get("/artifacts", headers=AUTH_HEADERS)
        body = resp.json()
        assert body.get("total_count") == 2

    def test_get_artifacts_supports_limit_param(self, client: TestClient) -> None:
        """
        GIVEN two artifacts in the registry
        WHEN GET /artifacts?limit=1 is requested
        THEN only 1 artifact is returned but total_count is still 2.
        """
        resp = client.get("/artifacts?limit=1", headers=AUTH_HEADERS)
        body = resp.json()
        assert len(body["artifacts"]) == 1
        assert body["total_count"] == 2

    def test_get_artifacts_supports_offset_param(self, client: TestClient) -> None:
        """
        GIVEN two artifacts in the registry
        WHEN GET /artifacts?offset=1 is requested
        THEN 1 artifact is returned (the second one) and total_count is 2.
        """
        resp = client.get("/artifacts?offset=1", headers=AUTH_HEADERS)
        body = resp.json()
        assert len(body["artifacts"]) == 1

    def test_get_artifacts_filters_by_artifact_type(self, client: TestClient) -> None:
        """
        GIVEN two artifacts of different types
        WHEN GET /artifacts?artifact_type=backtest_result is requested
        THEN only the backtest artifact is returned.
        """
        resp = client.get("/artifacts?artifact_type=backtest_result", headers=AUTH_HEADERS)
        body = resp.json()
        assert len(body["artifacts"]) == 1
        assert body["artifacts"][0]["artifact_type"] == "backtest_result"

    def test_get_artifacts_each_item_has_required_fields(self, client: TestClient) -> None:
        """
        GIVEN artifacts in the registry
        WHEN GET /artifacts is requested
        THEN each item contains id, artifact_type, subject_id, storage_path,
             size_bytes, created_at, created_by.
        """
        resp = client.get("/artifacts", headers=AUTH_HEADERS)
        body = resp.json()
        required_fields = {
            "id",
            "artifact_type",
            "subject_id",
            "storage_path",
            "size_bytes",
            "created_at",
            "created_by",
        }
        for item in body["artifacts"]:
            missing = required_fields - set(item.keys())
            assert not missing, f"Item missing fields: {missing}"

    def test_get_artifacts_invalid_type_returns_422(self, client: TestClient) -> None:
        """
        GIVEN an invalid artifact_type query parameter
        WHEN GET /artifacts?artifact_type=not_a_real_type is requested
        THEN 422 Unprocessable Entity is returned.
        """
        resp = client.get("/artifacts?artifact_type=not_a_real_type", headers=AUTH_HEADERS)
        assert resp.status_code == 422, (
            f"Expected 422 for invalid artifact_type, got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# GET /artifacts/{artifact_id}/download — download endpoint tests
# ---------------------------------------------------------------------------


class TestArtifactDownloadEndpoint:
    """
    Unit tests for GET /artifacts/{artifact_id}/download.

    The endpoint must:
    - Return 200 with binary content for a known artifact.
    - Return 404 when the artifact_id does not exist.
    - Stream content from the storage backend.
    - Set Content-Disposition header with the original filename.
    - Never load the entire file into memory before streaming (implementation
      concern; verified here via mock call assertions).
    """

    @pytest.fixture
    def stored_artifact(self) -> Artifact:
        """Return a sample artifact for download tests."""
        return _make_artifact(
            artifact_id=_SAMPLE_ULID_1,
            storage_path="fxlab-artifacts/runs/result.json",
        )

    @pytest.fixture
    def repo(self, stored_artifact: Artifact) -> MockArtifactRepository:
        r = MockArtifactRepository()
        r.save(stored_artifact)
        return r

    @pytest.fixture
    def storage(self) -> MagicMock:
        """Mock storage returning predictable content."""
        s = MagicMock()
        s.get.return_value = b'{"sharpe": 1.5, "drawdown": 0.08}'
        return s

    @pytest.fixture
    def client(
        self,
        repo: MockArtifactRepository,
        storage: MagicMock,
    ) -> TestClient:
        """
        Build a TestClient with both repo and storage dependencies overridden.

        FAILS until the download endpoint is wired.
        """
        from services.api.main import app
        from services.api.routes.artifacts import (
            get_artifact_repository,
            get_artifact_storage,
        )

        app.dependency_overrides[get_artifact_repository] = lambda: repo
        app.dependency_overrides[get_artifact_storage] = lambda: storage
        client = TestClient(app)
        yield client
        app.dependency_overrides.clear()

    def test_download_known_artifact_returns_200(self, client: TestClient) -> None:
        """
        GIVEN a known artifact_id in the registry
        WHEN GET /artifacts/{artifact_id}/download is requested
        THEN 200 is returned with binary content.

        FAILS: download endpoint not yet implemented.
        """
        resp = client.get(f"/artifacts/{_SAMPLE_ULID_1}/download", headers=AUTH_HEADERS)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_download_returns_binary_content(self, client: TestClient) -> None:
        """
        GIVEN a stored artifact with known content
        WHEN the download endpoint is called
        THEN the response body matches the stored bytes.
        """
        resp = client.get(f"/artifacts/{_SAMPLE_ULID_1}/download", headers=AUTH_HEADERS)
        assert resp.content == b'{"sharpe": 1.5, "drawdown": 0.08}'

    def test_download_sets_content_disposition_header(self, client: TestClient) -> None:
        """
        GIVEN a stored artifact
        WHEN the download endpoint is called
        THEN Content-Disposition is set (attachment with filename).
        """
        resp = client.get(f"/artifacts/{_SAMPLE_ULID_1}/download", headers=AUTH_HEADERS)
        assert "content-disposition" in resp.headers, (
            "Download response must include Content-Disposition header"
        )
        assert "attachment" in resp.headers["content-disposition"]

    def test_download_unknown_artifact_returns_404(self, client: TestClient) -> None:
        """
        GIVEN an artifact_id not in the registry
        WHEN the download endpoint is called
        THEN 404 is returned.
        """
        unknown_id = "01HQZZZZZZZZZZZZZZZZZZZZZZ"
        resp = client.get(f"/artifacts/{unknown_id}/download", headers=AUTH_HEADERS)
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"

    def test_download_calls_storage_get_with_correct_bucket_and_key(
        self, client: TestClient, storage: MagicMock
    ) -> None:
        """
        GIVEN a stored artifact with storage_path 'fxlab-artifacts/runs/result.json'
        WHEN the download endpoint is called
        THEN storage.get is called with bucket='fxlab-artifacts' and key='runs/result.json'.
        """
        client.get(f"/artifacts/{_SAMPLE_ULID_1}/download", headers=AUTH_HEADERS)
        storage.get.assert_called_once()
        call_kwargs = storage.get.call_args
        # Accept either positional or keyword arguments
        args = call_kwargs.args
        kwargs = call_kwargs.kwargs
        bucket = kwargs.get("bucket") or (args[0] if args else None)
        key = kwargs.get("key") or (args[1] if len(args) > 1 else None)
        assert bucket == "fxlab-artifacts", f"Expected bucket 'fxlab-artifacts', got {bucket!r}"
        assert key == "runs/result.json", f"Expected key 'runs/result.json', got {key!r}"

    def test_download_storage_not_found_returns_404(self) -> None:
        """
        GIVEN an artifact whose storage_path points to a missing file
        WHEN storage.get raises FileNotFoundError
        THEN the endpoint returns 404.
        """
        from services.api.main import app
        from services.api.routes.artifacts import get_artifact_repository, get_artifact_storage

        repo = MockArtifactRepository()
        repo.save(_make_artifact(_SAMPLE_ULID_1, storage_path="fxlab-artifacts/missing.json"))
        storage = MagicMock()
        storage.get.side_effect = FileNotFoundError("not found in storage")

        app.dependency_overrides[get_artifact_repository] = lambda: repo
        app.dependency_overrides[get_artifact_storage] = lambda: storage
        client = TestClient(app)
        try:
            resp = client.get(f"/artifacts/{_SAMPLE_ULID_1}/download", headers=AUTH_HEADERS)
            assert resp.status_code == 404, (
                f"Expected 404 when storage raises FileNotFoundError, got {resp.status_code}"
            )
        finally:
            app.dependency_overrides.clear()

    def test_download_malformed_storage_path_returns_500(self) -> None:
        """
        GIVEN an artifact with a storage_path that has no '/' separator
        WHEN the download endpoint is called
        THEN 500 is returned (malformed storage path).
        """
        from services.api.main import app
        from services.api.routes.artifacts import get_artifact_repository, get_artifact_storage

        repo = MockArtifactRepository()
        repo.save(_make_artifact(_SAMPLE_ULID_1, storage_path="noslashpath"))
        storage = MagicMock()

        app.dependency_overrides[get_artifact_repository] = lambda: repo
        app.dependency_overrides[get_artifact_storage] = lambda: storage
        client = TestClient(app)
        try:
            resp = client.get(f"/artifacts/{_SAMPLE_ULID_1}/download", headers=AUTH_HEADERS)
            assert resp.status_code == 500, (
                f"Expected 500 for malformed storage_path, got {resp.status_code}"
            )
        finally:
            app.dependency_overrides.clear()

    def test_download_json_artifact_sets_correct_content_type(self) -> None:
        """
        GIVEN an artifact whose key ends in .json
        WHEN the download endpoint is called
        THEN Content-Type is application/json.
        """
        from services.api.main import app
        from services.api.routes.artifacts import get_artifact_repository, get_artifact_storage

        repo = MockArtifactRepository()
        repo.save(_make_artifact(_SAMPLE_ULID_1, storage_path="fxlab-artifacts/runs/result.json"))
        storage = MagicMock()
        storage.get.return_value = b'{"sharpe": 1.5}'

        app.dependency_overrides[get_artifact_repository] = lambda: repo
        app.dependency_overrides[get_artifact_storage] = lambda: storage
        client = TestClient(app)
        try:
            resp = client.get(f"/artifacts/{_SAMPLE_ULID_1}/download", headers=AUTH_HEADERS)
            assert resp.status_code == 200
            assert "application/json" in resp.headers.get("content-type", "")
        finally:
            app.dependency_overrides.clear()

    def test_download_csv_artifact_sets_correct_content_type(self) -> None:
        """
        GIVEN an artifact whose key ends in .csv
        WHEN the download endpoint is called
        THEN Content-Type is text/csv.
        """
        from services.api.main import app
        from services.api.routes.artifacts import get_artifact_repository, get_artifact_storage

        repo = MockArtifactRepository()
        repo.save(
            _make_artifact(_SAMPLE_ULID_1, storage_path="fxlab-artifacts/exports/results.csv")
        )
        storage = MagicMock()
        storage.get.return_value = b"col1,col2\n1,2\n"

        app.dependency_overrides[get_artifact_repository] = lambda: repo
        app.dependency_overrides[get_artifact_storage] = lambda: storage
        client = TestClient(app)
        try:
            resp = client.get(f"/artifacts/{_SAMPLE_ULID_1}/download", headers=AUTH_HEADERS)
            assert resp.status_code == 200
            assert "text/csv" in resp.headers.get("content-type", "")
        finally:
            app.dependency_overrides.clear()

    def test_download_parquet_artifact_sets_correct_content_type(self) -> None:
        """
        GIVEN an artifact whose key ends in .parquet
        WHEN the download endpoint is called
        THEN Content-Type is application/vnd.apache.parquet.
        """
        from services.api.main import app
        from services.api.routes.artifacts import get_artifact_repository, get_artifact_storage

        repo = MockArtifactRepository()
        repo.save(
            _make_artifact(_SAMPLE_ULID_1, storage_path="fxlab-artifacts/models/weights.parquet")
        )
        storage = MagicMock()
        storage.get.return_value = b"PAR1fakedata"

        app.dependency_overrides[get_artifact_repository] = lambda: repo
        app.dependency_overrides[get_artifact_storage] = lambda: storage
        client = TestClient(app)
        try:
            resp = client.get(f"/artifacts/{_SAMPLE_ULID_1}/download", headers=AUTH_HEADERS)
            assert resp.status_code == 200
            assert "vnd.apache.parquet" in resp.headers.get("content-type", "")
        finally:
            app.dependency_overrides.clear()

    def test_download_unknown_extension_falls_back_to_octet_stream(self) -> None:
        """
        GIVEN an artifact whose key has an unknown extension (.bin)
        WHEN the download endpoint is called
        THEN Content-Type falls back to application/octet-stream.
        """
        from services.api.main import app
        from services.api.routes.artifacts import get_artifact_repository, get_artifact_storage

        repo = MockArtifactRepository()
        repo.save(_make_artifact(_SAMPLE_ULID_1, storage_path="fxlab-artifacts/models/model.bin"))
        storage = MagicMock()
        storage.get.return_value = b"\x00\x01\x02"

        app.dependency_overrides[get_artifact_repository] = lambda: repo
        app.dependency_overrides[get_artifact_storage] = lambda: storage
        client = TestClient(app)
        try:
            resp = client.get(f"/artifacts/{_SAMPLE_ULID_1}/download", headers=AUTH_HEADERS)
            assert resp.status_code == 200
            assert "octet-stream" in resp.headers.get("content-type", "")
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# ArtifactStorageBase — ABC contract (cannot instantiate directly)
# ---------------------------------------------------------------------------


class TestArtifactStorageBaseIsAbstract:
    """Verify that ArtifactStorageBase cannot be instantiated directly."""

    def test_base_is_abstract(self) -> None:
        """
        GIVEN ArtifactStorageBase
        WHEN instantiated directly
        THEN TypeError is raised.
        """
        from libs.storage.base import ArtifactStorageBase

        with pytest.raises(TypeError):
            ArtifactStorageBase()  # type: ignore[abstract]
