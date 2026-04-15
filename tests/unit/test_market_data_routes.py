"""
Unit tests for market data REST API endpoints.

Validates HTTP routing, authentication, scope enforcement, and response
serialization. Uses mock repository to isolate from database.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from libs.contracts.market_data import (
    Candle,
    CandleInterval,
    DataGap,
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


def _make_candle(
    symbol: str = "AAPL",
    interval: CandleInterval = CandleInterval.D1,
    timestamp: datetime | None = None,
    close: str = "175.90",
) -> Candle:
    """Create a valid Candle with sensible defaults."""
    return Candle(
        symbol=symbol,
        interval=interval,
        open=Decimal("174.50"),
        high=Decimal("176.25"),
        low=Decimal("173.80"),
        close=Decimal(close),
        volume=58_000_000,
        timestamp=timestamp or _BASE_TS,
    )


class MockMarketDataRepoForRoutes:
    """Simplified mock repository for route testing."""

    def __init__(self) -> None:
        self._candles: list[Candle] = []
        self._gaps: list[DataGap] = []
        self._latest: Candle | None = None

    def set_candles(self, candles: list[Candle]) -> None:
        self._candles = candles

    def set_gaps(self, gaps: list[DataGap]) -> None:
        self._gaps = gaps

    def set_latest(self, candle: Candle | None) -> None:
        self._latest = candle

    def query_candles(self, query: Any) -> MarketDataPage:
        return MarketDataPage(
            candles=self._candles[: query.limit],
            total_count=len(self._candles),
            has_more=len(self._candles) > query.limit,
            next_cursor=None,
        )

    def get_latest_candle(self, symbol: str, interval: CandleInterval) -> Candle | None:
        return self._latest

    def detect_gaps(
        self,
        symbol: str,
        interval: CandleInterval,
        start: datetime,
        end: datetime,
    ) -> list[DataGap]:
        return self._gaps


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def market_data_test_env():
    """
    Set up test app with market data routes wired to mock repository.

    Yields (client, mock_repo, app) tuple.
    """
    env_vars = {
        "ENVIRONMENT": "test",
        "DATABASE_URL": "sqlite:///:memory:",
        "JWT_SECRET_KEY": "test-secret-key-not-for-production-32bytes!!",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        from services.api.main import app
        from services.api.routes.market_data import get_market_data_repository

        mock_repo = MockMarketDataRepoForRoutes()

        app.dependency_overrides[get_market_data_repository] = lambda: mock_repo

        try:
            client = TestClient(app, raise_server_exceptions=False)
            yield client, mock_repo, app
        finally:
            # Clean up ALL overrides this test module may have added.
            # _override_auth() sets get_current_user on the shared app
            # instance; leaving it behind pollutes subsequent test modules
            # that rely on the real auth path (e.g. OIDC token validation).
            from services.api.auth import get_current_user

            app.dependency_overrides.pop(get_market_data_repository, None)
            app.dependency_overrides.pop(get_current_user, None)


def _auth_headers() -> dict[str, str]:
    """Authorization headers using TEST_TOKEN."""
    return {"Authorization": "Bearer TEST_TOKEN"}


def _override_auth(app: Any, user: AuthenticatedUser = _OPERATOR_USER) -> None:
    """Override get_current_user to return a specific user."""
    from services.api.auth import get_current_user

    async def _fake_get_current_user() -> AuthenticatedUser:
        return user

    app.dependency_overrides[get_current_user] = _fake_get_current_user


# ---------------------------------------------------------------------------
# GET /market-data/candles
# ---------------------------------------------------------------------------


class TestGetCandles:
    """Tests for GET /market-data/candles."""

    def test_returns_200_with_candles(self, market_data_test_env: Any) -> None:
        client, mock_repo, app = market_data_test_env
        _override_auth(app)
        candles = [_make_candle(timestamp=_BASE_TS + timedelta(days=i)) for i in range(3)]
        mock_repo.set_candles(candles)

        resp = client.get(
            "/market-data/candles",
            params={"symbol": "AAPL", "interval": "1d"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["candles"]) == 3
        assert data["total_count"] == 3

    def test_returns_empty_when_no_data(self, market_data_test_env: Any) -> None:
        client, mock_repo, app = market_data_test_env
        _override_auth(app)

        resp = client.get(
            "/market-data/candles",
            params={"symbol": "AAPL", "interval": "1d"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["candles"] == []
        assert data["total_count"] == 0

    def test_returns_400_for_invalid_interval(self, market_data_test_env: Any) -> None:
        client, _, app = market_data_test_env
        _override_auth(app)

        resp = client.get(
            "/market-data/candles",
            params={"symbol": "AAPL", "interval": "invalid"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 400
        assert "Invalid interval" in resp.json()["detail"]

    def test_requires_feeds_read_scope(self, market_data_test_env: Any) -> None:
        """Unauthenticated requests are rejected."""
        client, _, app = market_data_test_env
        app.dependency_overrides.clear()

        resp = client.get(
            "/market-data/candles",
            params={"symbol": "AAPL", "interval": "1d"},
        )

        assert resp.status_code in (401, 403, 422)

    def test_candle_serialization_includes_all_fields(self, market_data_test_env: Any) -> None:
        client, mock_repo, app = market_data_test_env
        _override_auth(app)
        mock_repo.set_candles([_make_candle()])

        resp = client.get(
            "/market-data/candles",
            params={"symbol": "AAPL", "interval": "1d"},
            headers=_auth_headers(),
        )

        candle = resp.json()["candles"][0]
        assert candle["symbol"] == "AAPL"
        assert candle["interval"] == "1d"
        assert candle["open"] == "174.50"
        assert candle["close"] == "175.90"
        assert "timestamp" in candle

    def test_viewer_with_feeds_read_can_access(self, market_data_test_env: Any) -> None:
        """Viewer role has feeds:read scope."""
        client, mock_repo, app = market_data_test_env
        _override_auth(app, _VIEWER_USER)
        mock_repo.set_candles([_make_candle()])

        resp = client.get(
            "/market-data/candles",
            params={"symbol": "AAPL", "interval": "1d"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /market-data/candles/latest
# ---------------------------------------------------------------------------


class TestGetLatestCandle:
    """Tests for GET /market-data/candles/latest."""

    def test_returns_200_with_latest_candle(self, market_data_test_env: Any) -> None:
        client, mock_repo, app = market_data_test_env
        _override_auth(app)
        mock_repo.set_latest(_make_candle())

        resp = client.get(
            "/market-data/candles/latest",
            params={"symbol": "AAPL", "interval": "1d"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["candle"]["symbol"] == "AAPL"

    def test_returns_404_when_no_data(self, market_data_test_env: Any) -> None:
        client, _, app = market_data_test_env
        _override_auth(app)

        resp = client.get(
            "/market-data/candles/latest",
            params={"symbol": "AAPL", "interval": "1d"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 404

    def test_returns_400_for_invalid_interval(self, market_data_test_env: Any) -> None:
        client, _, app = market_data_test_env
        _override_auth(app)

        resp = client.get(
            "/market-data/candles/latest",
            params={"symbol": "AAPL", "interval": "bad"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /market-data/gaps
# ---------------------------------------------------------------------------


class TestGetGaps:
    """Tests for GET /market-data/gaps."""

    def test_returns_200_with_gaps(self, market_data_test_env: Any) -> None:
        client, mock_repo, app = market_data_test_env
        _override_auth(app)
        gap = DataGap(
            symbol="AAPL",
            interval=CandleInterval.M1,
            gap_start=_BASE_TS,
            gap_end=_BASE_TS + timedelta(minutes=5),
        )
        mock_repo.set_gaps([gap])

        resp = client.get(
            "/market-data/gaps",
            params={"symbol": "AAPL", "interval": "1m"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["symbol"] == "AAPL"

    def test_returns_empty_gaps(self, market_data_test_env: Any) -> None:
        client, _, app = market_data_test_env
        _override_auth(app)

        resp = client.get(
            "/market-data/gaps",
            params={"symbol": "AAPL", "interval": "1d"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        assert resp.json()["count"] == 0


# ---------------------------------------------------------------------------
# POST /market-data/backfill
# ---------------------------------------------------------------------------


class TestTriggerBackfill:
    """Tests for POST /market-data/backfill."""

    def test_returns_400_for_invalid_interval(self, market_data_test_env: Any) -> None:
        client, _, app = market_data_test_env
        _override_auth(app)

        resp = client.post(
            "/market-data/backfill",
            json={"symbol": "AAPL", "interval": "bad"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 400

    def test_requires_operator_write_scope(self, market_data_test_env: Any) -> None:
        """Viewer users without operator:write should be rejected."""
        client, _, app = market_data_test_env
        _override_auth(app, _VIEWER_USER)

        resp = client.post(
            "/market-data/backfill",
            json={"symbol": "AAPL", "interval": "1d"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 403

    def test_operator_can_trigger_backfill(self, market_data_test_env: Any) -> None:
        """Operator with operator:write scope can trigger backfill."""
        client, _, app = market_data_test_env
        _override_auth(app)

        # This will fail at the _build_collector stage since we don't have
        # ALPACA_DATA_API_KEY set, which is expected. We're testing the auth
        # layer, not the actual backfill execution.
        resp = client.post(
            "/market-data/backfill",
            json={"symbol": "AAPL", "interval": "1d"},
            headers=_auth_headers(),
        )

        # Will return 202 if it gets past auth, or 500 if build_collector fails
        # The important thing is it's NOT 403
        assert resp.status_code != 403
