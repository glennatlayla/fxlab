"""
Unit tests for indicator REST API endpoints.

Validates HTTP routing, authentication, scope enforcement, response
serialization, and error handling. Uses mock service to isolate from
database and indicator engine internals.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest

from libs.contracts.market_data import (
    Candle,
    CandleInterval,
    MarketDataPage,
)
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

_VIEWER_USER = AuthenticatedUser(
    user_id="01HTESTFAKE000000000000000",
    role="viewer",
    email="viewer@fxlab.test",
    scopes=ROLE_SCOPES["viewer"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_TS = datetime(2026, 1, 2, 14, 30, 0, tzinfo=timezone.utc)


def _make_candles(n: int = 5) -> list[Candle]:
    """Create n candles with ascending prices."""
    return [
        Candle(
            symbol="AAPL",
            interval=CandleInterval.D1,
            open=Decimal(f"{100 + i}.00"),
            high=Decimal(f"{102 + i}.00"),
            low=Decimal(f"{99 + i}.00"),
            close=Decimal(f"{101 + i}.00"),
            volume=1_000_000,
            timestamp=datetime(2026, 1, 2 + i, 14, 30, 0, tzinfo=timezone.utc),
        )
        for i in range(n)
    ]


class MockMarketDataRepoForIndicators:
    """Simplified mock repository for indicator route tests."""

    def __init__(self) -> None:
        self._candles: list[Candle] = []

    def set_candles(self, candles: list[Candle]) -> None:
        self._candles = candles

    def query_candles(self, query: Any) -> MarketDataPage:
        return MarketDataPage(
            candles=self._candles,
            total_count=len(self._candles),
            has_more=False,
            next_cursor=None,
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def indicator_test_env():
    """
    Set up test app with indicator routes wired to mock repository.

    Yields (client, mock_repo, app) tuple.
    """
    env_vars = {
        "ENVIRONMENT": "test",
        "DATABASE_URL": "sqlite:///:memory:",
        "JWT_SECRET_KEY": "test-secret-key-not-for-production-32bytes!!",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        from libs.indicators import default_engine
        from services.api.main import app
        from services.api.routes.indicators import get_indicator_service
        from services.api.services.indicator_service import IndicatorService

        mock_repo = MockMarketDataRepoForIndicators()
        service = IndicatorService(engine=default_engine, market_data_repo=mock_repo)

        app.dependency_overrides[get_indicator_service] = lambda: service

        try:
            from fastapi.testclient import TestClient

            client = TestClient(app, raise_server_exceptions=False)
            yield client, mock_repo, app
        finally:
            # Clean up ALL overrides this test module may have added,
            # not just the indicator service.  _override_auth() sets
            # get_current_user on the shared app instance; leaving it
            # behind pollutes subsequent test modules that rely on the
            # real auth path (e.g. TEST_TOKEN bypass).
            from services.api.auth import get_current_user

            app.dependency_overrides.pop(get_indicator_service, None)
            app.dependency_overrides.pop(get_current_user, None)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer TEST_TOKEN"}


def _override_auth(app: Any, user: AuthenticatedUser = _OPERATOR_USER) -> None:
    from services.api.auth import get_current_user

    async def _fake() -> AuthenticatedUser:
        return user

    app.dependency_overrides[get_current_user] = _fake


# ---------------------------------------------------------------------------
# GET /indicators
# ---------------------------------------------------------------------------


class TestListIndicators:
    """Tests for GET /indicators."""

    def test_returns_200_with_indicator_list(self, indicator_test_env: Any) -> None:
        client, _, app = indicator_test_env
        _override_auth(app)

        resp = client.get("/indicators", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 24  # M5 + M6 indicators
        assert len(data["indicators"]) == data["count"]

    def test_indicators_have_required_fields(self, indicator_test_env: Any) -> None:
        client, _, app = indicator_test_env
        _override_auth(app)

        resp = client.get("/indicators", headers=_auth_headers())
        data = resp.json()
        for ind in data["indicators"]:
            assert "name" in ind
            assert "description" in ind
            assert "category" in ind
            assert "default_params" in ind

    def test_requires_auth(self, indicator_test_env: Any) -> None:
        client, _, app = indicator_test_env
        app.dependency_overrides.clear()

        resp = client.get("/indicators")
        assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# GET /indicators/{name}/info
# ---------------------------------------------------------------------------


class TestGetIndicatorInfo:
    """Tests for GET /indicators/{name}/info."""

    def test_returns_200_for_known_indicator(self, indicator_test_env: Any) -> None:
        client, _, app = indicator_test_env
        _override_auth(app)

        resp = client.get("/indicators/SMA/info", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()["indicator"]
        assert data["name"] == "SMA"
        assert data["category"] == "trend"

    def test_case_insensitive_lookup(self, indicator_test_env: Any) -> None:
        client, _, app = indicator_test_env
        _override_auth(app)

        resp = client.get("/indicators/sma/info", headers=_auth_headers())
        assert resp.status_code == 200

    def test_returns_404_for_unknown_indicator(self, indicator_test_env: Any) -> None:
        client, _, app = indicator_test_env
        _override_auth(app)

        resp = client.get("/indicators/NONEXISTENT/info", headers=_auth_headers())
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /indicators/compute
# ---------------------------------------------------------------------------


class TestComputeIndicators:
    """Tests for POST /indicators/compute."""

    def test_compute_single_indicator(self, indicator_test_env: Any) -> None:
        client, mock_repo, app = indicator_test_env
        _override_auth(app)
        mock_repo.set_candles(_make_candles(30))

        resp = client.post(
            "/indicators/compute",
            json={
                "symbol": "AAPL",
                "interval": "1d",
                "indicators": [{"name": "SMA", "params": {"period": 5}}],
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "AAPL"
        assert data["interval"] == "1d"
        assert data["indicator_count"] == 1
        assert "SMA" in data["results"]

    def test_compute_multiple_indicators(self, indicator_test_env: Any) -> None:
        client, mock_repo, app = indicator_test_env
        _override_auth(app)
        mock_repo.set_candles(_make_candles(30))

        resp = client.post(
            "/indicators/compute",
            json={
                "symbol": "AAPL",
                "interval": "1d",
                "indicators": [
                    {"name": "SMA", "params": {"period": 5}},
                    {"name": "RSI", "params": {"period": 14}},
                ],
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["indicator_count"] == 2
        assert "SMA" in data["results"]
        assert "RSI" in data["results"]

    def test_compute_result_has_values_and_timestamps(self, indicator_test_env: Any) -> None:
        client, mock_repo, app = indicator_test_env
        _override_auth(app)
        mock_repo.set_candles(_make_candles(10))

        resp = client.post(
            "/indicators/compute",
            json={
                "symbol": "AAPL",
                "interval": "1d",
                "indicators": [{"name": "SMA", "params": {"period": 3}}],
            },
            headers=_auth_headers(),
        )

        data = resp.json()
        sma_result = data["results"]["SMA"]
        assert "values" in sma_result
        assert "timestamps" in sma_result
        assert len(sma_result["values"]) == 10
        assert len(sma_result["timestamps"]) == 10

    def test_compute_nan_serialized_as_null(self, indicator_test_env: Any) -> None:
        client, mock_repo, app = indicator_test_env
        _override_auth(app)
        mock_repo.set_candles(_make_candles(10))

        resp = client.post(
            "/indicators/compute",
            json={
                "symbol": "AAPL",
                "interval": "1d",
                "indicators": [{"name": "SMA", "params": {"period": 5}}],
            },
            headers=_auth_headers(),
        )

        data = resp.json()
        values = data["results"]["SMA"]["values"]
        # First 4 values should be None (NaN → null for period=5)
        assert values[0] is None
        assert values[3] is None
        # 5th value should be a number
        assert isinstance(values[4], (int, float))

    def test_compute_multi_output_indicator(self, indicator_test_env: Any) -> None:
        client, mock_repo, app = indicator_test_env
        _override_auth(app)
        mock_repo.set_candles(_make_candles(30))

        resp = client.post(
            "/indicators/compute",
            json={
                "symbol": "AAPL",
                "interval": "1d",
                "indicators": [
                    {
                        "name": "MACD",
                        "params": {"fast_period": 5, "slow_period": 10, "signal_period": 3},
                    }
                ],
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        macd = resp.json()["results"]["MACD"]
        assert macd["values"] is None  # Multi-output → values is None
        assert "macd_line" in macd["components"]
        assert "signal_line" in macd["components"]
        assert "histogram" in macd["components"]

    def test_compute_returns_400_for_invalid_interval(self, indicator_test_env: Any) -> None:
        client, _, app = indicator_test_env
        _override_auth(app)

        resp = client.post(
            "/indicators/compute",
            json={
                "symbol": "AAPL",
                "interval": "bad",
                "indicators": [{"name": "SMA"}],
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 400
        assert "Invalid interval" in resp.json()["detail"]

    def test_compute_returns_400_for_unknown_indicator(self, indicator_test_env: Any) -> None:
        client, mock_repo, app = indicator_test_env
        _override_auth(app)
        mock_repo.set_candles(_make_candles(10))

        resp = client.post(
            "/indicators/compute",
            json={
                "symbol": "AAPL",
                "interval": "1d",
                "indicators": [{"name": "NONEXISTENT"}],
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 400

    def test_compute_returns_404_when_no_candle_data(self, indicator_test_env: Any) -> None:
        client, _, app = indicator_test_env
        _override_auth(app)
        # mock_repo has no candles by default

        resp = client.post(
            "/indicators/compute",
            json={
                "symbol": "AAPL",
                "interval": "1d",
                "indicators": [{"name": "SMA", "params": {"period": 5}}],
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 404

    def test_viewer_can_compute(self, indicator_test_env: Any) -> None:
        """Viewer role has feeds:read scope and can compute indicators."""
        client, mock_repo, app = indicator_test_env
        _override_auth(app, _VIEWER_USER)
        mock_repo.set_candles(_make_candles(10))

        resp = client.post(
            "/indicators/compute",
            json={
                "symbol": "AAPL",
                "interval": "1d",
                "indicators": [{"name": "SMA", "params": {"period": 3}}],
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
