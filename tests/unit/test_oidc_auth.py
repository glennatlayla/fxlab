"""
Tests for OIDC authentication components (M14-T8).

Covers:
- Scope claim in access tokens
- ROLE_SCOPES mapping
- AuthenticatedUser.has_scope()
- require_scope() FastAPI dependency
- RefreshTokenRepository (mock implementation)
- OIDC discovery endpoint
- Token endpoint (password + refresh grants)
- Token revocation endpoint
- JWKS endpoint (501 stub)

Example:
    pytest tests/unit/test_oidc_auth.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from libs.contracts.errors import NotFoundError
from libs.contracts.mocks.mock_refresh_token_repository import (
    MockRefreshTokenRepository,
)
from services.api.auth import (
    ROLE_SCOPES,
    AuthenticatedUser,
    create_access_token,
    require_scope,
)

# ---------------------------------------------------------------------------
# ROLE_SCOPES and AuthenticatedUser
# ---------------------------------------------------------------------------


class TestRoleScopes:
    """ROLE_SCOPES mapping is complete and consistent."""

    def test_admin_has_all_scopes(self):
        """Admin role includes all Phase 3 + Phase 4 deployment + Phase 6 live + Phase 7 operator + compliance scopes, plus admin:manage (Tranche L)."""
        assert len(ROLE_SCOPES["admin"]) == 17
        assert "admin:manage" in ROLE_SCOPES["admin"]

    def test_operator_cannot_approve(self):
        """Operator role does not include approval scopes."""
        assert "approvals:write" not in ROLE_SCOPES["operator"]
        assert "overrides:approve" not in ROLE_SCOPES["operator"]

    def test_reviewer_cannot_write_strategies(self):
        """Reviewer role does not include strategy/run write scopes."""
        assert "strategies:write" not in ROLE_SCOPES["reviewer"]
        assert "runs:write" not in ROLE_SCOPES["reviewer"]

    def test_viewer_has_read_only(self):
        """Viewer role only has read scopes."""
        for s in ROLE_SCOPES["viewer"]:
            assert s.endswith(":read"), f"Viewer scope {s} is not read-only"

    def test_all_roles_present(self):
        """All five defined roles exist in ROLE_SCOPES."""
        assert set(ROLE_SCOPES.keys()) == {"admin", "operator", "live_trader", "reviewer", "viewer"}


class TestAuthenticatedUserScopes:
    """AuthenticatedUser.has_scope() works correctly."""

    def test_has_scope_true(self):
        """has_scope returns True for granted scopes."""
        user = AuthenticatedUser(
            user_id="01HTESTFAKE000000000000000",
            role="operator",
            scopes=["feeds:read", "strategies:write"],
        )
        assert user.has_scope("feeds:read") is True
        assert user.has_scope("strategies:write") is True

    def test_has_scope_false(self):
        """has_scope returns False for ungranted scopes."""
        user = AuthenticatedUser(
            user_id="01HTESTFAKE000000000000000",
            role="viewer",
            scopes=["feeds:read"],
        )
        assert user.has_scope("approvals:write") is False

    def test_default_scopes_empty(self):
        """Default scopes list is empty."""
        user = AuthenticatedUser(
            user_id="01HTESTFAKE000000000000000",
            role="viewer",
        )
        assert user.scopes == []


# ---------------------------------------------------------------------------
# create_access_token with scope claim
# ---------------------------------------------------------------------------


class TestAccessTokenScopes:
    """create_access_token includes scope claim."""

    def test_token_includes_scope_claim(self):
        """Token payload contains space-separated scope string."""
        token = create_access_token(
            "01HTESTFAKE000000000000000",
            "operator",
            expires_minutes=5,
        )
        payload = jwt.decode(token, options={"verify_signature": False})
        assert "scope" in payload
        scopes = payload["scope"].split()
        assert "feeds:read" in scopes
        assert "strategies:write" in scopes

    def test_custom_scopes_override_role(self):
        """Explicit scopes override role-based defaults."""
        token = create_access_token(
            "01HTESTFAKE000000000000000",
            "viewer",
            expires_minutes=5,
            scopes=["custom:scope"],
        )
        payload = jwt.decode(token, options={"verify_signature": False})
        assert payload["scope"] == "custom:scope"

    def test_unknown_role_gets_empty_scope(self):
        """Unknown role gets empty scope string."""
        token = create_access_token(
            "01HTESTFAKE000000000000000",
            "unknown_role",
            expires_minutes=5,
        )
        payload = jwt.decode(token, options={"verify_signature": False})
        assert payload["scope"] == ""


# ---------------------------------------------------------------------------
# require_scope dependency
# ---------------------------------------------------------------------------


class TestRequireScope:
    """require_scope() returns a dependency that enforces scope checks."""

    def test_scope_granted_passes(self):
        """Dependency returns user when scope is present.

        Uses ``asyncio.run()`` rather than ``asyncio.get_event_loop()
        .run_until_complete()``: on Python 3.12+, after an earlier
        test in this module runs ``TestClient`` (which creates and
        closes an ASGI lifespan loop), ``get_event_loop()`` returns
        the closed loop and ``run_until_complete()`` raises
        ``RuntimeError: Event loop is closed``. ``asyncio.run()``
        allocates a fresh loop for each call and sidesteps the issue.
        """
        import asyncio

        dep = require_scope("feeds:read")
        user = AuthenticatedUser(
            user_id="01HTESTFAKE000000000000000",
            role="operator",
            scopes=["feeds:read", "strategies:write"],
        )
        result = asyncio.run(dep(user=user))
        assert result.user_id == user.user_id

    def test_scope_denied_raises_403(self):
        """Dependency raises 403 when scope is missing.

        See ``test_scope_granted_passes`` for why this uses
        ``asyncio.run()`` rather than ``asyncio.get_event_loop()``.
        """
        import asyncio

        dep = require_scope("approvals:write")
        user = AuthenticatedUser(
            user_id="01HTESTFAKE000000000000000",
            role="operator",
            scopes=["feeds:read"],
        )
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(dep(user=user))
        assert exc_info.value.status_code == 403
        assert "approvals:write" in exc_info.value.detail


# ---------------------------------------------------------------------------
# MockRefreshTokenRepository
# ---------------------------------------------------------------------------


class TestMockRefreshTokenRepository:
    """Mock implementation honours the interface contract."""

    def _make_repo(self) -> MockRefreshTokenRepository:
        return MockRefreshTokenRepository()

    def test_create_and_find_by_hash(self):
        """Created tokens are findable by hash."""
        repo = self._make_repo()
        exp = datetime.now(timezone.utc) + timedelta(days=7)
        repo.create(
            token_id="T1",
            user_id="U1",
            token_hash="hash1",
            expires_at=exp,
        )
        record = repo.find_by_hash("hash1")
        assert record is not None
        assert record["user_id"] == "U1"
        assert record["revoked_at"] is None

    def test_find_by_hash_not_found(self):
        """find_by_hash returns None for unknown hash."""
        repo = self._make_repo()
        assert repo.find_by_hash("nonexistent") is None

    def test_revoke(self):
        """Revoking a token sets revoked_at."""
        repo = self._make_repo()
        exp = datetime.now(timezone.utc) + timedelta(days=7)
        repo.create(token_id="T1", user_id="U1", token_hash="h1", expires_at=exp)
        repo.revoke("T1")
        record = repo.find_by_hash("h1")
        assert record is not None
        assert record["revoked_at"] is not None

    def test_revoke_not_found_raises(self):
        """Revoking a nonexistent token raises NotFoundError."""
        repo = self._make_repo()
        with pytest.raises(NotFoundError):
            repo.revoke("NONEXISTENT")

    def test_revoke_all_for_user(self):
        """revoke_all_for_user revokes all active tokens for a user."""
        repo = self._make_repo()
        exp = datetime.now(timezone.utc) + timedelta(days=7)
        repo.create(token_id="T1", user_id="U1", token_hash="h1", expires_at=exp)
        repo.create(token_id="T2", user_id="U1", token_hash="h2", expires_at=exp)
        repo.create(token_id="T3", user_id="U2", token_hash="h3", expires_at=exp)
        count = repo.revoke_all_for_user("U1")
        assert count == 2
        # U2's token should be unaffected
        assert repo.find_by_hash("h3")["revoked_at"] is None

    def test_delete_expired(self):
        """delete_expired removes tokens past their expiry."""
        repo = self._make_repo()
        past = datetime.now(timezone.utc) - timedelta(days=1)
        future = datetime.now(timezone.utc) + timedelta(days=7)
        repo.create(token_id="T1", user_id="U1", token_hash="h1", expires_at=past)
        repo.create(token_id="T2", user_id="U1", token_hash="h2", expires_at=future)
        count = repo.delete_expired()
        assert count == 1
        assert repo.find_by_hash("h1") is None
        assert repo.find_by_hash("h2") is not None

    def test_count_and_clear(self):
        """Introspection helpers work correctly."""
        repo = self._make_repo()
        exp = datetime.now(timezone.utc) + timedelta(days=7)
        repo.create(token_id="T1", user_id="U1", token_hash="h1", expires_at=exp)
        assert repo.count() == 1
        repo.clear()
        assert repo.count() == 0


# ---------------------------------------------------------------------------
# Auth routes via TestClient
# ---------------------------------------------------------------------------


@pytest.fixture
def _app():
    """Create a fresh app instance for route testing."""
    from services.api.main import app

    return app


@pytest.fixture
def client(_app):
    """TestClient with test environment."""
    return TestClient(_app)


class TestOIDCDiscovery:
    """GET /.well-known/openid-configuration returns a valid discovery doc."""

    def test_discovery_returns_200(self, client):
        """Discovery endpoint is publicly accessible."""
        resp = client.get("/.well-known/openid-configuration")
        assert resp.status_code == 200

    def test_discovery_has_required_fields(self, client):
        """Discovery document contains all OIDC required fields."""
        resp = client.get("/.well-known/openid-configuration")
        data = resp.json()
        assert "issuer" in data
        assert "token_endpoint" in data
        assert "revocation_endpoint" in data
        assert "jwks_uri" in data
        assert "grant_types_supported" in data
        assert "password" in data["grant_types_supported"]
        assert "refresh_token" in data["grant_types_supported"]

    def test_discovery_scopes_include_all_defined(self, client):
        """Scopes in discovery include all from ROLE_SCOPES."""
        resp = client.get("/.well-known/openid-configuration")
        scopes = set(resp.json()["scopes_supported"])
        all_scopes = {s for ss in ROLE_SCOPES.values() for s in ss}
        assert all_scopes == scopes


class TestJWKSEndpoint:
    """GET /auth/jwks returns 501 for HS256."""

    def test_jwks_returns_501(self, client):
        """JWKS endpoint returns 501 since we use HS256."""
        resp = client.get("/auth/jwks")
        assert resp.status_code == 501
        assert "keys" in resp.json()
        assert resp.json()["keys"] == []


class TestTokenEndpoint:
    """POST /auth/token handles password and refresh grants."""

    def test_unsupported_grant_type_returns_400(self, client):
        """Unknown grant_type returns 400."""
        resp = client.post(
            "/auth/token",
            json={"grant_type": "authorization_code"},
        )
        assert resp.status_code == 400
        assert "Unsupported grant_type" in resp.json()["detail"]

    def test_missing_grant_type_returns_400(self, client):
        """Missing grant_type returns 400."""
        resp = client.post("/auth/token", json={})
        assert resp.status_code == 400

    def test_password_grant_missing_credentials_returns_401(self, client):
        """Password grant without username/password returns 401."""
        resp = client.post(
            "/auth/token",
            json={"grant_type": "password"},
        )
        assert resp.status_code == 401

    def test_password_grant_unknown_user_returns_401(self, client):
        """Password grant with unknown email returns 401."""
        resp = client.post(
            "/auth/token",
            json={
                "grant_type": "password",
                "username": "nobody@example.com",
                "password": "secret",
            },
        )
        assert resp.status_code == 401

    def test_refresh_grant_missing_token_returns_401(self, client):
        """Refresh grant without refresh_token returns 401."""
        resp = client.post(
            "/auth/token",
            json={"grant_type": "refresh_token"},
        )
        assert resp.status_code == 401

    def test_refresh_grant_invalid_token_returns_401(self, client):
        """Refresh grant with unknown token returns 401."""
        resp = client.post(
            "/auth/token",
            json={
                "grant_type": "refresh_token",
                "refresh_token": "invalid_token_here",
            },
        )
        assert resp.status_code == 401


class TestRevokeEndpoint:
    """POST /auth/revoke requires auth and revokes tokens."""

    def test_revoke_without_auth_returns_401(self, client):
        """Revoke endpoint requires authentication."""
        resp = client.post("/auth/revoke", json={"revoke_all": True})
        assert resp.status_code == 401

    def test_revoke_with_auth_and_empty_body_returns_400(self, client):
        """Revoke with no token and revoke_all=false returns 400."""
        resp = client.post(
            "/auth/revoke",
            json={"token": "", "revoke_all": False},
            headers={"Authorization": "Bearer TEST_TOKEN"},
        )
        assert resp.status_code == 400

    def test_revoke_all_with_auth_returns_200(self, client):
        """Revoke all tokens returns success (even if 0 revoked)."""
        resp = client.post(
            "/auth/revoke",
            json={"revoke_all": True},
            headers={"Authorization": "Bearer TEST_TOKEN"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "revoked"
        assert "count" in data

    def test_revoke_unknown_token_returns_200(self, client):
        """Revoking an unknown token returns 200 with count=0 (RFC 7009)."""
        resp = client.post(
            "/auth/revoke",
            json={"token": "some_unknown_refresh_token"},
            headers={"Authorization": "Bearer TEST_TOKEN"},
        )
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


# ---------------------------------------------------------------------------
# Integration: password grant with real User row
# ---------------------------------------------------------------------------


class TestPasswordGrantIntegration:
    """Full password grant flow against SQLite with a real User row."""

    def test_password_grant_success(self, client):
        """Valid credentials return access + refresh tokens."""
        from services.api.db import Base, SessionLocal, engine

        # Create tables
        Base.metadata.create_all(engine)

        # Insert test user
        from libs.contracts.models import User

        session = SessionLocal()
        hashed = bcrypt.hashpw(b"testpass123", bcrypt.gensalt()).decode("utf-8")
        user = User(
            id="01HTESTUSER000000000000001",
            email="test@fxlab.io",
            hashed_password=hashed,
            role="operator",
            is_active=True,
        )
        session.add(user)
        session.commit()
        session.close()

        try:
            resp = client.post(
                "/auth/token",
                json={
                    "grant_type": "password",
                    "username": "test@fxlab.io",
                    "password": "testpass123",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "access_token" in data
            assert "refresh_token" in data
            assert data["token_type"] == "Bearer"
            assert data["expires_in"] > 0
            assert "scope" in data

            # Verify access token is valid
            from services.api.auth import _get_secret_key

            payload = jwt.decode(
                data["access_token"],
                _get_secret_key(),
                algorithms=["HS256"],
                audience="fxlab-api",
            )
            assert payload["sub"] == "01HTESTUSER000000000000001"
            assert payload["role"] == "operator"
            assert "scope" in payload

            # Verify refresh token can be used
            resp2 = client.post(
                "/auth/token",
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": data["refresh_token"],
                },
            )
            assert resp2.status_code == 200
            data2 = resp2.json()
            assert "access_token" in data2
            # Refresh tokens are always rotated (new random value)
            assert data2["refresh_token"] != data["refresh_token"]

            # Old refresh token should be revoked (rotation)
            resp3 = client.post(
                "/auth/token",
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": data["refresh_token"],
                },
            )
            # Revoked token returns 401
            assert resp3.status_code == 401

        finally:
            # Cleanup
            session = SessionLocal()
            session.query(User).filter(User.id == "01HTESTUSER000000000000001").delete()
            session.commit()
            session.close()

    def test_password_grant_wrong_password(self, client):
        """Wrong password returns 401."""
        from services.api.db import Base, SessionLocal, engine

        Base.metadata.create_all(engine)

        from libs.contracts.models import User

        session = SessionLocal()
        hashed = bcrypt.hashpw(b"correct", bcrypt.gensalt()).decode("utf-8")
        user = User(
            id="01HTESTUSER000000000000002",
            email="wrong@fxlab.io",
            hashed_password=hashed,
            role="operator",
            is_active=True,
        )
        session.add(user)
        session.commit()
        session.close()

        try:
            resp = client.post(
                "/auth/token",
                json={
                    "grant_type": "password",
                    "username": "wrong@fxlab.io",
                    "password": "incorrect",
                },
            )
            assert resp.status_code == 401
        finally:
            session = SessionLocal()
            session.query(User).filter(User.id == "01HTESTUSER000000000000002").delete()
            session.commit()
            session.close()

    def test_password_grant_inactive_user(self, client):
        """Inactive user returns 401."""
        from services.api.db import Base, SessionLocal, engine

        Base.metadata.create_all(engine)

        from libs.contracts.models import User

        session = SessionLocal()
        hashed = bcrypt.hashpw(b"pass", bcrypt.gensalt()).decode("utf-8")
        user = User(
            id="01HTESTUSER000000000000003",
            email="inactive@fxlab.io",
            hashed_password=hashed,
            role="operator",
            is_active=False,
        )
        session.add(user)
        session.commit()
        session.close()

        try:
            resp = client.post(
                "/auth/token",
                json={
                    "grant_type": "password",
                    "username": "inactive@fxlab.io",
                    "password": "pass",
                },
            )
            assert resp.status_code == 401
            assert "disabled" in resp.json()["detail"]
        finally:
            session = SessionLocal()
            session.query(User).filter(User.id == "01HTESTUSER000000000000003").delete()
            session.commit()
            session.close()
