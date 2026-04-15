"""
Unit tests for approvals route handlers.

Responsibilities:
- Test all endpoints in services/api/routes/approvals.py in isolation.
- Mock GovernanceService and its dependencies.
- Verify request parsing, validation, and error handling.
- Confirm structured logging events are emitted correctly.

Does NOT:
- Call real database or external services (all mocked).
- Test service business logic (that is the service's test responsibility).

Test coverage:
- Happy path: approve and reject with valid payloads.
- Validation: missing/invalid fields → 422.
- Not found: approval_id does not exist → 404.
- SoD violation: reviewer == submitter → 409.
- Authentication: missing auth header → 401.

Example:
    pytest tests/unit/test_approvals_routes.py -v
"""

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from libs.contracts.errors import NotFoundError, SeparationOfDutiesError
from services.api.auth import AuthenticatedUser, get_current_user
from services.api.main import app


@pytest.fixture
def client() -> TestClient:
    """Provide a FastAPI TestClient for the app."""
    return TestClient(app)


@pytest.fixture
def auth_headers_approvals() -> dict[str, str]:
    """Return auth headers with TEST_TOKEN."""
    return {"Authorization": "Bearer TEST_TOKEN"}


@pytest.fixture
def mock_authenticated_user() -> AuthenticatedUser:
    """Return a mock authenticated user with approvals:write scope."""
    return AuthenticatedUser(
        user_id="01HQZXYZ123456789ABCDEFGHJ",
        role="reviewer",
        email="reviewer@fxlab.test",
        scopes=[
            "approvals:write",
            "overrides:approve",
            "exports:read",
            "feeds:read",
            "operator:read",
            "audit:read",
        ],
    )


