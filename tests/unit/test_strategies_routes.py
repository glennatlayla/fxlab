"""
Unit tests for strategies route handlers.

Responsibilities:
- Test all endpoints in services/api/routes/strategies.py in isolation.
- Mock DraftAutosaveRepository and its dependencies.
- Verify request validation and error handling.
- Confirm structured logging at key lifecycle points.

Does NOT:
- Call real database or external services (all mocked).
- Test repository business logic (repository tests handle that).

Test coverage:
- Happy path: POST /draft/autosave, GET /latest, DELETE /{id}.
- Validation: missing required fields → 422.
- Not found: autosave_id or user_id → 404 or 204.
- Authentication: missing auth header → 401.
- Listing strategies (stub endpoint).

Example:
    pytest tests/unit/test_strategies_routes.py -v
"""

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from services.api.auth import AuthenticatedUser, get_current_user
from services.api.main import app
from services.api.routes.strategies import set_strategy_service


@pytest.fixture
def client() -> TestClient:
    """Provide a FastAPI TestClient for the app."""
    return TestClient(app)


@pytest.fixture
def auth_headers_strategies() -> dict[str, str]:
    """Return auth headers with TEST_TOKEN for strategies scope."""
    return {"Authorization": "Bearer TEST_TOKEN"}


@pytest.fixture
def mock_authenticated_user() -> AuthenticatedUser:
    """Return a mock authenticated user with strategies scope."""
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
def valid_autosave_payload() -> dict:
    """Return a valid DraftAutosavePayload."""
    return {
        "user_id": "01HUSER123ABCDEFGHIJKL",
        "draft_payload": {"name": "MyStrategy", "lookback": 30},
        "form_step": "parameters",
        "client_ts": "2026-03-28T11:00:00Z",
        "session_id": "sess-abc123def456",
    }


