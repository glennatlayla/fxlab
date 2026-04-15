"""
Tests for strategy routes (POST /strategies, GET /strategies/{id}, POST /strategies/validate-dsl).

Verifies:
- Strategy creation returns 201 with validation metadata.
- DSL validation errors return 422.
- Strategy retrieval by ID returns parsed code.
- 404 on nonexistent strategy.
- Authentication enforcement on all endpoints.
- DSL validation endpoint returns structured results.
- List strategies with pagination.

Example:
    pytest tests/unit/test_strategy_routes.py -v
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from services.api.auth import ROLE_SCOPES, AuthenticatedUser

# ---------------------------------------------------------------------------
# Environment setup — must happen before app import
# ---------------------------------------------------------------------------

os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-for-strategy-routes")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")

from services.api.main import app  # noqa: E402
from services.api.routes.strategies import set_strategy_service  # noqa: E402

# ---------------------------------------------------------------------------
# Mock service
# ---------------------------------------------------------------------------


class MockStrategyService:
    """
    Mock StrategyService for route testing.

    Configurable error injection for testing error responses.

    Attributes:
        raise_validation: If set, create_strategy raises ValidationError.
        raise_not_found: If set, get_strategy raises NotFoundError.
    """

    def __init__(self) -> None:
        self.raise_validation: str | None = None
        self.raise_not_found: bool = False
        self._strategies: list[dict] = []

    def create_strategy(self, **kwargs) -> dict:
        from libs.contracts.errors import ValidationError

        if self.raise_validation:
            raise ValidationError(self.raise_validation)

        strategy = {
            "id": "01HSTRAT0000000000000001",
            "name": kwargs["name"],
            "code": "{}",
            "version": "0.1.0",
            "created_by": kwargs["created_by"],
            "is_active": True,
            "row_version": 1,
            "created_at": "2026-04-12T14:00:00+00:00",
            "updated_at": "2026-04-12T14:00:00+00:00",
        }
        self._strategies.append(strategy)

        return {
            "strategy": strategy,
            "entry_validation": {
                "is_valid": True,
                "errors": [],
                "indicators_used": ["RSI"],
                "variables_used": [],
            },
            "exit_validation": {
                "is_valid": True,
                "errors": [],
                "indicators_used": ["RSI"],
                "variables_used": [],
            },
            "indicators_used": ["RSI"],
            "variables_used": ["price"],
        }

    def get_strategy(self, strategy_id: str) -> dict:
        from libs.contracts.errors import NotFoundError

        if self.raise_not_found:
            raise NotFoundError(f"Strategy {strategy_id} not found")

        return {
            "id": strategy_id,
            "name": "Test Strategy",
            "code": '{"entry_condition": "RSI(14) < 30"}',
            "version": "0.1.0",
            "created_by": "01HTESTFAKE000000000000000",
            "is_active": True,
            "parsed_code": {"entry_condition": "RSI(14) < 30"},
            "created_at": "2026-04-12T14:00:00+00:00",
            "updated_at": "2026-04-12T14:00:00+00:00",
        }

    def list_strategies(self, **kwargs) -> dict:
        return {
            "strategies": self._strategies,
            "limit": kwargs.get("limit", 50),
            "offset": kwargs.get("offset", 0),
            "count": len(self._strategies),
        }

    def validate_dsl_expression(self, expression: str) -> dict:
        if not expression or not expression.strip():
            return {
                "is_valid": False,
                "errors": [
                    {"message": "Empty expression", "line": 1, "column": 1, "suggestion": None}
                ],
                "indicators_used": [],
                "variables_used": [],
            }
        return {
            "is_valid": True,
            "errors": [],
            "indicators_used": ["RSI"],
            "variables_used": ["price"],
        }


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

_OPERATOR_USER = AuthenticatedUser(
    user_id="01HTESTFAKE000000000000000",
    email="trader@fxlab.test",
    role="operator",
    scopes=ROLE_SCOPES.get("operator", set()),
)


def _auth_headers() -> dict[str, str]:
    """Authorization headers using a test token."""
    return {"Authorization": "Bearer TEST_TOKEN"}


def _override_auth(application: Any) -> None:
    """Override get_current_user to return a test operator user."""
    from services.api.auth import get_current_user

    async def _fake_get_current_user() -> AuthenticatedUser:
        return _OPERATOR_USER

    application.dependency_overrides[get_current_user] = _fake_get_current_user


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def strategy_test_env():
    """
    Set up a TestClient with mock StrategyService and auth override.

    Yields:
        Tuple of (TestClient, MockStrategyService, app).
    """
    mock_service = MockStrategyService()
    set_strategy_service(mock_service)
    _override_auth(app)

    client = TestClient(app)
    yield client, mock_service, app

    app.dependency_overrides.clear()
    set_strategy_service(None)


# ---------------------------------------------------------------------------
# Tests: POST /strategies
# ---------------------------------------------------------------------------


class TestCreateStrategyRoute:
    """Tests for POST /strategies."""

    def test_create_strategy_returns_201(self, strategy_test_env) -> None:
        """Valid creation returns 201 with strategy and validation metadata."""
        client, _, _app = strategy_test_env

        resp = client.post(
            "/strategies/",
            json={
                "name": "RSI Reversal",
                "entry_condition": "RSI(14) < 30",
                "exit_condition": "RSI(14) > 70",
                "instrument": "AAPL",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["strategy"]["name"] == "RSI Reversal"
        assert data["entry_validation"]["is_valid"] is True
        assert "RSI" in data["indicators_used"]

    def test_create_strategy_dsl_error_returns_422(self, strategy_test_env) -> None:
        """Invalid DSL should return 422."""
        client, mock_service, _ = strategy_test_env
        mock_service.raise_validation = "Entry condition: RSI requires 1 argument"

        resp = client.post(
            "/strategies/",
            json={
                "name": "Bad Strategy",
                "entry_condition": "RSI() < 30",
                "exit_condition": "RSI(14) > 70",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 422

    def test_create_strategy_missing_name_returns_422(self, strategy_test_env) -> None:
        """Missing name should return 422 from Pydantic validation."""
        client, _, _ = strategy_test_env

        resp = client.post(
            "/strategies/",
            json={
                "entry_condition": "RSI(14) < 30",
                "exit_condition": "RSI(14) > 70",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 422

    def test_create_strategy_requires_auth(self, strategy_test_env) -> None:
        """Request without auth should be rejected."""
        client, _, _app = strategy_test_env
        _app.dependency_overrides.clear()

        resp = client.post(
            "/strategies/",
            json={
                "name": "No Auth",
                "entry_condition": "RSI(14) < 30",
                "exit_condition": "RSI(14) > 70",
            },
        )

        assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# Tests: GET /strategies/{id}
# ---------------------------------------------------------------------------


class TestGetStrategyRoute:
    """Tests for GET /strategies/{id}."""

    def test_get_strategy_returns_200(self, strategy_test_env) -> None:
        """Existing strategy returns 200 with parsed code."""
        client, _, _ = strategy_test_env

        resp = client.get("/strategies/01HSTRAT0000000000000001", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Strategy"
        assert "parsed_code" in data

    def test_get_strategy_not_found_returns_404(self, strategy_test_env) -> None:
        """Nonexistent strategy returns 404."""
        client, mock_service, _ = strategy_test_env
        mock_service.raise_not_found = True

        resp = client.get("/strategies/01HNONEXISTENT0000000000", headers=_auth_headers())

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: POST /strategies/validate-dsl
# ---------------------------------------------------------------------------


class TestValidateDslRoute:
    """Tests for POST /strategies/validate-dsl."""

    def test_validate_valid_dsl(self, strategy_test_env) -> None:
        """Valid DSL returns is_valid=True."""
        client, _, _ = strategy_test_env

        resp = client.post(
            "/strategies/validate-dsl",
            json={
                "expression": "RSI(14) < 30 AND price > SMA(200)",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_valid"] is True

    def test_validate_empty_dsl(self, strategy_test_env) -> None:
        """Empty DSL returns is_valid=False with errors."""
        client, _, _ = strategy_test_env

        resp = client.post(
            "/strategies/validate-dsl",
            json={
                "expression": "",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_valid"] is False
        assert len(data["errors"]) > 0

    def test_validate_dsl_returns_indicators(self, strategy_test_env) -> None:
        """Validation result should include detected indicators."""
        client, _, _ = strategy_test_env

        resp = client.post(
            "/strategies/validate-dsl",
            json={
                "expression": "RSI(14) < 30",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "RSI" in data["indicators_used"]


# ---------------------------------------------------------------------------
# Tests: GET /strategies/ (list)
# ---------------------------------------------------------------------------


class TestListStrategiesRoute:
    """Tests for GET /strategies/."""

    def test_list_empty(self, strategy_test_env) -> None:
        """Empty list returns count 0."""
        client, _, _ = strategy_test_env

        resp = client.get("/strategies/", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    def test_list_after_create(self, strategy_test_env) -> None:
        """After creating a strategy, list should include it."""
        client, _, _ = strategy_test_env

        client.post(
            "/strategies/",
            json={
                "name": "Listed Strategy",
                "entry_condition": "RSI(14) < 30",
                "exit_condition": "RSI(14) > 70",
            },
            headers=_auth_headers(),
        )

        resp = client.get("/strategies/", headers=_auth_headers())
        data = resp.json()
        assert data["count"] == 1