class TestApproveRequest:
    """Tests for POST /approvals/{approval_id}/approve endpoint."""

    def test_approve_request_happy_path(
        self,
        client: TestClient,
        auth_headers_approvals: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test successful approval with valid approval_id and auth.

        Scenario: User with approvals:write scope approves a pending request.
        Expected: 200 response with approval_id and status='approved'.
        """
        approval_id = "01HAPPROVAL123ABCDEFGHIJKL"

        # Mock the governance service in the dependency graph
        mock_service = MagicMock()
        mock_service.approve_request.return_value = {
            "approval_id": approval_id,
            "status": "approved",
        }

        from services.api.routes.approvals import get_governance_service

        app.dependency_overrides[get_governance_service] = lambda: mock_service
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                f"/approvals/{approval_id}/approve",
                headers=auth_headers_approvals,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["approval_id"] == approval_id
            assert data["status"] == "approved"
            mock_service.approve_request.assert_called_once()
        finally:
            app.dependency_overrides.clear()

    def test_approve_request_not_found(
        self,
        client: TestClient,
        auth_headers_approvals: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test approval request with non-existent approval_id.

        Scenario: User attempts to approve an approval_id that does not exist.
        Expected: 404 Not Found with appropriate error message.
        """
        approval_id = "01HNOTEXIST123ABCDEFGHIJKL"

        mock_service = MagicMock()
        mock_service.approve_request.side_effect = NotFoundError(
            f"Approval {approval_id} not found"
        )

        from services.api.routes.approvals import get_governance_service

        app.dependency_overrides[get_governance_service] = lambda: mock_service
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                f"/approvals/{approval_id}/approve",
                headers=auth_headers_approvals,
            )

            assert response.status_code == 404
            data = response.json()
            assert "not found" in data["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    def test_approve_request_separation_of_duties_violation(
        self,
        client: TestClient,
        auth_headers_approvals: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test approval fails when reviewer is the same as submitter.

        Scenario: User attempts to approve their own approval request.
        Expected: 409 Conflict with SoD violation message.
        """
        approval_id = "01HAPPROVAL123ABCDEFGHIJKL"

        mock_service = MagicMock()
        mock_service.approve_request.side_effect = SeparationOfDutiesError(
            "Reviewer cannot be the same as submitter"
        )

        from services.api.routes.approvals import get_governance_service

        app.dependency_overrides[get_governance_service] = lambda: mock_service
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                f"/approvals/{approval_id}/approve",
                headers=auth_headers_approvals,
            )

            assert response.status_code == 409
            data = response.json()
            assert "same person" in data["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    def test_approve_request_missing_auth(self, client: TestClient) -> None:
        """
        Test approval fails without authentication header.

        Scenario: Request is sent without Authorization header.
        Expected: 401 Unauthorized.
        """
        approval_id = "01HAPPROVAL123ABCDEFGHIJKL"

        response = client.post(f"/approvals/{approval_id}/approve")

        assert response.status_code == 401


class TestRejectRequest:
    """Tests for POST /approvals/{approval_id}/reject endpoint."""

    def test_reject_request_happy_path(
        self,
        client: TestClient,
        auth_headers_approvals: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test successful rejection with valid payload.

        Scenario: User with approvals:write scope rejects with valid rationale.
        Expected: 200 response with approval_id and status='rejected'.
        """
        approval_id = "01HAPPROVAL123ABCDEFGHIJKL"
        rationale = "Evidence link is stale; backtest does not cover current regime."

        mock_service = MagicMock()
        mock_service.reject_request.return_value = {
            "approval_id": approval_id,
            "status": "rejected",
            "rationale": rationale,
        }

        from services.api.routes.approvals import get_governance_service

        app.dependency_overrides[get_governance_service] = lambda: mock_service
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                f"/approvals/{approval_id}/reject",
                headers=auth_headers_approvals,
                json={"rationale": rationale},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["approval_id"] == approval_id
            assert data["status"] == "rejected"
            assert data["rationale"] == rationale
        finally:
            app.dependency_overrides.clear()

    def test_reject_request_missing_payload(
        self,
        client: TestClient,
        auth_headers_approvals: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test rejection fails without request body.

        Scenario: POST with no JSON body.
        Expected: 422 Unprocessable Entity.
        """
        approval_id = "01HAPPROVAL123ABCDEFGHIJKL"

        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                f"/approvals/{approval_id}/reject",
                headers=auth_headers_approvals,
            )

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_reject_request_rationale_too_short(
        self,
        client: TestClient,
        auth_headers_approvals: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test rejection fails when rationale is below minimum length (10 chars).

        Scenario: Rationale is "Too short" (9 characters).
        Expected: 422 Unprocessable Entity.
        """
        approval_id = "01HAPPROVAL123ABCDEFGHIJKL"

        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                f"/approvals/{approval_id}/reject",
                headers=auth_headers_approvals,
                json={"rationale": "Too short"},
            )

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_reject_request_empty_rationale(
        self,
        client: TestClient,
        auth_headers_approvals: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test rejection fails when rationale is empty string.

        Scenario: Rationale is empty ("").
        Expected: 422 Unprocessable Entity.
        """
        approval_id = "01HAPPROVAL123ABCDEFGHIJKL"

        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                f"/approvals/{approval_id}/reject",
                headers=auth_headers_approvals,
                json={"rationale": ""},
            )

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_reject_request_not_found(
        self,
        client: TestClient,
        auth_headers_approvals: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test rejection fails when approval_id does not exist.

        Scenario: approval_id not in database.
        Expected: 404 Not Found.
        """
        approval_id = "01HNOTEXIST123ABCDEFGHIJKL"
        rationale = "Evidence link is stale; backtest does not cover current regime."

        mock_service = MagicMock()
        mock_service.reject_request.side_effect = NotFoundError(f"Approval {approval_id} not found")

        from services.api.routes.approvals import get_governance_service

        app.dependency_overrides[get_governance_service] = lambda: mock_service
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                f"/approvals/{approval_id}/reject",
                headers=auth_headers_approvals,
                json={"rationale": rationale},
            )

            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_reject_request_separation_of_duties_violation(
        self,
        client: TestClient,
        auth_headers_approvals: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test rejection fails when reviewer is the same as submitter.

        Scenario: User attempts to reject their own approval request.
        Expected: 409 Conflict.
        """
        approval_id = "01HAPPROVAL123ABCDEFGHIJKL"
        rationale = "Evidence link is stale; backtest does not cover current regime."

        mock_service = MagicMock()
        mock_service.reject_request.side_effect = SeparationOfDutiesError(
            "Reviewer cannot be the same as submitter"
        )

        from services.api.routes.approvals import get_governance_service

        app.dependency_overrides[get_governance_service] = lambda: mock_service
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                f"/approvals/{approval_id}/reject",
                headers=auth_headers_approvals,
                json={"rationale": rationale},
            )

            assert response.status_code == 409
        finally:
            app.dependency_overrides.clear()

    def test_reject_request_missing_auth(self, client: TestClient) -> None:
        """
        Test rejection fails without authentication header.

        Scenario: Request is sent without Authorization header.
        Expected: 401 Unauthorized.
        """
        approval_id = "01HAPPROVAL123ABCDEFGHIJKL"

        response = client.post(
            f"/approvals/{approval_id}/reject",
            json={"rationale": "Some valid reason of sufficient length"},
        )

        assert response.status_code == 401