class TestListStrategies:
    """Tests for GET /strategies/ endpoint."""

    def test_list_strategies_happy_path(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test successful strategy listing.

        Scenario: Authenticated user with strategies:write scope requests
                  strategy list via the StrategyService.
        Expected: 200 OK with strategies list, count, limit, offset.
        """
        mock_service = MagicMock()
        mock_service.list_strategies.return_value = {
            "strategies": [],
            "limit": 50,
            "offset": 0,
            "count": 0,
        }
        set_strategy_service(mock_service)
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.get(
                "/strategies/",
                headers=auth_headers_strategies,
            )

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data["strategies"], list)
            assert data["count"] == 0
        finally:
            app.dependency_overrides.clear()
            set_strategy_service(None)

    def test_list_strategies_missing_auth(self, client: TestClient) -> None:
        """
        Test strategy list fails without authentication header.

        Scenario: Request is sent without Authorization header.
        Expected: 401 Unauthorized.
        """
        response = client.get("/strategies/")

        assert response.status_code == 401


class TestPostDraftAutosave:
    """Tests for POST /strategies/draft/autosave endpoint."""

    def test_post_draft_autosave_happy_path(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        valid_autosave_payload: dict,
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test successful draft autosave creation.

        Scenario: Valid payload with all required fields.
        Expected: 200 OK with autosave_id and saved_at timestamp.
        """
        mock_repo = MagicMock()
        mock_repo.create.return_value = {
            "autosave_id": "01HAUTOSAVE123ABCDEFGHIJK",
            "saved_at": "2026-03-28T11:00:01Z",
        }

        from services.api.routes.strategies import get_draft_autosave_repository

        app.dependency_overrides[get_draft_autosave_repository] = lambda: mock_repo
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/strategies/draft/autosave",
                headers=auth_headers_strategies,
                json=valid_autosave_payload,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["autosave_id"] == "01HAUTOSAVE123ABCDEFGHIJK"
            assert "saved_at" in data
        finally:
            app.dependency_overrides.clear()

    def test_post_draft_autosave_missing_user_id(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        valid_autosave_payload: dict,
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test autosave fails when user_id is missing.

        Scenario: Payload has no user_id field.
        Expected: 422 Unprocessable Entity.
        """
        payload = valid_autosave_payload.copy()
        del payload["user_id"]

        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/strategies/draft/autosave",
                headers=auth_headers_strategies,
                json=payload,
            )

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_post_draft_autosave_missing_draft_payload(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        valid_autosave_payload: dict,
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test autosave fails when draft_payload is missing.

        Scenario: Payload has no draft_payload field.
        Expected: 422 Unprocessable Entity.
        """
        payload = valid_autosave_payload.copy()
        del payload["draft_payload"]

        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/strategies/draft/autosave",
                headers=auth_headers_strategies,
                json=payload,
            )

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_post_draft_autosave_missing_form_step(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        valid_autosave_payload: dict,
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test autosave fails when form_step is missing.

        Scenario: Payload has no form_step field.
        Expected: 422 Unprocessable Entity.
        """
        payload = valid_autosave_payload.copy()
        del payload["form_step"]

        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/strategies/draft/autosave",
                headers=auth_headers_strategies,
                json=payload,
            )

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_post_draft_autosave_missing_client_ts(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        valid_autosave_payload: dict,
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test autosave fails when client_ts is missing.

        Scenario: Payload has no client_ts field.
        Expected: 422 Unprocessable Entity.
        """
        payload = valid_autosave_payload.copy()
        del payload["client_ts"]

        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/strategies/draft/autosave",
                headers=auth_headers_strategies,
                json=payload,
            )

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_post_draft_autosave_missing_session_id(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        valid_autosave_payload: dict,
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test autosave fails when session_id is missing.

        Scenario: Payload has no session_id field.
        Expected: 422 Unprocessable Entity.
        """
        payload = valid_autosave_payload.copy()
        del payload["session_id"]

        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/strategies/draft/autosave",
                headers=auth_headers_strategies,
                json=payload,
            )

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_post_draft_autosave_missing_auth(
        self, client: TestClient, valid_autosave_payload: dict
    ) -> None:
        """
        Test autosave fails without authentication header.

        Scenario: Request is sent without Authorization header.
        Expected: 401 Unauthorized.
        """
        response = client.post(
            "/strategies/draft/autosave",
            json=valid_autosave_payload,
        )

        assert response.status_code == 401


class TestGetLatestDraftAutosave:
    """Tests for GET /strategies/draft/autosave/latest endpoint."""

    def test_get_latest_draft_autosave_happy_path(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test successful retrieval of latest autosave.

        Scenario: User has a saved autosave record.
        Expected: 200 OK with autosave data.
        """
        user_id = "01HQZXYZ123456789ABCDEFGHJ"

        mock_repo = MagicMock()
        mock_repo.get_latest.return_value = {
            "autosave_id": "01HAUTOSAVE123ABCDEFGHIJK",
            "user_id": user_id,
            "draft_payload": {"name": "MyStrategy", "lookback": 30},
            "form_step": "parameters",
            "session_id": "sess-abc123def456",
            "saved_at": "2026-03-28T11:00:01Z",
        }

        from services.api.routes.strategies import get_draft_autosave_repository

        app.dependency_overrides[get_draft_autosave_repository] = lambda: mock_repo
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.get(
                f"/strategies/draft/autosave/latest?user_id={user_id}",
                headers=auth_headers_strategies,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["autosave_id"] == "01HAUTOSAVE123ABCDEFGHIJK"
            assert data["user_id"] == user_id
        finally:
            app.dependency_overrides.clear()

    def test_get_latest_draft_autosave_none_found(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test GET /latest returns 204 when no autosave exists for user.

        Scenario: User has never saved an autosave.
        Expected: 204 No Content.
        """
        user_id = "01HUSER_NO_AUTOSAVE123456"

        mock_repo = MagicMock()
        mock_repo.get_latest.return_value = None

        from services.api.routes.strategies import get_draft_autosave_repository

        app.dependency_overrides[get_draft_autosave_repository] = lambda: mock_repo
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.get(
                f"/strategies/draft/autosave/latest?user_id={user_id}",
                headers=auth_headers_strategies,
            )

            assert response.status_code == 204
        finally:
            app.dependency_overrides.clear()

    def test_get_latest_draft_autosave_missing_user_id(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test GET /latest fails when user_id query parameter is missing.

        Scenario: Request has no user_id query parameter.
        Expected: 422 Unprocessable Entity.
        """
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.get(
                "/strategies/draft/autosave/latest",
                headers=auth_headers_strategies,
            )

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_get_latest_draft_autosave_missing_auth(self, client: TestClient) -> None:
        """
        Test GET /latest fails without authentication header.

        Scenario: Request is sent without Authorization header.
        Expected: 401 Unauthorized.
        """
        user_id = "01HUSER123ABCDEFGHIJKL"

        response = client.get(
            f"/strategies/draft/autosave/latest?user_id={user_id}",
        )

        assert response.status_code == 401


class TestDeleteDraftAutosave:
    """Tests for DELETE /strategies/draft/autosave/{autosave_id} endpoint."""

    def test_delete_draft_autosave_happy_path(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test successful deletion of a draft autosave.

        Scenario: Valid autosave_id exists and is deleted.
        Expected: 204 No Content (no response body).
        """
        autosave_id = "01HAUTOSAVE123ABCDEFGHIJK"

        mock_repo = MagicMock()
        mock_repo.delete.return_value = True

        from services.api.routes.strategies import get_draft_autosave_repository

        app.dependency_overrides[get_draft_autosave_repository] = lambda: mock_repo
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.delete(
                f"/strategies/draft/autosave/{autosave_id}",
                headers=auth_headers_strategies,
            )

            assert response.status_code == 204
            assert response.text == "" or response.content == b""
        finally:
            app.dependency_overrides.clear()

    def test_delete_draft_autosave_not_found(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """
        Test deletion fails when autosave_id does not exist.

        Scenario: autosave_id not in repository.
        Expected: 404 Not Found.
        """
        autosave_id = "01HNOTEXIST123ABCDEFGHIJK"

        mock_repo = MagicMock()
        mock_repo.delete.return_value = False

        from services.api.routes.strategies import get_draft_autosave_repository

        app.dependency_overrides[get_draft_autosave_repository] = lambda: mock_repo
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.delete(
                f"/strategies/draft/autosave/{autosave_id}",
                headers=auth_headers_strategies,
            )

            assert response.status_code == 404
            data = response.json()
            assert "not found" in data["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    def test_delete_draft_autosave_missing_auth(self, client: TestClient) -> None:
        """
        Test deletion fails without authentication header.

        Scenario: Request is sent without Authorization header.
        Expected: 401 Unauthorized.
        """
        autosave_id = "01HAUTOSAVE123ABCDEFGHIJK"

        response = client.delete(
            f"/strategies/draft/autosave/{autosave_id}",
        )

        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Soft-archive lifecycle routes (POST /archive | POST /restore)
# ---------------------------------------------------------------------------


class TestArchiveStrategyRoute:
    """Tests for POST /strategies/{strategy_id}/archive."""

    def test_archive_happy_path_returns_200_and_updated_strategy(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """Archive returns 200 with the updated record carrying archived_at."""
        archived_dict = {
            "id": "01HSRC0000000000000000001",
            "name": "Bollinger",
            "code": "{}",
            "version": "0.1.0",
            "source": "draft_form",
            "created_by": "01HUSER000000000000000001",
            "is_active": True,
            "row_version": 2,
            "archived_at": "2026-04-26T18:53:34+00:00",
            "created_at": "2026-04-25T12:00:00+00:00",
            "updated_at": "2026-04-26T18:53:34+00:00",
        }
        mock_service = MagicMock()
        mock_service.archive_strategy.return_value = archived_dict
        set_strategy_service(mock_service)
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/strategies/01HSRC0000000000000000001/archive",
                headers=auth_headers_strategies,
            )
            assert response.status_code == 200
            body = response.json()
            assert body["strategy"]["id"] == "01HSRC0000000000000000001"
            assert body["strategy"]["archived_at"] == "2026-04-26T18:53:34+00:00"
            assert body["strategy"]["row_version"] == 2

            # Service was called with the path id and the operator's user_id.
            mock_service.archive_strategy.assert_called_once_with(
                "01HSRC0000000000000000001",
                requested_by=mock_authenticated_user.user_id,
            )
        finally:
            app.dependency_overrides.clear()
            set_strategy_service(None)

    def test_archive_unknown_strategy_returns_404(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """NotFoundError from the service maps to HTTP 404."""
        from libs.contracts.errors import NotFoundError

        mock_service = MagicMock()
        mock_service.archive_strategy.side_effect = NotFoundError(
            "Strategy 01HMISSING0000000000000001 not found"
        )
        set_strategy_service(mock_service)
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/strategies/01HMISSING0000000000000001/archive",
                headers=auth_headers_strategies,
            )
            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()
            set_strategy_service(None)

    def test_archive_already_archived_returns_409(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """StrategyArchiveStateError maps to HTTP 409 with detail."""
        from libs.contracts.errors import StrategyArchiveStateError

        mock_service = MagicMock()
        mock_service.archive_strategy.side_effect = StrategyArchiveStateError(
            "Strategy 01HSRC0000000000000000001 is already archived",
            strategy_id="01HSRC0000000000000000001",
            current_state="archived",
        )
        set_strategy_service(mock_service)
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/strategies/01HSRC0000000000000000001/archive",
                headers=auth_headers_strategies,
            )
            assert response.status_code == 409
            assert "already archived" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()
            set_strategy_service(None)

    def test_archive_missing_auth_returns_401(self, client: TestClient) -> None:
        """No Authorization header → 401."""
        response = client.post("/strategies/01HSRC0000000000000000001/archive")
        assert response.status_code == 401

    def test_archive_insufficient_scope_returns_403(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
    ) -> None:
        """User lacking strategies:write scope is rejected with 403."""
        viewer = AuthenticatedUser(
            user_id="01HVEWR00000000000000000A2",
            role="viewer",
            email="viewer@fxlab.test",
            scopes=["audit:read"],
        )
        app.dependency_overrides[get_current_user] = lambda: viewer
        try:
            response = client.post(
                "/strategies/01HSRC0000000000000000001/archive",
                headers=auth_headers_strategies,
            )
            assert response.status_code == 403
        finally:
            app.dependency_overrides.clear()


class TestRestoreStrategyRoute:
    """Tests for POST /strategies/{strategy_id}/restore."""

    def test_restore_happy_path_returns_200_with_cleared_archived_at(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """Restore returns 200 with archived_at == null."""
        restored_dict = {
            "id": "01HSRC0000000000000000001",
            "name": "Bollinger",
            "code": "{}",
            "version": "0.1.0",
            "source": "draft_form",
            "created_by": "01HUSER000000000000000001",
            "is_active": True,
            "row_version": 3,
            "archived_at": None,
            "created_at": "2026-04-25T12:00:00+00:00",
            "updated_at": "2026-04-26T19:00:00+00:00",
        }
        mock_service = MagicMock()
        mock_service.restore_strategy.return_value = restored_dict
        set_strategy_service(mock_service)
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/strategies/01HSRC0000000000000000001/restore",
                headers=auth_headers_strategies,
            )
            assert response.status_code == 200
            body = response.json()
            assert body["strategy"]["archived_at"] is None
            assert body["strategy"]["row_version"] == 3

            mock_service.restore_strategy.assert_called_once_with(
                "01HSRC0000000000000000001",
                requested_by=mock_authenticated_user.user_id,
            )
        finally:
            app.dependency_overrides.clear()
            set_strategy_service(None)

    def test_restore_unknown_strategy_returns_404(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """NotFoundError → 404."""
        from libs.contracts.errors import NotFoundError

        mock_service = MagicMock()
        mock_service.restore_strategy.side_effect = NotFoundError(
            "Strategy 01HMISSING0000000000000001 not found"
        )
        set_strategy_service(mock_service)
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/strategies/01HMISSING0000000000000001/restore",
                headers=auth_headers_strategies,
            )
            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()
            set_strategy_service(None)

    def test_restore_when_not_archived_returns_409(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """Restore on an active row → 409."""
        from libs.contracts.errors import StrategyArchiveStateError

        mock_service = MagicMock()
        mock_service.restore_strategy.side_effect = StrategyArchiveStateError(
            "Strategy 01HSRC0000000000000000001 is not archived",
            strategy_id="01HSRC0000000000000000001",
            current_state="active",
        )
        set_strategy_service(mock_service)
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.post(
                "/strategies/01HSRC0000000000000000001/restore",
                headers=auth_headers_strategies,
            )
            assert response.status_code == 409
            assert "not archived" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()
            set_strategy_service(None)

    def test_restore_missing_auth_returns_401(self, client: TestClient) -> None:
        """No Authorization header → 401."""
        response = client.post("/strategies/01HSRC0000000000000000001/restore")
        assert response.status_code == 401

    def test_restore_insufficient_scope_returns_403(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
    ) -> None:
        """User lacking strategies:write scope → 403."""
        viewer = AuthenticatedUser(
            user_id="01HVEWR00000000000000000A2",
            role="viewer",
            email="viewer@fxlab.test",
            scopes=["audit:read"],
        )
        app.dependency_overrides[get_current_user] = lambda: viewer
        try:
            response = client.post(
                "/strategies/01HSRC0000000000000000001/restore",
                headers=auth_headers_strategies,
            )
            assert response.status_code == 403
        finally:
            app.dependency_overrides.clear()


class TestListStrategiesIncludeArchivedQuery:
    """Verify the ``include_archived`` query parameter plumbs to the service."""

    def test_list_default_passes_include_archived_false_to_service(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """No query param → service called with include_archived=False."""
        mock_service = MagicMock()
        mock_service.list_strategies.return_value = {
            "strategies": [],
            "limit": 50,
            "offset": 0,
            "count": 0,
        }
        set_strategy_service(mock_service)
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.get("/strategies/", headers=auth_headers_strategies)
            assert response.status_code == 200
            kwargs = mock_service.list_strategies.call_args.kwargs
            assert kwargs["include_archived"] is False
        finally:
            app.dependency_overrides.clear()
            set_strategy_service(None)

    def test_list_with_include_archived_true_passes_through(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """?include_archived=true plumbs through to the service kwarg."""
        mock_service = MagicMock()
        mock_service.list_strategies.return_value = {
            "strategies": [],
            "limit": 50,
            "offset": 0,
            "count": 0,
        }
        set_strategy_service(mock_service)
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.get(
                "/strategies/?include_archived=true",
                headers=auth_headers_strategies,
            )
            assert response.status_code == 200
            kwargs = mock_service.list_strategies.call_args.kwargs
            assert kwargs["include_archived"] is True
        finally:
            app.dependency_overrides.clear()
            set_strategy_service(None)

    def test_list_paged_passes_include_archived_to_service(
        self,
        client: TestClient,
        auth_headers_strategies: dict[str, str],
        mock_authenticated_user: AuthenticatedUser,
    ) -> None:
        """The M2.D5 paginated envelope honours include_archived too."""
        # Build a minimal StrategyListPage stand-in via MagicMock since the
        # route only calls model_dump on it.
        page_obj = MagicMock()
        page_obj.model_dump.return_value = {
            "strategies": [],
            "page": 1,
            "page_size": 20,
            "total_count": 0,
            "total_pages": 0,
        }
        mock_service = MagicMock()
        mock_service.list_strategies_page.return_value = page_obj
        set_strategy_service(mock_service)
        app.dependency_overrides[get_current_user] = lambda: mock_authenticated_user

        try:
            response = client.get(
                "/strategies/?page=1&page_size=20&include_archived=true",
                headers=auth_headers_strategies,
            )
            assert response.status_code == 200
            kwargs = mock_service.list_strategies_page.call_args.kwargs
            assert kwargs["include_archived"] is True
        finally:
            app.dependency_overrides.clear()
            set_strategy_service(None)
