"""
Unit tests for M0 gap fill: AuthMode enum and auth_mode field on AuthenticatedUser.

Covers:
- AuthMode enum values (LOCAL_JWT, KEYCLOAK)
- AuthenticatedUser.auth_mode field defaults and serialization
- _validate_token sets auth_mode based on validation path

Example:
    pytest tests/unit/test_auth_mode_m0.py -v
"""

from __future__ import annotations

import os
from unittest.mock import patch

from services.api.auth import (
    AuthenticatedUser,
    AuthMode,
    create_access_token,
)

# ---------------------------------------------------------------------------
# AuthMode enum
# ---------------------------------------------------------------------------


class TestAuthMode:
    """AuthMode enum defines supported authentication modes."""

    def test_local_jwt_value(self) -> None:
        """LOCAL_JWT mode is the HS256 self-rolled default."""
        assert AuthMode.LOCAL_JWT == "local_jwt"

    def test_keycloak_value(self) -> None:
        """KEYCLOAK mode is the RS256 Keycloak-delegated mode."""
        assert AuthMode.KEYCLOAK == "keycloak"

    def test_enum_members(self) -> None:
        """AuthMode has exactly two members."""
        assert len(AuthMode) == 2


# ---------------------------------------------------------------------------
# AuthenticatedUser.auth_mode field
# ---------------------------------------------------------------------------


class TestAuthenticatedUserAuthMode:
    """AuthenticatedUser carries the auth_mode that validated the token."""

    def test_default_auth_mode_is_local_jwt(self) -> None:
        """AuthenticatedUser defaults auth_mode to LOCAL_JWT."""
        user = AuthenticatedUser(
            user_id="01HABC00000000000000000000",
            role="operator",
        )
        assert user.auth_mode == AuthMode.LOCAL_JWT

    def test_auth_mode_can_be_set_to_keycloak(self) -> None:
        """AuthenticatedUser accepts auth_mode=KEYCLOAK."""
        user = AuthenticatedUser(
            user_id="01HABC00000000000000000000",
            role="operator",
            auth_mode=AuthMode.KEYCLOAK,
        )
        assert user.auth_mode == AuthMode.KEYCLOAK

    def test_auth_mode_serializes_to_string(self) -> None:
        """auth_mode appears as string in model_dump."""
        user = AuthenticatedUser(
            user_id="01HABC00000000000000000000",
            role="operator",
            auth_mode=AuthMode.KEYCLOAK,
        )
        data = user.model_dump()
        assert data["auth_mode"] == "keycloak"


# ---------------------------------------------------------------------------
# _validate_token sets auth_mode based on path
# ---------------------------------------------------------------------------


class TestValidateTokenAuthMode:
    """_validate_token assigns the correct auth_mode to the returned user."""

    def test_hs256_path_sets_local_jwt_mode(self) -> None:
        """Tokens validated via HS256 get auth_mode=LOCAL_JWT."""
        env = {
            "ENVIRONMENT": "test",
            "JWT_SECRET_KEY": "test-secret-key-not-for-production",
            "JWT_AUDIENCE": "fxlab-api",
            "JWT_ISSUER": "fxlab",
        }
        with patch.dict(os.environ, env, clear=False):
            token = create_access_token(
                "01HABC00000000000000000000",
                "operator",
            )
            from services.api.auth import _validate_token

            user = _validate_token(token)
            assert user.auth_mode == AuthMode.LOCAL_JWT

    def test_test_token_sets_local_jwt_mode(self) -> None:
        """TEST_TOKEN shortcut also sets auth_mode=LOCAL_JWT."""
        env = {"ENVIRONMENT": "test"}
        with patch.dict(os.environ, env, clear=False):
            from services.api.auth import TEST_TOKEN, _validate_token

            user = _validate_token(TEST_TOKEN)
            assert user.auth_mode == AuthMode.LOCAL_JWT
