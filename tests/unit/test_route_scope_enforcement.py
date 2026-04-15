"""
Unit tests for route-level scope enforcement (M14-T9 Gap 1).

Verifies that all 28 protected route handlers enforce the correct scope
from spec §7.7 via require_scope() or require_any_scope().  Each test
creates a user who is authenticated but LACKS the required scope, and
asserts a 403 Forbidden response.

Test naming: test_<route_file>_<endpoint>_rejects_user_without_<scope>

Approach:
- FastAPI TestClient exercises real route wiring.
- dependency_overrides injects a user with a controlled scope list.
- Each route's non-auth dependencies (DB, repos, services) are overridden
  with stubs to isolate the auth check.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from services.api.auth import AuthenticatedUser, get_current_user

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_VIEWER_USER_ID = "01HABCDEF00000000000000000"


def _make_user(scopes: list[str], role: str = "viewer") -> AuthenticatedUser:
    """Create an AuthenticatedUser with explicit scopes."""
    return AuthenticatedUser(
        user_id=_VIEWER_USER_ID,
        role=role,
        email="test@fxlab.test",
        scopes=scopes,
    )


@pytest.fixture(autouse=True)
def _test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure test environment for all tests."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-not-for-production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")


@pytest.fixture
def app() -> Any:
    """Import the FastAPI app fresh for each test."""
    from services.api.main import app as _app

    return _app


@pytest.fixture
def mock_db_session() -> MagicMock:
    """Return a mock DB session."""
    return MagicMock(spec=Session)


# ---------------------------------------------------------------------------
# Helper: override get_db for all routes
# ---------------------------------------------------------------------------


def _override_db(app: Any, mock_session: MagicMock) -> None:
    """Override get_db to return a mock session."""
    from services.api.db import get_db

    app.dependency_overrides[get_db] = lambda: mock_session


def _set_user_scopes(app: Any, scopes: list[str], role: str = "viewer") -> None:
    """
    Override get_current_user AND all require_scope closures to use a user
    with the given scopes.

    The require_scope factory creates closure functions that internally call
    get_current_user.  By overriding get_current_user, the scope check in
    the closure still runs against our injected user's scopes.
    """
    user = _make_user(scopes, role)

    async def _fake_user() -> AuthenticatedUser:
        return user

    app.dependency_overrides[get_current_user] = _fake_user


@pytest.fixture(autouse=True)
def _cleanup_overrides(app: Any) -> Generator:
    """Ensure dependency overrides are cleaned up after each test."""
    yield
    app.dependency_overrides.clear()


# ===========================================================================
# strategies.py — requires "strategies:write"
# ===========================================================================


class TestStrategiesScopeEnforcement:
    """Verify strategies routes enforce strategies:write scope."""

    def test_list_strategies_rejects_user_without_strategies_write(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["feeds:read"])  # missing strategies:write
        client = TestClient(app)
        resp = client.get("/strategies/")
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

    def test_post_draft_autosave_rejects_user_without_strategies_write(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["feeds:read"])
        client = TestClient(app)
        resp = client.post(
            "/strategies/draft/autosave",
            json={
                "user_id": _VIEWER_USER_ID,
                "draft_payload": {},
                "form_step": "parameters",
                "session_id": "sess-1",
                "client_ts": "2026-04-03T12:00:00Z",
            },
        )
        assert resp.status_code == 403

    def test_get_latest_draft_autosave_rejects_user_without_strategies_write(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["feeds:read"])
        client = TestClient(app)
        resp = client.get(f"/strategies/draft/autosave/latest?user_id={_VIEWER_USER_ID}")
        assert resp.status_code == 403

    def test_delete_draft_autosave_rejects_user_without_strategies_write(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["feeds:read"])
        client = TestClient(app)
        resp = client.delete("/strategies/draft/autosave/01HABCDEF00000000000000001")
        assert resp.status_code == 403

    def test_list_strategies_allows_user_with_strategies_write(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        from services.api.routes.strategies import set_strategy_service

        mock_service = MagicMock()
        mock_service.list_strategies.return_value = {
            "strategies": [],
            "limit": 50,
            "offset": 0,
            "count": 0,
        }
        set_strategy_service(mock_service)
        try:
            _override_db(app, mock_db_session)
            _set_user_scopes(app, scopes=["strategies:write"], role="operator")
            client = TestClient(app)
            resp = client.get("/strategies/")
            # Should NOT be 403 — may be 200 or other non-auth error
            assert resp.status_code != 403
        finally:
            set_strategy_service(None)


# ===========================================================================
# runs.py — requires "exports:read" (GET run results is a read operation)
# ===========================================================================


class TestRunsScopeEnforcement:
    """Verify runs routes enforce exports:read scope."""

    def test_get_run_results_rejects_user_without_exports_read(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["strategies:write"])  # missing exports:read
        client = TestClient(app)
        resp = client.get("/runs/01HABCDEF00000000000000001/results")
        assert resp.status_code == 403


# ===========================================================================
# promotions.py — requires "promotions:request"
# ===========================================================================


class TestPromotionsScopeEnforcement:
    """Verify promotions routes enforce promotions:request scope."""

    def test_request_promotion_rejects_user_without_promotions_request(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["feeds:read"])  # missing promotions:request
        client = TestClient(app)
        resp = client.post(
            "/promotions/request",
            json={
                "candidate_id": "01HABCDEF00000000000000002",
                "target_environment": "staging",
                "requester_id": _VIEWER_USER_ID,
            },
        )
        assert resp.status_code == 403


# ===========================================================================
# approvals.py — requires "approvals:write"
# ===========================================================================


class TestApprovalsScopeEnforcement:
    """Verify approvals routes enforce approvals:write scope."""

    def test_approve_request_rejects_user_without_approvals_write(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["feeds:read"])
        client = TestClient(app)
        resp = client.post("/approvals/01HABCDEF00000000000000003/approve")
        assert resp.status_code == 403

    def test_reject_request_rejects_user_without_approvals_write(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["feeds:read"])
        client = TestClient(app)
        resp = client.post(
            "/approvals/01HABCDEF00000000000000003/reject",
            json={"rationale": "Insufficient evidence provided for this request."},
        )
        assert resp.status_code == 403


# ===========================================================================
# overrides.py — POST /request requires "overrides:request",
#                GET /{id} requires "overrides:request"
# ===========================================================================


class TestOverridesScopeEnforcement:
    """Verify overrides routes enforce overrides:request scope."""

    def test_request_override_rejects_user_without_overrides_request(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["feeds:read"])
        client = TestClient(app)
        resp = client.post(
            "/overrides/request",
            json={
                "object_id": "01HABCDEF00000000000000004",
                "object_type": "candidate",
                "override_type": "promote",
                "original_state": "blocked",
                "new_state": "promoted",
                "evidence_link": "https://evidence.example.com/doc/123",
                "rationale": "This override is justified because the backtest shows strong performance.",
            },
        )
        assert resp.status_code == 403

    def test_get_override_rejects_user_without_overrides_request(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["feeds:read"])
        client = TestClient(app)
        resp = client.get("/overrides/01HABCDEF00000000000000004")
        assert resp.status_code == 403


# ===========================================================================
# charts.py — requires "exports:read"
# ===========================================================================


class TestChartsScopeEnforcement:
    """Verify charts routes enforce exports:read scope."""

    def test_get_run_charts_rejects_user_without_exports_read(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["strategies:write"])
        client = TestClient(app)
        resp = client.get("/runs/01HABCDEF00000000000000005/charts")
        assert resp.status_code == 403

    def test_get_run_equity_chart_rejects_user_without_exports_read(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["strategies:write"])
        client = TestClient(app)
        resp = client.get("/runs/01HABCDEF00000000000000005/charts/equity")
        assert resp.status_code == 403

    def test_get_run_drawdown_chart_rejects_user_without_exports_read(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["strategies:write"])
        client = TestClient(app)
        resp = client.get("/runs/01HABCDEF00000000000000005/charts/drawdown")
        assert resp.status_code == 403


# ===========================================================================
# artifacts.py — requires "exports:read"
# ===========================================================================


class TestArtifactsScopeEnforcement:
    """Verify artifacts routes enforce exports:read scope."""

    def test_list_artifacts_rejects_user_without_exports_read(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["strategies:write"])
        client = TestClient(app)
        resp = client.get("/artifacts")
        assert resp.status_code == 403

    def test_download_artifact_rejects_user_without_exports_read(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["strategies:write"])
        client = TestClient(app)
        resp = client.get("/artifacts/01HABCDEF00000000000000006/download")
        assert resp.status_code == 403


# ===========================================================================
# feeds.py — requires "feeds:read"
# ===========================================================================


class TestFeedsScopeEnforcement:
    """Verify feeds routes enforce feeds:read scope."""

    def test_list_feeds_rejects_user_without_feeds_read(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["strategies:write"])
        client = TestClient(app)
        resp = client.get("/feeds")
        assert resp.status_code == 403

    def test_get_feed_detail_rejects_user_without_feeds_read(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["strategies:write"])
        client = TestClient(app)
        resp = client.get("/feeds/01HABCDEF00000000000000007")
        assert resp.status_code == 403


# ===========================================================================
# feed_health.py — requires "feeds:read"
# ===========================================================================


class TestFeedHealthScopeEnforcement:
    """Verify feed_health routes enforce feeds:read scope."""

    def test_get_feed_health_rejects_user_without_feeds_read(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["strategies:write"])
        client = TestClient(app)
        resp = client.get("/feed-health")
        assert resp.status_code == 403


# ===========================================================================
# parity.py — requires "feeds:read"
# ===========================================================================


class TestParityScopeEnforcement:
    """Verify parity routes enforce feeds:read scope."""

    def test_get_parity_events_rejects_user_without_feeds_read(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["strategies:write"])
        client = TestClient(app)
        resp = client.get("/parity/events")
        assert resp.status_code == 403

    def test_get_parity_event_rejects_user_without_feeds_read(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["strategies:write"])
        client = TestClient(app)
        resp = client.get("/parity/events/01HABCDEF00000000000000008")
        assert resp.status_code == 403

    def test_get_parity_summary_rejects_user_without_feeds_read(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["strategies:write"])
        client = TestClient(app)
        resp = client.get("/parity/summary")
        assert resp.status_code == 403


# ===========================================================================
# queues.py — requires "operator:read"
# ===========================================================================


class TestQueuesScopeEnforcement:
    """Verify queues routes enforce operator:read scope."""

    def test_list_queues_rejects_user_without_operator_read(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["strategies:write"])
        client = TestClient(app)
        resp = client.get("/queues/")
        assert resp.status_code == 403

    def test_get_queue_contention_rejects_user_without_operator_read(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["strategies:write"])
        client = TestClient(app)
        resp = client.get("/queues/research/contention")
        assert resp.status_code == 403


# ===========================================================================
# audit.py — requires "audit:read"
# ===========================================================================


class TestAuditScopeEnforcement:
    """Verify audit routes enforce audit:read scope."""

    def test_list_audit_events_rejects_user_without_audit_read(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["strategies:write"])
        client = TestClient(app)
        resp = client.get("/audit")
        assert resp.status_code == 403

    def test_get_audit_event_rejects_user_without_audit_read(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["strategies:write"])
        client = TestClient(app)
        resp = client.get("/audit/01HABCDEF00000000000000009")
        assert resp.status_code == 403


# ===========================================================================
# governance.py — requires any of: "approvals:write", "overrides:request"
# ===========================================================================


class TestGovernanceScopeEnforcement:
    """Verify governance list route enforces governance-related scopes."""

    def test_list_governance_rejects_user_without_governance_scopes(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        # User has only feeds:read — no governance scopes
        _set_user_scopes(app, scopes=["feeds:read"])
        client = TestClient(app)
        resp = client.get("/governance/")
        assert resp.status_code == 403

    def test_list_governance_allows_user_with_approvals_write(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["approvals:write"], role="reviewer")
        client = TestClient(app)
        resp = client.get("/governance/")
        assert resp.status_code != 403

    def test_list_governance_allows_user_with_overrides_request(
        self, app: Any, mock_db_session: MagicMock
    ) -> None:
        _override_db(app, mock_db_session)
        _set_user_scopes(app, scopes=["overrides:request"], role="operator")
        client = TestClient(app)
        resp = client.get("/governance/")
        assert resp.status_code != 403
