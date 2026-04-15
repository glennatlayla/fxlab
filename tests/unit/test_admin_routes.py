"""
Tests for Admin API routes (/admin/secrets, /admin/users).

Covers:
- GET /admin/secrets — list secret metadata (admin only)
- POST /admin/secrets/{key}/rotate — rotate a secret (admin only)
- GET /admin/users — list Keycloak users (admin only)
- POST /admin/users — create Keycloak user (admin only)
- PUT /admin/users/{id}/roles — assign roles (admin only)
- POST /admin/users/{id}/reset-password — reset password (admin only)
- 403 rejection for non-admin callers

Example:
    pytest tests/unit/test_admin_routes.py -v
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from libs.contracts.mocks.mock_secret_provider import MockSecretProvider
from services.api.auth import ROLE_SCOPES, AuthenticatedUser

# ---------------------------------------------------------------------------
# Fake admin user for dependency overrides
# ---------------------------------------------------------------------------

_ADMIN_USER = AuthenticatedUser(
    user_id="01HTESTFAKE000000000000000",
    role="admin",
    email="admin@fxlab.test",
    scopes=ROLE_SCOPES["admin"] + ["admin:manage"],
)


class MockKeycloakAdmin:
    """Fake KeycloakAdminService for route testing."""

    def __init__(self) -> None:
        self.users: list[dict[str, Any]] = [
            {"id": "kc-user-1", "username": "admin@fxlab.io", "email": "admin@fxlab.io"},
            {"id": "kc-user-2", "username": "operator@fxlab.io", "email": "operator@fxlab.io"},
        ]
        self.created_users: list[dict] = []
        self.role_assignments: list[dict] = []
        self.password_resets: list[str] = []

    def list_users(self, first: int = 0, max_results: int = 100) -> list[dict[str, Any]]:
        """Return mock user list."""
        return self.users[first : first + max_results]

    def create_user(self, **kwargs: Any) -> dict[str, Any]:
        """Record user creation and return fake ID."""
        self.created_users.append(kwargs)
        return {"user_id": "kc-new-user-id"}

    def update_user_roles(self, user_id: str, roles: list[str]) -> None:
        """Record role assignment."""
        self.role_assignments.append({"user_id": user_id, "roles": roles})

    def reset_password(self, user_id: str) -> None:
        """Record password reset."""
        self.password_resets.append(user_id)


@pytest.fixture()
def admin_test_env():
    """
    Set up the test app with admin routes wired to mock dependencies.

    Uses FastAPI dependency_overrides so the patched dependencies actually
    take effect at request time (unlike module-level patching which fails
    because FastAPI resolves Depends() closures eagerly).

    Yields (client, secret_provider, keycloak_admin) tuple.
    """
    env_vars = {
        "ENVIRONMENT": "test",
        "DATABASE_URL": "sqlite:///:memory:",
        "JWT_SECRET_KEY": "test-secret-key-not-for-production-32bytes!!",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        from services.api.routes import admin as admin_module

        secret_provider = MockSecretProvider(
            {
                "JWT_SECRET_KEY": "test-key",
                "DATABASE_URL": "sqlite:///:memory:",
            }
        )
        keycloak_admin = MockKeycloakAdmin()

        admin_module.set_secret_provider(secret_provider)
        admin_module.set_keycloak_admin(keycloak_admin)

        try:
            from services.api.main import app

            client = TestClient(app, raise_server_exceptions=False)
            yield client, secret_provider, keycloak_admin, app
        finally:
            admin_module.set_secret_provider(None)
            admin_module.set_keycloak_admin(None)


def _admin_headers() -> dict[str, str]:
    """Authorization headers using the TEST_TOKEN."""
    return {"Authorization": "Bearer TEST_TOKEN"}


def _override_scope_check(app, admin_user=_ADMIN_USER):
    """
    Override the require_scope dependency in the admin router to always return admin_user.

    The admin routes use Depends(require_scope("admin:manage")) which is a factory
    returning an inner function. We find that inner function dependency and override it.
    """
    from services.api.auth import get_current_user

    # Override get_current_user to return admin user with admin:manage scope
    async def _fake_get_current_user():
        return admin_user

    app.dependency_overrides[get_current_user] = _fake_get_current_user


def _clear_overrides(app):
    """Remove all dependency overrides."""
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Secret endpoints
# ---------------------------------------------------------------------------


class TestAdminSecrets:
    """Tests for /admin/secrets endpoints."""

    def test_list_secrets_returns_metadata(self, admin_test_env):
        """GET /admin/secrets returns secret metadata for admin users."""
        client, provider, _, app = admin_test_env
        _override_scope_check(app)
        try:
            response = client.get("/admin/secrets", headers=_admin_headers())
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) == 2
            keys = [s["key"] for s in data]
            assert "JWT_SECRET_KEY" in keys
            assert "DATABASE_URL" in keys
        finally:
            _clear_overrides(app)

    def test_rotate_secret_succeeds(self, admin_test_env):
        """POST /admin/secrets/{key}/rotate updates the secret value."""
        client, provider, _, app = admin_test_env
        _override_scope_check(app)
        try:
            response = client.post(
                "/admin/secrets/JWT_SECRET_KEY/rotate",
                json={"new_value": "rotated-secret-value"},
                headers=_admin_headers(),
            )
            assert response.status_code == 200
            assert response.json()["status"] == "rotated"
            assert provider.get_secret("JWT_SECRET_KEY") == "rotated-secret-value"
        finally:
            _clear_overrides(app)

    def test_rotate_env_provider_returns_400_when_new_missing(self, admin_test_env):
        """Rotation on EnvSecretProvider returns 400 when KEY_NEW is not set."""
        client, _, _, app = admin_test_env
        _override_scope_check(app)

        from services.api.infrastructure.env_secret_provider import EnvSecretProvider
        from services.api.routes import admin as admin_module

        env_provider = EnvSecretProvider()
        admin_module.set_secret_provider(env_provider)

        try:
            response = client.post(
                "/admin/secrets/JWT_SECRET_KEY/rotate",
                json={"new_value": "new-value"},
                headers=_admin_headers(),
            )
            assert response.status_code == 400
            assert "_NEW" in response.json()["detail"]
        finally:
            _clear_overrides(app)
            admin_module.set_secret_provider(None)

    def test_list_expiring_secrets_returns_200(self, admin_test_env):
        """GET /admin/secrets/expiring returns list of expiring secrets."""
        client, provider, _, app = admin_test_env
        _override_scope_check(app)
        try:
            response = client.get(
                "/admin/secrets/expiring?threshold_days=90",
                headers=_admin_headers(),
            )
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
        finally:
            _clear_overrides(app)

    def test_list_expiring_secrets_uses_default_threshold(self, admin_test_env):
        """GET /admin/secrets/expiring without threshold_days uses default 90."""
        client, provider, _, app = admin_test_env
        _override_scope_check(app)
        try:
            response = client.get(
                "/admin/secrets/expiring",
                headers=_admin_headers(),
            )
            assert response.status_code == 200
        finally:
            _clear_overrides(app)


# ---------------------------------------------------------------------------
# User management endpoints
# ---------------------------------------------------------------------------


class TestAdminUsers:
    """Tests for /admin/users endpoints."""

    def test_list_users(self, admin_test_env):
        """GET /admin/users returns Keycloak user list."""
        client, _, kc_admin, app = admin_test_env
        _override_scope_check(app)
        try:
            response = client.get("/admin/users", headers=_admin_headers())
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["username"] == "admin@fxlab.io"
        finally:
            _clear_overrides(app)

    def test_create_user(self, admin_test_env):
        """POST /admin/users creates a user in Keycloak."""
        client, _, kc_admin, app = admin_test_env
        _override_scope_check(app)
        try:
            response = client.post(
                "/admin/users",
                json={
                    "username": "newuser@fxlab.io",
                    "email": "newuser@fxlab.io",
                    "first_name": "New",
                    "last_name": "User",
                    "temporary_password": "changeme123",
                },
                headers=_admin_headers(),
            )
            assert response.status_code == 201
            assert response.json()["user_id"] == "kc-new-user-id"
            assert len(kc_admin.created_users) == 1
        finally:
            _clear_overrides(app)

    def test_update_user_roles(self, admin_test_env):
        """PUT /admin/users/{id}/roles assigns roles."""
        client, _, kc_admin, app = admin_test_env
        _override_scope_check(app)
        try:
            response = client.put(
                "/admin/users/kc-user-1/roles",
                json={"roles": ["operator", "viewer"]},
                headers=_admin_headers(),
            )
            assert response.status_code == 204
            assert len(kc_admin.role_assignments) == 1
            assert kc_admin.role_assignments[0]["roles"] == ["operator", "viewer"]
        finally:
            _clear_overrides(app)

    def test_reset_user_password(self, admin_test_env):
        """POST /admin/users/{id}/reset-password triggers reset."""
        client, _, kc_admin, app = admin_test_env
        _override_scope_check(app)
        try:
            response = client.post(
                "/admin/users/kc-user-2/reset-password",
                headers=_admin_headers(),
            )
            assert response.status_code == 204
            assert "kc-user-2" in kc_admin.password_resets
        finally:
            _clear_overrides(app)


# ---------------------------------------------------------------------------
# Authorization enforcement
# ---------------------------------------------------------------------------


class TestAdminAuthorization:
    """Verify that non-admin users are rejected from /admin endpoints."""

    def test_secrets_rejects_non_admin(self, admin_test_env):
        """GET /admin/secrets returns 403 for non-admin users (operator lacks admin:manage)."""
        client, _, _, _ = admin_test_env
        response = client.get("/admin/secrets", headers=_admin_headers())
        assert response.status_code == 403

    def test_users_rejects_non_admin(self, admin_test_env):
        """GET /admin/users returns 403 for non-admin users."""
        client, _, _, _ = admin_test_env
        response = client.get("/admin/users", headers=_admin_headers())
        assert response.status_code == 403

    def test_rotate_rejects_non_admin(self, admin_test_env):
        """POST /admin/secrets/{key}/rotate returns 403 for non-admin users."""
        client, _, _, _ = admin_test_env
        response = client.post(
            "/admin/secrets/JWT_SECRET_KEY/rotate",
            json={"new_value": "new"},
            headers=_admin_headers(),
        )
        assert response.status_code == 403
