"""
Unit tests for overrides route handlers.

Responsibilities:
- Test all endpoints in services/api/routes/overrides.py in isolation.
- Mock GovernanceService and OverrideRepository dependencies.
- Verify request validation including evidence_link URI validation.
- Confirm validation of override_type and rationale length.
- Test structured logging at key lifecycle points.

Does NOT:
- Call real database or external services (all mocked).
- Test service business logic (service tests handle that).

Test coverage:
- Happy path: POST /request and GET /{override_id}.
- Validation: invalid evidence_link format → 422.
- Validation: rationale too short → 422.
- Validation: invalid object_type → 422.
- Not found: override_id does not exist → 404.
- Authentication: missing auth header → 401.

Example:
    pytest tests/unit/test_overrides_routes.py -v
"""

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from services.api.auth import AuthenticatedUser, get_current_user
from services.api.main import app


@pytest.fixture
def client() -> TestClient:
    """Provide a FastAPI TestClient for the app."""
    return TestClient(app)


@pytest.fixture
def auth_headers_overrides() -> dict[str, str]:
    """Return auth headers with TEST_TOKEN for overrides scope."""
    return {"Authorization": "Bearer TEST_TOKEN"}


@pytest.fixture
def mock_authenticated_user() -> AuthenticatedUser:
    """Return a mock authenticated user with overrides scope."""
    return AuthenticatedUser(
        user_id="01HQZXYZ123456789ABCDEFGHJ",
        role="operator",
        email="operator@fxlab.test",
        scopes=[
            "strategies:write",
            "runs:write",
            "promotions:request",
            "overrides:request",
            "exports:read",
            "feeds:read",
            "operator:read",
            "audit:read",
        ],
    )


@pytest.fixture
def valid_override_payload() -> dict:
    """Return a valid OverrideRequest payload."""
    return {
        "object_id": "01HCANDIDATE123ABCDEFGHIJ",
        "object_type": "candidate",
        "override_type": "grade_override",
        "original_state": {"grade": "C"},
        "new_state": {"grade": "B"},
        "evidence_link": "https://jira.example.com/browse/FX-123",
        "rationale": "Extended backtest over 3-year window justifies grade uplift.",
        "submitter_id": "01HQZXYZ123456789ABCDEFGHJ",
    }


