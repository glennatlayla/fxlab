"""
Unit tests for audit export and retention policy route handlers (Phase 6 — M12).

Verifies:
    - POST /audit/export creates an export with valid parameters.
    - POST /audit/export rejects invalid date ranges (422).
    - GET /audit/export/{job_id} retrieves export job metadata.
    - GET /audit/export/{job_id} returns 404 for unknown job_id.
    - GET /audit/export/{job_id}/content returns raw export bytes.
    - GET /audit/export/{job_id}/content returns 404 for unknown job_id.
    - GET /audit/retention-policy returns retention configuration.
    - Authentication: missing auth → 401.

Dependencies:
    - pytest for assertions.
    - starlette.testclient for request simulation.
    - AuditExportServiceInterface mocked via FastAPI dependency overrides.

Example:
    pytest tests/unit/test_audit_export_routes.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from libs.contracts.audit_export import (
    AuditExportFormat,
    AuditExportRequest,
    AuditExportResult,
    RetentionEntityType,
    RetentionPolicyConfig,
    RetentionPolicyEntry,
)
from libs.contracts.errors import NotFoundError, ValidationError
from services.api.auth import AuthenticatedUser, get_current_user
from services.api.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MOCK_EXPORT_RESULT = AuditExportResult(
    job_id="01HQEXPORT0AAAAAAAAAAAAAAA",
    status="completed",
    record_count=42,
    content_hash="sha256:abc123def456",
    byte_size=1024,
    format=AuditExportFormat.JSON,
    compressed=False,
    created_at=datetime(2026, 4, 12, 10, 0, 0, tzinfo=timezone.utc),
    completed_at=datetime(2026, 4, 12, 10, 0, 5, tzinfo=timezone.utc),
)

_MOCK_RETENTION_CONFIG = RetentionPolicyConfig(
    policies=[
        RetentionPolicyEntry(
            entity_type=RetentionEntityType.AUDIT_EVENTS,
            retention_days=2555,
            grace_period_days=30,
        ),
        RetentionPolicyEntry(
            entity_type=RetentionEntityType.PNL_SNAPSHOTS,
            retention_days=0,
            grace_period_days=0,
        ),
    ],
    last_run_at=None,
    next_run_at=None,
)

_MOCK_EXPORT_CONTENT = b'[{"id":"01HQ","actor":"test@fxlab.test"}]'


@pytest.fixture()
def mock_export_service() -> MagicMock:
    """Build a MagicMock implementing AuditExportServiceInterface."""
    svc = MagicMock()
    svc.create_export.return_value = _MOCK_EXPORT_RESULT
    svc.get_export_result.return_value = _MOCK_EXPORT_RESULT
    svc.get_export_content.return_value = _MOCK_EXPORT_CONTENT
    svc.get_retention_policy.return_value = _MOCK_RETENTION_CONFIG
    return svc


@pytest.fixture()
def mock_auth_user() -> AuthenticatedUser:
    """Return a mock authenticated user with exports:read scope."""
    return AuthenticatedUser(
        user_id="01HQZXYZ123456789ABCDEFGHJ",
        role="admin",
        email="admin@fxlab.test",
        scopes=[
            "exports:read",
            "exports:write",
            "audit:read",
            "operator:read",
            "feeds:read",
        ],
    )


@pytest.fixture()
def client(
    mock_export_service: MagicMock,
    mock_auth_user: AuthenticatedUser,
) -> TestClient:
    """Provide a TestClient with mocked dependencies."""
    from services.api.routes.audit_export import get_audit_export_service

    app.dependency_overrides[get_audit_export_service] = lambda: mock_export_service
    app.dependency_overrides[get_current_user] = lambda: mock_auth_user
    yield TestClient(app)  # type: ignore[misc]
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: POST /audit/export
# ---------------------------------------------------------------------------


class TestCreateExport:
    """Tests for POST /audit/export."""

    def test_create_export_happy_path(
        self, client: TestClient, mock_export_service: MagicMock
    ) -> None:
        """Valid export request returns 200 with job metadata."""
        payload = {
            "date_from": "2025-01-01T00:00:00Z",
            "date_to": "2025-12-31T23:59:59Z",
            "format": "json",
        }
        resp = client.post("/audit/export", json=payload)

        assert resp.status_code == 200
        body = resp.json()
        assert body["job_id"] == "01HQEXPORT0AAAAAAAAAAAAAAA"
        assert body["status"] == "completed"
        assert body["record_count"] == 42
        assert body["content_hash"].startswith("sha256:")
        mock_export_service.create_export.assert_called_once()

    def test_create_export_with_filters(
        self, client: TestClient, mock_export_service: MagicMock
    ) -> None:
        """Export request with actor and action_type filters is accepted."""
        payload = {
            "date_from": "2025-01-01T00:00:00Z",
            "date_to": "2025-06-30T23:59:59Z",
            "format": "csv",
            "actor": "trader@fxlab.test",
            "action_type": "order",
            "compress": True,
        }
        resp = client.post("/audit/export", json=payload)

        assert resp.status_code == 200
        call_args = mock_export_service.create_export.call_args
        request_arg = call_args[0][0]
        assert isinstance(request_arg, AuditExportRequest)
        assert request_arg.actor == "trader@fxlab.test"
        assert request_arg.action_type == "order"
        assert request_arg.compress is True

    def test_create_export_service_validation_error(
        self, client: TestClient, mock_export_service: MagicMock
    ) -> None:
        """Service raises ValidationError → 422 response."""
        mock_export_service.create_export.side_effect = ValidationError(
            "date_from must be before date_to"
        )
        payload = {
            "date_from": "2025-12-31T00:00:00Z",
            "date_to": "2025-01-01T00:00:00Z",
            "format": "json",
        }
        resp = client.post("/audit/export", json=payload)

        assert resp.status_code == 422
        assert "date_from" in resp.json()["detail"]

    def test_create_export_missing_required_fields(self, client: TestClient) -> None:
        """Missing date_from or date_to → 422."""
        resp = client.post("/audit/export", json={"format": "json"})

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests: GET /audit/export/{job_id}
# ---------------------------------------------------------------------------


class TestGetExportResult:
    """Tests for GET /audit/export/{job_id}."""

    def test_get_export_result_happy_path(
        self, client: TestClient, mock_export_service: MagicMock
    ) -> None:
        """Valid job_id returns 200 with export metadata."""
        resp = client.get("/audit/export/01HQEXPORT0AAAAAAAAAAAAAAA")

        assert resp.status_code == 200
        body = resp.json()
        assert body["job_id"] == "01HQEXPORT0AAAAAAAAAAAAAAA"
        assert body["record_count"] == 42
        mock_export_service.get_export_result.assert_called_once_with("01HQEXPORT0AAAAAAAAAAAAAAA")

    def test_get_export_result_not_found(
        self, client: TestClient, mock_export_service: MagicMock
    ) -> None:
        """Unknown job_id → 404."""
        mock_export_service.get_export_result.side_effect = NotFoundError("Export job not found")
        resp = client.get("/audit/export/01HQNONEXISTENT00000000000")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Tests: GET /audit/export/{job_id}/content
# ---------------------------------------------------------------------------


class TestGetExportContent:
    """Tests for GET /audit/export/{job_id}/content."""

    def test_get_export_content_happy_path(
        self, client: TestClient, mock_export_service: MagicMock
    ) -> None:
        """Valid job_id returns raw content bytes."""
        resp = client.get("/audit/export/01HQEXPORT0AAAAAAAAAAAAAAA/content")

        assert resp.status_code == 200
        assert resp.content == _MOCK_EXPORT_CONTENT
        assert resp.headers["content-type"] == "application/octet-stream"

    def test_get_export_content_not_found(
        self, client: TestClient, mock_export_service: MagicMock
    ) -> None:
        """Unknown job_id for content → 404."""
        mock_export_service.get_export_content.side_effect = NotFoundError(
            "Export content not found"
        )
        resp = client.get("/audit/export/01HQNONEXISTENT00000000000/content")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: GET /audit/retention-policy
# ---------------------------------------------------------------------------


class TestGetRetentionPolicy:
    """Tests for GET /audit/retention-policy."""

    def test_get_retention_policy_happy_path(
        self, client: TestClient, mock_export_service: MagicMock
    ) -> None:
        """Returns retention policy configuration."""
        resp = client.get("/audit/retention-policy")

        assert resp.status_code == 200
        body = resp.json()
        assert "policies" in body
        assert len(body["policies"]) == 2
        mock_export_service.get_retention_policy.assert_called_once()

    def test_retention_policy_includes_entity_types(
        self, client: TestClient, mock_export_service: MagicMock
    ) -> None:
        """Each policy entry includes entity_type and retention_days."""
        resp = client.get("/audit/retention-policy")

        body = resp.json()
        entity_types = {p["entity_type"] for p in body["policies"]}
        assert "audit_events" in entity_types
        assert "pnl_snapshots" in entity_types


# ---------------------------------------------------------------------------
# Tests: Authentication
# ---------------------------------------------------------------------------


class TestExportAuthentication:
    """Tests for authentication requirements on export endpoints."""

    def test_create_export_no_auth_returns_401(self) -> None:
        """POST /audit/export without auth → 401."""
        # Clear overrides so real auth is used
        app.dependency_overrides.clear()
        test_client = TestClient(app)
        payload = {
            "date_from": "2025-01-01T00:00:00Z",
            "date_to": "2025-12-31T23:59:59Z",
            "format": "json",
        }
        resp = test_client.post("/audit/export", json=payload)

        # Should be 401 or 403 depending on auth middleware
        assert resp.status_code in (401, 403)
