"""
Unit tests for export API routes.

Covers:
- POST /exports — create (201, auth, invalid payload)
- GET /exports — list with filters (200)
- GET /exports/{job_id} — get detail (200, 404)
- GET /exports/{job_id}/download — download (200, 404)

Uses MockExportRepository with ExportService and a simple
MockArtifactStorage. TEST_TOKEN bypass for auth.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from libs.contracts.mocks.mock_export_repository import MockExportRepository
from services.api.services.export_service import ExportService

# ---------------------------------------------------------------------------
# Mock artifact storage for tests
# ---------------------------------------------------------------------------


class _MockArtifactStorage:
    """Minimal in-memory artifact storage for route tests."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    def initialize(self, correlation_id: str) -> None:
        pass

    def is_initialized(self) -> bool:
        return True

    def health_check(self, correlation_id: str) -> bool:
        return True

    def put(
        self,
        data: bytes,
        bucket: str,
        key: str,
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> str:
        path = f"{bucket}/{key}"
        self._store[path] = data
        return path

    def get(self, bucket: str, key: str, correlation_id: str) -> bytes:
        path = f"{bucket}/{key}"
        if path not in self._store:
            raise FileNotFoundError(f"Object not found: {path}")
        return self._store[path]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _test_env():
    """Ensure ENVIRONMENT=test for TEST_TOKEN bypass."""
    old = os.environ.get("ENVIRONMENT")
    os.environ["ENVIRONMENT"] = "test"
    yield
    if old is None:
        os.environ.pop("ENVIRONMENT", None)
    else:
        os.environ["ENVIRONMENT"] = old


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer TEST_TOKEN"}


@pytest.fixture()
def repo() -> MockExportRepository:
    return MockExportRepository()


@pytest.fixture()
def storage() -> _MockArtifactStorage:
    return _MockArtifactStorage()


@pytest.fixture()
def export_service(
    repo: MockExportRepository,
    storage: _MockArtifactStorage,
) -> ExportService:
    return ExportService(repo=repo, storage=storage)  # type: ignore[arg-type]


@pytest.fixture()
def client(export_service: ExportService) -> TestClient:
    from services.api.routes.exports import set_export_service

    set_export_service(export_service)
    from services.api.main import app

    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# POST /exports
# ---------------------------------------------------------------------------


class TestCreateExport:
    """Tests for POST /exports."""

    def test_create_trades_export(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            "/exports/",
            json={"export_type": "trades", "object_id": "01HOBJECT001"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["export_type"] == "trades"
        assert data["object_id"] == "01HOBJECT001"
        assert data["status"] == "complete"
        assert data["artifact_uri"] is not None

    def test_create_runs_export(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            "/exports/",
            json={"export_type": "runs", "object_id": "01HOBJECT002"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["export_type"] == "runs"
        assert resp.json()["status"] == "complete"

    def test_create_no_auth_returns_401(
        self,
        client: TestClient,
    ) -> None:
        resp = client.post(
            "/exports/",
            json={"export_type": "trades", "object_id": "01HOBJECT001"},
        )
        assert resp.status_code == 401

    def test_create_invalid_type_returns_422(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            "/exports/",
            json={"export_type": "invalid_type", "object_id": "01H"},
            headers=auth_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /exports
# ---------------------------------------------------------------------------


class TestListExports:
    """Tests for GET /exports."""

    def test_list_by_requested_by(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Create two exports
        for _ in range(2):
            client.post(
                "/exports/",
                json={"export_type": "trades", "object_id": "01HOBJECT001"},
                headers=auth_headers,
            )

        # TEST_TOKEN user is "01HTESTFAKE000000000000000"
        resp = client.get(
            "/exports/?requested_by=01HTESTFAKE000000000000000",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 2
        assert len(data["exports"]) == 2

    def test_list_by_object_id(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        client.post(
            "/exports/",
            json={"export_type": "trades", "object_id": "01HOBJECTAAA"},
            headers=auth_headers,
        )
        client.post(
            "/exports/",
            json={"export_type": "runs", "object_id": "01HOBJECTBBB"},
            headers=auth_headers,
        )

        resp = client.get(
            "/exports/?object_id=01HOBJECTAAA",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 1

    def test_list_empty(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.get(
            "/exports/?requested_by=nonexistent",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["total_count"] == 0


# ---------------------------------------------------------------------------
# GET /exports/{job_id}
# ---------------------------------------------------------------------------


class TestGetExport:
    """Tests for GET /exports/{job_id}."""

    def test_get_existing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        create_resp = client.post(
            "/exports/",
            json={"export_type": "trades", "object_id": "01HOBJECT001"},
            headers=auth_headers,
        )
        job_id = create_resp.json()["id"]

        resp = client.get(f"/exports/{job_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == job_id

    def test_get_nonexistent_returns_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.get("/exports/nonexistent", headers=auth_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /exports/{job_id}/download
# ---------------------------------------------------------------------------


class TestDownloadExport:
    """Tests for GET /exports/{job_id}/download."""

    def test_download_completed_export(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        create_resp = client.post(
            "/exports/",
            json={"export_type": "trades", "object_id": "01HOBJECT001"},
            headers=auth_headers,
        )
        job_id = create_resp.json()["id"]

        resp = client.get(f"/exports/{job_id}/download", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        assert "content-disposition" in resp.headers
        assert len(resp.content) > 0

    def test_download_nonexistent_returns_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.get("/exports/nonexistent/download", headers=auth_headers)
        assert resp.status_code == 404

    def test_download_no_auth_returns_401(
        self,
        client: TestClient,
    ) -> None:
        resp = client.get("/exports/someid/download")
        assert resp.status_code == 401
