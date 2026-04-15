"""
Unit tests for position sizing API endpoints.

Validates HTTP routing, authentication, scope enforcement, response
serialization, and error handling. Uses a mock PositionSizingService.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest

from libs.contracts.errors import ValidationError
from libs.contracts.position_sizing import SizingMethod, SizingResult
from services.api.auth import ROLE_SCOPES, AuthenticatedUser

# ---------------------------------------------------------------------------
# Fake users
# ---------------------------------------------------------------------------

_OPERATOR_USER = AuthenticatedUser(
    user_id="01HTESTFAKE000000000000000",
    role="operator",
    email="operator@fxlab.test",
    scopes=ROLE_SCOPES["operator"],
)


# ---------------------------------------------------------------------------
# Mock service
# ---------------------------------------------------------------------------


class MockPositionSizingService:
    """In-memory mock for route testing."""

    def __init__(self) -> None:
        self._result: SizingResult | None = None
        self._raise_validation: str | None = None

    def set_result(self, result: SizingResult) -> None:
        self._result = result

    def set_raise_validation(self, msg: str) -> None:
        self._raise_validation = msg

    def compute_size(self, request: Any) -> SizingResult:
        if self._raise_validation:
            raise ValidationError(self._raise_validation)
        return self._result or SizingResult(
            recommended_quantity=Decimal("100"),
            recommended_value=Decimal("17500.00"),
            stop_loss_price=Decimal("165.00"),
            risk_amount=Decimal("2000.00"),
            method_used=SizingMethod.ATR_BASED,
            reasoning="ATR-based: test computation",
            was_capped=False,
        )

    def get_available_methods(self) -> list[SizingMethod]:
        return list(SizingMethod)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sizing_env():
    env_vars = {
        "ENVIRONMENT": "test",
        "DATABASE_URL": "sqlite:///:memory:",
        "JWT_SECRET_KEY": "test-secret-key-not-for-production-32bytes!!",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        from services.api.main import app
        from services.api.routes.position_sizing import get_position_sizing_service

        mock_service = MockPositionSizingService()
        app.dependency_overrides[get_position_sizing_service] = lambda: mock_service

        try:
            from fastapi.testclient import TestClient

            client = TestClient(app, raise_server_exceptions=False)
            yield client, mock_service, app
        finally:
            app.dependency_overrides.pop(get_position_sizing_service, None)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer TEST_TOKEN"}


def _override_auth(app: Any, user: AuthenticatedUser = _OPERATOR_USER) -> None:
    from services.api.auth import get_current_user

    async def _fake() -> AuthenticatedUser:
        return user

    app.dependency_overrides[get_current_user] = _fake


# ---------------------------------------------------------------------------
# POST /risk/position-size
# ---------------------------------------------------------------------------


class TestComputePositionSize:
    """Tests for POST /risk/position-size."""

    def test_returns_200_with_atr_based_result(self, sizing_env: Any) -> None:
        client, _, app = sizing_env
        _override_auth(app)

        resp = client.post(
            "/risk/position-size",
            json={
                "symbol": "AAPL",
                "side": "buy",
                "method": "atr_based",
                "risk_per_trade_pct": "2.0",
                "account_equity": "100000",
                "current_price": "175.00",
                "atr_value": "3.50",
                "atr_multiplier": "2.0",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "recommended_quantity" in data
        assert "recommended_value" in data
        assert "method_used" in data
        assert "reasoning" in data

    def test_returns_200_with_kelly_result(self, sizing_env: Any) -> None:
        client, mock_service, app = sizing_env
        _override_auth(app)

        mock_service.set_result(
            SizingResult(
                recommended_quantity=Decimal("200"),
                recommended_value=Decimal("20000.00"),
                risk_amount=Decimal("20000.00"),
                method_used=SizingMethod.KELLY,
                reasoning="Kelly: W=0.6, R=2.0, f*=0.4000, half-Kelly=0.200000",
                was_capped=False,
            )
        )

        resp = client.post(
            "/risk/position-size",
            json={
                "symbol": "AAPL",
                "side": "buy",
                "method": "kelly",
                "account_equity": "100000",
                "current_price": "100.00",
                "win_rate": "0.6",
                "avg_win_loss_ratio": "2.0",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["method_used"] == "kelly"
        assert data["recommended_quantity"] == "200"

    def test_returns_400_for_unknown_method(self, sizing_env: Any) -> None:
        client, _, app = sizing_env
        _override_auth(app)

        resp = client.post(
            "/risk/position-size",
            json={
                "symbol": "AAPL",
                "side": "buy",
                "method": "nonexistent_method",
                "account_equity": "100000",
                "current_price": "175.00",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 400
        data = resp.json()
        assert "Unknown method" in data["detail"]

    def test_returns_400_for_validation_error(self, sizing_env: Any) -> None:
        client, mock_service, app = sizing_env
        _override_auth(app)
        mock_service.set_raise_validation("ATR_BASED method requires atr_value > 0")

        resp = client.post(
            "/risk/position-size",
            json={
                "symbol": "AAPL",
                "side": "buy",
                "method": "atr_based",
                "account_equity": "100000",
                "current_price": "175.00",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 400
        assert "atr_value" in resp.json()["detail"]

    def test_returns_capped_result(self, sizing_env: Any) -> None:
        client, mock_service, app = sizing_env
        _override_auth(app)

        mock_service.set_result(
            SizingResult(
                recommended_quantity=Decimal("100"),
                recommended_value=Decimal("17500.00"),
                risk_amount=Decimal("2000.00"),
                method_used=SizingMethod.ATR_BASED,
                reasoning="ATR-based: capped from 500 to 100",
                was_capped=True,
            )
        )

        resp = client.post(
            "/risk/position-size",
            json={
                "symbol": "AAPL",
                "side": "buy",
                "method": "atr_based",
                "account_equity": "100000",
                "current_price": "175.00",
                "atr_value": "1.00",
                "max_position_size": "100",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["was_capped"] is True

    def test_requires_auth(self, sizing_env: Any) -> None:
        client, _, app = sizing_env
        app.dependency_overrides.clear()

        resp = client.post(
            "/risk/position-size",
            json={
                "symbol": "AAPL",
                "side": "buy",
                "method": "fixed",
                "account_equity": "100000",
            },
        )
        assert resp.status_code in (401, 403, 422)

    def test_rejects_invalid_side(self, sizing_env: Any) -> None:
        client, _, app = sizing_env
        _override_auth(app)

        resp = client.post(
            "/risk/position-size",
            json={
                "symbol": "AAPL",
                "side": "hold",
                "method": "fixed",
                "account_equity": "100000",
            },
            headers=_auth_headers(),
        )

        # Pydantic validation rejects invalid side
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /risk/position-size/methods
# ---------------------------------------------------------------------------


class TestListMethods:
    """Tests for GET /risk/position-size/methods."""

    def test_returns_200_with_all_methods(self, sizing_env: Any) -> None:
        client, _, app = sizing_env
        _override_auth(app)

        resp = client.get("/risk/position-size/methods", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 5
        assert len(data["methods"]) == 5

    def test_methods_have_required_fields(self, sizing_env: Any) -> None:
        client, _, app = sizing_env
        _override_auth(app)

        resp = client.get("/risk/position-size/methods", headers=_auth_headers())

        for method in resp.json()["methods"]:
            assert "name" in method
            assert "description" in method

    def test_methods_include_all_sizing_types(self, sizing_env: Any) -> None:
        client, _, app = sizing_env
        _override_auth(app)

        resp = client.get("/risk/position-size/methods", headers=_auth_headers())

        method_names = {m["name"] for m in resp.json()["methods"]}
        expected = {"fixed", "atr_based", "kelly", "risk_parity", "equal_weight"}
        assert method_names == expected

    def test_requires_auth(self, sizing_env: Any) -> None:
        client, _, app = sizing_env
        app.dependency_overrides.clear()

        resp = client.get("/risk/position-size/methods")
        assert resp.status_code in (401, 403, 422)