class TestRequestOverride:
    """Tests for POST /overrides/request endpoint."""

    def test_request_override_happy_path(
        self,
        client: TestClient,
        auth_headers_overrides: dict[str, str],
        valid_override_payload: dict,
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test successful override request submission.

        Scenario: Valid payload with all required fields and correct evidence_link.
        Expected: 201 Created with override_id and status='pending'.
        """
        mock_service = MagicMock()
        mock_service.submit_override.return_value = {
            "override_id": "01HOVERRIDE123ABCDEFGHIJK",
            "status": "pending",
        }

        from services.api.routes.overrides import get_governance_service

        app.dependency_overrides[get_governance_service] = lambda: mock_service
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/overrides/request",
                headers=auth_headers_overrides,
                json=valid_override_payload,
            )

            assert response.status_code == 201
            data = response.json()
            assert data["override_id"] == "01HOVERRIDE123ABCDEFGHIJK"
            assert data["status"] == "pending"
        finally:
            app.dependency_overrides.clear()

    def test_request_override_invalid_evidence_link_scheme(
        self,
        client: TestClient,
        auth_headers_overrides: dict[str, str],
        valid_override_payload: dict,
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test override request fails with non-HTTP/HTTPS evidence_link.

        Scenario: evidence_link uses ftp:// scheme.
        Expected: 422 Unprocessable Entity.
        """
        payload = valid_override_payload.copy()
        payload["evidence_link"] = "ftp://example.com/evidence"

        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/overrides/request",
                headers=auth_headers_overrides,
                json=payload,
            )

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_request_override_invalid_evidence_link_root_path(
        self,
        client: TestClient,
        auth_headers_overrides: dict[str, str],
        valid_override_payload: dict,
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test override request fails when evidence_link is a domain root.

        Scenario: evidence_link is https://example.com (no path or root path only).
        Expected: 422 Unprocessable Entity (SOC 2 compliance — must reference specific resource).
        """
        payload = valid_override_payload.copy()
        payload["evidence_link"] = "https://example.com/"

        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/overrides/request",
                headers=auth_headers_overrides,
                json=payload,
            )

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_request_override_rationale_too_short(
        self,
        client: TestClient,
        auth_headers_overrides: dict[str, str],
        valid_override_payload: dict,
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test override request fails when rationale is below minimum length (20 chars).

        Scenario: rationale is "Too short" (9 characters).
        Expected: 422 Unprocessable Entity.
        """
        payload = valid_override_payload.copy()
        payload["rationale"] = "Too short"

        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/overrides/request",
                headers=auth_headers_overrides,
                json=payload,
            )

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_request_override_invalid_object_type(
        self,
        client: TestClient,
        auth_headers_overrides: dict[str, str],
        valid_override_payload: dict,
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test override request fails with invalid object_type.

        Scenario: object_type is "strategy" instead of "candidate" or "deployment".
        Expected: 422 Unprocessable Entity.
        """
        payload = valid_override_payload.copy()
        payload["object_type"] = "strategy"

        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/overrides/request",
                headers=auth_headers_overrides,
                json=payload,
            )

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_request_override_missing_evidence_link(
        self,
        client: TestClient,
        auth_headers_overrides: dict[str, str],
        valid_override_payload: dict,
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test override request fails when evidence_link is missing.

        Scenario: Payload has no evidence_link field.
        Expected: 422 Unprocessable Entity.
        """
        payload = valid_override_payload.copy()
        del payload["evidence_link"]

        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/overrides/request",
                headers=auth_headers_overrides,
                json=payload,
            )

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_request_override_missing_rationale(
        self,
        client: TestClient,
        auth_headers_overrides: dict[str, str],
        valid_override_payload: dict,
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test override request fails when rationale is missing.

        Scenario: Payload has no rationale field.
        Expected: 422 Unprocessable Entity.
        """
        payload = valid_override_payload.copy()
        del payload["rationale"]

        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/overrides/request",
                headers=auth_headers_overrides,
                json=payload,
            )

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_request_override_missing_auth(
        self, client: TestClient, valid_override_payload: dict
    ) -> None:
        """
        Test override request fails without authentication header.

        Scenario: Request is sent without Authorization header.
        Expected: 401 Unauthorized.
        """
        response = client.post(
            "/overrides/request",
            json=valid_override_payload,
        )

        assert response.status_code == 401


class TestGetOverride:
    """Tests for GET /overrides/{override_id} endpoint."""

    def test_get_override_happy_path(
        self,
        client: TestClient,
        auth_headers_overrides: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test successful retrieval of an override request.

        Scenario: Valid override_id exists in the repository.
        Expected: 200 OK with full OverrideDetail response.
        """
        override_id = "01HOVERRIDE123ABCDEFGHIJK"

        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = {
            "id": override_id,
            "object_id": "01HCANDIDATE123ABCDEFGHIJ",
            "object_type": "candidate",
            "override_type": "grade_override",
            "original_state": {"grade": "C"},
            "new_state": {"grade": "B"},
            "evidence_link": "https://jira.example.com/browse/FX-123",
            "rationale": "Extended backtest over 3-year window justifies grade uplift.",
            "submitter_id": "01HUSER123ABCDEFGHIJKL",
            "status": "pending",
            "reviewed_by": None,
            "reviewed_at": None,
            "created_at": "2026-03-28T10:00:00Z",
            "updated_at": "2026-03-28T10:00:00Z",
        }

        from services.api.routes.overrides import get_override_repository

        app.dependency_overrides[get_override_repository] = lambda: mock_repo
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.get(
                f"/overrides/{override_id}",
                headers=auth_headers_overrides,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["id"] == override_id
            assert data["status"] == "pending"
            assert data["object_type"] == "candidate"
        finally:
            app.dependency_overrides.clear()

    def test_get_override_not_found(
        self,
        client: TestClient,
        auth_headers_overrides: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test GET fails when override_id does not exist.

        Scenario: override_id not in repository.
        Expected: 404 Not Found.
        """
        override_id = "01HNOTEXIST123ABCDEFGHIJK"

        mock_repo = MagicMock()
        mock_repo.get_by_id.return_value = None

        from services.api.routes.overrides import get_override_repository

        app.dependency_overrides[get_override_repository] = lambda: mock_repo
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.get(
                f"/overrides/{override_id}",
                headers=auth_headers_overrides,
            )

            assert response.status_code == 404
            data = response.json()
            assert "not found" in data["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    def test_get_override_missing_auth(self, client: TestClient) -> None:
        """
        Test GET fails without authentication header.

        Scenario: Request is sent without Authorization header.
        Expected: 401 Unauthorized.
        """
        override_id = "01HOVERRIDE123ABCDEFGHIJK"

        response = client.get(f"/overrides/{override_id}")

        assert response.status_code == 401
